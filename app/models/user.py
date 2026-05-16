import uuid
from sqlalchemy import String, Boolean, DateTime, Enum as SAEnum, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
from enum import Enum
from app.database import Base
from typing import Optional
from enum import Enum as PyEnum

class UserRole(str, Enum):
    BUYER = "buyer"
    FARMER = "farmer"
    AGENT = "agent"
    ADMIN = "admin"
#class ApprovalStatus(str, PyEnum):
 #   PENDING = "pending"
  #  APPROVED = "approved"
   # REJECTED = "rejected"

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False)
    phone: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    wallet: Mapped["Wallet"] = relationship(back_populates="user", uselist=False)
    profile_picture_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    approval_status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)
    gps_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gps_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    