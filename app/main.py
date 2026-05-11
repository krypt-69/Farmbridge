from fastapi import FastAPI
from app.config import get_settings
from app.api.v1.router import api_router

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

@app.on_event("startup")
async def startup():
    # Placeholder: any startup tasks (e.g., verify DB connection)
    pass

@app.on_event("shutdown")
async def shutdown():
    pass

app.include_router(api_router, prefix="/api/v1")