import uuid
import os
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from typing import List
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, require_role
from app.models.user import User, UserRole

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_SIZE_MB = 5
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
UPLOAD_VERIFICATION_DIR = "uploads/verifications"
UPLOAD_PROFILE_DIR = "uploads/profiles"

def _validate_image(file: UploadFile):
    ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type .{ext} not allowed")
    # Check size by reading file (spool to disk? For simplicity, read into memory; may be improved)
    # We'll check after reading, but FastAPI can limit via .size? We'll read and check length.
    return ext

def _save_file(file: UploadFile, directory: str) -> str:
    # Generate unique filename
    ext = file.filename.split(".")[-1] if file.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = os.path.join(directory, filename)
    contents = file.file.read()
    if len(contents) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds 5 MB limit")
    with open(file_path, "wb") as f:
        f.write(contents)
    return filename

@router.post("/verification-images", response_model=List[str])
async def upload_verification_images(
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
):
    urls = []
    for file in files:
        ext = _validate_image(file)
        filename = _save_file(file, UPLOAD_VERIFICATION_DIR)
        # Return absolute URL; we'll construct from request or use static mount
        url = f"/uploads/verifications/{filename}"
        urls.append(url)
    return urls

@router.post("/profile-picture", response_model=str)
async def upload_profile_picture(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = _validate_image(file)
    filename = _save_file(file, UPLOAD_PROFILE_DIR)
    url = f"/uploads/profiles/{filename}"
    return url