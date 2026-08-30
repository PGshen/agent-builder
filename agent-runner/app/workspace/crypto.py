"""解密 Agent 绑定仓库的鉴权凭证。与 backend-api `app/modules/agents/crypto.py` 使用同一把
Fernet 密钥（`AGENT_REPO_ENCRYPTION_KEY`，两侧从同一个 .env 读取），Runner 侧只负责解密（clone 时
需要明文凭证），不负责加密——加密只发生在 backend-api 保存 Agent 仓库配置时。
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().agent_repo_encryption_key.encode("utf-8"))


def decrypt_credential(credential_encrypted: str) -> str:
    return _fernet().decrypt(credential_encrypted.encode("ascii")).decode("utf-8")
