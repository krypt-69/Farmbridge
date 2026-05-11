from fastapi import APIRouter

api_router = APIRouter()

# We'll add route includes in subsequent phases.
# Example:
# from app.api.v1 import auth, shipments, orders
# api_router.include_router(auth.router, tags=["auth"])