from celery.utils.log import get_task_logger
from app.workers.celery_app import celery_app
from app.models.notification import Notification
from app.integrations.firestore import sync_notification
from app.database import AsyncSessionLocal
from sqlalchemy.future import select

logger = get_task_logger(__name__)

@celery_app.task(name="send_push_notification")
def send_push_notification_task(notification_id: str):
    import asyncio
    async def _run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Notification).where(Notification.id == notification_id))
            notif = result.scalar_one_or_none()
            if notif:
                # In a real scenario, we'd send FCM here.
                # For now, log and sync to Firestore.
                logger.info(f"Push notification would be sent: {notif.title}")
                sync_notification(str(notif.id), {
                    "id": str(notif.id),
                    "user_id": str(notif.user_id),
                    "type": notif.type.value,
                    "title": notif.title,
                    "body": notif.body,
                    "data": notif.data,
                    "created_at": notif.created_at.isoformat(),
                })
    asyncio.run(_run())