import uuid
from sqlalchemy import String, DateTime, Enum as SAEnum, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime, timezone
from enum import Enum
from app.database import Base

class NotificationType(str, Enum):
    ORDER_CONFIRMED = "order_confirmed"
    GRACE_PERIOD_ENDING = "grace_period_ending"
    SHIPMENT_FULL = "shipment_full"
    PICKUP_SCHEDULED = "pickup_scheduled"
    LORRY_DISPATCHED = "lorry_dispatched"
    LORRY_ARRIVED = "lorry_arrived"
    DELIVERY_COMPLETED = "delivery_completed"
    PAYMENT_CONFIRMED = "payment_confirmed"
    DISPUTE = "dispute"
    ADMIN_ALERT = "admin_alert"

class NotificationChannel(str, Enum):
    PUSH = "push"
    SMS = "sms"

class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[NotificationType] = mapped_column(SAEnum(NotificationType))
    channel: Mapped[NotificationChannel] = mapped_column(SAEnum(NotificationChannel))
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSONB, nullable=True)  # Could use JSONB later
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))