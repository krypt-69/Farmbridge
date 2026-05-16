from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from app.database import get_db
from app.api.deps import require_role, get_current_user
from app.models.user import User, UserRole

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