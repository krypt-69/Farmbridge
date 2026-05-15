from fastapi import APIRouter
from app.api.v1 import auth, shipments, wallet, orders, verifications, admin, agents, farmers, agent_farmers, pricing, device, ratings

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(shipments.router)
api_router.include_router(wallet.router)
api_router.include_router(orders.router)
api_router.include_router(verifications.router)
api_router.include_router(admin.router)
api_router.include_router(agents.router)
api_router.include_router(farmers.router)
api_router.include_router(agent_farmers.router)
api_router.include_router(pricing.router)
api_router.include_router(device.router)
api_router.include_router(ratings.router)