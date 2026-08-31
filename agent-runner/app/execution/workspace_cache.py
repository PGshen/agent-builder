"""本地磁盘热缓存：把 MinIO 里的仓库快照/输出快照/Skill zip 拉取并解压到本地工作目录，
版本未变时跳过重新拉取（TASKS.md T4.3 验收标准）。

目录结构（`RUNNER_LOCAL_CACHE_DIR/{workspace_id}/` 下）：
- `repo/`      仓库快照解压结果，只读参考资料，作为 SDK `add_dirs` 的一员暴露给执行（TECH_DESIGN 4.4
               第 5 步"按 Agent 配置生成 additionalDirectories"——不合并进 cwd，靠 add_dirs 单独暴露，
               这样仓库刷新、输出同步互不干扰，不需要处理两者内容的合并/冲突）
- `output/`    输出快照解压结果，本次执行的 `cwd`（唯一可写目录）
- `skills/<skill-name>/`  各绑定 Skill 解压结果，作为 SDK `skills` 参数的路径列表
- `.cache_meta.json`  记录当前本地缓存对应的各部分版本号，下次准备时用来判断是否命中热缓存
"""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.execution.context import ExecutionContext
from app.logging_config import get_logger
from app.workspace import archive, storage

logger = get_logger(__name__)

_META_FILENAME = ".cache_meta.json"


@dataclass
class PreparedWorkspace:
    cwd: Path
    add_dirs: list[Path] = field(default_factory=list)
    skill_dirs: list[Path] = field(default_factory=list)


def _workspace_root(workspace_id: str) -> Path:
    return Path(get_settings().runner_local_cache_dir) / workspace_id


def _load_meta(root: Path) -> dict:
    meta_path = root / _META_FILENAME
    if not meta_path.exists():
        return {"repo_version": 0, "output_version": 0, "skills": {}}
    try:
        return json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"repo_version": 0, "output_version": 0, "skills": {}}


def _save_meta(root: Path, meta: dict) -> None:
    (root / _META_FILENAME).write_text(json.dumps(meta))


async def prepare_workspace(context: ExecutionContext) -> PreparedWorkspace:
    root = _workspace_root(context.workspace_id)
    root.mkdir(parents=True, exist_ok=True)
    meta = _load_meta(root)

    repo_dir = root / "repo"
    output_dir = root / "output"
    skills_root = root / "skills"

    await _sync_dir_if_stale(
        label="repo",
        workspace_id=context.workspace_id,
        dest=repo_dir,
        object_key=context.repo_snapshot_object_key,
        current_version=context.repo_snapshot_version,
        cached_version=meta.get("repo_version", 0),
        fetch=storage.get_workspace_object,
    )
    meta["repo_version"] = context.repo_snapshot_version

    await _sync_dir_if_stale(
        label="output",
        workspace_id=context.workspace_id,
        dest=output_dir,
        object_key=context.output_snapshot_object_key,
        current_version=context.output_snapshot_version,
        cached_version=meta.get("output_version", 0),
        fetch=storage.get_workspace_object,
    )
    meta["output_version"] = context.output_snapshot_version

    cached_skills: dict = meta.get("skills", {})
    skill_dirs: list[Path] = []
    current_skill_names = {skill.name for skill in context.skills}
    for skill in context.skills:
        skill_dir = skills_root / skill.name
        await _sync_dir_if_stale(
            label=f"skill:{skill.name}",
            workspace_id=context.workspace_id,
            dest=skill_dir,
            object_key=skill.object_key,
            current_version=skill.version,
            cached_version=cached_skills.get(skill.name, 0),
            fetch=storage.get_skill_object,
        )
        cached_skills[skill.name] = skill.version
        skill_dirs.append(skill_dir)

    # 清理已解绑 Skill 留下的本地目录，避免它们残留在 workspace 里被误当成仍然生效
    for stale_name in list(cached_skills):
        if stale_name not in current_skill_names:
            _remove_dir(skills_root / stale_name)
            del cached_skills[stale_name]
    meta["skills"] = cached_skills

    _save_meta(root, meta)

    # 仓库快照打包时（`app/worker/tasks/workspace.py` `_clone_and_pack`）用的是
    # `archive.zip_directory(repos_root)`，压缩包内路径以 `repos_root` 的父目录为基准，
    # 所以解压后各仓库实际落在 `repo_dir/repos/<repo-dir-name>/` 下，不是直接落在 `repo_dir/` 下
    repos_subdir = repo_dir / "repos"
    add_dirs = [repos_subdir] if repos_subdir.exists() else [repo_dir]

    return PreparedWorkspace(cwd=output_dir, add_dirs=add_dirs, skill_dirs=skill_dirs)


async def _sync_dir_if_stale(
    *,
    label: str,
    workspace_id: str,
    dest: Path,
    object_key: str | None,
    current_version: int,
    cached_version: int,
    fetch,
) -> None:
    if object_key is None:
        return

    if dest.exists() and cached_version == current_version:
        logger.info(
            "workspace_cache_hit", workspace_id=workspace_id, part=label, version=current_version
        )
        return

    logger.info(
        "workspace_cache_miss",
        workspace_id=workspace_id,
        part=label,
        cached_version=cached_version,
        current_version=current_version,
    )
    data = await fetch(object_key)
    archive.extract_zip(data, dest)


def _remove_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()
