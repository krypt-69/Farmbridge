from celery.utils.log import get_task_logger
from app.workers.celery_app import celery_app
from app.models.notification import Notification
from app.models.device_token import DeviceToken
from app.integrations.firestore import sync_notification
from app.database import SyncSessionLocal
from sqlalchemy.future import select
from firebase_admin import messaging
from app.integrations.firebase_auth import init_firebase
init_firebase()

logger = get_task_logger(__name__)

@celery_app.task(name="send_push_notification")
def send_push_notification_task(notification_id: str):
    db = SyncSessionLocal()
    try:
        notif = db.query(Notification).filter(Notification.id == notification_id).first()
        if not notif:
            return
        # Get device tokens for the user
        tokens = db.query(DeviceToken.token).filter(DeviceToken.user_id == notif.user_id).all()
        token_list = [t[0] for t in tokens]
        if not token_list:
            logger.info(f"No device tokens for user {notif.user_id}")
            return
        # Send to each token (multicast)
        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=notif.title,
                body=notif.body,
            ),
            data={"type": notif.type.value, "shipment_id": notif.data.get("shipment_id", "")},
            tokens=token_list,
        )
        response = messaging.send_each_for_multicast(message)
        logger.info(f"Successfully sent {response.success_count} messages, {response.failure_count} failures")
    except Exception as e:
        logger.error(f"Failed to send push for notification {notification_id}: {e}")
    finally:
        db.close()