import zipfile
from io import BytesIO
from pathlib import Path

from app.workspace import archive


def test_zip_directory_packs_files_with_relative_arcnames(tmp_path: Path):
    repos_root = tmp_path / "repos"
    (repos_root / "repo-a").mkdir(parents=True)
    (repos_root / "repo-a" / "README.md").write_text("hello")
    (repos_root / "repo-b" / "nested").mkdir(parents=True)
    (repos_root / "repo-b" / "nested" / "file.bin").write_bytes(b"\x00\x01\x02")

    data = archive.zip_directory(repos_root)

    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert names == {"repos/repo-a/README.md", "repos/repo-b/nested/file.bin"}
        assert zf.read("repos/repo-a/README.md") == b"hello"
        assert zf.read("repos/repo-b/nested/file.bin") == b"\x00\x01\x02"


def test_zip_directory_on_missing_or_empty_dir_returns_empty_archive(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    data = archive.zip_directory(missing)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert zf.namelist() == []


def test_empty_zip_has_no_entries():
    data = archive.empty_zip()
    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert zf.namelist() == []
