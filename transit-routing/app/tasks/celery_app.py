from celery import Celery
from celery.schedules import crontab
import os

celery = Celery(
    "tasks",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    include=["tasks"],  # tasks 모듈 자동 import
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,  # 작업 시작 추적
    task_time_limit=300,  # 5분 제한
    task_soft_time_limit=240,  # 4분 소프트 제한
    result_expires=3600,  # 결과 1시간 후 만료
    worker_max_tasks_per_child=1000,  # 메모리 누수 방지
)

# 주기적 작업 스케줄링
celery.conf.beat_schedule = {
    "cleanup-old-sessions-daily": {
        "task": "tasks.cleanup_old_sessions",
        "schedule": crontab(hour=2, minute=0),  # 매일 새벽 2시
    },
}


# Celery 이벤트 로깅
@celery.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
