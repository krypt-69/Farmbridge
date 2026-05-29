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
from app.models.pricing import PricingConfig
from app.models.shipment import Shipment, ShipmentStatus
from app.models.rating import Rating
from pydantic import BaseModel
from typing import Optional, List


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
# Add this import at the top of app/api/v1/admin.py

@router.get("/export-data", response_model=dict)
async def export_operational_data(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    # 1. Farmers (approved only)
    farmers = (await db.execute(
        select(User).where(User.role == UserRole.FARMER, User.is_active == True)
    )).scalars().all()
    farmer_list = [
        {
            "id": str(f.id),
            "full_name": f.full_name,
            "phone": f.phone,
            "gps_latitude": f.gps_latitude,
            "gps_longitude": f.gps_longitude,
            "rating": (
                lambda r: r.overall_score if r else None
            )((await db.execute(select(Rating).where(Rating.user_id == f.id, Rating.role == "FARMER"))).scalar_one_or_none()),        }
        for f in farmers
    ]

    # 2. Harvests (pending or matched)
    harvests = (await db.execute(
        select(Harvest).where(Harvest.status.in_([HarvestStatus.PENDING, HarvestStatus.MATCHED]))
    )).scalars().all()
    harvest_list = [
        {
            "id": str(h.id),
            "farmer_id": str(h.farmer_id),
            "crop": h.crop,
            "quantity_bags": h.quantity_bags,
            "region": h.region,
            "expected_harvest_date": h.expected_harvest_date.isoformat() if h.expected_harvest_date else None,
            "status": h.status.value,
            "latitude": h.latitude,
            "longitude": h.longitude,
            "shipment_id": str(h.shipment_id) if h.shipment_id else None,
        }
        for h in harvests
    ]

    # 3. Orders (pending or reserved)
    orders = (await db.execute(
        select(Order).where(Order.status.in_([OrderStatus.PENDING, OrderStatus.RESERVED]))
    )).scalars().all()
    order_list = [
        {
            "id": str(o.id),
            "buyer_id": str(o.buyer_id),
            "quantity_bags": o.quantity_bags,
            "delivery_location": o.delivery_location,
            "crop": o.crop,
            "status": o.status.value,
            "payment_mode": o.payment_mode,
            "price_per_bag": o.price_per_bag,
            "shipment_id": str(o.shipment_id) if o.shipment_id else None,
        }
        for o in orders
    ]

    # 4. Agents (active with GPS)
    agents = (await db.execute(
        select(User).where(User.role == UserRole.AGENT, User.is_active == True)
    )).scalars().all()
    agent_list = [
        {
            "id": str(a.id),
            "full_name": a.full_name,
            "gps_latitude": a.gps_latitude,
            "gps_longitude": a.gps_longitude,
            "rating": (
                lambda r: r.overall_score if r else None
            )((await db.execute(select(Rating).where(Rating.user_id == a.id, Rating.role == "AGENT"))).scalar_one_or_none()),        }
        for a in agents
    ]

    # 5. Pricing configurations
    pricing_configs = (await db.execute(select(PricingConfig))).scalars().all()
    pricing_list = [
        {
            "region": pc.region,
            "crop": pc.crop,
            "base_market_price_cents": pc.base_market_price_cents,
            "platform_fee_cents": pc.platform_fee_cents,
            "transport_fee_cents": pc.transport_fee_cents,
            "buyer_discount_cents": pc.buyer_discount_cents,
        }
        for pc in pricing_configs
    ]

    # 6. Open shipments (excluding terminal states)
    open_statuses = [
        ShipmentStatus.MATCHING,
        ShipmentStatus.LOCKED,
        ShipmentStatus.VERIFYING,
        ShipmentStatus.LOADING,
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.ARRIVED_URBAN,
    ]
    shipments = (await db.execute(
        select(Shipment).where(Shipment.status.in_(open_statuses))
    )).scalars().all()
    shipment_list = [
        {
            "id": str(s.id),
            "status": s.status.value,
            "region": s.region,
            "crop": s.crop,
            "target_quantity_bags": s.target_quantity_bags,
            "actual_quantity_bags": s.actual_quantity_bags,
            "extra_data": s.extra_data,
        }
        for s in shipments
    ]

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "farmers": farmer_list,
        "harvests": harvest_list,
        "orders": order_list,
        "agents": agent_list,
        "pricing_configs": pricing_list,
        "open_shipments": shipment_list,
    }


