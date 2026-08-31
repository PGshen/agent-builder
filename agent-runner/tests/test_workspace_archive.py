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


def test_zip_directory_flat_uses_root_relative_arcnames(tmp_path: Path):
    output_dir = tmp_path / "output"
    (output_dir / "nested").mkdir(parents=True)
    (output_dir / "README.md").write_text("hello")
    (output_dir / "nested" / "file.bin").write_bytes(b"\x00\x01")

    data = archive.zip_directory_flat(output_dir)

    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert set(zf.namelist()) == {"README.md", "nested/file.bin"}
        assert zf.read("README.md") == b"hello"


def test_extract_zip_round_trips_zip_directory_flat(tmp_path: Path):
    src = tmp_path / "src"
    (src / "nested").mkdir(parents=True)
    (src / "a.txt").write_text("A")
    (src / "nested" / "b.txt").write_text("B")
    data = archive.zip_directory_flat(src)

    dest = tmp_path / "dest"
    archive.extract_zip(data, dest)

    assert (dest / "a.txt").read_text() == "A"
    assert (dest / "nested" / "b.txt").read_text() == "B"


def test_extract_zip_clears_stale_files_not_present_in_new_zip(tmp_path: Path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "stale.txt").write_text("old")

    data = archive.zip_directory_flat(Path("/nonexistent"))  # 空 zip
    archive.extract_zip(data, dest)

    assert not (dest / "stale.txt").exists()


def test_empty_zip_has_no_entries():
    data = archive.empty_zip()
    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert zf.namelist() == []
