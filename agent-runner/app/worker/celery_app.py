from celery import Celery

from app.config import get_settings
from app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "agent-runner",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks.probe", "app.worker.tasks.workspace", "app.worker.tasks.refresh"],
)

celery_app.conf.update(
    task_track_started=True,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
)
