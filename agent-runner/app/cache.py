from pathlib import Path

from app.config import get_settings


def ensure_local_cache_dir() -> Path:
    """确保本地临时磁盘缓存目录存在。供后续 workspace 相关任务（clone/快照合并）使用，本任务只建目录不写业务数据。"""

    cache_dir = Path(get_settings().runner_local_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def check_local_cache_writable() -> bool:
    try:
        cache_dir = ensure_local_cache_dir()
        probe_file = cache_dir / ".write_probe"
        probe_file.write_text("ok")
        probe_file.unlink()
        return True
    except OSError:
        return False
