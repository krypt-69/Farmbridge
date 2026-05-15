import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

class PricingConfig(Base):
    __tablename__ = "pricing_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    region: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    crop: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    base_market_price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=600000)  # e.g., KES 6,000
    platform_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=40000)        # KES 400
    transport_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)       # KES 300
    buyer_discount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=100000)     # buyer pays less than market
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("region", "crop", name="uq_pricing_region_crop"),
    )