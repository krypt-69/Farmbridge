from fastapi import FastAPI
from app.config import get_settings
from app.api.v1.router import api_router
from app.integrations.firebase_auth import init_firebase

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

@app.on_event("startup")
async def startup():
    init_firebase()

app.include_router(api_router, prefix="/api/v1")