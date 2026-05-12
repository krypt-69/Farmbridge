from fastapi import APIRouter
from app.api.v1 import auth, shipments

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(shipments.router)