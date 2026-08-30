from celery import Celery

from app.config import get_settings
from app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "agent-builder-scheduler",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "scan-due-agents": {
            "task": "scheduler.scan_due_agents",
            "schedule": settings.scheduler_scan_interval_seconds,
            # 显式路由到 scheduler 专属队列（与 agent-runner 共用同一个 broker 时避免互相争抢任务，
            # 见 docs/TASKS.md T3.1 决策记录）
            "options": {"queue": "scheduler"},
        }
    },
)
