from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.models.order import Order, OrderStatus
from app.models.harvest import Harvest, HarvestStatus
from pydantic import BaseModel
from app.core.payment_engine import reserve_funds
from app.core.matching_engine import DEFAULT_PRICE_PER_BAG
from app.core.shipment_engine import lock_shipment
from app.models.shipment import Shipment, ShipmentStatus
from datetime import datetime, timezone, timedelta
from app.core import payment_engine
import uuid

class ManualShipmentCreate(BaseModel):
    region: str
    crop: str = "potatoes"
    target_quantity_bags: int = 50
    order_ids: List[UUID] = []
    harvest_ids: List[UUID] = []

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------- Audit Logs ----------
@router.get("/audit", response_model=List[dict])
async def list_audit_logs(
    entity_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "admin_id": str(log.admin_id),
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]

# ---------- User Management ----------
@router.get("/users", response_model=List[dict])
async def list_users(
    role: Optional[UserRole] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    query = select(User)
    if role:
        query = query.where(User.role == role)
    result = await db.execute(query)
    users = result.scalars().all()
    return [
        {
            "id": str(user.id),
            "firebase_uid": user.firebase_uid,
            "role": user.role.value,
            "phone": user.phone,
            "full_name": user.full_name,
            "is_active": user.is_active,
        }
        for user in users
    ]

@router.put("/users/{user_id}/role", response_model=dict)
async def update_user_role(
    user_id: UUID,
    new_role: UserRole,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    if current_user.id == user_id and new_role != UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = new_role
    await db.commit()
    return {"message": f"Role updated to {new_role.value}"}

@router.get("/pending-farmers", response_model=List[dict])
async def list_pending_farmers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(
        select(User).where(
            User.role == UserRole.FARMER,
            User.approval_status == "PENDING"
        )
    )
    farmers = result.scalars().all()
    return [
        {
            "id": str(f.id),
            "full_name": f.full_name,
            "phone": f.phone,
            "profile_picture_url": f.profile_picture_url,
        }
        for f in farmers
    ]

@router.post("/approve-farmer/{user_id}", response_model=dict)
async def approve_farmer(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.role != UserRole.FARMER:
        raise HTTPException(status_code=404, detail="Farmer not found")
    user.approval_status = "APPROVED"
    await db.commit()
    return {"message": "Farmer approved"}

@router.post("/reject-farmer/{user_id}", response_model=dict)
async def reject_farmer(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.role != UserRole.FARMER:
        raise HTTPException(status_code=404, detail="Farmer not found")
    user.approval_status = "REJECTED"
    user.is_active = False
    await db.commit()
    return {"message": "Farmer rejected"}

@router.get("/pending-orders", response_model=List[dict])
async def list_pending_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(
        select(Order).where(Order.status == OrderStatus.PENDING).order_by(Order.created_at)
    )
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "buyer_id": str(o.buyer_id),
            "quantity_bags": o.quantity_bags,
            "delivery_location": o.delivery_location,
            "crop": o.crop,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]

@router.get("/pending-harvests", response_model=List[dict])
async def list_pending_harvests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(
        select(Harvest).where(Harvest.status == HarvestStatus.PENDING).order_by(Harvest.created_at)
    )
    harvests = result.scalars().all()
    farmer_ids = set(h.farmer_id for h in harvests)
    farmers = (await db.execute(select(User).where(User.id.in_(farmer_ids)))).scalars().all()
    farmer_map = {f.id: f.full_name for f in farmers}
    return [
        {
            "id": str(h.id),
            "farmer_id": str(h.farmer_id),
            "farmer_name": farmer_map.get(h.farmer_id, "Unknown"),
            "crop": h.crop,
            "quantity_bags": h.quantity_bags,
            "region": h.region,
            "latitude": h.latitude,
            "longitude": h.longitude,
            "created_at": h.created_at.isoformat(),
        }
        for h in harvests
    ]

@router.post("/shipments", response_model=dict)
async def create_shipment_manual(
    data: ManualShipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    shipment = Shipment(
        id=uuid.uuid4(),
        status=ShipmentStatus.MATCHING,
        region=data.region,
        crop=data.crop,
        target_quantity_bags=data.target_quantity_bags,
        matching_timeout=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(shipment)
    await db.flush()

    total_order_bags = 0
    for order_id in data.order_ids:
        order = await db.execute(select(Order).where(Order.id == order_id, Order.status == OrderStatus.PENDING))
        order = order.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=400, detail=f"Order {order_id} not found or already assigned")
        total_amount = order.quantity_bags * DEFAULT_PRICE_PER_BAG
        buyer = await db.execute(select(User).where(User.id == order.buyer_id))
        buyer = buyer.scalar_one_or_none()
        if buyer:
            await reserve_funds(db, buyer, total_amount, shipment.id)
        order.shipment_id = shipment.id
        order.price_per_bag = DEFAULT_PRICE_PER_BAG
        order.status = OrderStatus.RESERVED
        total_order_bags += order.quantity_bags

    total_harvest_bags = 0
    for harvest_id in data.harvest_ids:
        harvest = await db.execute(select(Harvest).where(Harvest.id == harvest_id, Harvest.status == HarvestStatus.PENDING))
        harvest = harvest.scalar_one_or_none()
        if not harvest:
            raise HTTPException(status_code=400, detail=f"Harvest {harvest_id} not found or already assigned")
        harvest.shipment_id = shipment.id
        harvest.status = HarvestStatus.MATCHED
        total_harvest_bags += harvest.quantity_bags

    shipment.actual_quantity_bags = total_order_bags + total_harvest_bags
    await db.commit()
    await db.refresh(shipment)

    return {
        "shipment_id": str(shipment.id),
        "status": shipment.status.value,
        "orders_assigned": len(data.order_ids),
        "harvests_assigned": len(data.harvest_ids),
    }

@router.get("/manual-orders", response_model=List[dict])
async def list_manual_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(
        select(Order).where(Order.payment_mode == "MANUAL_CALL", Order.status == OrderStatus.PENDING)
    )
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "buyer_id": str(o.buyer_id),
            "quantity_bags": o.quantity_bags,
            "delivery_location": o.delivery_location,
            "crop": o.crop,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]

@router.post("/orders/{order_id}/convert-to-escrow", response_model=dict)
async def convert_manual_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    order = await db.execute(select(Order).where(Order.id == order_id))
    order = order.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_mode != "MANUAL_CALL":
        raise HTTPException(status_code=400, detail="Order is not in manual payment mode")

    buyer = await db.execute(select(User).where(User.id == order.buyer_id))
    buyer = buyer.scalar_one_or_none()
    if not buyer:
        raise HTTPException(status_code=400, detail="Buyer not found")
    wallet = await payment_engine.get_or_create_wallet(db, buyer)
    total_needed = order.quantity_bags * DEFAULT_PRICE_PER_BAG
    if wallet.available_balance_cents < total_needed:
        raise HTTPException(status_code=402, detail="Buyer has insufficient funds")

    await payment_engine.reserve_funds(db, buyer, total_needed)
    order.price_per_bag = DEFAULT_PRICE_PER_BAG
    order.payment_mode = "AUTO_ESCROW"
    await db.commit()
    await db.refresh(order)

    from app.core.matching_engine import match_pending_orders
    await match_pending_orders(db)
    await db.refresh(order)
    return _order_to_dict(order)

@router.post("/payout-farmer/{harvest_id}", response_model=dict)
async def manual_payout_farmer(
    harvest_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    harvest = await db.execute(select(Harvest).where(Harvest.id == harvest_id))
    harvest = harvest.scalar_one_or_none()
    if not harvest:
        raise HTTPException(status_code=404, detail="Harvest not found")
    if harvest.payout_status == "PAID":
        raise HTTPException(status_code=400, detail="Farmer already paid")
    if not harvest.shipment_id:
        raise HTTPException(status_code=400, detail="Harvest not linked to a shipment")

    shipment = await db.execute(select(Shipment).where(Shipment.id == harvest.shipment_id))
    shipment = shipment.scalar_one_or_none()
    if not shipment or not shipment.extra_data or "pricing_snapshot" not in shipment.extra_data:
        raise HTTPException(status_code=400, detail="Shipment pricing not available")
    pricing = shipment.extra_data["pricing_snapshot"]
    payout_per_bag = pricing["farmer_payout_per_bag"]
    total_payout = harvest.quantity_bags * payout_per_bag

    farmer = await db.execute(select(User).where(User.id == harvest.farmer_id))
    farmer = farmer.scalar_one_or_none()
    if not farmer:
        raise HTTPException(status_code=400, detail="Farmer not found")

    wallet = await payment_engine.get_or_create_wallet(db, farmer)
    wallet.available_balance_cents += total_payout

    from app.models.ledger import LedgerEntry, LedgerEntryType
    entry = LedgerEntry(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        shipment_id=shipment.id,
        entry_type=LedgerEntryType.PAYOUT,
        amount_cents=total_payout,
        description=f"Manual payout for harvest {harvest_id}",
    )
    db.add(entry)
    harvest.payout_status = "PAID"
    await db.commit()
    return {"message": f"Farmer paid {total_payout} cents"}

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
        "payment_mode": order.payment_mode,
    }