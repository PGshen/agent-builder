# AgentBuilder 任务交接记录

> 每完成（或阶段性中断）一个任务，在本文件末尾追加一条记录，方便下一个任务/下一次会话接手时不用重新翻代码或猜实现细节。按时间顺序追加，不要修改或删除历史记录（发现旧记录有误，用新记录说明更正，而不是回去改旧的）。

## 归档记录

> 本文件太长时，按 Phase 边界把已完成 Phase 的记录整体搬到 `docs/handoff-archive/`，本文件只保留归档索引 + 尚未归档（通常是当前 Phase）的记录。归档只搬运、不改写内容；接手任务前，除了看本文件末尾的最近记录，也要检查下面的归档索引里是否有相关 Phase 的历史决策。

| Phase | 归档文件 | 归档时间 | 覆盖任务 |
|---|---|---|---|
| Phase 0（基础设施与骨架，T0.1~T0.5） | [handoff-archive/phase0-2026-08-29.md](./handoff-archive/phase0-2026-08-29.md) | 2026-08-29 | T0.1 Docker Compose、T0.2 Backend API 骨架（+ uv 迁移补充）、T0.3 Agent Runner 骨架、T0.4 前端骨架（+ pnpm/shadcn 补充）、T0.5 登录鉴权 |
| Phase 1（元数据管理：Skill / MCP，T1.1~T1.5） | [handoff-archive/phase1-2026-08-30.md](./handoff-archive/phase1-2026-08-30.md) | 2026-08-30 | T1.1 数据模型与迁移、T1.2 Skill Service（+ 版本历史补充）、T1.3 Skill 管理前端页面（+ 抽屉/嵌套树/新建目录补充）、T1.4 MCP Service（加密+脱敏）、T1.5 MCP 管理前端页面 |

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

Phase 0（T0.1~T0.5）、Phase 1（T1.1~T1.5）均已全部完成并归档，见上方归档索引。当前进入 Phase 2（Agent 构建器与 Workspace 初始化）。

## [T2.1] Agent Service —— 2026-08-30

**状态**：已完成

**完成内容**：
- `backend-api` 新增依赖 `celery[redis]==5.4.0`（只当 Celery 生产者用，不消费）
- `app/config.py` 新增 `celery_broker_db`（复用 agent-runner 同一个 `CELERY_BROKER_DB` 环境变量，指向同一个 broker）+ `agent_repo_encryption_key`（独立于 T1.4 `mcp_encryption_key` 的新 Fernet 密钥）；顺带把 `auth_redis_url` 重构成走新增的 `_redis_url(db)` 私有 helper（跟 agent-runner `config.py` 的写法对齐）
- `.env.example` 新增 `AGENT_REPO_ENCRYPTION_KEY` 及生成方式说明
- `app/modules/agents/` 新增五个文件（`models.py` 是 T1.1 就绪的）：
  - `crypto.py` —— `encrypt_credential`/`decrypt_credential`，单字符串 Fernet 加解密（不是 T1.4 那种整份 dict）
  - `masking.py` —— `mask_credential`（打码）、`resolve_credential_encrypted`（占位符回填/真正轮换的解析逻辑）
  - `schemas.py` —— `AgentRepositoryInput`（含可选 `id`，编辑时用来匹配旧仓库行以沿用密文）/`AgentRepositoryDetail`/`AgentCreateRequest`/`AgentUpdateRequest`/`AgentListItem`（含三个绑定计数）/`AgentDetail`（含 skills/mcp_servers/repositories 明细）
  - `tasks.py` —— 轻量 Celery 生产者客户端，`trigger_workspace_init(agent_id)` 向 `"workspace.init"` 任务发消息，发送失败只记警告不抛异常
  - `service.py` —— `list_agents`（聚合查询算三类绑定数量，非 N+1）/`get_agent_detail`/`create_agent`/`update_agent`/`delete_agent`，`AgentNotFoundError`/`AgentNameConflictError`/`InvalidBindingError` 三个业务异常
  - `router.py` —— `GET/POST /agents`、`GET/PUT/DELETE /agents/{id}`，整体挂 `Depends(get_current_admin)`
