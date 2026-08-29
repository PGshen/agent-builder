# AgentBuilder 任务交接记录

> 每完成（或阶段性中断）一个任务，在本文件末尾追加一条记录，方便下一个任务/下一次会话接手时不用重新翻代码或猜实现细节。按时间顺序追加，不要修改或删除历史记录（发现旧记录有误，用新记录说明更正，而不是回去改旧的）。

## 归档记录

> 本文件太长时，按 Phase 边界把已完成 Phase 的记录整体搬到 `docs/handoff-archive/`，本文件只保留归档索引 + 尚未归档（通常是当前 Phase）的记录。归档只搬运、不改写内容；接手任务前，除了看本文件末尾的最近记录，也要检查下面的归档索引里是否有相关 Phase 的历史决策。

| Phase | 归档文件 | 归档时间 | 覆盖任务 |
|---|---|---|---|
| Phase 0（基础设施与骨架，T0.1~T0.5） | [handoff-archive/phase0-2026-08-29.md](./handoff-archive/phase0-2026-08-29.md) | 2026-08-29 | T0.1 Docker Compose、T0.2 Backend API 骨架（+ uv 迁移补充）、T0.3 Agent Runner 骨架、T0.4 前端骨架（+ pnpm/shadcn 补充）、T0.5 登录鉴权 |

## 记录模板

```
## [任务ID] 任务名 —— YYYY-MM-DD

**状态**：已完成 / 阻塞 / 部分完成

**完成内容**：
- 做了什么，落在哪些文件/服务里

**关键决策与偏差**：
- 实现过程中做的、TASKS.md 里没写清楚的决策
- 与原计划不一致的地方，以及为什么这么改（若涉及需要回写 PRD/TECH_DESIGN 的决策，注明是否已回写）

**遗留问题**：
- 已知但本次没解决的问题，或有意留到后面处理的事项

**给下一个任务的建议**：
- 下一个任务接手时需要注意什么、可以复用什么
```

---

Phase 0（T0.1~T0.5）已全部完成并归档，见上方归档索引。当前进入 Phase 1（元数据管理：Skill / MCP）。

## [T1.1] 数据模型与数据库迁移 —— 2026-08-29

**状态**：已完成

**完成内容**：
- `backend-api` 新增 Alembic（`uv add alembic`），异步模板初始化在 `alembic/`（`alembic.ini` + `alembic/env.py` + `alembic/versions/`）
- 新增 `app/db_base.py`：`Base`（DeclarativeBase）+ `UUIDPKMixin`（UUID 主键，`gen_random_uuid()` 服务端默认）+ `TimestampMixin`（`created_at`/`updated_at`），供各模块模型共用
- 各业务模块新增 `models.py`：
  - `app/modules/skills/models.py` —— `Skill`（name/object_key/version/status）
  - `app/modules/mcp/models.py` —— `MCPServerConfig`（name/config JSONB/status）
  - `app/modules/agents/models.py` —— `Agent`（含 workspace_id/permission_mode/repo_refresh_interval_minutes/status/status_message）、`AgentSkill`/`AgentMCPServer`（多对多关联表）、`AgentRepository`（每个 Agent 可绑定多仓库，含鉴权字段与最近同步信息）、`WorkspaceSnapshot`（与 Agent 一对一，仓库快照/输出快照两段各自独立版本化）
  - `app/modules/conversations/models.py` —— `Conversation`（agent_id/session_id/status）
  - 新增 `app/modules/sessions/` 模块目录 + `models.py` —— `SDKSession`（`sdk_sessions` 表，SessionStore 记录，为 T4.1 预留）
