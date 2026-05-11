from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "FarmBridge"
    debug: bool = False
    environment: str = "development"

    # Database
    database_url: str  # e.g., postgresql+asyncpg://user:pass@host/db

    # Firebase
    firebase_credentials_path: str = "./firebase-credentials.json"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # M-Pesa
    mpesa_environment: str = "sandbox"
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_passkey: str = ""
    mpesa_shortcode: str = ""

    # SMS
    sms_api_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings() -> Settings:
    return Settings()