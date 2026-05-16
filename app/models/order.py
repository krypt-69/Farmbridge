import uuid
from sqlalchemy import String, DateTime, Enum as SAEnum, Integer, Float, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
from enum import Enum
from app.database import Base
from typing import Optional

class OrderStatus(str, Enum):
    PENDING = "pending"           # before shipment locked
    RESERVED = "reserved"         # locked into shipment
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
#class PaymentMode(str, Enum):
 #   AUTO_ESCROW = "auto_escrow"
  #  MANUAL_CALL = "manual_call"

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("shipments.id"), nullable=True, index=True)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(
            OrderStatus,
            values_callable=lambda obj: [e.value for e in obj]
        ),
        default=OrderStatus.PENDING
    )
    quantity_bags: Mapped[int] = mapped_column(Integer)
    price_per_bag: Mapped[int] = mapped_column(Integer)  # cents
    delivery_location: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    payment_mode: Mapped[str] = mapped_column(String, default="AUTO_ESCROW", nullable=False)
    # Relationships
    buyer: Mapped["User"] = relationship(foreign_keys=[buyer_id])
    shipment: Mapped[Optional["Shipment"]] = relationship(back_populates="orders")
    crop: Mapped[str] = mapped_column(String, default="potatoes")