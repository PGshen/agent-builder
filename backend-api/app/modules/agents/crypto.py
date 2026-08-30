from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().agent_repo_encryption_key.encode("utf-8"))


def encrypt_credential(credential: str) -> str:
    return _fernet().encrypt(credential.encode("utf-8")).decode("ascii")


def decrypt_credential(credential_encrypted: str) -> str:
    return _fernet().decrypt(credential_encrypted.encode("ascii")).decode("utf-8")
