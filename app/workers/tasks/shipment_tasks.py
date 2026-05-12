from datetime import datetime, timezone
from celery.utils.log import get_task_logger
from app.workers.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.shipment import Shipment, ShipmentStatus, ShipmentFailureCategory
from sqlalchemy.future import select
from app.core import shipment_engine

logger = get_task_logger(__name__)

@celery_app.task(name="app.workers.tasks.shipment_tasks.check_matching_timeouts")
def check_matching_timeouts():
    """Periodic task that fails shipments stuck in MATCHING beyond timeout."""
    import asyncio
    async def _check():
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(Shipment).where(
                    Shipment.status == ShipmentStatus.MATCHING,
                    Shipment.matching_timeout <= now,
                )
            )
            expired_shipments = result.scalars().all()
            for s in expired_shipments:
                logger.info(f"Failing shipment {s.id} due to matching timeout")
                try:
                    await shipment_engine.fail_shipment(db, s, ShipmentFailureCategory.TIMEOUT)
                except Exception as e:
                    logger.error(f"Failed to timeout shipment {s.id}: {e}")
    asyncio.run(_check())