from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.audit import AuditLog

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
    # Optional: audit log entry
    return {"message": f"Role updated to {new_role.value}"}