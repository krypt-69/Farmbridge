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
from app.models.shipment import Shipment, ShipmentStatus
from app.models.verification import VerificationReport, VerificationStatus
from app.utils.idempotency import ensure_idempotent, check_idempotency
from app.utils.gps import is_within_radius
from app.core import shipment_engine

router = APIRouter(prefix="/verifications", tags=["verifications"])

class VerificationSubmit(BaseModel):
    shipment_id: UUID
    farmer_id: UUID
    operation_id: UUID = Field(description="Unique client‑generated operation ID")
    claimed_quantity_bags: int
    actual_quantity_bags: Optional[int] = None
    quality_notes: Optional[str] = None
    image_urls: Optional[List[str]] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    status: VerificationStatus = VerificationStatus.PENDING  # agent can set APPROVED/ADJUSTED/REJECTED

@router.post("/submit", response_model=dict)
async def submit_verification(
    report: VerificationSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
):
    # 1. Idempotency check
    existing = await check_idempotency(db, report.operation_id)
    if existing:
        return _report_to_dict(existing)

    # 2. Validate shipment exists and is in VERIFYING state
    shipment_result = await db.execute(
        select(Shipment).where(Shipment.id == report.shipment_id)
    )
    shipment = shipment_result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if shipment.status != ShipmentStatus.VERIFYING:
        raise HTTPException(
            status_code=400,
            detail="Shipment is not in VERIFYING state",
        )

    # 3. Basic GPS validation (if agent provides coordinates and we have shipment region centre)
    if report.gps_latitude is not None and report.gps_longitude is not None:
        # For now, compare with a dummy farm location (we'll later fetch from a farmer listing)
        # We'll just log that coordinates were provided – no strict rejections yet.
        pass  # future: call is_within_radius with farmer listing coordinates

    # 4. Create verification report
    new_report = VerificationReport(
        id=uuid.uuid4(),
        agent_id=current_user.id,
        farmer_id=report.farmer_id,
        shipment_id=report.shipment_id,
        operation_id=report.operation_id,
        status=report.status,
        claimed_quantity_bags=report.claimed_quantity_bags,
        actual_quantity_bags=report.actual_quantity_bags,
        quality_notes=report.quality_notes,
        image_urls=report.image_urls,
        gps_latitude=report.gps_latitude,
        gps_longitude=report.gps_longitude,
        client_timestamp=...,  # we'll take client timestamp from request? The model expects a datetime; we can ask client to send it or use server time. We'll take an optional field.
    )
    # We'll add a field from the client if they send it; for now we'll set to current server time.
    # The model expects client_timestamp (non-null). We'll use server time if not provided.
    from datetime import datetime, timezone
    new_report.client_timestamp = datetime.now(timezone.utc)
    db.add(new_report)

    # 5. Recalculate shipment composition (if APPROVED or ADJUSTED, update actual_quantity_bags)
    # For simplicity, we'll just log; later we can aggregate.
    if report.status == VerificationStatus.APPROVED:
        # Assume the farmer's contributed bags are exactly claimed
        shipment.actual_quantity_bags = (shipment.actual_quantity_bags or 0) + report.claimed_quantity_bags
    elif report.status == VerificationStatus.ADJUSTED:
        if report.actual_quantity_bags:
            shipment.actual_quantity_bags = (shipment.actual_quantity_bags or 0) + report.actual_quantity_bags
        else:
            raise HTTPException(status_code=400, detail="Adjusted verification requires actual_quantity_bags")

    await db.commit()
    await db.refresh(new_report)
    return _report_to_dict(new_report)


@router.get("/", response_model=List[dict])
async def list_verifications(
    shipment_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(VerificationReport)
    if shipment_id:
        query = query.where(VerificationReport.shipment_id == shipment_id)
    result = await db.execute(query)
    reports = result.scalars().all()
    return [_report_to_dict(r) for r in reports]


@router.get("/{report_id}", response_model=dict)
async def get_verification(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VerificationReport).where(VerificationReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return _report_to_dict(report)


def _report_to_dict(r: VerificationReport) -> dict:
    return {
        "id": str(r.id),
        "agent_id": str(r.agent_id),
        "farmer_id": str(r.farmer_id),
        "shipment_id": str(r.shipment_id),
        "operation_id": str(r.operation_id),
        "status": r.status.value,
        "claimed_quantity_bags": r.claimed_quantity_bags,
        "actual_quantity_bags": r.actual_quantity_bags,
        "quality_notes": r.quality_notes,
        "image_urls": r.image_urls,
        "gps_latitude": r.gps_latitude,
        "gps_longitude": r.gps_longitude,
    }