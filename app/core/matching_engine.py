import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.order import Order, OrderStatus
from app.models.shipment import Shipment, ShipmentStatus
from app.core.payment_engine import reserve_funds, release_reservation

DEFAULT_PRICE_PER_BAG = 500000  # 5000 KES in cents

async def match_pending_orders(db: AsyncSession):
    """Try to match all pending orders to open shipments."""
    orders_query = select(Order).where(Order.status == OrderStatus.PENDING).options(selectinload(Order.buyer))
    result = await db.execute(orders_query)
    pending_orders = result.scalars().all()

    for order in pending_orders:
        shipment = await find_suitable_shipment(db, order)
        if shipment:
            await assign_order_to_shipment(db, order, shipment)
            await maybe_lock_shipment(db, shipment)
    await db.commit()

async def find_suitable_shipment(db: AsyncSession, order: Order) -> Optional[Shipment]:
    """Find a MATCHING shipment in same region and crop with enough remaining capacity."""
    query = select(Shipment).where(
        Shipment.status == ShipmentStatus.MATCHING,
        Shipment.region == order.delivery_location,   # we treat delivery_location as region for now
        Shipment.crop == order.crop,
    )
    result = await db.execute(query)
    shipments = result.scalars().all()

    for shipment in shipments:
        # Sum reserved bags from orders already in this shipment
        orders_sum = await db.execute(
            select(Order).where(
                Order.shipment_id == shipment.id,
                Order.status == OrderStatus.RESERVED,
            )
        )
        orders_list = orders_sum.scalars().all()
        total_reserved = sum(o.quantity_bags for o in orders_list)
        remaining = shipment.target_quantity_bags - total_reserved
        if remaining >= order.quantity_bags:
            return shipment
    return None

async def assign_order_to_shipment(db: AsyncSession, order: Order, shipment: Shipment):
    """Assign order to shipment, reserve buyer's funds."""
    order.price_per_bag = DEFAULT_PRICE_PER_BAG
    order.shipment_id = shipment.id
    order.status = OrderStatus.RESERVED

    total_amount = order.quantity_bags * DEFAULT_PRICE_PER_BAG
    await reserve_funds(db, order.buyer, total_amount, shipment.id)

async def maybe_lock_shipment(db: AsyncSession, shipment: Shipment):
    """If shipment target is reached, lock it."""
    orders_list = await db.execute(
        select(Order).where(
            Order.shipment_id == shipment.id,
            Order.status == OrderStatus.RESERVED,
        )
    )
    total = sum(o.quantity_bags for o in orders_list.scalars().all())
    if total >= shipment.target_quantity_bags:
        from app.core.shipment_engine import lock_shipment
        await lock_shipment(db, shipment)