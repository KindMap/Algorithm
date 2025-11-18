from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery(
    "tasks",
    broker=settings.CELERY_BROKER_URL,  # task queue => redis/1
    backend=settings.CELERY_RESULT_BACKEND,  # backend => redis/2
    include=["app.tasks.tasks"],
)

celery.conf.update(
    # 작업과 결과를 JSON으로 통일
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # 시간대 설정 => 스케줄링에 사용
    timezone="Asia/Seoul",
    enable_utc=True,
    # 안정성 및 워커 동작 설정!!!
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    # 타임아웃 설정
    task_time_limit=300,
    task_soft_time_limit=240,
    # 리소스 관리 설정
    result_expires=3600,
    worker_max_tasks_per_child=1000,
)

# 특정 작업을 주기적으로 실행하게 해주는 스케줄러 기능
celery.conf.beat_schedule = {
    "cleanup-old-sessions-daily": {
        "task": "app.tasks.tasks.cleanup_old_sessions",
        "schedule": crontab(hour=2, minute=0),
    },
}


@celery.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
