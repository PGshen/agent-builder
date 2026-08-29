from app.worker.celery_app import celery_app
from app.worker.tasks.probe import ping


def test_probe_task_runs_synchronously_in_eager_mode():
    celery_app.conf.task_always_eager = True
    try:
        result = ping.delay()
        assert result.get(timeout=5) == "pong"
    finally:
        celery_app.conf.task_always_eager = False
