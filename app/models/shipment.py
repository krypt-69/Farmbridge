import uuid
from sqlalchemy import String, DateTime, Enum as SAEnum, Integer, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime, timezone
from enum import Enum
from app.database import Base
from typing import Optional, List

class ShipmentStatus(str, Enum):
    MATCHING = "matching"
    LOCKED = "locked"
    VERIFYING = "verifying"
    LOADING = "loading"
    IN_TRANSIT = "in_transit"
    ARRIVED_URBAN = "arrived_urban"
    DELIVERED = "delivered"
    FAILED = "failed"

class ShipmentFailureCategory(str, Enum):
    TIMEOUT = "timeout"
    INSUFFICIENT_SUPPLY = "insufficient_supply"
    QUALITY_REJECTION = "quality_rejection"
    LOGISTICS_BREAKDOWN = "logistics_breakdown"
    OPERATIONAL_INCONSISTENCY = "operational_inconsistency"
    FRAUD = "fraud"

class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[ShipmentStatus] = mapped_column(SAEnum(ShipmentStatus), default=ShipmentStatus.MATCHING, index=True)
    failure_category: Mapped[Optional[ShipmentFailureCategory]] = mapped_column(SAEnum(ShipmentFailureCategory), nullable=True)

    # Region information
    region: Mapped[str] = mapped_column(String, index=True)
    crop: Mapped[str] = mapped_column(String, default="potatoes")
    target_quantity_bags: Mapped[int] = mapped_column(Integer)  # target total bags to fill
    actual_quantity_bags: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    matching_timeout: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    loading_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    departed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_urban_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Additional metadata (e.g., route, transporter)
    metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    orders: Mapped[List["Order"]] = relationship(back_populates="shipment")
    verifications: Mapped[List["VerificationReport"]] = relationship(back_populates="shipment")