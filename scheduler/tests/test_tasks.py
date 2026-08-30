import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from app import tasks as scheduler_tasks
from app.celery_app import celery_app
from app.db import AgentRepoSyncStatus


@pytest.fixture(autouse=True)
def _eager_mode():
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


def _status(min_last_synced_at, interval_minutes=30) -> AgentRepoSyncStatus:
    return AgentRepoSyncStatus(
        agent_id=uuid.uuid4(),
        repo_refresh_interval_minutes=interval_minutes,
        min_last_synced_at=min_last_synced_at,
    )


def test_scan_dispatches_only_due_agents(monkeypatch):
    now = datetime.now(UTC)
    due = _status(now - timedelta(minutes=45), interval_minutes=30)
    not_due = _status(now - timedelta(minutes=5), interval_minutes=30)

    monkeypatch.setattr(
        scheduler_tasks, "fetch_ready_agents_repo_sync_status", AsyncMock(return_value=[due, not_due])
    )
    monkeypatch.setattr(scheduler_tasks, "try_acquire_dispatch_lock", lambda agent_id: True)
    send_task = Mock()
    monkeypatch.setattr(celery_app, "send_task", send_task)

    dispatched = scheduler_tasks.scan_due_agents.apply().get(timeout=5)

    assert dispatched == 1
    send_task.assert_called_once_with(
        scheduler_tasks.WORKSPACE_REFRESH_TASK_NAME, args=[str(due.agent_id)], queue="agent-runner"
    )


def test_scan_skips_agent_locked_by_previous_round(monkeypatch):
    now = datetime.now(UTC)
    due = _status(now - timedelta(minutes=45), interval_minutes=30)

    monkeypatch.setattr(
        scheduler_tasks, "fetch_ready_agents_repo_sync_status", AsyncMock(return_value=[due])
    )
    monkeypatch.setattr(scheduler_tasks, "try_acquire_dispatch_lock", lambda agent_id: False)
    send_task = Mock()
    monkeypatch.setattr(celery_app, "send_task", send_task)

    dispatched = scheduler_tasks.scan_due_agents.apply().get(timeout=5)

    assert dispatched == 0
    send_task.assert_not_called()


def test_scan_dispatches_nothing_when_none_due(monkeypatch):
    now = datetime.now(UTC)
    not_due = _status(now - timedelta(minutes=5), interval_minutes=30)

    monkeypatch.setattr(
        scheduler_tasks, "fetch_ready_agents_repo_sync_status", AsyncMock(return_value=[not_due])
    )
    send_task = Mock()
    monkeypatch.setattr(celery_app, "send_task", send_task)

    dispatched = scheduler_tasks.scan_due_agents.apply().get(timeout=5)

    assert dispatched == 0
    send_task.assert_not_called()
