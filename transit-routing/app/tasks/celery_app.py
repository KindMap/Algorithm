from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery(
    "tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    result_expires=3600,
    worker_max_tasks_per_child=1000,
)

celery.conf.beat_schedule = {
    "cleanup-old-sessions-daily": {
        "task": "app.tasks.tasks.cleanup_old_sessions",
        "schedule": crontab(hour=2, minute=0),
    },
}


@celery.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
