"""解密 Agent 绑定 MCP Server 的配置。与 backend-api `app/modules/mcp/crypto.py` 使用同一把
Fernet 密钥（`MCP_ENCRYPTION_KEY`，两侧从同一个 .env 读取）；Runner 侧只负责解密（组装 SDK
`mcp_servers` 参数时需要明文），不负责加密——加密只发生在 backend-api 保存 MCP 配置时。
"""

import json
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().mcp_encryption_key.encode("utf-8"))


def decrypt_config(config_encrypted: str) -> dict:
    payload = _fernet().decrypt(config_encrypted.encode("ascii"))
    return json.loads(payload.decode("utf-8"))
