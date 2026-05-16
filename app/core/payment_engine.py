import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.wallet import Wallet
from app.models.ledger import LedgerEntry, LedgerEntryType
from app.models.user import User
from app.models.order import Order, OrderStatus
from app.models.shipment import Shipment, ShipmentFailureCategory


async def get_or_create_wallet(db: AsyncSession, user: User) -> Wallet:
    result = await db.execute(select(Wallet).where(Wallet.user_id == user.id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        wallet = Wallet(id=uuid.uuid4(), user_id=user.id)
        db.add(wallet)
        await db.flush()
    return wallet

async def deposit_funds(
    db: AsyncSession,
    user: User,
    amount_cents: int,
    description: Optional[str] = None,
) -> Wallet:
    wallet = await get_or_create_wallet(db, user)
    wallet.available_balance_cents += amount_cents

    entry = LedgerEntry(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        shipment_id=None,
        entry_type=LedgerEntryType.DEPOSIT,
        amount_cents=amount_cents,
        description=description or "M-Pesa deposit",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(wallet)
    return wallet

async def reserve_funds(
    db: AsyncSession,
    user: User,
    amount_cents: int,
    shipment_id: Optional[uuid.UUID] = None,   # make optional
) -> Wallet:
    wallet = await get_or_create_wallet(db, user)
    if wallet.available_balance_cents < amount_cents:
        raise ValueError("Insufficient available balance")
    wallet.available_balance_cents -= amount_cents
    wallet.locked_balance_cents += amount_cents

    entry = LedgerEntry(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        shipment_id=shipment_id,   # can be None now
        entry_type=LedgerEntryType.RESERVATION,
        amount_cents=-amount_cents,
        description=f"Reservation for shipment {shipment_id}" if shipment_id else "Reservation (no shipment yet)",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(wallet)
    return wallet

async def release_reservation(
    db: AsyncSession,
    user: User,
    amount_cents: int,
    shipment_id: uuid.UUID,
) -> Wallet:
    wallet = await get_or_create_wallet(db, user)
    if wallet.locked_balance_cents < amount_cents:
        raise ValueError("Insufficient locked balance")
    wallet.locked_balance_cents -= amount_cents
    wallet.available_balance_cents += amount_cents

    entry = LedgerEntry(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        shipment_id=shipment_id,
        entry_type=LedgerEntryType.RESERVATION_REVERSAL,
        amount_cents=amount_cents,
        description=f"Reservation reversal for shipment {shipment_id}",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(wallet)
    return wallet

async def payout_farmer(
    db: AsyncSession,
    user: User,
    amount_cents: int,
    shipment_id: uuid.UUID,
) -> Wallet:
    wallet = await get_or_create_wallet(db, user)
    # Payout comes from locked or platform balance – depending on flow.
    # For now, we'll simply deduct from locked (simulating escrow release to farmer).
    if wallet.locked_balance_cents < amount_cents:
        raise ValueError("Insufficient locked balance for payout")
    wallet.locked_balance_cents -= amount_cents

    entry = LedgerEntry(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        shipment_id=shipment_id,
        entry_type=LedgerEntryType.PAYOUT,
        amount_cents=-amount_cents,
        description=f"Payout for shipment {shipment_id}",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(wallet)
    return wallet

async def refund_buyer(
    db: AsyncSession,
    user: User,
    amount_cents: int,
    shipment_id: uuid.UUID,
) -> Wallet:
    wallet = await get_or_create_wallet(db, user)
    # Refund is a credit to available balance
    wallet.available_balance_cents += amount_cents

    entry = LedgerEntry(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        shipment_id=shipment_id,
        entry_type=LedgerEntryType.REFUND,
        amount_cents=amount_cents,
        description=f"Refund for shipment {shipment_id}",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(wallet)
    return wallet

async def process_shipment_failure_financials(
    db: AsyncSession,
    shipment: Shipment,
):
    """Automatically reverse reservations for deterministic failures."""
    if shipment.failure_category in (
        ShipmentFailureCategory.TIMEOUT,
        ShipmentFailureCategory.INSUFFICIENT_SUPPLY,
    ):
        # Find all orders in RESERVED status for this shipment
        orders_query = select(Order).where(
            Order.shipment_id == shipment.id,
            Order.status == OrderStatus.RESERVED,
        ).options(selectinload(Order.buyer))
        result = await db.execute(orders_query)
        orders = result.scalars().all()
        for order in orders:
            buyer = order.buyer
            # Release locked funds equal to order value
            total_reserved = order.quantity_bags * order.price_per_bag
            try:
                await release_reservation(db, buyer, total_reserved, shipment.id)
            except ValueError as e:
                # Log or handle – should not happen in normal flow
                print(f"Error releasing reservation for order {order.id}: {e}")
        # If there were other buyers (maybe not via orders?), handle similarly
        # For now, only order-driven reservations exist.
    else:
        # Non-deterministic failures: admin must manually refund.
        # No automatic reversal – funds remain locked until admin decides.
        pass