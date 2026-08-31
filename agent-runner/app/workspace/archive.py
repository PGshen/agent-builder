"""仓库快照 / 输出快照打包成 zip。与 backend-api `app/modules/skills/storage.py` 的打包思路一致
（一个快照对应一个 zip 对象），但这里的仓库内容是任意二进制文件，不像 Skill 内容那样限定 UTF-8 文本，
所以直接按文件字节写入，不做文本解码/编码。
"""

import io
import zipfile
from pathlib import Path


def zip_directory(root: Path) -> bytes:
    """把 `root` 目录打包成 zip，压缩包内路径以 `root` 的父目录为基准（如 root 是 `<tmp>/repos`，
    压缩包内条目形如 `repos/<repo-dir-name>/...`）。`root` 不存在或为空目录时返回空 zip。
    """

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=str(path.relative_to(root.parent)))
    return buffer.getvalue()


def zip_directory_flat(root: Path) -> bytes:
    """把 `root` 目录本身的内容打包成 zip，压缩包内路径以 `root` 为基准（而不是 `zip_directory`
    那种以父目录为基准）——用于输出快照：`root` 就是执行用的 cwd 本身，解压回去要求原地还原成同一个
    目录内容，不需要（也不应该）多一层目录包裹。"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=str(path.relative_to(root)))
    return buffer.getvalue()


def empty_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w"):
        pass
    return buffer.getvalue()


def extract_zip(data: bytes, dest: Path) -> None:
    """把 zip 内容解压到 `dest`（T4.3 组装本地工作目录用）。先清空 `dest` 再解压，保证目录内容
    与快照内容完全一致，不会残留上一次解压后又被快照删除的文件。"""

    if dest.exists():
        for path in sorted(dest.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            else:
                path.rmdir()
    dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(dest)
