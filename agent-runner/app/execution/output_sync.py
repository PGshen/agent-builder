"""执行完成后把本地输出目录（cwd）打包同步回 MinIO（TECH_DESIGN 4.4 第 7 步）。
只回写输出快照，仓库快照只读、本任务不涉及。
"""

from pathlib import Path

from app.execution.context import ExecutionContext, save_output_snapshot
from app.logging_config import get_logger
from app.workspace import archive, storage

logger = get_logger(__name__)

SOURCE_CONVERSATION_SYNC = "conversation_sync"
SOURCE_EMERGENCY_FALLBACK = "emergency_fallback"


async def sync_output_snapshot(
    context: ExecutionContext, output_dir: Path, *, update_source: str = SOURCE_CONVERSATION_SYNC
) -> None:
    data = archive.zip_directory_flat(output_dir)
    version = context.output_snapshot_version + 1
    object_key = storage.output_snapshot_key(context.workspace_id, version)

    await storage.put_workspace_object(object_key, data)
    await save_output_snapshot(context.agent_id, object_key, version, update_source)

    logger.info(
        "output_snapshot_synced",
        agent_id=str(context.agent_id),
        version=version,
        update_source=update_source,
    )
