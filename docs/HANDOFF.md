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

---

## [T3.2] 仓库刷新任务 —— 2026-08-30

**状态**：已完成

**完成内容**：
- `agent-runner/app/worker/tasks/refresh.py`（新增）：`@celery_app.task(name="workspace.refresh_repos")`，消费 T3.1 已经在跑的 `"workspace.refresh_repos"` 任务。逻辑上是 `workspace.init`（T2.3）的裁剪版——`load_agent_context` 拿到 Agent 名下全部仓库 → 逐个 `git_ops.clone_repository` → `archive.zip_directory` 打包 → `storage.put_workspace_object` 上传新版本仓库快照 → 只更新 `workspace_snapshots` 的 `repo_snapshot_*` 三列，**全程不调用 `mark_agent_status`**（不像 init 那样把 Agent 打成 initializing/ready/failed），也不touch `output_snapshot_*`
- `agent-runner/app/workspace/db.py` 新增两个函数：`update_repo_snapshot(agent_id, repo_snapshot_object_key, repo_snapshot_version)`（只 UPDATE 仓库快照三列，不是 UPSERT——刷新时该行必然已存在）、`update_repository_sync_error(repo_id, error_message)`（只写 `last_sync_error`，不动 `last_synced_at`/`last_synced_commit`）；`update_repository_sync_info`（init/refresh 共用）顺带在成功时清空 `last_sync_error`
- **backend-api 新增字段** `agent_repositories.last_sync_error`（Text，nullable）承载"记录失败信息"：`app/modules/agents/models.py` 加列、`schemas.py` 的 `AgentRepositoryDetail` 加字段、`router.py` 构造处补上、新增 Alembic 迁移 `backend-api/alembic/versions/7c2a4e1f9b3d_agent_repository_last_sync_error.py`（`down_revision` 接在 T2.1 补丁的 `dbf10ea831f1` 之后）
- `agent-runner/app/worker/celery_app.py` 的 `include` 列表加上 `"app.worker.tasks.refresh"`
- 新增测试 `agent-runner/tests/test_workspace_refresh_task.py`（后续被"补丁"小节重写为 6 个用例，见下方）

**关键决策与偏差**：
- 已回写到 [TASKS.md](../TASKS.md) T3.2 的"决策记录"小节，要点见上方，核心是：**直接复用 T2.3 的 `git_ops.py`/`archive.py`/`storage.py`/`crypto.py`/`AgentInitContext`/`load_agent_context`，不做额外抽象**——T2.3 交接记录建议过"可以把 clone+打包抽出来共用"，但实际写下来发现刷新任务本身已经足够薄（`_clone_and_pack` 只是去掉了 output 快照那部分），复用现有函数即可，不需要再抽一层
- **`last_sync_error` 是本任务新增的字段**，TASKS.md 原文"记录失败信息"没写清楚落在哪——Agent 表的 `status_message` 语义上绑定 Agent 整体状态，而刷新决策要求不碰 Agent 状态，所以选了仓库级新字段，粒度对得上"是哪个仓库刷新失败"。这是超出任务描述原文、但没有冲突现有决策的补充，已回写 TASKS.md
- **多仓库场景是全有全无（all-or-nothing）**：任意一个仓库 clone 失败，整轮刷新放弃、不落新版本快照，只把失败原因记到那一个出错的仓库上，跟它一起"陪跑"的其它仓库自身 `last_sync_error`/`last_synced_at` 不受影响（它们没有出错，只是所在的这轮刷新被回滚）。这个是延续 T2.3 `workspace.init` 的"整体失败不做部分成功"策略做的选择，TASKS.md 原文没有明确要求 all-or-nothing 还是逐仓库独立提交，做了个和 T2.3 一致的决定

**遗留问题**：
- TASKS.md T3.2 第三条验收标准"一次对话执行期间触发刷新，不会相互阻塞或报错"**仍未完整验证**：T4.2（Agent 互斥锁）还没实现，本任务只能确认刷新任务本身不 touch 任何对话执行相关的状态/锁，理论上不会冲突，但没有真正跑一次"对话执行中触发刷新"的并发场景。留给 T4.2 落地后补验证
- `agent_repositories.last_sync_error` 目前只有后端字段和 API 暴露，**前端没有展示**（Agent 详情页目前只展示 Agent 级 `status_message`）。留给 T5.x 或有需要时再加，不阻塞当前任务
- 与历次任务一致的已知遗留：MinIO 历史快照对象（`repo-v1.zip`/`repo-v2.zip`/…）没有清理机制，刷新越多、历史版本堆积越多，仍未解决

