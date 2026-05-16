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
from app.models.order import Order, OrderStatus   # PaymentMode no longer needed
from app.models.shipment import Shipment, ShipmentStatus
from app.core import matching_engine, payment_engine

router = APIRouter(prefix="/orders", tags=["orders"])

class OrderCreate(BaseModel):
    quantity_bags: int = Field(gt=0)
    delivery_location: str
    crop: str = "potatoes"
    manual_payment: bool = False

@router.post("/", response_model=dict)
async def place_order(
    order_data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.BUYER, UserRole.ADMIN)),
):
    # Manual payment path: no funds reserved, no automatic matching
    if order_data.manual_payment:
        order = Order(
            id=uuid.uuid4(),
            buyer_id=current_user.id,
            quantity_bags=order_data.quantity_bags,
            delivery_location=order_data.delivery_location,
            crop=order_data.crop,
            status=OrderStatus.PENDING,
            payment_mode="MANUAL_CALL",          # string, not enum
            price_per_bag=0,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        return _order_to_dict(order)

    # Automatic (escrow) path: require sufficient balance
    wallet = await payment_engine.get_or_create_wallet(db, current_user)
    total_needed = order_data.quantity_bags * matching_engine.DEFAULT_PRICE_PER_BAG
    if wallet.available_balance_cents < total_needed:
        raise HTTPException(status_code=402, detail="Insufficient funds")

    order = Order(
        id=uuid.uuid4(),
        buyer_id=current_user.id,
        quantity_bags=order_data.quantity_bags,
        delivery_location=order_data.delivery_location,
        crop=order_data.crop,
        status=OrderStatus.PENDING,
        payment_mode="AUTO_ESCROW",              # string
        price_per_bag=0,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    # Immediately try to match this order
    await matching_engine.match_pending_orders(db)
    await db.refresh(order)

    return _order_to_dict(order)

@router.get("/", response_model=List[dict])
async def list_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.buyer_id == current_user.id).order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    return [_order_to_dict(o) for o in orders]

@router.get("/all", response_model=List[dict])
async def list_all_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(select(Order).order_by(Order.created_at.desc()))
    orders = result.scalars().all()
    return [_order_to_dict(o) for o in orders]

@router.post("/{order_id}/cancel", response_model=dict)
async def cancel_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order_result = await db.execute(select(Order).where(Order.id == order_id, Order.buyer_id == current_user.id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in (OrderStatus.PENDING, OrderStatus.RESERVED):
        raise HTTPException(status_code=400, detail="Cannot cancel order in current state")

    if order.status == OrderStatus.RESERVED:
        shipment_result = await db.execute(select(Shipment).where(Shipment.id == order.shipment_id))
        shipment = shipment_result.scalar_one_or_none()
        if shipment and shipment.status == ShipmentStatus.LOCKED:
            raise HTTPException(status_code=400, detail="Order is locked in a shipment, cannot cancel")
        total_reserved = order.quantity_bags * order.price_per_bag
        await payment_engine.release_reservation(db, current_user, total_reserved, order.shipment_id)
    order.status = OrderStatus.CANCELLED
    await db.commit()
    return {"message": "Order cancelled"}

@router.post("/trigger-matching", response_model=dict)
async def trigger_matching(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    await matching_engine.match_pending_orders(db)
    return {"message": "Matching completed"}

def _order_to_dict(order: Order) -> dict:
    return {
        "id": str(order.id),
        "buyer_id": str(order.buyer_id),
        "shipment_id": str(order.shipment_id) if order.shipment_id else None,
        "status": order.status.value,
        "quantity_bags": order.quantity_bags,
        "price_per_bag": order.price_per_bag,
        "delivery_location": order.delivery_location,
        "crop": order.crop,
        "created_at": order.created_at.isoformat(),
        "payment_mode": order.payment_mode,      # already a string
    }