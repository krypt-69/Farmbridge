from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])

class ProfilePictureUpdate(BaseModel):
    profile_picture_url: str

@router.put("/me/picture", response_model=dict)
async def update_profile_picture(
    data: ProfilePictureUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.profile_picture_url = data.profile_picture_url
    await db.commit()
    return {"message": "Profile picture updated"}