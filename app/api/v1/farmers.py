import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.harvest import Harvest, HarvestStatus
from app.models.verification import VerificationReport
from datetime import datetime, timezone
from dateutil import parser  

router = APIRouter(prefix="/farmers", tags=["farmers"])

# ---------- Schemas ----------
class HarvestCreate(BaseModel):
    crop: str = "potatoes"
    quantity_bags: int = Field(gt=0)
    region: str
    expected_harvest_date: Optional[str] = None  # ISO format

# ---------- Harvest Endpoints ----------
@router.post("/harvest", response_model=dict)
async def create_harvest(
    data: HarvestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FARMER)),
):
    # Convert expected_harvest_date from string to datetime if provided
    harvest_date = None
    if data.expected_harvest_date:
        try:
            harvest_date = parser.isoparse(data.expected_harvest_date)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Invalid expected_harvest_date format. Use ISO 8601 (e.g., 2026-06-01T00:00:00Z)",
            )

    harvest = Harvest(
        id=uuid.uuid4(),
        farmer_id=current_user.id,
        crop=data.crop,
        quantity_bags=data.quantity_bags,
        region=data.region,
        expected_harvest_date=harvest_date,
        status=HarvestStatus.PENDING,
    )
    db.add(harvest)
    await db.commit()
    await db.refresh(harvest)
    return _harvest_to_dict(harvest)

@router.get("/harvests", response_model=List[dict])
async def list_harvests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FARMER)),
):
    result = await db.execute(
        select(Harvest).where(Harvest.farmer_id == current_user.id).order_by(Harvest.created_at.desc())
    )
    harvests = result.scalars().all()
    return [_harvest_to_dict(h) for h in harvests]

# ---------- Verification Endpoints for Farmer ----------
@router.get("/verifications", response_model=List[dict])
async def list_my_verifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FARMER)),
):
    result = await db.execute(
        select(VerificationReport)
        .where(VerificationReport.farmer_id == current_user.id)
        .order_by(VerificationReport.server_timestamp.desc())
    )
    reports = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "agent_id": str(r.agent_id),
            "shipment_id": str(r.shipment_id),
            "status": r.status.value,
            "claimed_quantity_bags": r.claimed_quantity_bags,
            "actual_quantity_bags": r.actual_quantity_bags,
            "quality_notes": r.quality_notes,
            "image_urls": r.image_urls,
            "gps_latitude": r.gps_latitude,
            "gps_longitude": r.gps_longitude,
            "client_timestamp": r.client_timestamp.isoformat(),
            "server_timestamp": r.server_timestamp.isoformat(),
        }
        for r in reports
    ]

def _harvest_to_dict(h: Harvest) -> dict:
    return {
        "id": str(h.id),
        "crop": h.crop,
        "quantity_bags": h.quantity_bags,
        "region": h.region,
        "expected_harvest_date": h.expected_harvest_date.isoformat() if h.expected_harvest_date else None,
        "status": h.status.value,
        "created_at": h.created_at.isoformat(),
    }