import firebase_admin
from firebase_admin import auth, credentials
from app.config import get_settings
from functools import lru_cache

settings = get_settings()

_firebase_initialized = False

def init_firebase():
    global _firebase_initialized
    if not _firebase_initialized:
        cred = credentials.Certificate(settings.firebase_credentials_path)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True

def verify_firebase_token(token: str) -> dict:
    """Verify Firebase ID token and return decoded claims."""
    if not _firebase_initialized:
        init_firebase()
    decoded = auth.verify_id_token(token)
    return decoded