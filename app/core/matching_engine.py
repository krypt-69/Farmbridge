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
from app.core.payment_engine import reserve_funds, release_reservation
from app.core.shipment_engine import lock_shipment   # <--- ADD THIS LINE

DEFAULT_PRICE_PER_BAG = 500000

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


async def match_harvests_to_shipments(db: AsyncSession):
    """Assign pending harvests to matching shipments if they fit."""
    pending_harvests = (await db.execute(
        select(Harvest).where(Harvest.status == HarvestStatus.PENDING)
    )).scalars().all()

    for harvest in pending_harvests:
        shipment = await find_suitable_shipment_for_harvest(db, harvest)
        if shipment:
            harvest.shipment_id = shipment.id
            harvest.status = HarvestStatus.MATCHED
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