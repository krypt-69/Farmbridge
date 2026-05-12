from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

# Async engine for FastAPI endpoints
async_engine = create_async_engine(settings.database_url, echo=settings.debug, future=True)

AsyncSessionLocal = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Synchronous engine for Celery workers (must use psycopg2)
sync_db_url = settings.database_url.replace("+asyncpg", "+psycopg2")
sync_engine = create_engine(sync_db_url, echo=settings.debug)

SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)