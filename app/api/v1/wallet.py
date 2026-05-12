from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.wallet import Wallet
from app.models.ledger import LedgerEntry
from app.core import payment_engine

router = APIRouter(prefix="/wallet", tags=["wallet"])

@router.get("/", response_model=dict)
async def get_my_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Wallet).where(Wallet.user_id == current_user.id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        # Auto-create wallet? No, deposit will create it. Return zero.
        return {
            "available_balance_cents": 0,
            "locked_balance_cents": 0,
            "currency": "KES",
        }
    return {
        "available_balance_cents": wallet.available_balance_cents,
        "locked_balance_cents": wallet.locked_balance_cents,
        "currency": wallet.currency,
    }

@router.get("/ledger", response_model=List[dict])
async def get_ledger_entries(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Find wallet
    result = await db.execute(select(Wallet).where(Wallet.user_id == current_user.id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        return []
    ledger_query = (
        select(LedgerEntry)
        .where(LedgerEntry.wallet_id == wallet.id)
        .order_by(LedgerEntry.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    ledger_result = await db.execute(ledger_query)
    entries = ledger_result.scalars().all()
    return [
        {
            "id": str(e.id),
            "type": e.entry_type.value,
            "amount_cents": e.amount_cents,
            "shipment_id": str(e.shipment_id) if e.shipment_id else None,
            "description": e.description,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]

@router.post("/admin/deposit", response_model=dict)
async def admin_deposit(
    user_id: UUID,
    amount_cents: int,
    description: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    # Find user
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    wallet = await payment_engine.deposit_funds(db, user, amount_cents, description)
    return {
        "user_id": str(user.id),
        "available_balance_cents": wallet.available_balance_cents,
        "locked_balance_cents": wallet.locked_balance_cents,
    }