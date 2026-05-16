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
from app.models.harvest import Harvest, HarvestStatus
from app.utils.gps import cluster_harvests, haversine_distance
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
@router.get("/{shipment_id}/harvests", response_model=List[dict])
async def list_shipment_harvests(
    shipment_id: UUID,
    group_by_proximity: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shipment_result = await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    shipment = shipment_result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    harvest_query = select(Harvest).where(
        Harvest.region == shipment.region,
        Harvest.crop == shipment.crop,
        Harvest.status.in_([HarvestStatus.PENDING, HarvestStatus.MATCHED]),
    )
    harvests = (await db.execute(harvest_query)).scalars().all()

    if group_by_proximity:
        clusters = cluster_harvests(harvests, max_distance_m=10000)  # 10 km
        # Build farmer name map
        farmer_ids = set(h.farmer_id for cluster in clusters for h in cluster)
        farmers = (await db.execute(select(User).where(User.id.in_(farmer_ids)))).scalars().all()
        farmer_map = {f.id: f.full_name for f in farmers}
        result = []
        for idx, cluster in enumerate(clusters):
            cluster_data = []
            for h in cluster:
                cluster_data.append({
                    "id": str(h.id),
                    "farmer_name": farmer_map.get(h.farmer_id, "Unknown"),
                    "crop": h.crop,
                    "quantity_bags": h.quantity_bags,
                    "latitude": h.latitude,
                    "longitude": h.longitude,
                })
            result.append({"cluster": idx+1, "harvests": cluster_data})
        return result
    else:
        # Original flat list
        return [
            {
                "id": str(h.id),
                "farmer_name": (await db.execute(select(User).where(User.id == h.farmer_id))).scalar_one_or_none().full_name,
                "crop": h.crop,
                "quantity_bags": h.quantity_bags,
                "region": h.region,
            }
            for h in harvests
        ]
@router.get("/{shipment_id}/available-agents", response_model=List[dict])
async def list_available_agents(
    shipment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    # Get shipment to know region/crop
    shipment_result = await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    shipment = shipment_result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    # Get harvests with coordinates for this shipment
    harvest_query = select(Harvest).where(
        Harvest.region == shipment.region,
        Harvest.crop == shipment.crop,
        Harvest.latitude != None,
        Harvest.longitude != None,
        Harvest.status.in_([HarvestStatus.PENDING, HarvestStatus.MATCHED]),
    )
    harvests = (await db.execute(harvest_query)).scalars().all()

    # Get all agents with coordinates
    agent_query = select(User).where(
        User.role.in_([UserRole.AGENT, UserRole.ADMIN]),   # admins can act as agents
        User.is_active == True,
        User.gps_latitude != None,
        User.gps_longitude != None,
    )
    agents = (await db.execute(agent_query)).scalars().all()

    if not harvests:
        # No harvest coordinates, return agents unsorted
        return [
            {"agent_id": str(a.id), "full_name": a.full_name, "latitude": a.gps_latitude, "longitude": a.gps_longitude, "distance_km": None}
            for a in agents
        ]

    # For each agent, compute distance to the nearest harvest
    agent_distances = []
    for agent in agents:
        min_distance = float("inf")
        for h in harvests:
            d = haversine_distance(agent.gps_latitude, agent.gps_longitude, h.latitude, h.longitude)
            if d < min_distance:
                min_distance = d
        agent_distances.append((agent, min_distance))

    # Sort by distance
    agent_distances.sort(key=lambda x: x[1])

    return [
        {
            "agent_id": str(agent.id),
            "full_name": agent.full_name,
            "latitude": agent.gps_latitude,
            "longitude": agent.gps_longitude,
            "distance_km": round(distance / 1000, 2),
        }
        for agent, distance in agent_distances
    ]
@router.post("/shipments/{shipment_id}/assign", response_model=dict)
async def assign_to_shipment(
    shipment_id: UUID,
    order_ids: List[UUID] = [],
    harvest_ids: List[UUID] = [],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    shipment = await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    shipment = shipment.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if shipment.status != ShipmentStatus.MATCHING:
        raise HTTPException(status_code=400, detail="Can only assign to MATCHING shipments")

    # Assign orders
    for order_id in order_ids:
        order = await db.execute(select(Order).where(Order.id == order_id, Order.status == OrderStatus.PENDING))
        order = order.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=400, detail=f"Order {order_id} not available")
        total_amount = order.quantity_bags * DEFAULT_PRICE_PER_BAG
        buyer = await db.execute(select(User).where(User.id == order.buyer_id))
        buyer = buyer.scalar_one_or_none()
        if buyer:
            await reserve_funds(db, buyer, total_amount, shipment.id)
        order.shipment_id = shipment.id
        order.price_per_bag = DEFAULT_PRICE_PER_BAG
        order.status = OrderStatus.RESERVED

    # Assign harvests
    for harvest_id in harvest_ids:
        harvest = await db.execute(select(Harvest).where(Harvest.id == harvest_id, Harvest.status == HarvestStatus.PENDING))
        harvest = harvest.scalar_one_or_none()
        if not harvest:
            raise HTTPException(status_code=400, detail=f"Harvest {harvest_id} not available")
        harvest.shipment_id = shipment.id
        harvest.status = HarvestStatus.MATCHED

    await db.commit()
    return {"message": "Assigned successfully"}

@router.post("/shipments/{shipment_id}/unassign", response_model=dict)
async def unassign_from_shipment(
    shipment_id: UUID,
    order_ids: List[UUID] = [],
    harvest_ids: List[UUID] = [],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    shipment = await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    shipment = shipment.scalar_one_or_none()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if shipment.status != ShipmentStatus.MATCHING:
        raise HTTPException(status_code=400, detail="Can only unassign from MATCHING shipments")

    # Unassign orders
    for order_id in order_ids:
        order = await db.execute(select(Order).where(Order.id == order_id, Order.shipment_id == shipment_id, Order.status == OrderStatus.RESERVED))
        order = order.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=400, detail=f"Order {order_id} not in this shipment")
        # Release funds
        from app.core.payment_engine import release_reservation
        total_amount = order.quantity_bags * order.price_per_bag
        buyer = await db.execute(select(User).where(User.id == order.buyer_id))
        buyer = buyer.scalar_one_or_none()
        if buyer:
            await release_reservation(db, buyer, total_amount, shipment.id)
        order.shipment_id = None
        order.status = OrderStatus.PENDING

    # Unassign harvests
    for harvest_id in harvest_ids:
        harvest = await db.execute(select(Harvest).where(Harvest.id == harvest_id, Harvest.shipment_id == shipment_id, Harvest.status == HarvestStatus.MATCHED))
        harvest = harvest.scalar_one_or_none()
        if not harvest:
            raise HTTPException(status_code=400, detail=f"Harvest {harvest_id} not in this shipment")
        harvest.shipment_id = None
        harvest.status = HarvestStatus.PENDING

    await db.commit()
    return {"message": "Unassigned successfully"}