import subprocess
import uuid
from pathlib import Path

import pytest

from app.workspace import git_ops
from app.workspace.db import RepositoryRecord


def _init_local_repo(path: Path) -> str:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_repo_dir_name_sanitizes_and_dedupes():
    used: set[str] = set()
    assert git_ops.repo_dir_name("https://github.com/org/my-repo.git", 0, used) == "my-repo"
    # 同名仓库（比如两个不同 org 但 basename 相同）不能覆盖，要出现 -2 后缀
    assert git_ops.repo_dir_name("https://gitlab.com/other/my-repo.git", 1, used) == "my-repo-2"


def test_repo_dir_name_falls_back_when_basename_is_empty():
    used: set[str] = set()
    # basename 全是正则会替换掉的非法字符，sanitize 后变成空字符串，落到 "repo-{position}" 兜底
    assert git_ops.repo_dir_name("https://example.com/@@@.git", 3, used) == "repo-3"


def test_inject_token_places_credential_in_netloc():
    url = git_ops._inject_token("https://github.com/org/repo.git", "s3cr3t")
    assert url == "https://s3cr3t@github.com/org/repo.git"


def test_clone_repository_clones_local_repo_and_strips_git_dir(tmp_path: Path):
    source = tmp_path / "source"
    expected_commit = _init_local_repo(source)

    dest = tmp_path / "dest"
    repo = RepositoryRecord(
        id=uuid.uuid4(), url=str(source), branch=None, auth_type="none", auth_credential=None, position=0
    )

    commit = git_ops.clone_repository(repo, dest)

    assert commit == expected_commit
    assert (dest / "README.md").read_text() == "hello"
    assert not (dest / ".git").exists()


def test_clone_repository_raises_workspace_init_error_for_unreachable_repo(tmp_path: Path):
    dest = tmp_path / "dest"
    repo = RepositoryRecord(
        id=uuid.uuid4(),
        url=str(tmp_path / "does-not-exist"),
        branch=None,
        auth_type="none",
        auth_credential=None,
        position=0,
    )

    with pytest.raises(git_ops.WorkspaceInitError):
        git_ops.clone_repository(repo, dest)
