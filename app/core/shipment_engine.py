from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.shipment import Shipment, ShipmentStatus, ShipmentFailureCategory
from app.models.ledger import LedgerEntry, LedgerEntryType
from app.core import payment_engine
from app.workers.tasks.firestore_sync import sync_shipment_task
import uuid
from app.models.audit import AuditLog
from app.models.user import User
from sqlalchemy import select as sa_select
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
    shipment.grace_period_end = now + timedelta(hours=1)

    # ---------- NEW: freeze pricing snapshot ----------
    from app.models.pricing import PricingConfig
    from sqlalchemy import select as sa_select

    # Try exact region/crop match
    pricing_result = await db.execute(
        sa_select(PricingConfig).where(
            PricingConfig.region == shipment.region,
            PricingConfig.crop == shipment.crop,
        )
    )
    pricing = pricing_result.scalar_one_or_none()
    if not pricing:
        # Try region with crop=NULL
        pricing_result = await db.execute(
            sa_select(PricingConfig).where(
                PricingConfig.region == shipment.region,
                PricingConfig.crop == None,
            )
        )
        pricing = pricing_result.scalar_one_or_none()
    if not pricing:
        # Global default
        pricing_result = await db.execute(
            sa_select(PricingConfig).where(
                PricingConfig.region == None,
                PricingConfig.crop == None,
            )
        )
        pricing = pricing_result.scalar_one_or_none()

    if pricing:
        shipment.extra_data = {
            "pricing_snapshot": {
                "base_market_price_cents": pricing.base_market_price_cents,
                "platform_fee_cents": pricing.platform_fee_cents,
                "transport_fee_cents": pricing.transport_fee_cents,
                "buyer_discount_cents": pricing.buyer_discount_cents,
                "buyer_price_per_bag": pricing.base_market_price_cents - pricing.buyer_discount_cents,
                "farmer_payout_per_bag": pricing.base_market_price_cents - pricing.platform_fee_cents - pricing.transport_fee_cents,
            }
        }
    # ------------------------------------------------

    await db.commit()
    await db.refresh(shipment)
    sync_shipment_task.delay(str(shipment.id))
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
    sync_shipment_task.delay(str(shipment.id))
    return shipment

async def depart_shipment(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.IN_TRANSIT)
    shipment.status = ShipmentStatus.IN_TRANSIT
    shipment.departed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    sync_shipment_task.delay(str(shipment.id))
    return shipment

async def arrive_urban(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.ARRIVED_URBAN)
    shipment.status = ShipmentStatus.ARRIVED_URBAN
    shipment.arrived_urban_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    sync_shipment_task.delay(str(shipment.id))
    return shipment

async def deliver_shipment(db: AsyncSession, shipment: Shipment) -> Shipment:
    validate_transition(shipment.status, ShipmentStatus.DELIVERED)
    shipment.status = ShipmentStatus.DELIVERED
    shipment.delivered_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shipment)
    sync_shipment_task.delay(str(shipment.id))
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

    # Reverse all locked funds for deterministic failures
    if category in (
        ShipmentFailureCategory.TIMEOUT,
        ShipmentFailureCategory.INSUFFICIENT_SUPPLY,
    ):
        from app.models.order import Order, OrderStatus
        orders_query = select(Order).where(
            Order.shipment_id == shipment.id,
            Order.status == OrderStatus.RESERVED,
        ).options(selectinload(Order.buyer))
        result = await db.execute(orders_query)
        orders = result.scalars().all()
        for order in orders:
            total_reserved = order.quantity_bags * order.price_per_bag
            buyer = order.buyer
            wallet = await payment_engine.get_or_create_wallet(db, buyer)
            wallet.locked_balance_cents -= total_reserved
            wallet.available_balance_cents += total_reserved
            entry = LedgerEntry(
                id=uuid.uuid4(),
                wallet_id=wallet.id,
                shipment_id=shipment.id,
                entry_type=LedgerEntryType.RESERVATION_REVERSAL,
                amount_cents=total_reserved,
                description=f"Auto-reversal for failed shipment {shipment.id}",
            )
            db.add(entry)
            order.status = OrderStatus.CANCELLED

    await db.commit()
    await db.refresh(shipment)
    sync_shipment_task.delay(str(shipment.id))
    return shipment

async def admin_override_transition(
    db: AsyncSession,
    shipment: Shipment,
    new_status: ShipmentStatus,
    admin_user: User,
    reason: Optional[str] = None,
) -> Shipment:
    """Admin forced transition with relaxed rules, with mandatory audit logging."""
    # Prevent impossible jumps
    if new_status == ShipmentStatus.DELIVERED and shipment.status != ShipmentStatus.ARRIVED_URBAN:
        raise InvalidStateTransition("Cannot override to DELIVERED unless previous is ARRIVED_URBAN")
    if new_status == ShipmentStatus.IN_TRANSIT and shipment.status not in (ShipmentStatus.LOADING,):
        raise InvalidStateTransition("Must be LOADING to go IN_TRANSIT")

    # Capture old status for audit
    old_status = shipment.status

    # Override state
    shipment.status = new_status
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

    # Record the override in the audit log
    audit = AuditLog(
        id=uuid.uuid4(),
        admin_id=admin_user.id,
        action="shipment_override",
        entity_type="shipment",
        entity_id=str(shipment.id),
        details=f"Status changed from {old_status.value} to {new_status.value}. Reason: {reason or 'No reason provided'}",
    )
    db.add(audit)

    await db.commit()
    await db.refresh(shipment)
    sync_shipment_task.delay(str(shipment.id))
    return shipment