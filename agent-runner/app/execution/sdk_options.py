"""组装 Claude Agent SDK 调用参数（TECH_DESIGN 4.4 第 5 步）。

`SessionStore` 的 `project_key` 不是本模块显式传入的——SDK 内部用 `project_key_for_directory(cwd)`
（realpath + 规范化 + 哈希）自动派生。这对"跨 Runner 副本 resume"这条验收标准反而是有利的：只要
`RUNNER_LOCAL_CACHE_DIR` 在所有副本间是同一个绝对路径（compose 里挂同一个具名 volume，见 T0.3 决策），
同一个 `workspace_id` 在任意副本上算出的 `cwd`（`{RUNNER_LOCAL_CACHE_DIR}/{workspace_id}/output`）
都相同，派生出的 `project_key` 自然也相同，不需要额外传参对齐。
"""

from claude_agent_sdk import ClaudeAgentOptions

from app.execution import mcp_crypto
from app.execution.context import ExecutionContext
from app.execution.workspace_cache import PreparedWorkspace
from app.sessions.store import PostgresSessionStore


def build_options(
    context: ExecutionContext,
    workspace: PreparedWorkspace,
    *,
    resume_session_id: str | None,
) -> ClaudeAgentOptions:
    mcp_servers = {
        server.name: mcp_crypto.decrypt_config(server.config_encrypted) for server in context.mcp_servers
    }

    return ClaudeAgentOptions(
        cwd=str(workspace.cwd),
        add_dirs=[str(d) for d in workspace.add_dirs],
        skills=[str(d) for d in workspace.skill_dirs] or None,
        mcp_servers=mcp_servers,
        permission_mode=context.permission_mode,
        resume=resume_session_id,
        session_store=PostgresSessionStore(agent_id=context.agent_id),
    )
