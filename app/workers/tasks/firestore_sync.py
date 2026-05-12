from celery.utils.log import get_task_logger
from app.workers.celery_app import celery_app
from app.integrations import firestore
from app.database import SyncSessionLocal
from app.models.shipment import Shipment
from app.models.order import Order
from app.models.wallet import Wallet
from app.models.verification import VerificationReport

logger = get_task_logger(__name__)

def shipment_to_firestore(shipment):
    return {
        "id": str(shipment.id),
        "status": shipment.status.value,
        "region": shipment.region,
        "target_quantity_bags": shipment.target_quantity_bags,
        "actual_quantity_bags": shipment.actual_quantity_bags,
        "crop": shipment.crop,
        "created_at": shipment.created_at.isoformat(),
        "locked_at": shipment.locked_at.isoformat() if shipment.locked_at else None,
        "verification_started_at": shipment.verification_started_at.isoformat() if shipment.verification_started_at else None,
        "departed_at": shipment.departed_at.isoformat() if shipment.departed_at else None,
        "delivered_at": shipment.delivered_at.isoformat() if shipment.delivered_at else None,
        "failed_at": shipment.failed_at.isoformat() if shipment.failed_at else None,
        "extra_data": shipment.extra_data,
    }

@celery_app.task(name="sync_shipment_firestore")
def sync_shipment_task(shipment_id: str):
    with SyncSessionLocal() as db:
        shipment = db.query(Shipment).filter(Shipment.id == shipment_id).first()
        if shipment:
            firestore.sync_shipment(shipment_id, shipment_to_firestore(shipment))
            logger.info(f"Synced shipment {shipment_id} to Firestore")