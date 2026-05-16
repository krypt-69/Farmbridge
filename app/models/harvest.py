import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import String, DateTime, Enum as SAEnum, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from sqlalchemy import Float

class HarvestStatus(str, Enum):
    PENDING = "pending"
    MATCHED = "matched"
    VERIFIED = "verified"
    CANCELLED = "cancelled"
#class PayoutStatus(str, Enum):
  #  PENDING_PAYOUT = "pending_payout"
 #   PAID = "paid"


class Harvest(Base):
    __tablename__ = "harvests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    farmer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    crop: Mapped[str] = mapped_column(String, default="potatoes")
    quantity_bags: Mapped[int] = mapped_column(Integer)
    actual_quantity_bags: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    region: Mapped[str] = mapped_column(String)
    expected_harvest_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[HarvestStatus] = mapped_column(SAEnum(HarvestStatus), default=HarvestStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Add these columns
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("shipments.id"), nullable=True, index=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    payout_status: Mapped[str] = mapped_column(String, default="PENDING_PAYOUT", nullable=False)
