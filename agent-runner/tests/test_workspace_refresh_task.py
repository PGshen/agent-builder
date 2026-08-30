import uuid
from unittest.mock import AsyncMock

import pytest

from app.worker.celery_app import celery_app
from app.worker.tasks import refresh as refresh_task
from app.workspace import db, git_ops, storage


@pytest.fixture(autouse=True)
def _eager_mode():
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


def _context_with_repos(n: int, repo_snapshot_version: int = 3, synced_commit: str = "deadbeef") -> db.AgentInitContext:
    agent_id = uuid.uuid4()
    repos = [
        db.RepositoryRecord(
            id=uuid.uuid4(),
            url=f"https://example.com/repo-{i}.git",
            branch=None,
            auth_type="none",
            auth_credential=None,
            position=i,
            last_synced_commit=synced_commit,
        )
        for i in range(n)
    ]
    return db.AgentInitContext(
        agent_id=agent_id,
        workspace_id="ws-" + agent_id.hex,
        repositories=repos,
        repo_snapshot_version=repo_snapshot_version,
        output_snapshot_version=1,
    )


def _patch_all(monkeypatch):
    update_repo_snapshot = AsyncMock()
    monkeypatch.setattr(db, "update_repo_snapshot", update_repo_snapshot)
    update_sync_info = AsyncMock()
    monkeypatch.setattr(db, "update_repository_sync_info", update_sync_info)
    update_sync_error = AsyncMock()
    monkeypatch.setattr(db, "update_repository_sync_error", update_sync_error)
    mark_status = AsyncMock()
    monkeypatch.setattr(db, "mark_agent_status", mark_status)
    put_object = AsyncMock()
    monkeypatch.setattr(storage, "put_workspace_object", put_object)
    return update_repo_snapshot, update_sync_info, update_sync_error, mark_status, put_object


def test_refresh_repos_with_new_commits_bumps_repo_snapshot_only(monkeypatch):
    context = _context_with_repos(2, synced_commit="old-commit")
    update_repo_snapshot, update_sync_info, update_sync_error, mark_status, put_object = _patch_all(monkeypatch)

    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=context))
    monkeypatch.setattr(git_ops, "remote_head_commit", lambda repo: "new-commit")
    monkeypatch.setattr(git_ops, "clone_repository", lambda repo, dest: "new-commit")

    result = refresh_task.refresh_repos.apply(args=[str(context.agent_id)]).get(timeout=5)

    assert result == "refreshed"
    put_object.assert_awaited_once()
    update_repo_snapshot.assert_awaited_once_with(context.agent_id, "ws-" + context.agent_id.hex + "/repo-v4.zip", 4)
    assert update_sync_info.await_count == 2
    update_sync_error.assert_not_awaited()
    mark_status.assert_not_awaited()  # 刷新绝不改变 Agent 状态


def test_refresh_repos_skips_snapshot_when_remote_unchanged(monkeypatch):
    context = _context_with_repos(2, synced_commit="same-commit")
    update_repo_snapshot, update_sync_info, update_sync_error, mark_status, put_object = _patch_all(monkeypatch)

    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=context))
    monkeypatch.setattr(git_ops, "remote_head_commit", lambda repo: "same-commit")
    clone_called = []
    monkeypatch.setattr(git_ops, "clone_repository", lambda repo, dest: clone_called.append(repo) or "same-commit")

    result = refresh_task.refresh_repos.apply(args=[str(context.agent_id)]).get(timeout=5)

    assert result == "unchanged"
    assert clone_called == []  # 远程没有变化，不应该真的去 clone
    put_object.assert_not_awaited()
    update_repo_snapshot.assert_not_awaited()  # 没有新快照，版本号不应该被 bump
    assert update_sync_info.await_count == 2  # 但要刷新 last_synced_at，避免下一轮扫描立刻又判定到期
    for repo in context.repositories:
        update_sync_info.assert_any_await(repo.id, "same-commit")
    update_sync_error.assert_not_awaited()
    mark_status.assert_not_awaited()


def test_refresh_repos_remote_check_failure_records_error_without_cloning(monkeypatch):
    context = _context_with_repos(1, synced_commit="old-commit")
    update_repo_snapshot, update_sync_info, update_sync_error, mark_status, put_object = _patch_all(monkeypatch)

    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=context))

    def _fail_remote_check(repo):
        raise git_ops.WorkspaceInitError("仓库不可达")

    monkeypatch.setattr(git_ops, "remote_head_commit", _fail_remote_check)
    clone_called = []
    monkeypatch.setattr(git_ops, "clone_repository", lambda repo, dest: clone_called.append(repo) or "x")

    result = refresh_task.refresh_repos.apply(args=[str(context.agent_id)]).get(timeout=5)

    assert result == "failed"
    assert clone_called == []  # 更新检查阶段就失败了，不应该再走到 clone
    put_object.assert_not_awaited()
    update_repo_snapshot.assert_not_awaited()
    update_sync_info.assert_not_awaited()
    update_sync_error.assert_awaited_once_with(context.repositories[0].id, "仓库不可达")
    mark_status.assert_not_awaited()


def test_refresh_repos_clone_failure_keeps_previous_snapshot(monkeypatch):
    context = _context_with_repos(2, synced_commit="old-commit")
    update_repo_snapshot, update_sync_info, update_sync_error, mark_status, put_object = _patch_all(monkeypatch)

    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=context))
    monkeypatch.setattr(git_ops, "remote_head_commit", lambda repo: "new-commit")

    def _fail_second_repo(repo, dest):
        if repo.position == 1:
            raise git_ops.WorkspaceInitError("仓库不可达")
        return "new-commit"

    monkeypatch.setattr(git_ops, "clone_repository", _fail_second_repo)

    result = refresh_task.refresh_repos.apply(args=[str(context.agent_id)]).get(timeout=5)

    assert result == "failed"
    put_object.assert_not_awaited()
    update_repo_snapshot.assert_not_awaited()  # 保留上一次成功的仓库快照不变
    update_sync_info.assert_not_awaited()
    update_sync_error.assert_awaited_once_with(context.repositories[1].id, "仓库不可达")
    mark_status.assert_not_awaited()  # 失败也不影响 Agent 可用性


def test_refresh_repos_returns_early_when_agent_not_found(monkeypatch):
    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=None))
    update_repo_snapshot = AsyncMock()
    monkeypatch.setattr(db, "update_repo_snapshot", update_repo_snapshot)

    result = refresh_task.refresh_repos.apply(args=[str(uuid.uuid4())]).get(timeout=5)

    assert result == "agent_not_found"
    update_repo_snapshot.assert_not_awaited()


def test_refresh_repos_returns_early_when_no_repositories(monkeypatch):
    context = _context_with_repos(0)
    monkeypatch.setattr(db, "load_agent_context", AsyncMock(return_value=context))
    update_repo_snapshot = AsyncMock()
    monkeypatch.setattr(db, "update_repo_snapshot", update_repo_snapshot)

    result = refresh_task.refresh_repos.apply(args=[str(context.agent_id)]).get(timeout=5)

    assert result == "no_repositories"
    update_repo_snapshot.assert_not_awaited()
