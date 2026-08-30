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


def empty_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w"):
        pass
    return buffer.getvalue()
