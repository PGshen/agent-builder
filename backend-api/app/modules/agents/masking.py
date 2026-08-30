"""Agent 绑定仓库鉴权凭证（auth_credential）的脱敏 / 回填逻辑，方式与 mcp/masking.py 保持一致，
但字段本身是单个字符串（不是 key-value dict），所以不需要按 key 逐个处理。
"""

from app.modules.agents import crypto
from app.modules.agents.models import AgentRepository

MASK_SENTINEL = "********"


def mask_credential(repository: AgentRepository) -> str | None:
    return MASK_SENTINEL if repository.auth_credential else None


def resolve_credential_encrypted(
    *, existing: AgentRepository | None, auth_type: str, submitted_credential: str | None
) -> str | None:
    """把创建/更新请求里的明文（或 MASK_SENTINEL 占位符）凭证解析成待落库的密文。

    - `auth_type == "none"`：不需要凭证，直接返回 None
    - 提交值是 MASK_SENTINEL（未重新输入）：沿用 `existing` 那一行的密文（新增仓库没有 `existing` 可沿用，视为未提供凭证）
    - 其它非空值：视为真实明文，重新加密
    """
    if auth_type == "none":
        return None
    if submitted_credential is None or submitted_credential == MASK_SENTINEL:
        return existing.auth_credential if existing is not None else None
    return crypto.encrypt_credential(submitted_credential)
