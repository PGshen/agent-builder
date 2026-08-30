"""Clone 单个绑定仓库到本地目录。auth_type 三种取值（T2.1 约定）分别处理：
`none` 直接 clone；`token` 把解密后的凭证拼进 https URL；`ssh_key` 把解密后的私钥内容写入临时文件，
通过 `GIT_SSH_COMMAND` 让 git 使用它。凭证只在本函数调用栈内以明文存在，用完（含异常路径）立即清理临时文件。
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.config import get_settings
from app.logging_config import get_logger
from app.workspace.crypto import decrypt_credential
from app.workspace.db import RepositoryRecord

logger = get_logger(__name__)


class WorkspaceInitError(Exception):
    """clone 仓库失败（地址不可达、鉴权失败、超时等）。整个 workspace 初始化任务据此整体标记失败，
    不做部分成功（TASKS.md T2.3 决策）。"""


def repo_dir_name(url: str, position: int, used_names: set[str]) -> str:
    """把仓库 URL 转成快照 zip 里可读的目录名，多仓库场景下各自独立、互不冲突。"""

    base = url.rstrip("/").rsplit("/", 1)[-1]
    if base.endswith(".git"):
        base = base[:-4]
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("._")
    if not base:
        base = f"repo-{position}"

    name = base
    suffix = 1
    while name in used_names:
        suffix += 1
        name = f"{base}-{suffix}"
    used_names.add(name)
    return name


def _inject_token(url: str, token: str) -> str:
    parsed = urlsplit(url)
    netloc = f"{token}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _write_ssh_key(private_key: str) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="agent-repo-key-")
    key_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(private_key if private_key.endswith("\n") else private_key + "\n")
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        key_path.unlink(missing_ok=True)
        raise
    return key_path


def _force_remove_readonly(func, path, exc_info):  # noqa: ANN001 — shutil.rmtree onerror 签名固定
    # git 在 .git/objects 下会把部分对象文件设成只读；Windows 上 shutil.rmtree 遇到只读文件直接报错，
    # 需要先去掉只读位再重试删除（Linux 容器里通常不会触发这个分支，但同一份逻辑跨平台都适用）
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _redact(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


@contextmanager
def _prepared_auth(repo: RepositoryRecord):
    """按 `auth_type` 准备好可直接喂给 git 命令的 url/env（token 拼进 URL、ssh_key 落临时文件走
    `GIT_SSH_COMMAND`），`clone_repository` 和 `remote_head_commit`（刷新前的更新检查）共用同一份
    凭证准备逻辑，避免重复。ssh_key 场景的临时私钥文件在 with 块结束（含异常路径）时立即清理。
    """

    credential = decrypt_credential(repo.auth_credential) if repo.auth_credential else None
    url = repo.url
    env = os.environ.copy()
    ssh_key_path: Path | None = None
    secrets_to_redact = [credential] if credential else []

    try:
        if repo.auth_type == "token" and credential:
            url = _inject_token(repo.url, credential)
        elif repo.auth_type == "ssh_key" and credential:
            ssh_key_path = _write_ssh_key(credential)
            env["GIT_SSH_COMMAND"] = (
                f'ssh -i "{ssh_key_path}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
            )
        yield url, env, secrets_to_redact
    finally:
        if ssh_key_path is not None:
            ssh_key_path.unlink(missing_ok=True)


def clone_repository(repo: RepositoryRecord, dest: Path) -> str:
    """clone 到 `dest`（须不存在，git clone 会自己创建），成功返回 HEAD commit hash。
    clone 完成后删除 `.git` 目录——仓库在 workspace 里只读展示，不需要保留完整的 git 历史/对象库。
    """

    with _prepared_auth(repo) as (clone_url, env, secrets_to_redact):
        cmd = ["git", "clone", "--depth", "1", "--single-branch"]
        if repo.branch:
            cmd += ["--branch", repo.branch]
        cmd += [clone_url, str(dest)]

        timeout = get_settings().workspace_clone_timeout_seconds
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise WorkspaceInitError(f"仓库 {repo.url} clone 超时（超过 {timeout} 秒）") from exc

        if result.returncode != 0:
            reason = _redact(result.stderr.strip(), secrets_to_redact)
            raise WorkspaceInitError(f"仓库 {repo.url} clone 失败：{reason}")

        rev_parse = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True, timeout=30
        )
        commit = rev_parse.stdout.strip() if rev_parse.returncode == 0 else ""

        shutil.rmtree(dest / ".git", onerror=_force_remove_readonly)
        return commit


def remote_head_commit(repo: RepositoryRecord) -> str:
    """只查询远程仓库当前 HEAD（或 `repo.branch` 指定分支）指向的 commit，不 clone、不下载内容。
    定时刷新（TASKS.md T3.2）用它判断仓库是否真的有更新——没有更新就不重新 clone+打包+写 MinIO
    快照，避免快照版本号和存储空间无意义膨胀。"""

    with _prepared_auth(repo) as (url, env, secrets_to_redact):
        ref = repo.branch if repo.branch else "HEAD"
        cmd = ["git", "ls-remote", url, ref]

        timeout = get_settings().workspace_clone_timeout_seconds
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired as exc:
            raise WorkspaceInitError(f"仓库 {repo.url} 查询远程更新超时（超过 {timeout} 秒）") from exc

        if result.returncode != 0:
            reason = _redact(result.stderr.strip(), secrets_to_redact)
            raise WorkspaceInitError(f"仓库 {repo.url} 查询远程更新失败：{reason}")

        first_line = next((line for line in result.stdout.splitlines() if line.strip()), "")
        commit = first_line.split("\t", 1)[0].strip() if first_line else ""
        if not commit:
            raise WorkspaceInitError(f"仓库 {repo.url} 查询远程更新失败：未找到 {ref} 对应的提交")
        return commit
