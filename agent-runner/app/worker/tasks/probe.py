from app.logging_config import get_logger
from app.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="probe.ping")
def ping() -> str:
    """最简单的测试任务：验证 Celery worker 能连上 Redis broker 并正确消费任务。"""

    logger.info("probe_ping_executed")
    return "pong"
