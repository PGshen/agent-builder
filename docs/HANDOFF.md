# AgentBuilder 任务交接记录

> 每完成（或阶段性中断）一个任务，在本文件末尾追加一条记录，方便下一个任务/下一次会话接手时不用重新翻代码或猜实现细节。按时间顺序追加，不要修改或删除历史记录（发现旧记录有误，用新记录说明更正，而不是回去改旧的）。

## 归档记录

> 本文件太长时，按 Phase 边界把已完成 Phase 的记录整体搬到 `docs/handoff-archive/`，本文件只保留归档索引 + 尚未归档（通常是当前 Phase）的记录。归档只搬运、不改写内容；接手任务前，除了看本文件末尾的最近记录，也要检查下面的归档索引里是否有相关 Phase 的历史决策。

| Phase | 归档文件 | 归档时间 | 覆盖任务 |
|---|---|---|---|
| Phase 0（基础设施与骨架，T0.1~T0.5） | [handoff-archive/phase0-2026-08-29.md](./handoff-archive/phase0-2026-08-29.md) | 2026-08-29 | T0.1 Docker Compose、T0.2 Backend API 骨架（+ uv 迁移补充）、T0.3 Agent Runner 骨架、T0.4 前端骨架（+ pnpm/shadcn 补充）、T0.5 登录鉴权 |
| Phase 1（元数据管理：Skill / MCP，T1.1~T1.5） | [handoff-archive/phase1-2026-08-30.md](./handoff-archive/phase1-2026-08-30.md) | 2026-08-30 | T1.1 数据模型与迁移、T1.2 Skill Service（+ 版本历史补充）、T1.3 Skill 管理前端页面（+ 抽屉/嵌套树/新建目录补充）、T1.4 MCP Service（加密+脱敏）、T1.5 MCP 管理前端页面 |
| Phase 2（Agent 构建器与 Workspace 初始化，T2.1~T2.4） | [handoff-archive/phase2-2026-08-30.md](./handoff-archive/phase2-2026-08-30.md) | 2026-08-30 | T2.1 Agent Service（+ PUT 编辑仓库自动重新触发初始化补丁）、T2.2 Agent Builder 前端页面（+ 交互优化补充：抽屉/能力描述字段/穿梭器）、T2.3 Workspace 初始化任务、T2.4 Agent 状态管理与展示（轮询+失败重试） |

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

Phase 0（T0.1~T0.5）、Phase 1（T1.1~T1.5）、Phase 2（T2.1~T2.4）均已全部完成并归档，见上方归档索引。当前进入 Phase 3（仓库定时刷新）。

## [T3.1] Scheduler 服务（Celery beat） —— 2026-08-30

**状态**：已完成

**完成内容**：
- 新增独立服务 `scheduler/`（`uv` 管理，目录结构比照 backend-api/agent-runner 但没有 FastAPI/HTTP 业务 API）：
  - `app/config.py` —— Postgres/Redis 连接配置 + `scheduler_scan_interval_seconds`（默认 60）/`scheduler_dispatch_lock_ttl_seconds`（默认 600）/`scheduler_lock_db`（独立 redis db 4，不与 agent-runner 的 Celery broker/result db 0/1、`AUTH_REDIS_DB`=3、T4.2 预留的 db 2 混用）
  - `app/db.py` —— `fetch_ready_agents_repo_sync_status()`，`asyncpg` 原生 SQL 查所有 `status='ready'` 且绑定了仓库的 Agent，及其名下仓库 `last_synced_at` 的 `MIN`
  - `app/due.py` —— 纯函数 `is_due(status, now)`，不依赖数据库连接，方便单测
  - `app/dispatch_lock.py` —— `try_acquire_dispatch_lock(agent_id)`，Redis `SET NX EX` 实现的派发去重锁
  - `app/celery_app.py` —— 内嵌 `beat_schedule`（一条固定周期任务 `scheduler.scan_due_agents`，路由到专属队列 `"scheduler"`）
  - `app/tasks.py` —— `scan_due_agents` 任务本体：查状态 → 逐个判断到期 → 抢锁成功才 `send_task("workspace.refresh_repos", args=[agent_id], queue="agent-runner")`
  - `entrypoint.sh` —— `celery -A app.celery_app worker --beat --loglevel=info -Q scheduler`（单进程内嵌 beat，不需要独立 beat 容器）
  - `tests/`（11 个用例）—— `test_due.py`（到期判断：NULL 兜底、边界值、MIN 口径）、`test_dispatch_lock.py`（内存假 Redis 验证 NX+TTL 语义）、`test_tasks.py`（到期/未到期/被锁定三种场景的派发行为，`task_always_eager` 模式）
