import json
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().mcp_encryption_key.encode("utf-8"))


def encrypt_config(config: dict) -> str:
    payload = json.dumps(config, ensure_ascii=False).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_config(config_encrypted: str) -> dict:
    payload = _fernet().decrypt(config_encrypted.encode("ascii"))
    return json.loads(payload.decode("utf-8"))
