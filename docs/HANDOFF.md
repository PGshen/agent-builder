# AgentBuilder 任务交接记录

> 每完成（或阶段性中断）一个任务，在本文件末尾追加一条记录，方便下一个任务/下一次会话接手时不用重新翻代码或猜实现细节。按时间顺序追加，不要修改或删除历史记录（发现旧记录有误，用新记录说明更正，而不是回去改旧的）。

## 归档记录

> 本文件太长时，按 Phase 边界把已完成 Phase 的记录整体搬到 `docs/handoff-archive/`，本文件只保留归档索引 + 尚未归档（通常是当前 Phase）的记录。归档只搬运、不改写内容；接手任务前，除了看本文件末尾的最近记录，也要检查下面的归档索引里是否有相关 Phase 的历史决策。

| Phase | 归档文件 | 归档时间 | 覆盖任务 |
|---|---|---|---|
| Phase 0（基础设施与骨架，T0.1~T0.5） | [handoff-archive/phase0-2026-08-29.md](./handoff-archive/phase0-2026-08-29.md) | 2026-08-29 | T0.1 Docker Compose、T0.2 Backend API 骨架（+ uv 迁移补充）、T0.3 Agent Runner 骨架、T0.4 前端骨架（+ pnpm/shadcn 补充）、T0.5 登录鉴权 |
| Phase 1（元数据管理：Skill / MCP，T1.1~T1.5） | [handoff-archive/phase1-2026-08-30.md](./handoff-archive/phase1-2026-08-30.md) | 2026-08-30 | T1.1 数据模型与迁移、T1.2 Skill Service（+ 版本历史补充）、T1.3 Skill 管理前端页面（+ 抽屉/嵌套树/新建目录补充）、T1.4 MCP Service（加密+脱敏）、T1.5 MCP 管理前端页面 |
| Phase 2（Agent 构建器与 Workspace 初始化，T2.1~T2.4） | [handoff-archive/phase2-2026-08-30.md](./handoff-archive/phase2-2026-08-30.md) | 2026-08-30 | T2.1 Agent Service（+ PUT 编辑仓库自动重新触发初始化补丁）、T2.2 Agent Builder 前端页面（+ 交互优化补充：抽屉/能力描述字段/穿梭器）、T2.3 Workspace 初始化任务、T2.4 Agent 状态管理与展示（轮询+失败重试） |
| Phase 3（仓库定时刷新，T3.1~T3.2） | [handoff-archive/phase3-2026-08-31.md](./handoff-archive/phase3-2026-08-31.md) | 2026-08-31 | T3.1 Scheduler 服务（Celery beat，+ 跨服务队列路由修复）、T3.2 仓库刷新任务（+ 无更新时跳过快照写入补丁） |

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

Phase 0（T0.1~T0.5）、Phase 1（T1.1~T1.5）、Phase 2（T2.1~T2.4）、Phase 3（T3.1~T3.2）均已全部完成并归档，见上方归档索引。当前进入 Phase 4（对话执行核心链路）。

## [T4.1] SessionStore Adapter —— 2026-08-31

**状态**：已完成

**完成内容**：
- **`sdk_sessions` 表结构重新设计**（T1.1 落地的旧结构在本任务之前没有任何写入代码路径，直接 drop/recreate，不涉及数据迁移）：`backend-api/app/modules/sessions/models.py` 改为复合主键 `(project_key, session_id, subpath)` + `agent_id`（FK CASCADE）+ `entries`（JSONB 数组）+ `mtime_ms`（BigInteger）；新增迁移 `backend-api/alembic/versions/9d3b6a2c1e4f_sdk_sessions_composite_key.py`（`down_revision` 接在 T3.2 的 `7c2a4e1f9b3d` 之后）
- `backend-api/app/modules/sessions/__init__.py` 的注释改写，说明这个目录只保留 schema/迁移职责，真正的 adapter 实现在 agent-runner
- **新增 `agent-runner/app/sessions/store.py`**：`PostgresSessionStore` 类，duck-typed 实现 Claude Agent SDK 的 `SessionStore` Protocol——必需方法 `append`/`load`，外加可选方法 `list_sessions`/`delete`/`list_subkeys`（`list_session_summaries` 未实现，未定义在类上，见决策记录）。`agent-runner/pyproject.toml` 新增依赖 `claude-agent-sdk==0.2.144`（仅用于导入 SDK 定义的 TypedDict 做类型标注，本任务不实际调用 SDK 执行）
- 新增测试 `agent-runner/tests/test_sessions_store.py`（9 个用例，用内存假 asyncpg 连接，不需要真实数据库）

