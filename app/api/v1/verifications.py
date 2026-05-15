import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.shipment import Shipment, ShipmentStatus
from app.models.verification import VerificationReport, VerificationStatus
from app.models.harvest import Harvest, HarvestStatus
from app.utils.idempotency import check_idempotency
from app.core.gps_validation import validate_agent_location

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
    status: VerificationStatus = VerificationStatus.PENDING
    harvest_id: Optional[UUID] = None   # NEW: link to specific harvest

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

    # 3. If harvest_id provided, validate it and enforce GPS
    if report.harvest_id:
        harvest_result = await db.execute(
            select(Harvest).where(Harvest.id == report.harvest_id)
        )
        harvest = harvest_result.scalar_one_or_none()
        if not harvest:
            raise HTTPException(status_code=404, detail="Harvest not found")
        if harvest.farmer_id != report.farmer_id:
            raise HTTPException(
                status_code=400,
                detail="Harvest does not belong to the given farmer",
            )
        # GPS enforcement if both harvest and agent coordinates present
        if (
            harvest.latitude is not None
            and harvest.longitude is not None
            and report.gps_latitude is not None
            and report.gps_longitude is not None
        ):
            validate_agent_location(
                report.gps_latitude,
                report.gps_longitude,
                harvest.latitude,
                harvest.longitude,
                max_distance_m=5000.0,  # 5 km radius
            )

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
        harvest_id=report.harvest_id,   # new field
        client_timestamp=datetime.now(timezone.utc),
    )
    db.add(new_report)

    # 5. Update shipment and harvest based on verification result
    if report.status == VerificationStatus.APPROVED:
        shipment.actual_quantity_bags = (
            shipment.actual_quantity_bags or 0
        ) + report.claimed_quantity_bags
        if report.harvest_id:
            harvest.status = HarvestStatus.VERIFIED
            harvest.actual_quantity_bags = report.claimed_quantity_bags
    elif report.status == VerificationStatus.ADJUSTED:
        if not report.actual_quantity_bags:
            raise HTTPException(
                status_code=400,
                detail="Adjusted verification requires actual_quantity_bags",
            )
        shipment.actual_quantity_bags = (
            shipment.actual_quantity_bags or 0
        ) + report.actual_quantity_bags
        if report.harvest_id:
            harvest.status = HarvestStatus.VERIFIED
            harvest.actual_quantity_bags = report.actual_quantity_bags
    # (REJECTED does not change quantity)

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
        "harvest_id": str(r.harvest_id) if r.harvest_id else None,
    }