- `app/main.py` 挂载 `agents_router`
- `tests/test_agents.py`（新增 5 个用例）+ `docker compose build/up backend-api` 重建镜像后用 `curl` 走了真实容器的登录 → 创建 → 列表 → 删除；用 `redis-cli LLEN celery` 确认 `trigger_workspace_init` 真的把消息发到了 broker（验证完清空了这几条测试消息，避免以后 T2.3 worker 上线消费到脏数据）

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T2.1 的"决策记录"小节，要点：workspace 初始化用 Celery `send_task("workspace.init", args=[agent_id])` 触发（T2.3 落地时 Runner 侧要注册同名任务消费，这是本任务定的契约）、发送失败不阻塞 Agent 创建；仓库凭证加密用独立密钥 `AGENT_REPO_ENCRYPTION_KEY`（不复用 MCP 的）；`AgentRepositoryInput.id` 是编辑时保留凭证密文的关键（按 id 匹配旧行，匹配不到视为新增仓库）；PUT 全量覆盖三类绑定（先删后插，不做差量 diff）；PUT 不会自动重新触发 workspace 初始化（留给 T2.4 的"失败重试"承担）；补充了 TASKS 原文没写的 `DELETE /agents/{id}`（对齐 Skill/MCP 已有的完整 CRUD 形状），级联删除子表全靠数据库 `ondelete=CASCADE`，应用层不用手动清理
- 仓库鉴权方式取值按 TASKS 原文"落地时约束"定为 `Literal["none", "token", "ssh_key"]`

**遗留问题**：
- `trigger_workspace_init` 发出的 `"workspace.init"` 任务目前没有任何 worker 消费（T2.3 还没实现），消息会在 Redis broker 队列里一直排队；T2.3 落地后要注意任务名/参数签名必须对上（`args=[agent_id_str]`），且要考虑给这个队列设置合理的过期/重试策略（本任务没有设置任何 message TTL 或 routing_key，用的是 Celery 默认队列 `"celery"`）
- Agent 删除目前只删 Postgres 行（级联删子表），T2.3 落地后 Agent 会在 MinIO 产生仓库快照/输出快照对象，那时候 `delete_agent` 需要同步清理这些 MinIO 对象（参考 Skill 删除的做法），本次没有实现（因为现在还没有对象可清）
- 编辑仓库列表时是否要自动重新触发 workspace 初始化（比如仓库 URL 改了，是不是应该马上重新 clone）没有定论，本任务刻意不做这件事，留给 T2.4 或后续任务基于实际交互需求决定
- `AgentUpdateRequest` 目前直接继承 `AgentCreateRequest`（字段完全一样），如果以后编辑接口需要跟创建接口有字段差异（比如编辑不允许改某个字段），需要拆开成独立定义

**给下一个任务的建议**：
- T2.2（Agent Builder 前端页面）：`GET /agents/{id}` 返回的 `repositories[].auth_credential` 已经是打码值（`"********"`，来自 `app/modules/agents/masking.py::MASK_SENTINEL`），前端表单展示时直接显示打码值即可；编辑保存时把仓库行（含原 `id`）整体带回 `PUT /agents/{id}`，不用自己判断"这行凭证改没改"；新增的仓库行不要带 `id`（或带 `null`）
- 勾选 skills/MCP 直接用已有的 `listSkills()`/`listMcpServers()`（T1.3/T1.5 已经有的前端 API 封装）拿列表，不需要新接口
- Agent 状态是 `initializing`/`ready`/`failed`（T2.4 定义），T2.2 详情页展示状态用的字段是 `AgentDetail.status`/`status_message`，创建接口返回的初始状态永远是 `"initializing"`
- T2.3（Workspace 初始化任务）落地时：Runner 侧要在 `agent-runner/app/worker/tasks/` 下新增一个任务，`@celery_app.task(name="workspace.init")`，接受 `agent_id`（字符串）参数；backend-api 这边已经在发这个任务了，不需要改 backend-api 代码，只需要 Runner 侧实现消费逻辑（clone、打包、更新 Postgres 里的 `Agent.status`/`status_message`/`WorkspaceSnapshot` 各字段）
- T2.4 如果要实现"失败状态下重试"，直接复用 `app/modules/agents/tasks.py::trigger_workspace_init(agent_id)` 即可，不需要重新写发送逻辑，只需要在重试接口里调用它 + 把 `Agent.status` 重置回 `"initializing"`
