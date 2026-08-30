"""Workspace 快照对象在 MinIO 中的存取。MinIO 客户端沿用 backend-api
`app/modules/skills/storage.py` 已验证的模式（同步 SDK + `asyncio.to_thread` 包一层）。

Object key 约定：`{workspace_id}/repo-v{version}.zip` / `{workspace_id}/output-v{version}.zip`——
每次初始化/刷新都是新版本号、新对象（不覆盖旧对象），与 Skill 版本历史的"新增而不覆盖"风格一致，
也让 `workspace_snapshots` 表里的历史 object_key 仍然可追溯。
"""

import asyncio
import io

from minio import Minio

from app.config import get_settings

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=False,
        )
    return _client


def repo_snapshot_key(workspace_id: str, version: int) -> str:
    return f"{workspace_id}/repo-v{version}.zip"


def output_snapshot_key(workspace_id: str, version: int) -> str:
    return f"{workspace_id}/output-v{version}.zip"


def _put_object_sync(object_key: str, data: bytes) -> None:
    settings = get_settings()
    get_minio_client().put_object(
        settings.minio_bucket_workspaces,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type="application/zip",
    )


async def put_workspace_object(object_key: str, data: bytes) -> None:
    await asyncio.to_thread(_put_object_sync, object_key, data)
