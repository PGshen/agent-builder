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

## [T1.2] Skill Service（zip 存取 + CRUD API） —— 2026-08-29

**状态**：已完成

**完成内容**：
- `backend-api` 新增依赖 `minio==7.2.13`（与 agent-runner 同版本）、`python-multipart==0.0.20`（FastAPI 表单/文件上传需要）
- `app/config.py` 补了 `minio_endpoint` 属性（`{host}:{port}`），之前只有零散的 `minio_*` 字段
- `app/api/deps.py` 新增 `get_db_session`（FastAPI 依赖项，`async with session_factory() as session: yield session`）——T1.1 交接记录里提到缺这个，本任务补上，后续业务 router 统一用它拿 DB session
- `app/modules/skills/` 新增四个文件：
  - `storage.py` —— MinIO 客户端单例（同步 SDK + `asyncio.to_thread` 包装，模式抄 agent-runner 的 `health.py`）；zip 打包/解包（`pack_zip`/`unpack_zip`，UTF-8 文本）；`validate_files`（非空、必须含根路径 `SKILL.md`、路径防 zip slip）；路径分隔符统一归一化成 `/`
  - `schemas.py` —— `SkillListItem`/`SkillDetail`（含 `files` 字典）/`SkillUpdateRequest`
  - `service.py` —— `list_skills`/`create_skill`/`get_skill_detail`/`update_skill`/`delete_skill`，`SkillNotFoundError`/`SkillNameConflictError` 两个业务异常
  - `router.py` —— `GET/POST /skills`、`GET/PUT/DELETE /skills/{id}`，整体挂 `Depends(get_current_admin)`
- `app/main.py` 挂载 `skills_router`
- `tests/test_skills.py`（新增，6 个用例）+ `tests/conftest.py` 新增 `_reset_db_engine_per_test` autouse fixture
- 手工全链路验证：`docker compose build/up backend-api` 重建镜像后，用真实 zip 文件（含 Windows `Compress-Archive` 生成的、路径分隔符是 `\` 的 zip）走了一遍 登录 → 创建 → 列表 → 详情（确认路径已归一化成 `/`）→ 编辑保存（版本号 1→2）→ 删除 → 再次 GET 返回 404 的完整闭环

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.2 的"决策记录"小节，要点：创建接口收 zip（multipart），编辑/保存接口收/发 JSON 文件树（不是 zip）；MinIO key 固定 `{skill_id}.zip` 原地覆盖，版本号只是 Postgres 字段；v1 只支持 UTF-8 文本文件，不支持二进制资源；名称唯一性靠 DB unique 约束 + `IntegrityError` 转译成 409；删除顺序是先删 MinIO 对象再删 DB 行
- **顺带修了 T0.2 的一个潜在 bug**（不是本任务范围内的新决策，是排查测试失败时发现的既有缺陷）：`app/db.py::dispose_engine()` 只清空了 `_engine` 全局单例，没有同步清空同样是全局单例、绑定着旧 engine 的 `_session_factory`。生产环境单进程单 event loop 场景下这个 bug 完全不会触发（`_session_factory` 只会被创建一次，从未需要"跟着 engine 一起换新"），但本任务写多用例 pytest 时稳定复现为 `RuntimeError: Event loop is closed`（且必定是整个测试会话里最后一个碰数据库的用例失败，因为前面用例的残留 `_session_factory` 一直没被清干净，直到最后一次 dispose 才会暴露）。已修复，`tests/conftest.py` 同步加了 `_reset_db_engine_per_test` fixture

**遗留问题**：
- 二进制资源文件不支持（v1 范围内的有意限制，见决策记录），如果后续 Skill 规范需要图片/二进制脚本等资源，需要重新设计文件树的传输格式（比如按扩展名分文本/二进制两种编码）
- `SKILL.md` 里的 YAML frontmatter（`name`/`description` 等字段）目前没有做内容级解析和与 Postgres `name` 字段的一致性校验——创建时的 `name` 是调用方显式传的表单字段，和 zip 内 `SKILL.md` frontmatter 里写的 name 可能不一致，本任务没有处理这个潜在的不一致，留给以后如果需要更严格的规范校验时再加
- 删除失败的部分成功场景（MinIO 删除失败）目前只是把错误抛给调用方、DB 行原样保留，没有专门的重试/告警机制，v1 认为手动重试删除已经够用

**给下一个任务的建议**：
- T1.3（Skill 管理前端页面）：`GET /skills/{id}` 返回的 `files` 是 `{路径: 文本内容}` 的 flat map（不是嵌套树结构），前端如果要做文件树 UI，需要自己按路径里的 `/` 分隔符在前端建树；保存时把编辑后的完整 `files` map（不只是改动的文件）整体传给 `PUT /skills/{id}`，因为后端是整体重新打包，不做增量 patch
- 创建页如果走"上传 zip"路线，直接对接 `POST /skills`（`multipart/form-data`：`name` 字段 + `file` 字段）；如果走"从模板创建"路线，则可以考虑前端本地构造一个含 `SKILL.md` 的最小文件树，用同样的 zip 打包后走同一个创建接口，不需要后端另开一个"从模板"专用接口
- `app/api/deps.py` 的 `get_db_session` 现在已经就绪，T1.4（MCP Service）直接复用，不用重新写一遍数据库 session 依赖项
- 以后写新的 async 测试如果又遇到 `RuntimeError: Event loop is closed` 或类似的跨 loop 报错，先检查是不是又出现了"模块级单例缓存了绑定旧 loop/旧资源的对象，但重置函数只清了部分变量"这种模式——这次踩的 `_session_factory` 坑和 T0.5 踩的 Redis 客户端坑是同一类问题，本质是全局单例 + pytest 每测试新 event loop 的组合，跟业务逻辑无关
