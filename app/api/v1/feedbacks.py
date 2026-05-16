from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.database import get_db
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole
from app.models.shipment import Shipment, ShipmentStatus
from app.models.order import Order, OrderStatus
from app.models.verification import VerificationReport
from app.models.feedback import Feedback, FeedbackType
from app.core.trust_engine import update_farmer_rating_from_feedback

router = APIRouter(prefix="/feedbacks", tags=["feedbacks"])

# ---------- Request Schemas ----------
class BuyerFeedbackCreate(BaseModel):
    shipment_id: UUID
    farmer_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None

class AgentFeedbackCreate(BaseModel):
    verification_report_id: UUID
    farmer_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None

# ---------- Submit Buyer Feedback ----------
@router.post("/buyer", response_model=dict)
async def submit_buyer_feedback(
    data: BuyerFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.BUYER, UserRole.ADMIN)),
):
    # Verify the shipment is delivered
    shipment_result = await db.execute(select(Shipment).where(Shipment.id == data.shipment_id))
    shipment = shipment_result.scalar_one_or_none()
    if not shipment or shipment.status != ShipmentStatus.DELIVERED:
        raise HTTPException(status_code=400, detail="Shipment not found or not delivered yet")
    
    # Verify the buyer had an order in this shipment
    order_result = await db.execute(
        select(Order).where(
            Order.shipment_id == data.shipment_id,
            Order.buyer_id == current_user.id,
            Order.status == OrderStatus.RESERVED,
        )
    )
    if not order_result.scalars().first():
        raise HTTPException(status_code=400, detail="You did not participate in this shipment")
    
    # Check if feedback already given by this buyer for this shipment
    existing = await db.execute(
        select(Feedback).where(
            Feedback.from_user_id == current_user.id,
            Feedback.shipment_id == data.shipment_id,
            Feedback.feedback_type == FeedbackType.BUYER_TO_FARMER,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Feedback already submitted for this shipment")
    
    # Create feedback
    feedback = Feedback(
        from_user_id=current_user.id,
        to_user_id=data.farmer_id,
        shipment_id=data.shipment_id,
        feedback_type=FeedbackType.BUYER_TO_FARMER,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    
    # Update farmer's rating
    await update_farmer_rating_from_feedback(db, data.farmer_id)
    
    return {"message": "Feedback submitted", "feedback_id": str(feedback.id)}

# ---------- Submit Agent Feedback ----------
@router.post("/agent", response_model=dict)
async def submit_agent_feedback(
    data: AgentFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
):
    # Verify the verification report exists and belongs to this agent
    verif_result = await db.execute(select(VerificationReport).where(VerificationReport.id == data.verification_report_id))
    verif = verif_result.scalar_one_or_none()
    if not verif:
        raise HTTPException(status_code=404, detail="Verification report not found")
    if verif.agent_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You did not submit this verification")
    
    # Check if feedback already given for this verification report
    existing = await db.execute(
        select(Feedback).where(
            Feedback.from_user_id == current_user.id,
            Feedback.verification_report_id == data.verification_report_id,
            Feedback.feedback_type == FeedbackType.AGENT_TO_FARMER,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Feedback already submitted for this verification")
    
    # Create feedback
    feedback = Feedback(
        from_user_id=current_user.id,
        to_user_id=data.farmer_id,
        verification_report_id=data.verification_report_id,
        feedback_type=FeedbackType.AGENT_TO_FARMER,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    
    # Update farmer's rating
    await update_farmer_rating_from_feedback(db, data.farmer_id)
    
    return {"message": "Feedback submitted", "feedback_id": str(feedback.id)}

# ---------- View Feedback (for a farmer) ----------
@router.get("/farmer/{farmer_id}", response_model=List[dict])
async def get_farmer_feedback(
    farmer_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Feedback).where(Feedback.to_user_id == farmer_id).order_by(Feedback.created_at.desc())
    )
    feedbacks = result.scalars().all()
    return [
        {
            "id": str(f.id),
            "from_user_id": str(f.from_user_id),
            "type": f.feedback_type.value,
            "rating": f.rating,
            "comment": f.comment,
            "created_at": f.created_at.isoformat(),
        }
        for f in feedbacks
    ]