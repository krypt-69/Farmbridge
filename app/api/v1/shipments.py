from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.shipment import Shipment, ShipmentStatus, ShipmentFailureCategory
from app.core import shipment_engine

router = APIRouter(prefix="/shipments", tags=["shipments"])

# Helper to convert shipment to dict
def shipment_to_dict(s: Shipment) -> dict:
    return {
        "id": str(s.id),
        "status": s.status.value,
        "failure_category": s.failure_category.value if s.failure_category else None,
        "region": s.region,
        "crop": s.crop,
        "target_quantity_bags": s.target_quantity_bags,
        "actual_quantity_bags": s.actual_quantity_bags,
        "created_at": s.created_at.isoformat(),
        "locked_at": s.locked_at.isoformat() if s.locked_at else None,
        "grace_period_end": s.grace_period_end.isoformat() if s.grace_period_end else None,
        "matching_timeout": s.matching_timeout.isoformat() if s.matching_timeout else None,
        "verification_started_at": s.verification_started_at.isoformat() if s.verification_started_at else None,
        "loading_at": s.loading_at.isoformat() if s.loading_at else None,
        "departed_at": s.departed_at.isoformat() if s.departed_at else None,
        "arrived_urban_at": s.arrived_urban_at.isoformat() if s.arrived_urban_at else None,
        "delivered_at": s.delivered_at.isoformat() if s.delivered_at else None,
        "failed_at": s.failed_at.isoformat() if s.failed_at else None,
        "extra_data": s.extra_data,
    }

@router.post("/", response_model=dict)
async def create_shipment(
    region: str,
    crop: str = "potatoes",
    target_quantity_bags: int = 50,
    matching_timeout_minutes: int = 1440,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    shipment = await shipment_engine.create_shipment(
        db, region, crop, target_quantity_bags, matching_timeout_minutes
    )
    return shipment_to_dict(shipment)

@router.get("/", response_model=List[dict])
async def list_shipments(
    status: Optional[ShipmentStatus] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Shipment)
    if status:
        query = query.where(Shipment.status == status)
    result = await db.execute(query)
    shipments = result.scalars().all()
    return [shipment_to_dict(s) for s in shipments]

@router.get("/{shipment_id}", response_model=dict)
async def get_shipment(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment_to_dict(shipment)

# Admin transition endpoint: /shipments/{id}/state
@router.post("/{shipment_id}/state", response_model=dict)
async def transition_shipment(
    shipment_id: UUID,
    action: str,        # "lock", "start_verification", "start_loading", "depart", "arrive_urban", "deliver", "fail"
    failure_category: Optional[ShipmentFailureCategory] = None,
    override: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    try:
        if override:
            # Admin override with new_status based on action string
            new_status = ShipmentStatus(action)
            shipment = await shipment_engine.admin_override_transition(
                db, shipment, new_status, current_user, reason=None   # you can add a query param for reason later
            )
        else:
            # Standard transitions
            if action == "lock":
                shipment = await shipment_engine.lock_shipment(db, shipment)
            elif action == "start_verification":
                shipment = await shipment_engine.start_verification(db, shipment)
            elif action == "start_loading":
                shipment = await shipment_engine.start_loading(db, shipment)
            elif action == "depart":
                shipment = await shipment_engine.depart_shipment(db, shipment)
            elif action == "arrive_urban":
                shipment = await shipment_engine.arrive_urban(db, shipment)
            elif action == "deliver":
                shipment = await shipment_engine.deliver_shipment(db, shipment)
            elif action == "fail":
                if not failure_category:
                    failure_category = ShipmentFailureCategory.OPERATIONAL_INCONSISTENCY
                shipment = await shipment_engine.fail_shipment(db, shipment, failure_category)
            else:
                raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    except shipment_engine.InvalidStateTransition as e:
        raise HTTPException(status_code=400, detail=str(e))

    return shipment_to_dict(shipment)