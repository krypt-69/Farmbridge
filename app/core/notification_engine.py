from typing import List, Optional
import uuid
from app.models.notification import Notification, NotificationType, NotificationChannel
from app.models.shipment import Shipment, ShipmentStatus
from app.models.order import Order, OrderStatus
from app.models.harvest import Harvest, HarvestStatus
from app.models.user import User, UserRole
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

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

async def create_notifications_for_shipment(db: AsyncSession, shipment: Shipment, new_status: ShipmentStatus) -> List[Notification]:
    """Generate and save Notification records for all relevant users."""
    note_type = get_notification_type_for_status(new_status)
    title = f"Shipment {new_status.value}"
    body = f"Shipment {shipment.id} in {shipment.region} is now {new_status.value}."

    notifications = []

    # Collect all user IDs that should be notified:
    user_ids = set()

    # 1. Buyers with orders in this shipment
    orders_result = await db.execute(
        select(Order.buyer_id).where(
            Order.shipment_id == shipment.id,
            Order.status == OrderStatus.RESERVED,
        )
    )
    for buyer_id in orders_result.scalars().all():
        user_ids.add(buyer_id)

    # 2. Farmers with harvests in this shipment
    harvests_result = await db.execute(
        select(Harvest.farmer_id).where(
            Harvest.shipment_id == shipment.id,
            Harvest.status == HarvestStatus.MATCHED,
        )
    )
    for farmer_id in harvests_result.scalars().all():
        user_ids.add(farmer_id)

    # 3. All admins
    admins_result = await db.execute(
        select(User.id).where(User.role == UserRole.ADMIN)
    )
    for admin_id in admins_result.scalars().all():
        user_ids.add(admin_id)

    # 4. Agent? If we want to notify the agent assigned? For now skip.

    # Create notifications
    for uid in user_ids:
        notif = Notification(
            id=uuid.uuid4(),
            user_id=uid,
            type=note_type,
            channel=NotificationChannel.PUSH,
            title=title,
            body=body,
            data={"shipment_id": str(shipment.id)},
        )
        db.add(notif)
        notifications.append(notif)

    # Flush to get IDs before we can enqueue tasks
    await db.flush()
    return notifications