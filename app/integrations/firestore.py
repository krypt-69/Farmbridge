from firebase_admin import firestore
from app.integrations.firebase_auth import init_firebase
from typing import Any, Dict

init_firebase()
db = firestore.client()

def sync_shipment(shipment_id: str, data: Dict[str, Any]):
    db.collection("shipments").document(shipment_id).set(data, merge=True)

def sync_order(order_id: str, data: Dict[str, Any]):
    db.collection("orders").document(order_id).set(data, merge=True)

def sync_wallet(user_id: str, data: Dict[str, Any]):
    db.collection("wallets").document(user_id).set(data, merge=True)

def sync_verification(verification_id: str, data: Dict[str, Any]):
    db.collection("verifications").document(verification_id).set(data, merge=True)

def sync_notification(notification_id: str, data: Dict[str, Any]):
    db.collection("notifications").document(notification_id).set(data, merge=True)