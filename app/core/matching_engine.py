import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from app.models.order import Order, OrderStatus
from app.models.shipment import Shipment, ShipmentStatus
from app.models.harvest import Harvest, HarvestStatus
from app.models.pricing import PricingConfig
from app.models.user import User   # <-- added import
from app.core.payment_engine import reserve_funds, release_reservation
from app.core.shipment_engine import lock_shipment
from app.utils.gps import haversine_distance
from datetime import datetime, timezone, timedelta


DEFAULT_PRICE_PER_BAG = 500000
# Maximum distance (metres) between harvests to be grouped in the same shipment
MAX_CLUSTER_DISTANCE_M = 15_000   # 15 km
# Maximum days spread between harvest dates in the same shipment
MAX_HARVEST_TIME_SPREAD_DAYS = 3
async def match_pending_orders(db: AsyncSession):
    """Try to match all pending orders to open shipments, then match harvests."""
    # --- Orders matching (unchanged) ---
    orders_query = select(Order).where(Order.status == OrderStatus.PENDING).options(selectinload(Order.buyer))
    result = await db.execute(orders_query)
    pending_orders = result.scalars().all()

    for order in pending_orders:
        shipment = await find_suitable_shipment(db, order)
        if shipment:
            await assign_order_to_shipment(db, order, shipment)
            await maybe_lock_shipment(db, shipment)
    # --- Harvest matching (new) ---
    await match_harvests_to_shipments(db)
    await db.commit()


async def find_suitable_shipment(db: AsyncSession, order: Order) -> Optional[Shipment]:
    """Find a MATCHING shipment in same region and crop with enough remaining capacity."""
    query = select(Shipment).where(
        Shipment.status == ShipmentStatus.MATCHING,
        Shipment.region == order.delivery_location,
        Shipment.crop == order.crop,
    )
    result = await db.execute(query)
    shipments = result.scalars().all()

    for shipment in shipments:
        total_reserved = await _get_total_committed_bags(db, shipment.id)
        remaining = shipment.target_quantity_bags - total_reserved
        if remaining >= order.quantity_bags:
            return shipment
    return None


async def find_suitable_shipment_for_harvest(db, harvest):
    """Find a MATCHING shipment in same region/crop with enough remaining capacity."""
    query = select(Shipment).where(
        Shipment.status == ShipmentStatus.MATCHING,
        Shipment.region == harvest.region,
        Shipment.crop == harvest.crop,
    )
    shipments = (await db.execute(query)).scalars().all()

    for shipment in shipments:
        total_committed = await _get_total_committed_bags(db, shipment.id)
        if total_committed + harvest.quantity_bags <= shipment.target_quantity_bags:
            return shipment
    return None


async def _get_total_committed_bags(db, shipment_id):
    """Return the total bags already committed (orders + matched harvests) for a shipment."""
    total_orders = await db.execute(
        select(func.coalesce(func.sum(Order.quantity_bags), 0)).where(
            Order.shipment_id == shipment_id,
            Order.status == OrderStatus.RESERVED,
        )
    )
    total_harvests = await db.execute(
        select(func.coalesce(func.sum(Harvest.quantity_bags), 0)).where(
            Harvest.shipment_id == shipment_id,
            Harvest.status == HarvestStatus.MATCHED,
        )
    )
    return total_orders.scalar() + total_harvests.scalar()
async def _is_harvest_near_shipment_cluster(
    db: AsyncSession,
    shipment: Shipment,
    harvest: Harvest,
    max_distance_m: int = MAX_CLUSTER_DISTANCE_M,
) -> bool:
    """
    Return True if the harvest's GPS is within max_distance_m of any harvest
    already assigned to the shipment. If no harvests are assigned yet, always return True.
    """
    if harvest.latitude is None or harvest.longitude is None:
        return False   # cannot determine distance, exclude

    # Get all harvests already assigned to this shipment
    assigned = (await db.execute(
        select(Harvest).where(
            Harvest.shipment_id == shipment.id,
            Harvest.status == HarvestStatus.MATCHED,
            Harvest.latitude != None,
            Harvest.longitude != None,
        )
    )).scalars().all()

    if not assigned:
        # No harvests in the cluster yet, always accept the first one
        return True

    for a in assigned:
        d = haversine_distance(
            harvest.latitude, harvest.longitude,
            a.latitude, a.longitude,
        )
        if d <= max_distance_m:
            return True
    return False
