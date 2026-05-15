import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional
from app.database import get_db
from app.api.deps import require_role, get_current_user
from app.models.user import User, UserRole
from app.models.harvest import Harvest, HarvestStatus

router = APIRouter(prefix="/agents", tags=["agent_farmers"])

class CreateFarmerRequest(BaseModel):
    phone: str
    full_name: str
    region: str
    crop: str = "potatoes"
    quantity_bags: int = Field(gt=0)
    expected_harvest_date: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None

@router.post("/create-farmer", response_model=dict)
async def create_farmer(
    data: CreateFarmerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
):
    # Check if phone already exists
    from sqlalchemy.future import select
    existing_user = await db.execute(select(User).where(User.phone == data.phone))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="A user with this phone number already exists")

    farmer = User(
        id=uuid.uuid4(),
        firebase_uid=None,  # Firebase account created later when farmer signs in
        role=UserRole.FARMER,
        phone=data.phone,
        full_name=data.full_name,
        is_active=True,
    )
    db.add(farmer)
    await db.flush()   # force generation of farmer.id

    # Create an initial harvest for this farmer
    harvest = Harvest(
        id=uuid.uuid4(),
        farmer_id=farmer.id,
        crop=data.crop,
        quantity_bags=data.quantity_bags,
        region=data.region,
        expected_harvest_date=data.expected_harvest_date,
        status=HarvestStatus.PENDING,
        latitude=data.gps_latitude,
        longitude=data.gps_longitude,
    )
    db.add(harvest)
    await db.commit()
    await db.refresh(farmer)
    await db.refresh(harvest)
    return {
        "farmer_id": str(farmer.id),
        "harvest_id": str(harvest.id),
        "message": "Farmer and harvest created"
    }