from typing import Optional
from app.models.notification import Notification, NotificationType, NotificationChannel
from app.models.shipment import ShipmentStatus
import uuid

def get_notification_type_for_status(status: ShipmentStatus) -> NotificationType:
    mapping = {
        ShipmentStatus.LOCKED: NotificationType.SHIPMENT_FULL,
        ShipmentStatus.LOADING: NotificationType.PICKUP_SCHEDULED,
        ShipmentStatus.IN_TRANSIT: NotificationType.LORRY_DISPATCHED,
        ShipmentStatus.ARRIVED_URBAN: NotificationType.LORRY_ARRIVED,
        ShipmentStatus.DELIVERED: NotificationType.DELIVERY_COMPLETED,
        ShipmentStatus.FAILED: NotificationType.ADMIN_ALERT,
    }
    return mapping.get(status, NotificationType.ADMIN_ALERT)

def create_notifications_for_shipment(shipment, admin_user_id: uuid.UUID) -> list[Notification]:
    note_type = get_notification_type_for_status(shipment.status)
    return [
        Notification(
            id=uuid.uuid4(),
            user_id=admin_user_id,  # placeholder – real implementation should fan out
            type=note_type,
            channel=NotificationChannel.PUSH,
            title=f"Shipment {shipment.status.value}",
            body=f"Shipment {shipment.id} has moved to {shipment.status.value}",
            data={"shipment_id": str(shipment.id)},
        )
    ]