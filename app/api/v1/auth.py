from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/me", response_model=dict)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "firebase_uid": current_user.firebase_uid,
        "role": current_user.role.value,
        "phone": current_user.phone,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
    }