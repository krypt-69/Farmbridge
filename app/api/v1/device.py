from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.device_token import DeviceToken

router = APIRouter(prefix="/device", tags=["device"])

class TokenRegister(BaseModel):
    token: str
    platform: str  # "ios" or "android"

@router.post("/register", response_model=dict)
async def register_device(
    data: TokenRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Check if token already exists for this user (upsert)
    from sqlalchemy.future import select
    existing = await db.execute(
        select(DeviceToken).where(
            DeviceToken.user_id == current_user.id,
            DeviceToken.token == data.token,
        )
    )
    if existing.scalar_one_or_none():
        return {"message": "Token already registered"}

    # Remove old token for this platform if present
    await db.execute(
        select(DeviceToken).where(
            DeviceToken.user_id == current_user.id,
            DeviceToken.platform == data.platform,
        )
    )
    # Actually delete old ones? Better to delete so we don't accumulate.
    old = (await db.execute(
        select(DeviceToken).where(
            DeviceToken.user_id == current_user.id,
            DeviceToken.platform == data.platform,
        )
    )).scalars().all()
    for old_token in old:
        await db.delete(old_token)

    new_token = DeviceToken(
        user_id=current_user.id,
        token=data.token,
        platform=data.platform,
    )
    db.add(new_token)
    await db.commit()
    return {"message": "Device registered"}