import uuid
from unittest.mock import AsyncMock

import pytest

from app.worker.celery_app import celery_app
from app.worker.tasks import workspace as workspace_task
from app.workspace import db, git_ops, storage


@pytest.fixture(autouse=True)
def _eager_mode():
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


def _context_with_repos(n: int) -> db.AgentInitContext:
    agent_id = uuid.uuid4()
    repos = [
        db.RepositoryRecord(
            id=uuid.uuid4(),
            url=f"https://example.com/repo-{i}.git",
            branch=None,
            auth_type="none",
            auth_credential=None,
            position=i,
        )
        for i in range(n)
    ]
    return db.AgentInitContext(
        agent_id=agent_id,
        workspace_id="ws-" + agent_id.hex,
        repositories=repos,
        repo_snapshot_version=0,
        output_snapshot_version=0,
    )


def test_init_workspace_success_marks_agent_ready(monkeypatch):
    context = _context_with_repos(2)

    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=context))
    monkeypatch.setattr(git_ops, "clone_repository", lambda repo, dest: "deadbeef")
    monkeypatch.setattr(storage, "put_workspace_object", AsyncMock())
    save_snapshot = AsyncMock()
    monkeypatch.setattr(db, "save_workspace_snapshot", save_snapshot)
    update_sync_info = AsyncMock()
    monkeypatch.setattr(db, "update_repository_sync_info", update_sync_info)
    mark_status = AsyncMock()
    monkeypatch.setattr(db, "mark_agent_status", mark_status)

    result = workspace_task.init_workspace.apply(args=[str(context.agent_id)]).get(timeout=5)

    assert result == "ready"
    save_snapshot.assert_awaited_once()
    assert save_snapshot.await_args.args[0] == context.agent_id
    assert save_snapshot.await_args.args[2] == 1  # repo_snapshot_version 从 0 变成 1
    assert save_snapshot.await_args.args[4] == 1  # output_snapshot_version 从 0 变成 1
    assert update_sync_info.await_count == 2
    mark_status.assert_awaited_once_with(context.agent_id, "ready", None)


def test_init_workspace_clone_failure_marks_agent_failed_without_partial_snapshot(monkeypatch):
    context = _context_with_repos(1)

    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=context))

    def _fail_clone(repo, dest):
        raise git_ops.WorkspaceInitError("仓库不可达")

    monkeypatch.setattr(git_ops, "clone_repository", _fail_clone)
    save_snapshot = AsyncMock()
    monkeypatch.setattr(db, "save_workspace_snapshot", save_snapshot)
    mark_status = AsyncMock()
    monkeypatch.setattr(db, "mark_agent_status", mark_status)

    result = workspace_task.init_workspace.apply(args=[str(context.agent_id)]).get(timeout=5)

    assert result == "failed"
    save_snapshot.assert_not_awaited()
    mark_status.assert_awaited_once_with(context.agent_id, "failed", "仓库不可达")


def test_init_workspace_returns_early_when_agent_not_found(monkeypatch):
    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=None))
    mark_status = AsyncMock()
    monkeypatch.setattr(db, "mark_agent_status", mark_status)

    result = workspace_task.init_workspace.apply(args=[str(uuid.uuid4())]).get(timeout=5)

    assert result == "agent_not_found"
    mark_status.assert_not_awaited()
