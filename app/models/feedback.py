import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from enum import Enum
from app.database import Base
from typing import Optional

class FeedbackType(str, Enum):
    BUYER_TO_FARMER = "buyer_to_farmer"
    AGENT_TO_FARMER = "agent_to_farmer"

class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("shipments.id"), nullable=True)  # for buyer feedback
    verification_report_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("verification_reports.id"), nullable=True)  # for agent feedback
    feedback_type: Mapped[FeedbackType] = mapped_column(SAEnum(FeedbackType), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5 stars
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))