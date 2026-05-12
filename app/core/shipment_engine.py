from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.shipment import Shipment, ShipmentStatus, ShipmentFailureCategory
import uuid
from app.core.payment_engine import process_shipment_failure_financials
class InvalidStateTransition(Exception):
    pass

LEGAL_TRANSITIONS = {
    ShipmentStatus.MATCHING: {ShipmentStatus.LOCKED, ShipmentStatus.FAILED},
    ShipmentStatus.LOCKED: {ShipmentStatus.VERIFYING, ShipmentStatus.FAILED},
    ShipmentStatus.VERIFYING: {ShipmentStatus.LOADING, ShipmentStatus.FAILED},
    ShipmentStatus.LOADING: {ShipmentStatus.IN_TRANSIT, ShipmentStatus.FAILED},
    ShipmentStatus.IN_TRANSIT: {ShipmentStatus.ARRIVED_URBAN, ShipmentStatus.FAILED},
    ShipmentStatus.ARRIVED_URBAN: {ShipmentStatus.DELIVERED, ShipmentStatus.FAILED},
    # DELIVERED and FAILED are terminal
}

def validate_transition(current: ShipmentStatus, new: ShipmentStatus):
    if new not in LEGAL_TRANSITIONS.get(current, set()):
        raise InvalidStateTransition(f"Cannot transition from {current.value} to {new.value}")

async def create_shipment(
    db: AsyncSession,
    region: str,
    crop: str = "potatoes",
    target_quantity_bags: int = 50,
    matching_timeout_minutes: int = 1440,  # 24 hours
) -> Shipment:
    shipment = Shipment(
        id=uuid.uuid4(),
        status=ShipmentStatus.MATCHING,
        region=region,
        crop=crop,
        target_quantity_bags=target_quantity_bags,
        matching_timeout=datetime.now(timezone.utc) + timedelta(minutes=matching_timeout_minutes),
    )
    db.add(shipment)
    await db.commit()
    await db.refresh(shipment)
    return shipment

async def lock_shipment(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.LOCKED)
    now = datetime.now(timezone.utc)
    shipment.status = ShipmentStatus.LOCKED
    shipment.locked_at = now
    # set grace period end (e.g., 1 hour)
    shipment.grace_period_end = now + timedelta(hours=1)
    await db.commit()
    await db.refresh(shipment)
    return shipment

async def start_verification(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.VERIFYING)
    shipment.status = ShipmentStatus.VERIFYING
    shipment.verification_started_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    return shipment

async def start_loading(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.LOADING)
    shipment.status = ShipmentStatus.LOADING
    shipment.loading_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    return shipment

async def depart_shipment(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.IN_TRANSIT)
    shipment.status = ShipmentStatus.IN_TRANSIT
    shipment.departed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    return shipment

async def arrive_urban(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.ARRIVED_URBAN)
    shipment.status = ShipmentStatus.ARRIVED_URBAN
    shipment.arrived_urban_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    return shipment

async def deliver_shipment(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.DELIVERED)
    shipment.status = ShipmentStatus.DELIVERED
    shipment.delivered_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    return shipment

async def fail_shipment(
    db: AsyncSession,
    shipment: Shipment,
    category: ShipmentFailureCategory,
) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.FAILED)
    shipment.status = ShipmentStatus.FAILED
    shipment.failure_category = category
    shipment.failed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    # In future: trigger refund/reversal logic
    return shipment

async def admin_override_transition(
    db: AsyncSession,
    shipment: Shipment,
    new_status: ShipmentStatus,
    reason: Optional[str] = None,
) -> Shipment:
    """Admin forced transition with relaxed rules."""
    # Prevent impossible jumps (e.g., MATCHING -> DELIVERED)
    if new_status == ShipmentStatus.DELIVERED and shipment.status != ShipmentStatus.ARRIVED_URBAN:
        raise InvalidStateTransition("Cannot override to DELIVERED unless previous is ARRIVED_URBAN")
    if new_status == ShipmentStatus.IN_TRANSIT and shipment.status not in (ShipmentStatus.LOADING,):
        raise InvalidStateTransition("Must be LOADING to go IN_TRANSIT")
    # All other admin overrides allowed if they don't break core flow
    # Override state
    shipment.status = new_status
    # Optionally set timestamp if applicable
    now = datetime.now(timezone.utc)
    if new_status == ShipmentStatus.LOCKED:
        shipment.locked_at = now
        shipment.grace_period_end = now + timedelta(hours=1)
    elif new_status == ShipmentStatus.VERIFYING:
        shipment.verification_started_at = now
    elif new_status == ShipmentStatus.LOADING:
        shipment.loading_at = now
    elif new_status == ShipmentStatus.IN_TRANSIT:
        shipment.departed_at = now
    elif new_status == ShipmentStatus.ARRIVED_URBAN:
        shipment.arrived_urban_at = now
    elif new_status == ShipmentStatus.DELIVERED:
        shipment.delivered_at = now
    elif new_status == ShipmentStatus.FAILED:
        shipment.failed_at = now
        if not shipment.failure_category:
            shipment.failure_category = ShipmentFailureCategory.OPERATIONAL_INCONSISTENCY
    # Log audit entry (future)
    await db.commit()
    await db.refresh(shipment)
        # Process financial reversals if deterministic
    await process_shipment_failure_financials(db, shipment)
    return shipment