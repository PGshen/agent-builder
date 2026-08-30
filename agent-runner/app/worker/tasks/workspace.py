"""Workspace 初始化任务（TECH_DESIGN 4.1 / 4.3，TASKS.md T2.3）：
逐个 clone Agent 绑定的仓库 → 打包为仓库快照 → 连同一个空的输出快照一起上传 MinIO →
回写 Agent 状态与 workspace_snapshots 元信息。

任务名 `"workspace.init"`、参数 `agent_id`（str）是 backend-api `app/modules/agents/tasks.py`
在 T2.1 就已经定好的契约，这里必须原样对上才能被消费到。同一个任务重复触发（T2.4 失败重试）是安全的：
每次都是全新 clone + 新版本号的快照对象，不依赖上一次的中间状态。
"""

import asyncio
import tempfile
import uuid
from pathlib import Path

from app.logging_config import get_logger
from app.worker.celery_app import celery_app
from app.workspace import archive, db, git_ops, storage

logger = get_logger(__name__)

# 对应 WorkspaceSnapshot.output_snapshot_update_source 的第三种取值（T2.1 定义时只写了
# conversation_sync/emergency_fallback 两种，这里补上"初始化产生的空快照"这一种）
OUTPUT_SNAPSHOT_SOURCE_INIT = "workspace_init"


@celery_app.task(name="workspace.init")
def init_workspace(agent_id: str) -> str:
    return asyncio.run(_run(agent_id))


async def _run(agent_id: str) -> str:
    agent_uuid = uuid.UUID(agent_id)
    context = await db.load_agent_context(agent_uuid)
    if context is None:
        logger.warning("workspace_init_agent_not_found", agent_id=agent_id)
        return "agent_not_found"

    try:
        synced_commits = await _clone_and_pack(context)
    except git_ops.WorkspaceInitError as exc:
        logger.warning("workspace_init_failed", agent_id=agent_id, reason=str(exc))
        await db.mark_agent_status(context.agent_id, "failed", str(exc))
        return "failed"
    except Exception as exc:  # noqa: BLE001 — 任何未预期异常都要落成 Agent 失败态，不能让任务默默丢失
        logger.exception("workspace_init_unexpected_error", agent_id=agent_id)
        await db.mark_agent_status(context.agent_id, "failed", f"未预期的错误：{exc}")
        return "failed"

    for repo_id, commit in synced_commits:
        await db.update_repository_sync_info(repo_id, commit)

    await db.mark_agent_status(context.agent_id, "ready", None)
    logger.info("workspace_init_succeeded", agent_id=agent_id, repo_count=len(context.repositories))
    return "ready"


async def _clone_and_pack(context: db.AgentInitContext) -> list[tuple[uuid.UUID, str]]:
    with tempfile.TemporaryDirectory(prefix="workspace-init-") as tmp_dir:
        repos_root = Path(tmp_dir) / "repos"
        repos_root.mkdir()

        used_names: set[str] = set()
        synced_commits: list[tuple[uuid.UUID, str]] = []
        for repo in context.repositories:
            dir_name = git_ops.repo_dir_name(repo.url, repo.position, used_names)
            commit = git_ops.clone_repository(repo, repos_root / dir_name)
            synced_commits.append((repo.id, commit))

        repo_zip = archive.zip_directory(repos_root)

    output_zip = archive.empty_zip()

    repo_version = context.repo_snapshot_version + 1
    output_version = context.output_snapshot_version + 1
    repo_key = storage.repo_snapshot_key(context.workspace_id, repo_version)
    output_key = storage.output_snapshot_key(context.workspace_id, output_version)

    await storage.put_workspace_object(repo_key, repo_zip)
    await storage.put_workspace_object(output_key, output_zip)

    await db.save_workspace_snapshot(
        context.agent_id,
        repo_key,
        repo_version,
        output_key,
        output_version,
        OUTPUT_SNAPSHOT_SOURCE_INIT,
    )

    return synced_commits