**给下一个任务的建议**：
- Agent 互斥锁（T4.2）落地时，可以直接对照本任务"刷新读写不冲突"的设计假设做验证：刷新只新增 MinIO 对象、只在最后一步整体切换 `workspace_snapshots` 指针，旧版本对象在切换前始终可读，理论上不需要跟对话执行的互斥锁产生任何交互
- 验证方式：`uv run pytest`（`agent-runner/` 目录下，17 个用例全过，新增 4 个）；`uv run pytest`（`backend-api/` 目录下，`uv run alembic upgrade head` 应用新迁移后 21 个用例全过）；`docker compose build backend-api agent-runner` + `up -d` 重建镜像后用真实容器链路验证：① 创建一个绑定真实仓库 `https://github.com/PGshen/chat-web.git`、`repo_refresh_interval_minutes=1` 的 Agent，等 T2.3 `workspace.init` 跑完到 `ready`（`repo-v1.zip`）；② 等 scheduler 到期派发 `workspace.refresh_repos`（60 秒扫描周期内自动触发，未手动构造消息），确认 `workspace_refresh_succeeded` 日志、MinIO 新增 `repo-v2.zip`、`workspace_snapshots.repo_snapshot_version` 变成 2 且 `output_snapshot_version`/`output_snapshot_object_key` 原样不动、`agent_repositories.last_synced_at` 更新、`last_sync_error` 为空；③ 把仓库 URL 改成不存在的地址、手动清掉 Redis 派发锁触发立即重试，确认 `workspace_refresh_failed` 日志、`workspace_snapshots` 仍停在 v2（未产生 v3、未覆盖已有对象）、`agent_repositories.last_synced_at`/`last_synced_commit` 保持刷新前的值不变、`last_sync_error` 写入了脱敏后的 git 报错信息、Agent `status` 全程是 `ready`（未被打成 failed）；验证完删除了测试 Agent 并清理了对应的 3 个 MinIO 对象（`repo-v1.zip`/`repo-v2.zip`/`output-v1.zip`）

### 补丁：仓库无更新时跳过快照写入 —— 2026-08-30

**背景（用户在验收时发现的问题）**：上面这版实现里 `_clone_and_pack` 无条件执行——只要到达刷新周期就重新 clone、打包、上传一份新版本 zip、`repo_snapshot_version` 无脑 +1，哪怕仓库自上次同步后完全没有新提交。长期不更新的仓库会在每个刷新周期都产生一份内容和上一版完全相同的快照，MinIO 存储和 `workspace_snapshots` 版本号会无意义膨胀，跟 TASKS.md 决策"独立版本化"的本意（版本号应该反映真实变更）不符。

**修复**：刷新前先做一次轻量的"有没有更新"检查，只有真的有变化才重新 clone+打包+上传。
- `agent-runner/app/workspace/git_ops.py` 新增 `remote_head_commit(repo) -> str`，用 `git ls-remote <url> <branch-or-HEAD>` 只查询远程当前指向的 commit，不下载任何内容；把 `clone_repository` 里原本内联的凭证准备逻辑（token 拼 URL / ssh_key 落临时文件 + `GIT_SSH_COMMAND`）抽成 `_prepared_auth` 上下文管理器，`clone_repository` 和 `remote_head_commit` 共用，避免重复
- `agent-runner/app/workspace/db.py` 的 `RepositoryRecord` 新增 `last_synced_commit: str | None = None` 字段，`load_agent_context` 的 SQL 一并 SELECT 出来（之前这个查询只取 clone 需要的字段，没取这一列）
- `agent-runner/app/worker/tasks/refresh.py` 的 `_run` 改成两阶段：先 `_resolve_remote_commits` 对每个仓库跑 `remote_head_commit` 拿到远程当前 commit；**如果全部仓库的远程 commit 都等于各自的 `last_synced_commit`，直接返回 `"unchanged"`**——跳过 `_clone_and_pack`，但仍然对每个仓库调用 `update_repository_sync_info(repo_id, 远程commit)` 把 `last_synced_at` 刷新到当前时间（commit 值不变，只是时间戳前进）；只要有一个仓库的远程 commit 变了，才走原来的整体重新 clone+打包+上传流程（快照是全部仓库的组合 zip，没有做单仓库增量更新的粒度）。远程查询本身失败（仓库不可达）跟原来 clone 失败一样处理：整体放弃，把失败原因记到 `last_sync_error`
- **`last_synced_at` 在"无变化"分支也必须推进**是这次修复里容易漏掉的一点：如果跳过打包时完全不写库，这个 Agent 的 `last_synced_at` 停留在上一次真正变更的时间，下一次 scheduler 扫描（默认 60 秒一次）会立刻又判定它"到期"、重新派发，变成事实上每 60 秒都要查一次远程，架空了用户在 Agent 上配置的 `repo_refresh_interval_minutes`
- 测试：`agent-runner/tests/test_workspace_refresh_task.py` 重写为 6 个用例（新增"远程无变化时跳过 clone+打包但推进 last_synced_at"、"远程查询本身失败时不进入 clone 阶段"两个）；`agent-runner/tests/test_workspace_git_ops.py` 新增 3 个 `remote_head_commit` 的真实本地仓库用例（正确返回 HEAD、能感知新提交、仓库不可达时报 `WorkspaceInitError`）

**验证方式**：`uv run pytest`（`agent-runner/` 目录下 22 个用例全过）；`docker compose build/up agent-runner` 重建镜像后用真实容器链路验证：创建一个绑定 `https://github.com/PGshen/chat-web.git`、`repo_refresh_interval_minutes=1` 的新 Agent，等 `workspace.init` 完成（`repo-v1.zip`）→ 等 scheduler 到期自动派发刷新（未手动触发）→ 确认日志是 `workspace_refresh_unchanged`（不是 `workspace_refresh_succeeded`）→ 确认 `workspace_snapshots.repo_snapshot_version` 仍是 1、MinIO 里没有出现 `repo-v2.zip`、`agent_repositories.last_synced_at` 确实推进到了刷新发生的时间点、`last_synced_commit` 不变；验证完删除了测试 Agent 并清理了对应的 2 个 MinIO 对象（`repo-v1.zip`/`output-v1.zip`）
