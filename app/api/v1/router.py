from fastapi import APIRouter
from app.api.v1 import auth, shipments, wallet, orders, verifications, admin

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(shipments.router)
api_router.include_router(wallet.router)
api_router.include_router(orders.router)
api_router.include_router(verifications.router)
api_router.include_router(admin.router)