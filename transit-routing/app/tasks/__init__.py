"""
Celery tasks for asynchronous operations
"""

from app.tasks.celery_app import celery
from app.tasks.tasks import (
    save_location_history,
    batch_save_locations,
    save_navigation_event,
    cleanup_old_sessions,
)

__all__ = [
    "celery",
    "save_location_history",
    "batch_save_locations",
    "save_navigation_event",
    "cleanup_old_sessions",
]
