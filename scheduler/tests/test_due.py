import uuid
from datetime import UTC, datetime, timedelta

from app.db import AgentRepoSyncStatus
from app.due import is_due


def _status(min_last_synced_at, interval_minutes=30) -> AgentRepoSyncStatus:
    return AgentRepoSyncStatus(
        agent_id=uuid.uuid4(),
        repo_refresh_interval_minutes=interval_minutes,
        min_last_synced_at=min_last_synced_at,
    )


def test_due_when_never_synced():
    assert is_due(_status(None), datetime.now(UTC)) is True


def test_not_due_within_interval():
    now = datetime.now(UTC)
    status = _status(now - timedelta(minutes=10), interval_minutes=30)
    assert is_due(status, now) is False


def test_due_exactly_at_interval_boundary():
    now = datetime.now(UTC)
    status = _status(now - timedelta(minutes=30), interval_minutes=30)
    assert is_due(status, now) is True


def test_due_past_interval():
    now = datetime.now(UTC)
    status = _status(now - timedelta(minutes=45), interval_minutes=30)
    assert is_due(status, now) is True


def test_due_uses_min_not_max_across_repos():
    # 名下某个仓库刚同步过，但最早的一个已经过期——MIN 口径下应判定到期
    now = datetime.now(UTC)
    status = _status(now - timedelta(minutes=40), interval_minutes=30)
    assert is_due(status, now) is True
