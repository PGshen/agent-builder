# sdk_sessions 表的 SQLAlchemy 模型只在这里定义（供 Alembic 迁移用）。
# 实际的 SessionStore adapter 实现（对接 Claude Agent SDK 的 SessionStore 接口读写这张表）
# 落在 agent-runner/app/sessions/store.py——因为 SDK 是在 agent-runner 进程内被调用的，
# adapter 对象要以 Python 对象形式传给 ClaudeAgentOptions.session_store，必须和 SDK 调用同进程。
# 见 docs/TASKS.md T4.1 决策记录。
