import uuid
from sqlalchemy import String, DateTime, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
from enum import Enum
from app.database import Base

class LedgerEntryType(str, Enum):
    DEPOSIT = "deposit"
    RESERVATION = "reservation"
    RESERVATION_REVERSAL = "reservation_reversal"
    PAYOUT = "payout"
    REFUND = "refund"
    PLATFORM_FEE = "platform_fee"
    TRANSPORT_FEE = "transport_fee"

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallets.id"), nullable=False, index=True)
    shipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipments.id"), nullable=True)  # nullable for deposits
    entry_type: Mapped[LedgerEntryType] = mapped_column(SAEnum(LedgerEntryType), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)  # positive for credit, negative for debit
    description: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # balance snapshot could be added later for simplicity