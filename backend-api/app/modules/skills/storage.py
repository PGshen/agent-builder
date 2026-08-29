"""Skill zip 包的打包/解包/校验，以及与 MinIO 的存取（一个 Skill 对应一个 zip 对象）。

MinIO 客户端沿用 agent-runner 已验证过的模式：官方 `minio` SDK 是同步客户端，
用 `asyncio.to_thread` 包一层给 async 代码用，不引入额外的异步 S3 客户端依赖。
"""

import asyncio
import io
import uuid
import zipfile

from minio import Minio

from app.config import get_settings

SKILL_MANIFEST_FILENAME = "SKILL.md"


class SkillValidationError(Exception):
    """zip 内容不符合 skill 目录规范（缺 SKILL.md、非法路径、非 UTF-8 文本等）。"""


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


def _object_key(skill_id: uuid.UUID) -> str:
    # 同一个 Skill 的 zip 对象固定用这个 key，保存时整体覆盖，不按版本号生成新 key
    # （版本号只是 Postgres 里的元数据字段）
    return f"{skill_id}.zip"


def _validate_path(path: str) -> None:
    if not path or path.startswith("/") or path.startswith("\\"):
        raise SkillValidationError(f"非法文件路径：{path}")
    if any(part in ("", "..") for part in path.replace("\\", "/").split("/")):
        raise SkillValidationError(f"非法文件路径：{path}")


def validate_files(files: dict[str, str]) -> None:
    if not files:
        raise SkillValidationError("Skill 内容不能为空")
    if SKILL_MANIFEST_FILENAME not in files:
        raise SkillValidationError(f"缺少 {SKILL_MANIFEST_FILENAME}，不符合 skill 目录规范")
    for path in files:
        _validate_path(path)


def pack_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content.encode("utf-8"))
    return buffer.getvalue()


def unpack_zip(data: bytes) -> dict[str, str]:
    files: dict[str, str] = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SkillValidationError("不是合法的 zip 文件") from exc

    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            _validate_path(info.filename)
            # zip 标准要求路径分隔符用 "/"；部分工具（如 Windows PowerShell 的 Compress-Archive）
            # 会写成 "\"，统一归一化成 "/"，否则同一路径在文件树里可能出现两种表示、保存时也不合规范
            path = info.filename.replace("\\", "/")
            raw = archive.read(info.filename)
            try:
                files[path] = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillValidationError(
                    f"文件 {path} 不是合法的 UTF-8 文本，v1 暂不支持二进制资源文件"
                ) from exc
    return files


def _put_object_sync(object_key: str, data: bytes) -> None:
    settings = get_settings()
    client = get_minio_client()
    client.put_object(
        settings.minio_bucket_skills,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type="application/zip",
    )


def _get_object_sync(object_key: str) -> bytes:
    settings = get_settings()
    client = get_minio_client()
    response = client.get_object(settings.minio_bucket_skills, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _remove_object_sync(object_key: str) -> None:
    settings = get_settings()
    client = get_minio_client()
    client.remove_object(settings.minio_bucket_skills, object_key)


async def put_skill_zip(skill_id: uuid.UUID, data: bytes) -> str:
    object_key = _object_key(skill_id)
    await asyncio.to_thread(_put_object_sync, object_key, data)
    return object_key


async def get_skill_zip(object_key: str) -> bytes:
    return await asyncio.to_thread(_get_object_sync, object_key)


async def delete_skill_zip(object_key: str) -> None:
    await asyncio.to_thread(_remove_object_sync, object_key)
