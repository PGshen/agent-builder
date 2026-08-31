import uuid
from unittest.mock import AsyncMock

import pytest

from app.config import get_settings
from app.execution import context as context_module
from app.execution import workspace_cache
from app.workspace import archive


def _context(**overrides) -> context_module.ExecutionContext:
    agent_id = uuid.uuid4()
    defaults = dict(
        agent_id=agent_id,
        workspace_id="ws-" + agent_id.hex,
        permission_mode="default",
        repo_snapshot_object_key="ws/repo-v1.zip",
        repo_snapshot_version=1,
        output_snapshot_object_key="ws/output-v1.zip",
        output_snapshot_version=1,
        skills=[context_module.SkillRef(id=uuid.uuid4(), name="skill-a", object_key="skills/a-v1.zip", version=1)],
    )
    defaults.update(overrides)
    return context_module.ExecutionContext(**defaults)


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "runner_local_cache_dir", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_prepare_workspace_fetches_everything_on_first_run(monkeypatch):
    ctx = _context()

    async def _fetch(object_key):
        return archive.empty_zip()

    from app.workspace import storage

    get = AsyncMock(side_effect=_fetch)
    monkeypatch.setattr(storage, "get_workspace_object", get)
    monkeypatch.setattr(storage, "get_skill_object", AsyncMock(return_value=archive.empty_zip()))

    prepared = await workspace_cache.prepare_workspace(ctx)

    assert prepared.cwd.exists()
    assert get.await_count == 2  # repo + output
    meta = workspace_cache._load_meta(workspace_cache._workspace_root(ctx.workspace_id))
    assert meta["repo_version"] == 1
    assert meta["output_version"] == 1
    assert meta["skills"] == {"skill-a": 1}


async def test_prepare_workspace_skips_refetch_when_versions_unchanged(monkeypatch):
    ctx = _context()
    from app.workspace import storage

    get_ws = AsyncMock(return_value=archive.empty_zip())
    get_skill = AsyncMock(return_value=archive.empty_zip())
    monkeypatch.setattr(storage, "get_workspace_object", get_ws)
    monkeypatch.setattr(storage, "get_skill_object", get_skill)

    await workspace_cache.prepare_workspace(ctx)
    assert get_ws.await_count == 2
    assert get_skill.await_count == 1

    # 第二次版本号不变，应该完全跳过重新拉取
    await workspace_cache.prepare_workspace(ctx)
    assert get_ws.await_count == 2
    assert get_skill.await_count == 1


async def test_prepare_workspace_refetches_only_the_part_whose_version_changed(monkeypatch):
    ctx = _context()
    from app.workspace import storage

    get_ws = AsyncMock(return_value=archive.empty_zip())
    get_skill = AsyncMock(return_value=archive.empty_zip())
    monkeypatch.setattr(storage, "get_workspace_object", get_ws)
    monkeypatch.setattr(storage, "get_skill_object", get_skill)

    await workspace_cache.prepare_workspace(ctx)
    assert get_ws.await_count == 2

    ctx2 = _context(
        workspace_id=ctx.workspace_id,
        agent_id=ctx.agent_id,
        output_snapshot_version=2,
        output_snapshot_object_key="ws/output-v2.zip",
        skills=ctx.skills,
    )
    await workspace_cache.prepare_workspace(ctx2)
    # repo 版本没变（跳过），output 版本变了（重新拉取一次）
    assert get_ws.await_count == 3


async def test_prepare_workspace_removes_local_dir_for_unbound_skill(monkeypatch):
    ctx = _context()
    from app.workspace import storage

    monkeypatch.setattr(storage, "get_workspace_object", AsyncMock(return_value=archive.empty_zip()))
    monkeypatch.setattr(storage, "get_skill_object", AsyncMock(return_value=archive.empty_zip()))

    prepared = await workspace_cache.prepare_workspace(ctx)
    skill_dir = prepared.skill_dirs[0]
    assert skill_dir.exists()

    ctx_no_skills = _context(
        workspace_id=ctx.workspace_id, agent_id=ctx.agent_id, skills=[]
    )
    await workspace_cache.prepare_workspace(ctx_no_skills)

    assert not skill_dir.exists()
