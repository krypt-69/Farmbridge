from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.pricing import PricingConfig

router = APIRouter(prefix="/pricing", tags=["pricing"])

# ---------- Helper to compute prices ----------
def compute_prices(config: PricingConfig) -> dict:
    return {
        "base_market_price_cents": config.base_market_price_cents,
        "platform_fee_cents": config.platform_fee_cents,
        "transport_fee_cents": config.transport_fee_cents,
        "buyer_discount_cents": config.buyer_discount_cents,
        "buyer_price_per_bag": config.base_market_price_cents - config.buyer_discount_cents,
        "farmer_payout_per_bag": config.base_market_price_cents - config.platform_fee_cents - config.transport_fee_cents,
    }

# ---------- Public / buyer / farmer endpoint ----------
@router.get("/", response_model=dict)
async def get_pricing(
    region: Optional[str] = None,
    crop: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # any logged‑in user
):
    # Look for the most specific config
    config = None
    if region and crop:
        result = await db.execute(
            select(PricingConfig).where(
                PricingConfig.region == region, PricingConfig.crop == crop
            )
        )
        config = result.scalar_one_or_none()
    if not config and region:
        # try region with crop=None
        result = await db.execute(
            select(PricingConfig).where(
                PricingConfig.region == region, PricingConfig.crop == None
            )
        )
        config = result.scalar_one_or_none()
    if not config:
        # global default (both None)
        result = await db.execute(
            select(PricingConfig).where(
                PricingConfig.region == None, PricingConfig.crop == None
            )
        )
        config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(status_code=404, detail="No pricing configuration found")

    return compute_prices(config)

# ---------- Admin update / create ----------
class PricingUpdate(BaseModel):
    region: Optional[str] = None
    crop: Optional[str] = None
    base_market_price_cents: int
    platform_fee_cents: int
    transport_fee_cents: int
    buyer_discount_cents: int

@router.post("/admin", response_model=dict)
async def upsert_pricing(
    data: PricingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    # Upsert: if exists, update; else create
    result = await db.execute(
        select(PricingConfig).where(
            PricingConfig.region == data.region,
            PricingConfig.crop == data.crop,
        )
    )
    config = result.scalar_one_or_none()
    if config:
        config.base_market_price_cents = data.base_market_price_cents
        config.platform_fee_cents = data.platform_fee_cents
        config.transport_fee_cents = data.transport_fee_cents
        config.buyer_discount_cents = data.buyer_discount_cents
    else:
        config = PricingConfig(
            region=data.region,
            crop=data.crop,
            base_market_price_cents=data.base_market_price_cents,
            platform_fee_cents=data.platform_fee_cents,
            transport_fee_cents=data.transport_fee_cents,
            buyer_discount_cents=data.buyer_discount_cents,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)
    return compute_prices(config)