"""仓库定时刷新任务（TECH_DESIGN 4.3，TASKS.md T3.2）：scheduler 按 Agent 的刷新周期定时派发
`"workspace.refresh_repos"`，Runner 侧重新 clone 全部绑定仓库 → 打包成新版本仓库快照 → 只更新
`workspace_snapshots` 的仓库快照部分，不触碰输出快照、不改变 Agent 状态（刷新独立于 Agent 可用性
和对话互斥锁，对应 `workspace.init` 会 mark_agent_status 但这里完全不调用）。

**先用 `git ls-remote` 查一遍远程 HEAD，跟每个仓库上一次同步的 commit 比较，全部没有变化才跳过
本次 clone+打包+上传**——否则每个刷新周期都无条件重新写一份新版本快照到 MinIO，仓库长期没有更新
时也会不停膨胀出没有实际差异的历史版本，既浪费存储也让 `workspace_snapshots` 的版本号失去意义。
跳过时仍然要 `update_repository_sync_info` 刷新 `last_synced_at`（清空可能存在的旧
`last_sync_error`），否则这个 Agent 会一直"到期"，下一轮扫描立刻被 scheduler 重新判定为到期
派发，变相绕过用户配置的刷新周期。

任意一个仓库的更新检查或 clone 失败时，整体放弃本次刷新（不落地部分快照，与 `workspace.init` 的
"整体失败、不做部分成功"一致），保留上一次成功的仓库快照不变，只把失败原因记到那个仓库的
`last_sync_error`，其余仓库、Agent 状态都不受影响。
"""

import asyncio
import tempfile
import uuid
from pathlib import Path

from app.logging_config import get_logger
from app.worker.celery_app import celery_app
from app.workspace import archive, db, git_ops, storage

logger = get_logger(__name__)


class _RepoRefreshError(Exception):
    """包一层，把 clone 失败的具体仓库 id 带出来，方便只标记那一个仓库的 `last_sync_error`。"""

    def __init__(self, repo_id: uuid.UUID, message: str) -> None:
        super().__init__(message)
        self.repo_id = repo_id
        self.message = message


@celery_app.task(name="workspace.refresh_repos")
def refresh_repos(agent_id: str) -> str:
    return asyncio.run(_run(agent_id))


async def _run(agent_id: str) -> str:
    agent_uuid = uuid.UUID(agent_id)
    context = await db.load_agent_context(agent_uuid)
    if context is None:
        logger.warning("workspace_refresh_agent_not_found", agent_id=agent_id)
        return "agent_not_found"

    if not context.repositories:
        logger.info("workspace_refresh_no_repositories", agent_id=agent_id)
        return "no_repositories"

    try:
        remote_commits = await _resolve_remote_commits(context.repositories)
    except _RepoRefreshError as exc:
        logger.warning("workspace_refresh_check_failed", agent_id=agent_id, reason=exc.message)
        await db.update_repository_sync_error(exc.repo_id, exc.message)
        return "failed"
    except Exception:  # noqa: BLE001 — 未预期异常也不能改变 Agent 可用性，只记日志
        logger.exception("workspace_refresh_unexpected_error", agent_id=agent_id)
        return "failed"

    if all(remote_commits[repo.id] == repo.last_synced_commit for repo in context.repositories):
        for repo in context.repositories:
            await db.update_repository_sync_info(repo.id, remote_commits[repo.id])
        logger.info("workspace_refresh_unchanged", agent_id=agent_id, repo_count=len(context.repositories))
        return "unchanged"

    try:
        synced_commits = await _clone_and_pack(context)
    except _RepoRefreshError as exc:
        logger.warning("workspace_refresh_failed", agent_id=agent_id, reason=exc.message)
        await db.update_repository_sync_error(exc.repo_id, exc.message)
        return "failed"
    except Exception:  # noqa: BLE001 — 未预期异常也不能改变 Agent 可用性，只记日志
        logger.exception("workspace_refresh_unexpected_error", agent_id=agent_id)
        return "failed"

    for repo_id, commit in synced_commits:
        await db.update_repository_sync_info(repo_id, commit)

    logger.info("workspace_refresh_succeeded", agent_id=agent_id, repo_count=len(context.repositories))
    return "refreshed"


async def _resolve_remote_commits(repositories: list[db.RepositoryRecord]) -> dict[uuid.UUID, str]:
    commits: dict[uuid.UUID, str] = {}
    for repo in repositories:
        try:
            commits[repo.id] = git_ops.remote_head_commit(repo)
        except git_ops.WorkspaceInitError as exc:
            raise _RepoRefreshError(repo.id, str(exc)) from exc
    return commits


async def _clone_and_pack(context: db.AgentInitContext) -> list[tuple[uuid.UUID, str]]:
    with tempfile.TemporaryDirectory(prefix="workspace-refresh-") as tmp_dir:
        repos_root = Path(tmp_dir) / "repos"
        repos_root.mkdir()

        used_names: set[str] = set()
        synced_commits: list[tuple[uuid.UUID, str]] = []
        for repo in context.repositories:
            dir_name = git_ops.repo_dir_name(repo.url, repo.position, used_names)
            try:
                commit = git_ops.clone_repository(repo, repos_root / dir_name)
            except git_ops.WorkspaceInitError as exc:
                raise _RepoRefreshError(repo.id, str(exc)) from exc
            synced_commits.append((repo.id, commit))

        repo_zip = archive.zip_directory(repos_root)

    repo_version = context.repo_snapshot_version + 1
    repo_key = storage.repo_snapshot_key(context.workspace_id, repo_version)
    await storage.put_workspace_object(repo_key, repo_zip)
    await db.update_repo_snapshot(context.agent_id, repo_key, repo_version)

    return synced_commits
