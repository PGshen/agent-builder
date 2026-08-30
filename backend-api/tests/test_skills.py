import io
import uuid
import zipfile

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    settings = get_settings()
    response = await client.post(
        "/auth/login",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _build_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _valid_skill_zip() -> bytes:
    return _build_zip(
        {
            "SKILL.md": "---\nname: demo\ndescription: a demo skill\n---\n# Demo\n",
            "scripts/run.py": "print('hello')\n",
        }
    )


async def test_skills_endpoints_require_auth():
    async with await _client() as client:
        response = await client.get("/skills")
    assert response.status_code == 401


async def test_create_reject_zip_missing_skill_md():
    bad_zip = _build_zip({"README.md": "not a skill manifest"})
    async with await _client() as client:
        headers = await _auth_headers(client)
        response = await client.post(
            "/skills",
            data={"name": f"bad-skill-{uuid.uuid4().hex[:8]}"},
            files={"file": ("skill.zip", bad_zip, "application/zip")},
            headers=headers,
        )
    assert response.status_code == 400
    assert "SKILL.md" in response.json()["detail"]


async def test_create_list_edit_save_delete_skill_lifecycle():
    name = f"demo-skill-{uuid.uuid4().hex[:8]}"
    async with await _client() as client:
        headers = await _auth_headers(client)

        create_response = await client.post(
            "/skills",
            data={"name": name},
            files={"file": ("skill.zip", _valid_skill_zip(), "application/zip")},
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["name"] == name
        assert created["version"] == 1
        assert created["active_version"] == 1
        skill_id = created["id"]

        list_response = await client.get("/skills", headers=headers)
        assert list_response.status_code == 200
        assert any(item["id"] == skill_id for item in list_response.json())

        detail_response = await client.get(f"/skills/{skill_id}", headers=headers)
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["files"]["SKILL.md"].startswith("---")
        assert "scripts/run.py" in detail["files"]

        edited_files = dict(detail["files"])
        edited_files["scripts/run.py"] = "print('edited')\n"
        update_response = await client.put(
            f"/skills/{skill_id}", json={"files": edited_files}, headers=headers
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["version"] == 2
        assert updated["active_version"] == 2

        detail_after_update = await client.get(f"/skills/{skill_id}", headers=headers)
        detail_after_update_body = detail_after_update.json()
        assert detail_after_update_body["files"]["scripts/run.py"] == "print('edited')\n"
        # 保存是新增版本，不是覆盖：旧版本的记录还在，且能各自拿到不同内容
        assert [v["version"] for v in detail_after_update_body["versions"]] == [1, 2]

        rollback_response = await client.post(f"/skills/{skill_id}/versions/1/activate", headers=headers)
        assert rollback_response.status_code == 200
        rolled_back = rollback_response.json()
        assert rolled_back["active_version"] == 1
        assert rolled_back["version"] == 2  # 历史上创建过的最新版本号不因回滚而改变

        detail_after_rollback = await client.get(f"/skills/{skill_id}", headers=headers)
        assert detail_after_rollback.json()["files"]["scripts/run.py"] == "print('hello')\n"

        activate_missing_version = await client.post(
            f"/skills/{skill_id}/versions/99/activate", headers=headers
        )
        assert activate_missing_version.status_code == 404

        restore_latest = await client.post(f"/skills/{skill_id}/versions/2/activate", headers=headers)
        assert restore_latest.json()["active_version"] == 2

        update_missing_manifest = await client.put(
            f"/skills/{skill_id}", json={"files": {"scripts/run.py": "x = 1\n"}}, headers=headers
        )
        assert update_missing_manifest.status_code == 400

        delete_response = await client.delete(f"/skills/{skill_id}", headers=headers)
        assert delete_response.status_code == 204

        get_after_delete = await client.get(f"/skills/{skill_id}", headers=headers)
        assert get_after_delete.status_code == 404


async def test_create_duplicate_name_conflicts():
    name = f"dup-skill-{uuid.uuid4().hex[:8]}"
    async with await _client() as client:
        headers = await _auth_headers(client)

        first = await client.post(
            "/skills",
            data={"name": name},
            files={"file": ("skill.zip", _valid_skill_zip(), "application/zip")},
            headers=headers,
        )
        assert first.status_code == 201
        skill_id = first.json()["id"]

        second = await client.post(
            "/skills",
            data={"name": name},
            files={"file": ("skill.zip", _valid_skill_zip(), "application/zip")},
            headers=headers,
        )
        assert second.status_code == 409

        await client.delete(f"/skills/{skill_id}", headers=headers)