- 生成并验证首个迁移 `alembic/versions/191e1f381995_initial_schema.py`（`alembic revision --autogenerate`），本地针对 T0.1 的 Postgres 实例验证：`upgrade head` 建出全部 10 张表（含 `alembic_version`）→ `alembic check` 确认模型与已应用 schema 无差异 → `downgrade base` 干净清空回到 1 张表 → 再次 `upgrade head` 复原，验证"空库一次性建出" + "增量应用" + "可回滚"三点
- `backend-api` 新增 `entrypoint.sh`（`alembic upgrade head` 后 `exec uvicorn`），`Dockerfile` 相应拷贝 `alembic.ini`/`alembic/`/`entrypoint.sh` 并把 `CMD` 换成该脚本；`docker compose build backend-api` + `up -d` + `restart` 验证过容器启动会自动把 schema 迁到最新且幂等（重启不报错、不重复建表）
- `uv run pytest -q` 5 个既有用例（T0.5 auth）全部仍通过，确认新增模型/迁移未破坏现有功能

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.1 的"决策记录"小节，要点：模型分散到各模块 `models.py`（而非集中 `app/models/`）；Agent 的 skill/MCP 绑定用关联表、仓库列表用独立表（都不用内嵌 JSON 数组）；Workspace 快照做成与 Agent 一对一的单表，仓库快照/输出快照字段各自一套；新增了 TASKS/TECH_DESIGN 都没明确写的 `Agent.status_message` 字段（为 T2.4 展示失败原因预留，避免后补迁移）；`workspace_id` 独立生成不复用主键；容器启动流程接入自动迁移
- Windows 本机 `alembic.ini` 一开始写了中文注释，触发 `configparser` 用 GBK locale 编码读取时的 `UnicodeDecodeError`，已改成纯 ASCII 注释，见 TASKS.md 决策记录里的具体说明——**以后凡是 alembic/pytest.ini 之类会被 Python 标准库 `configparser`/纯文本按 locale 编码读取的配置文件，本机环境下注释一律用英文**，避免重复踩坑

**遗留问题**：
- MCP 配置的敏感字段加密方式、Agent 绑定仓库凭证（`auth_credential`）的加密方式均未决定，当前 schema 只是预留了明文列（类型已定，内容处理留给 T1.4/T2.1）
- `sdk_sessions` 表的字段是"能跑起来的最小占位"（`session_id`+`agent_id`+不透明 JSONB `data`），T4.1 实现真正的 SessionStore adapter 时如果发现字段不够用（比如 SDK 接口需要额外的索引字段），需要再加一次迁移，不是本任务的遗漏，是有意留白
- 本次验证是针对本机单机 Postgres 做的（`docker compose down` 不会清库，用的是持久化 volume），没有专门起一个全新的空 Postgres 容器验证"从真正全新的空库建表"，但 `downgrade base` 后的库状态等价于全新空库（只剩 alembic 自身的版本表），逻辑上已覆盖这个验收点

**给下一个任务的建议**：
- T1.2（Skill Service）直接在 `app/modules/skills/` 下新增 `service.py`/`schemas.py`/`router.py`，`models.py` 里的 `Skill` 表已经就绪；数据库 session 用 `app/db.py` 的 `get_session_factory()`，目前还没有 FastAPI 依赖项包装成 `Depends`，需要自己在 `app/api/deps.py` 里补一个（如 `get_db_session`），T0.2 交接记录里也提过这一点，一直没有模块需要就没加，现在要用了
- 新建业务 router 记得接 `Depends(get_current_admin)`（`app/api/deps.py`），T0.5 交接记录强调过鉴权目前只保护了 `/auth/me`，业务路由需要自己接入，不要漏
- 以后新增/修改模型字段，流程是：改 `app/modules/<name>/models.py` → `uv run alembic revision --autogenerate -m "..."` → 检查生成的迁移文件（autogenerate 不总是完美，比如改字段类型、加索引名等有时需要手动调整）→ `uv run alembic upgrade head` 本地验证 → 提交时把 `alembic/versions/` 下新文件一并提交
- `agent_repositories`/`mcp_servers` 的敏感信息处理方式在 T1.4 定下来后，如果结论是要加密存储，记得同步回来看 `agent_repositories.auth_credential` 是否要用同样方式改造（TASKS.md T2.1 已经写了"与 T1.4 保持一致"这个约束）
- 本地起 backend-api 验证迁移：`cd backend-api && uv run alembic upgrade head`（连的是 `.env` 里 `localhost:5442`）；容器方式验证：`docker compose up -d --build backend-api`，日志里能看到 alembic 的输出在 uvicorn 启动之前
