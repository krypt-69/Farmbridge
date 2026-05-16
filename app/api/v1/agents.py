from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from app.database import get_db
from app.api.deps import require_role, get_current_user
from app.models.user import User, UserRole
from pydantic import BaseModel

class LocationUpdate(BaseModel):
    latitude: float
    longitude: float


router = APIRouter(prefix="/agents", tags=["agents"])

@router.get("/farmers", response_model=List[dict])
async def list_farmers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
):
    result = await db.execute(
        select(User).where(
            User.role == UserRole.FARMER,
            User.is_active == True,
            User.approval_status == "APPROVED",
        )
    )
    farmers = result.scalars().all()
    return [
        {
            "id": str(f.id),
            "full_name": f.full_name,
            "phone": f.phone,
        }
        for f in farmers
    ]

@router.put("/location", response_model=dict)
async def update_my_location(
    data: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
):
    current_user.gps_latitude = data.latitude
    current_user.gps_longitude = data.longitude
    await db.commit()
    return {"message": "Location updated"}