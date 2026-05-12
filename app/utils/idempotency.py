from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.verification import VerificationReport
from uuid import UUID
from typing import Optional

async def check_idempotency(db: AsyncSession, operation_id: UUID) -> Optional[VerificationReport]:
    """Return existing report with the same operation_id, or None."""
    result = await db.execute(
        select(VerificationReport).where(VerificationReport.operation_id == operation_id)
    )
    return result.scalar_one_or_none()

async def ensure_idempotent(db: AsyncSession, operation_id: UUID):
    """Raise HTTP 409 if the operation was already processed."""
    existing = await check_idempotency(db, operation_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate verification – this report was already submitted.",
        )