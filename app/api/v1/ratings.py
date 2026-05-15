from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.rating import Rating

router = APIRouter(prefix="/ratings", tags=["ratings"])

@router.get("/me", response_model=dict)
async def get_my_rating(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Rating).where(Rating.user_id == current_user.id))
    rating = result.scalar_one_or_none()
    if not rating:
        return {"message": "No rating yet"}
    return {
        "overall_score": rating.overall_score,
        "component_scores": rating.component_scores,
        "total_transactions": rating.total_transactions,
        "last_updated": rating.last_updated.isoformat(),
    }

@router.get("/{user_id}", response_model=dict)
async def get_user_rating(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(select(Rating).where(Rating.user_id == user_id))
    rating = result.scalar_one_or_none()
    if not rating:
        raise HTTPException(status_code=404, detail="Rating not found")
    return {
        "overall_score": rating.overall_score,
        "component_scores": rating.component_scores,
        "total_transactions": rating.total_transactions,
        "last_updated": rating.last_updated.isoformat(),
    }

# Admin can trigger recalculation manually
@router.post("/recalc/{user_id}", response_model=dict)
async def recalc_user_rating(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from app.core.trust_engine import recalc_farmer_rating, recalc_buyer_rating, recalc_agent_rating
    if user.role == UserRole.FARMER:
        rating = await recalc_farmer_rating(db, user_id)
    elif user.role == UserRole.BUYER:
        rating = await recalc_buyer_rating(db, user_id)
    elif user.role == UserRole.AGENT:
        rating = await recalc_agent_rating(db, user_id)
    else:
        raise HTTPException(status_code=400, detail="Role not supported")
    return {"message": "Rating recalculated", "overall_score": rating.overall_score}