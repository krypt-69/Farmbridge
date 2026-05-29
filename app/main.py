from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import get_settings
from app.api.v1.router import api_router
from app.integrations.firebase_auth import init_firebase

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

# CORS – must be added BEFORE any other middleware or routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    init_firebase()

# Static files mount (before API router, after CORS)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# API router
app.include_router(api_router, prefix="/api/v1")
