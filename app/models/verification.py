import uuid
from sqlalchemy import String, DateTime, Enum as SAEnum, Integer, Float, ForeignKey, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime, timezone
from enum import Enum
from app.database import Base
from typing import Optional, List

class VerificationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    ADJUSTED = "adjusted"
    REJECTED = "rejected"

class VerificationReport(Base):
    __tablename__ = "verification_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    farmer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    shipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)  # idempotency key
    status: Mapped[VerificationStatus] = mapped_column(SAEnum(VerificationStatus), default=VerificationStatus.PENDING)
    claimed_quantity_bags: Mapped[int] = mapped_column(Integer)
    actual_quantity_bags: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    image_urls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # Firebase Storage URLs
    gps_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gps_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    client_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)  # flag if duplicate

    # Relationships
    shipment: Mapped["Shipment"] = relationship(back_populates="verifications")
    harvest_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("harvests.id"), nullable=True, index=True)