class SuggestedShipment(BaseModel):
    region: str
    crop: str = "potatoes"
    harvest_ids: List[UUID] = []
    order_ids: List[UUID] = []
    suggested_agent_id: Optional[UUID] = None
    suggested_lorry_type: str = "small (3-ton)"
    explanation: Optional[str] = None

class ImportPlanRequest(BaseModel):
    suggested_shipments: List[SuggestedShipment]
    unmatched_harvest_ids: List[UUID] = []
    unmatched_order_ids: List[UUID] = []
    general_notes: Optional[str] = None

@router.post("/import-plan", response_model=dict)
async def import_optimized_plan(
    plan: ImportPlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    created_shipments = []
    errors = []

    for idx, suggestion in enumerate(plan.suggested_shipments):
        try:
            # 1. Create shipment
            shipment = Shipment(
                id=uuid.uuid4(),
                status=ShipmentStatus.MATCHING,
                region=suggestion.region,
                crop=suggestion.crop,
                target_quantity_bags=0,  # will be updated after assigning
                matching_timeout=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            db.add(shipment)
            await db.flush()

            total_quantity = 0

            # 2. Assign harvests
            for harvest_id in suggestion.harvest_ids:
                harvest = await db.execute(select(Harvest).where(Harvest.id == harvest_id))
                harvest = harvest.scalar_one_or_none()
                if not harvest:
                    errors.append(f"Harvest {harvest_id} not found")
                    continue
                if harvest.status not in (HarvestStatus.PENDING, HarvestStatus.MATCHED):
                    errors.append(f"Harvest {harvest_id} is not available (status: {harvest.status})")
                    continue
                # Unassign from previous shipment if needed
                if harvest.shipment_id and harvest.shipment_id != shipment.id:
                    # Optionally warn; we'll just reassign
                    pass
                harvest.shipment_id = shipment.id
                harvest.status = HarvestStatus.MATCHED
                total_quantity += harvest.quantity_bags

            # 3. Assign orders
            for order_id in suggestion.order_ids:
                order = await db.execute(select(Order).where(Order.id == order_id))
                order = order.scalar_one_or_none()
                if not order:
                    errors.append(f"Order {order_id} not found")
                    continue
                if order.status not in (OrderStatus.PENDING, OrderStatus.RESERVED):
                    errors.append(f"Order {order_id} is not available (status: {order.status})")
                    continue
                # Reserve funds if auto-escrow and not already reserved
                if order.payment_mode == "AUTO_ESCROW" and order.status == OrderStatus.PENDING:
                    buyer = await db.execute(select(User).where(User.id == order.buyer_id))
                    buyer = buyer.scalar_one_or_none()
                    if buyer:
                        from app.core.payment_engine import reserve_funds
                        from app.core.matching_engine import DEFAULT_PRICE_PER_BAG
                        await reserve_funds(db, buyer, order.quantity_bags * DEFAULT_PRICE_PER_BAG, shipment.id)
                        order.price_per_bag = DEFAULT_PRICE_PER_BAG
                order.shipment_id = shipment.id
                order.status = OrderStatus.RESERVED
                total_quantity += order.quantity_bags

            # 4. Update shipment target quantity and extra_data
            shipment.target_quantity_bags = total_quantity
            shipment.extra_data = shipment.extra_data or {}
            shipment.extra_data["ai_suggestion"] = {
                "explanation": suggestion.explanation,
                "suggested_agent_id": str(suggestion.suggested_agent_id) if suggestion.suggested_agent_id else None,
                "suggested_lorry_type": suggestion.suggested_lorry_type,
            }

            await db.commit()
            await db.refresh(shipment)
            created_shipments.append(str(shipment.id))

            # Optionally lock immediately if target reached? We'll leave it for admin to lock.
            # But we could call maybe_lock_shipment here; for now, just leave as matching.

        except Exception as e:
            await db.rollback()
            errors.append(f"Failed to create shipment {idx+1}: {str(e)}")

    return {
        "created_shipments": created_shipments,
        "errors": errors,
        "unmatched_harvest_ids": [str(h) for h in plan.unmatched_harvest_ids],
        "unmatched_order_ids": [str(o) for o in plan.unmatched_order_ids],
        "general_notes": plan.general_notes,
    }