**关键决策与偏差**：
- 已回写到 [TASKS.md](../TASKS.md) T4.1 的"决策记录"小节，要点见上方"完成内容"，核心增量决策（原任务描述没覆盖、实现时才发现）：SDK 的 `SessionKey` 是 `{project_key, session_id, subpath}` 三元组而非单纯 `session_id`；adapter 代码归属判定为 agent-runner（不是 backend-api）而非任务描述里未明确的选择——理由是 SDK 在 agent-runner 进程内被调用，`sessionStore` 必须以 Python 对象形式传给同进程的 `ClaudeAgentOptions`
- `append` 的 upsert/去重语义（带 `uuid` 的条目按幂等键去重，没有 `uuid` 的不去重）严格照抄 SDK 官方文档要求（`claude_agent_sdk/types.py` 里 `SessionStore.append` 的 docstring），不是本任务自行发明的行为
- **本任务不实际调用 SDK 执行对话**（那是 T4.3 的范围），只交付 adapter 本身；`project_key` 具体传什么值（大概率是 `str(agent_id)`）留给 T4.3 在组装 SDK 参数时决定，本任务的 `PostgresSessionStore.__init__` 只固定 `agent_id`（落 FK 列用），不对 `project_key` 的取值做任何假设或校验

**遗留问题**：
- `list_session_summaries`（对话列表页可能需要的增量摘要）v1 未实现——依赖 SDK 内部 `fold_session_summary` 帮助函数，且要求"`append` 内部维护摘要的读-改-写必须串行化（事务/CAS/per-session 锁）"，复杂度和当前验收标准不匹配，留给 T5.1（对话页面前端）如果真的需要摘要列表时再补
- 与历次任务一致：`sdk_sessions` 表没有任何清理机制（比如废弃很久的 session），MinIO 快照的历史版本清理问题在本任务里也依然没有涉及（本任务不产生 MinIO 对象）
- 验证时发现本地开发环境此前从未跑起来过完整的 docker compose 基础设施（`.env` 不存在、Docker Desktop 未启动、MinIO bucket 未初始化）——本次验证过程中补齐了这些（复制 `.env.example` 为 `.env`，在 `backend-api/`、`agent-runner/`、`scheduler/` 三个目录各建了指向根 `.env` 的符号链接，跑了一次 `docker compose up -d postgres redis minio` + `minio-init`），不是本任务的功能变更，但如果之前的任务都是纯 mock 验收、从没连过真实基础设施，这次补齐的本地环境可以直接复用给后续任务

**给下一个任务的建议**：
- **T4.2（Agent 互斥锁）** 和 **T4.3（Runner 流式执行接口）** 都会用到本任务的 `PostgresSessionStore`：T4.3 组装 `ClaudeAgentOptions` 时 `session_store=PostgresSessionStore(agent_id=...)`，`project_key` 建议直接用 `str(agent_id)`（简单够用，除非后续有更细的多租户划分需求）
- `PostgresSessionStore` 的每个方法都是独立 `asyncpg.connect()`/`close()`（不是连接池），跟 `agent-runner/app/workspace/db.py` 现有模式一致；T4.3 如果单次对话执行里会高频调用 `append`（SDK 文档：~100ms 一批），可以考虑评估是否需要换成连接池，本任务按现有代码库约定先保持一致，没有做这个优化
- 验证方式：`uv run pytest`（`agent-runner/` 目录下 31 个用例全过，新增 9 个）；`uv run pytest`（`backend-api/` 目录下，`uv run alembic upgrade head` 应用新迁移后 21 个用例全过）；额外用真实 Postgres 跑了端到端脚本验证（插入真实 `agents` 行 → append 两批含重复 uuid → load 验证去重合并 → subpath 隔离主/子 transcript → list_sessions/list_subkeys 正确 → **换一个全新的 adapter 实例 load 同一个 key，确认能读到同样内容**，对应验收标准"换一个 Runner 副本 resume" → 删除 agents 行确认 FK CASCADE 清理了对应 sdk_sessions 记录），验证完清理了脚本内创建的临时 Agent（脚本自身在最后一步已经删除，无需额外清理）