- `docker-compose.yml` 新增 `scheduler` service（依赖 postgres/redis healthy，健康检查用 `celery inspect ping` 而非 HTTP `/health`）；`.env`/`.env.example` 补充三个新配置项；`Makefile` 的 `APP_SERVICES`/`install`/`local-up`/`local-down` 加入 scheduler，新增 `local-scheduler` 前台调试目标
- **落地过程中发现并修复一个跨服务的 Celery 路由 bug**（详见下方"关键决策与偏差"）：`agent-runner/entrypoint.sh` 和 `backend-api/app/modules/agents/tasks.py::trigger_workspace_init` 各改了一行

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T3.1 的"决策记录"小节，要点：用"固定间隔扫描 + 到期判断"取代"每个 Agent 一条 beat schedule 条目"（避免引入 `django-celery-beat` 之类的额外基础设施，且能让用户改了某个 Agent 的刷新周期后无需重启即可在下一轮扫描生效）；到期判断用 Agent 名下所有仓库 `last_synced_at` 的 **MIN**（不是 MAX），保证不会有某个仓库长期滞后被掩盖；刷新期间**不**把 Agent 状态改成 `initializing`（对应 PRD"刷新独立于对话执行、不影响可用性"的既定策略，这点和 `workspace.init` 的行为刻意不同）；用 Redis `SET NX EX` 做派发去重锁，锁不要求 T3.2 的刷新任务主动清除，TTL 到期自动兜底
- **实现时才暴露的问题，超出预先写好的决策范围**：scheduler 上线前，`backend-api`（生产者）→ `agent-runner`（消费者）一直是"一对一"的任务流转，共用 Celery 默认队列 `"celery"` 从没出过问题；但 scheduler 的 worker 一上线，就和 agent-runner 的 worker 变成两个同时监听同一个默认队列的消费者——本地 `docker compose up` 联调时立刻复现：`agent-runner` 日志报 `Received unregistered task of type 'workspace.refresh_repos'`（消息被 agent-runner 收到但没注册这个任务名，直接丢弃，不重新入队）。说明如果不显式分队列，`workspace.init` 这类任务本来就有被 scheduler 的 worker 意外抢走并丢弃的风险，只是此前只有 agent-runner 一个消费者，从没暴露过。**修复**：`agent-runner` 只监听队列 `"agent-runner"`，`scheduler` 只监听队列 `"scheduler"`（各自 `entrypoint.sh`/`Makefile` 加 `-Q` 参数），三处 `send_task`/`beat_schedule` 都补上显式 `queue="agent-runner"`（`scheduler/app/tasks.py`、**回头修正 T2.1 的** `backend-api/app/modules/agents/tasks.py::trigger_workspace_init`）或 `queue="scheduler"`（`scheduler/app/celery_app.py` 的 `beat_schedule` options）。这个修复不改变 T2.1/T2.3 已验收的行为，纯粹是让隐式共享队列变成显式路由，消除竞态——**下一个引入新 Celery worker 的任务（如果有）要记得同样显式指定 `-Q`/`queue=`，不要依赖默认队列**

**遗留问题**：
- **`workspace.refresh_repos` 目前没有任何消费者**（T3.2 还没实现）：`agent-runner` 会收到这个任务但因为没注册而直接丢弃（不是排队等待，是真正丢失）。这跟 T2.1→T2.3 之间"`workspace.init` 排队等待"的空档期不同——因为现在 agent-runner 的 worker 已经在监听 `"agent-runner"` 队列，会主动消费到这条消息再发现自己不认识。T3.2 上线前，scheduler 派发的每一次刷新实际上都是无效的（不会有任何副作用，只是浪费一次 broker 往返），不影响任何数据正确性，但也意味着"仓库到期没有真的被刷新"，需要 T3.2 尽快跟进
- 数据库里遗留的测试 Agent（`76bcc309-9334-4c91-a69f-bd46cb14b267`，T2.1 补丁记录里提到的"问题排查"）状态是 `ready` 且早已过期未同步，验证期间被 scheduler 真实扫描到并按 10 分钟一次的节奏持续派发（受派发锁 TTL 限制），这是预期行为、不是 bug，但如果不想让它继续产生日志噪音，可以手动清理这个 Agent 或等 T3.2 落地后它会被正常刷新
- 与 T2.1/T2.3 一致的已知遗留仍未解决：Agent/仓库快照相关的 MinIO 对象生命周期管理（删除清理、历史版本清理）本任务没有涉及，因为 T3.1 本身不产生任何 MinIO 对象

**给下一个任务的建议**：
- **T3.2（仓库刷新任务）**：Runner 侧要注册 `@celery_app.task(name="workspace.refresh_repos")`，参数 `agent_id`（str）——契约已经在跑，上线即生效（不需要 backend-api/scheduler 那边改任何代码）。**队列层面不需要改动**：agent-runner 的 worker 已经在监听 `"agent-runner"` 队列（T3.1 落地时加的 `-Q agent-runner`），新任务在同一个进程里注册即可被消费，不用单独配置
- T2.3 交接记录建议过"可以把 `_clone_and_pack` 里 clone+打包这部分抽出来给 init/refresh 两边共用"，本任务没有动 `agent-runner/app/workspace/` 下的任何代码（T3.1 是纯 scheduler 侧的工作），这个抽象留给 T3.2 视实际情况决定是否要做
- T3.2 要留意 TASKS.md T3.2 原有的验收标准之一"一次对话执行期间触发刷新，不会相互阻塞或报错"——本任务的 scheduler 派发逻辑本身已经不依赖、不等待 Agent 互斥锁（T4.2 还没实现），刷新是否真的和对话执行无冲突，要等 T3.2 的具体 clone/打包实现 + T4.2 落地后才能完整验证
- 验证方式：`uv run pytest`（`scheduler/` 目录下，新增 11 个用例全过）；`uv run pytest`（`backend-api/` 目录下，`queue="agent-runner"` 改动后 21 个用例回归全过）；`docker compose build/up backend-api agent-runner scheduler` 后用数据库里真实存在的一个过期未同步的 ready Agent 观察了完整链路：`scheduler` 按 60 秒周期扫描 → 到期后派发（`scheduler_dispatch_refresh` 日志）→ 确认消息 `routing_key` 是 `"agent-runner"` 而非共享的 `"celery"` → 下一轮扫描被派发锁跳过（`scheduler_dispatch_skipped_locked`）→ 手动 `redis-cli -n 4 DEL` 清锁后确认能立即重新派发。全程未新建/删除任何测试数据（用的是数据库里已有的旧 Agent），未清理 broker 队列消息（T3.2 上线前这些消息本来就会被 agent-runner 当 unregistered task 丢弃，不会累积、不会被将来的 T3.2 worker 消费到脏数据）
