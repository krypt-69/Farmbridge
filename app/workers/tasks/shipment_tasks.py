from celery.utils.log import get_task_logger
from app.workers.celery_app import celery_app
from app.database import SyncSessionLocal
from app.models.shipment import Shipment, ShipmentStatus, ShipmentFailureCategory
from app.models.order import Order, OrderStatus
from app.models.wallet import Wallet
from app.models.ledger import LedgerEntry, LedgerEntryType
from datetime import datetime, timezone
import uuid

logger = get_task_logger(__name__)

@celery_app.task(name="app.workers.tasks.shipment_tasks.check_matching_timeouts")
def check_matching_timeouts():
    """Periodic task that fails shipments stuck in MATCHING beyond timeout."""
    db = SyncSessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired = (
            db.query(Shipment)
            .filter(
                Shipment.status == ShipmentStatus.MATCHING,
                Shipment.matching_timeout <= now,
            )
            .all()
        )
        for shipment in expired:
            logger.info(f"Failing shipment {shipment.id} due to matching timeout")
            try:
                # Mark shipment as failed
                shipment.status = ShipmentStatus.FAILED
                shipment.failure_category = ShipmentFailureCategory.TIMEOUT
                shipment.failed_at = now

                # Reverse all locked funds for this shipment (deterministic failure)
                orders = (
                    db.query(Order)
                    .filter(
                        Order.shipment_id == shipment.id,
                        Order.status == OrderStatus.RESERVED,
                    )
                    .all()
                )
                for order in orders:
                    buyer = order.buyer   # need to have relationship loaded
                    wallet = buyer.wallet   # rely on back_populates
                    total = order.quantity_bags * order.price_per_bag
                    wallet.locked_balance_cents -= total
                    wallet.available_balance_cents += total
                    # Add reversal ledger entry
                    db.add(
                        LedgerEntry(
                            id=uuid.uuid4(),
                            wallet_id=wallet.id,
                            shipment_id=shipment.id,
                            entry_type=LedgerEntryType.RESERVATION_REVERSAL,
                            amount_cents=total,
                            description=f"Auto-reversal for timed-out shipment {shipment.id}",
                        )
                    )
                    order.status = OrderStatus.CANCELLED
                db.commit()
                # Trigger Firestore sync
                from app.workers.tasks.firestore_sync import sync_shipment_task
                sync_shipment_task.delay(str(shipment.id))
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to timeout shipment {shipment.id}: {e}")
    finally:
        db.close()