## [T4.2] Agent 互斥锁（Redis）—— 2026-08-31

**状态**：已完成

**完成内容**：
- 新增 `agent-runner/app/locks/agent_lock.py`：`AgentLock` 类（异步上下文管理器）+ `AgentBusyError` 异常。key 格式 `agent_lock:{agent_id}`，独立 Redis db 2（`agent_lock_db`，`config.py` 里 T0.3/T3.1 时期就已预留的注释这次真正落地）
- `agent-runner/app/config.py` 新增 `agent_lock_db`（默认 2）、`agent_lock_ttl_seconds`（默认 60）、`agent_lock_renew_interval_seconds`（默认 20）三个配置项，以及 `agent_lock_redis_url` property
- 新增测试 `agent-runner/tests/test_agent_lock.py`（5 个用例，用本地真实 Redis，不 mock）

**关键决策与偏差**：
- 已回写到 [TASKS.md](../TASKS.md) T4.2 的"决策记录"小节，要点：① 锁代码放在 agent-runner（不是 backend-api），理由与 T4.1 的 `PostgresSessionStore` 一致——要覆盖的执行发生在 Runner 进程内；② 获取锁失败不排队、立刻抛 `AgentBusyError`，对应验收标准"明确得知 Agent 正忙而不是排队卡住"；③ 短 TTL（60s）+ 持锁期间后台 `asyncio.Task` 每 20s 续期一次，而不是获取时设一个覆盖最长可能执行时间的长 TTL——执行时长不可预知，长 TTL 会让进程真崩溃时锁悬挂太久；④ 释放/续期都用 Lua 脚本做"校验 token 匹配后再操作"的原子 check-and-act，避免误删/误续别人已经抢到的新锁
- 本任务只交付 `AgentLock`/`AgentBusyError` 两个可复用构件本身，**没有接入任何 HTTP 路由**——因为 T4.3（Runner 流式执行接口）还不存在，没有真实的调用方。`agent-runner/app/server/main.py` 未改动

**遗留问题**：
- 锁本身没有暴露"当前是否被占用/被谁占用"的查询接口（比如给前端展示"Agent 正在对话中"状态用）——当前验收标准只要求"发起执行时能明确得知正忙"，没有要求旁路查询；如果 T5.1 对话页面需要这种状态展示，需要另外加一个只读的 `GET` 查询方法（直接 `redis.get(key)` 判断是否存在即可，不需要新决策）
- 续期失败（`_renew_loop` 里 `renewed` 为假，意味着锁在续期前就已经被判定过期/被人抢占）目前只记一条 `warning` 日志然后让续期协程退出，不会主动中断持锁方正在执行的业务逻辑（比如强行取消 T4.3 的 SDK 调用）——这种"锁丢了但业务还在跑"的极端情况（正常续期间隔 20s 远小于 TTL 60s，理论上只有 Redis 本身不可用/网络分区超过 40s 才会触发）本任务没有处理，T4.3/T4.4 落地时如果要做得更严格（比如续期失败后主动 cancel 执行任务），需要在那两个任务里补

**给下一个任务的建议**：
- **T4.3（Runner 流式执行接口）** 落地时，用 `async with AgentLock(agent_id) as lock:` 包住"拉取 workspace → 组装 SDK 参数 → 调用 SDK 执行 → 同步输出快照回 MinIO"这一整段（覆盖 T4.4 异常退出兜底保存也要在这个 `async with` 块内，退出时无论正常/异常锁都会被释放），在路由层 `except AgentBusyError as e:` 转成 HTTP 409（或类似"资源被占用"语义的状态码）响应
- `AgentLock` 构造时可传 `redis_client=` 复用已有连接（测试里这么用，避免每个用例各自新建/关闭连接、可能导致的连接数堆积）；T4.3 如果单次进程内会频繁创建/销毁 `AgentLock` 实例，可以考虑在 Runner 启动时建一个全局共享的 Redis client 传进去，本任务默认行为（不传时自己 `aioredis.from_url` 新建、退出时自己 `aclose()`）够用，不强制
- 验证方式：`uv run pytest tests/test_agent_lock.py -v`（`agent-runner/` 目录下，需要本地 `docker compose up -d redis` 已在跑，5 个用例全过）；`uv run pytest`（`agent-runner/` 目录下全量 36 个用例全过，含 T4.1 的 31 个 + 本次新增 5 个）