async def _is_harvest_within_time_window(
    db: AsyncSession,
    shipment: Shipment,
    harvest: Harvest,
    max_days: int = MAX_HARVEST_TIME_SPREAD_DAYS,
) -> bool:
    """
    Return True if the harvest's expected date (or today if missing)
    is within max_days of the earliest harvest already in the shipment.
    """
    # Determine the candidate's effective date
    candidate_date = harvest.expected_harvest_date or datetime.now(timezone.utc)

    # Get the earliest date among already matched harvests
    assigned = (await db.execute(
        select(Harvest).where(
            Harvest.shipment_id == shipment.id,
            Harvest.status == HarvestStatus.MATCHED,
            Harvest.expected_harvest_date != None,
        )
    )).scalars().all()

    if not assigned:
        # No harvests with dates yet – accept the first one
        return True

    # Find the earliest date in the cluster
    earliest = min(
        (h.expected_harvest_date for h in assigned if h.expected_harvest_date is not None),
        default=None,
    )
    if earliest is None:
        return True   # no dates in cluster, accept

    # Compare
    diff = abs((candidate_date - earliest).days)
    return diff <= max_days


async def match_harvests_to_shipments(db: AsyncSession):
    """Assign pending harvests to matching shipments if they fit, are near, and within time window."""
    pending_harvests = (await db.execute(
        select(Harvest)
        .where(Harvest.status == HarvestStatus.PENDING)
        .order_by(Harvest.expected_harvest_date.asc().nullsfirst())
    )).scalars().all()
    for harvest in pending_harvests:
        shipment = await find_suitable_shipment_for_harvest(db, harvest)
        if shipment:
            # Check proximity
            if not await _is_harvest_near_shipment_cluster(db, shipment, harvest):
                continue
            # Check time window
            if not await _is_harvest_within_time_window(db, shipment, harvest):
                continue
            # All checks passed → assign
            harvest.shipment_id = shipment.id
            harvest.status = HarvestStatus.MATCHED
            await db.flush()
            await maybe_lock_shipment(db, shipment)


async def assign_order_to_shipment(db: AsyncSession, order: Order, shipment: Shipment):
    # Fetch pricing for this region/crop
    pricing = await get_pricing_for(db, order.delivery_location, order.crop)
    buyer_price = pricing.base_market_price_cents - pricing.buyer_discount_cents
    order.price_per_bag = buyer_price
    order.shipment_id = shipment.id
    order.status = OrderStatus.RESERVED

    total_amount = order.quantity_bags * buyer_price
    await reserve_funds(db, order.buyer, total_amount, shipment.id)


async def maybe_lock_shipment(db: AsyncSession, shipment: Shipment):
    total_bags = await _get_total_committed_bags(db, shipment.id)
    if total_bags >= shipment.target_quantity_bags:
        await lock_shipment(db, shipment)


async def get_pricing_for(db: AsyncSession, region: str, crop: str) -> PricingConfig:
    # Try exact match
    result = await db.execute(
        select(PricingConfig).where(
            PricingConfig.region == region, PricingConfig.crop == crop
        )
    )
    config = result.scalar_one_or_none()
    if config:
        return config
    # Try region with crop=None
    result = await db.execute(
        select(PricingConfig).where(
            PricingConfig.region == region, PricingConfig.crop == None
        )
    )
    config = result.scalar_one_or_none()
    if config:
        return config
    # Global default
    result = await db.execute(
        select(PricingConfig).where(
            PricingConfig.region == None, PricingConfig.crop == None
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise ValueError("No pricing configuration found")
    return config