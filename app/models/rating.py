import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base

class Rating(Base):
    __tablename__ = "ratings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # "FARMER", "BUYER", "AGENT"
    overall_score: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)  # 1.0–5.0
    component_scores: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # e.g. {"agent_accuracy":4.5, "buyer_feedback":4.8, ...}
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))