from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "farmbridge",
    broker=settings.redis_url,
    backend=settings.redis_url,  # Optional result backend
    include=["app.workers.tasks.shipment_tasks"],  # Import task modules
)

# Optional configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Africa/Nairobi",  # Adjust to your timezone
    enable_utc=True,
    beat_schedule={
        "check-matching-timeouts-every-10-minutes": {
            "task": "app.workers.tasks.shipment_tasks.check_matching_timeouts",
            "schedule": 600.0,  # seconds (10 minutes)
        },
    },
)