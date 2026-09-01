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

## [T4.3] Agent Runner 流式执行接口 —— 2026-08-31

**状态**：已完成（当天补充：用户提供本机 `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` 后，已完成真实 SDK 端到端验证，原"遗留问题"里的这一条已解决，见文末补充记录）

**完成内容**：
- 新增 `POST /agents/{agent_id}/execute`（`agent-runner/app/server/execute.py`，已在 `app/server/main.py` 注册路由），body `{prompt, resume_session_id}`，响应 `text/event-stream`，把 SDK 消息实时转成 SSE 事件流推送
- 新增 `agent-runner/app/execution/` 模块：`context.py`（读 Agent 执行期上下文：workspace 快照版本、绑定的 skills/MCP、权限模式，Agent 未就绪时抛 `AgentNotReadyError`）、`workspace_cache.py`（本地热缓存准备，命中/未命中判断精确到仓库/输出/每个 Skill）、`sdk_options.py`（组装 `ClaudeAgentOptions`）、`mcp_crypto.py`（MCP 配置解密）、`output_sync.py`（执行完成后把输出目录打包同步回 MinIO + 回写 `workspace_snapshots`）
- `agent-runner/app/workspace/storage.py` 新增 `get_workspace_object`/`get_skill_object`（下载 MinIO 对象）；`archive.py` 新增 `extract_zip`（解压到目录，先清空避免残留陈旧文件）、`zip_directory_flat`（以打包目录本身为基准的扁平打包，供输出快照使用，区别于仓库快照用的 `zip_directory`）
- `agent-runner/app/locks/agent_lock.py`（T4.2 产物）拆出 `begin_renewal()`/`end_renewal()`/`close()` 三个公开方法，供本任务在路由层手动接管锁的生命周期（不能简单套 `async with`，因为拿不到锁时要能在开始 SSE 流之前就返回 HTTP 409），`async with` 用法保持不变
- `agent-runner/app/config.py` 新增 `mcp_encryption_key` 配置项（`.env.example` 同步更新注释，说明 agent-runner 也会读取 `MCP_ENCRYPTION_KEY`）
- 新增测试：`tests/test_execute_endpoint.py`（4 个，真实本地 Redis）、`tests/test_workspace_cache.py`（4 个）、`tests/test_workspace_archive.py`（新增 4 个）、`tests/test_execution_context.py`（5 个，真实本地 Postgres）

**关键决策与偏差**：
- 已回写到 [TASKS.md](../TASKS.md) T4.3 的"决策记录"小节，核心要点（详见该文档，这里只列标题）：① SSE 事件契约与"拿锁失败/Agent 未就绪直接走普通 HTTP 4xx、不进 SSE 流"；② `cwd`=输出目录、`add_dirs`=仓库目录（两者不合并，对应 TECH_DESIGN 4.4 第 5 步 additionalDirectories），Skill 各自独立目录传给 `skills` 参数；③ `SessionStore` `project_key` 不显式传递、靠 SDK 从 `cwd` 路径自动派生，**推翻了 T4.1 handoff 里"project_key 建议用 str(agent_id)"的建议**（SDK 实际不支持显式指定，该建议不成立）；④ 本地热缓存命中判断粒度拆到仓库/输出/每个 Skill 独立；⑤ 锁的生命周期跨越整个 SSE 流（`finally` 块统一处理同步+释放，覆盖正常/异常/客户端断开三种退出路径）；⑥ 输出快照用新增的 `zip_directory_flat`（扁平打包）而不是仓库快照用的 `zip_directory`（父目录基准打包），两者解压后的目录层级语义不同，不能混用
- **本任务不处理 SIGTERM 等进程级优雅关闭**——T4.4 的范围；本任务的 `finally` 块只覆盖"单次 HTTP 请求内的正常完成/SDK 异常/客户端主动断开连接"这三种路径，不覆盖"Runner 进程本身被信号终止导致所有正在进行的请求一起中断"这种场景（这种场景下 `finally` 会不会执行、Redis 连接来不来得及释放锁，取决于进程终止的方式，T4.4 需要专门处理）

**遗留问题**：
- ~~未验证真实 SDK 执行~~ **已在当天补充验证解决**，见文末"[T4.3 补充] 真实 SDK 端到端验证"记录
- **`skills=[...] or None`**（`sdk_options.py`）：没有绑定任何 Skill 时传 `None` 而不是空列表——这是照着 SDK 类型标注 `list[str] | Literal["all"] | None` 里"有列表用列表，没有传 None"的直觉写的，但 SDK 对"空列表"和"None"两种取值在实际行为上是否有差异（比如空列表是不是等价于"不加载任何 skill 包括默认的"）没有去读 SDK 源码/文档细究，如果后续发现行为不对，这里是第一个该检查的地方
- 与 T4.1/T4.2 一致：Runner 每次数据库/MinIO 操作都是独立连接（`asyncpg.connect`/MinIO 同步客户端+`asyncio.to_thread`），没有连接池；`execute` 接口如果未来发现高并发下连接数成为瓶颈，需要专门评估

**给下一个任务的建议**：
- **T4.4（异常退出兜底保存）** 要在本任务的基础上加"进程级"的信号处理钩子：收到 SIGTERM 时，遍历当前进程内所有正在进行的 `_execute_stream` 生成器（目前没有一个全局注册表跟踪它们），强制触发一次输出快照同步——这意味着 T4.4 可能需要给 `_execute_stream` 加一个模块级的"当前正在执行的任务"注册表，本任务没有预留这个结构，需要补
- **T4.5（Conversation Service）** 是本任务的真正调用方（backend-api 侧）：需要处理"Backend API 收到前端 SSE 连接 → 直连调用 Runner 这个 `execute` 接口 → 把 Runner 的 SSE 流原样转发/包装后再转发给前端"，以及"从 `ResultMessage` 事件里提取 `session_id` 持久化到 `conversation_id → session_id` 映射"这两件事；Runner 副本的选择（负载均衡）依赖 compose 服务名 DNS 轮询（TECH_DESIGN 6），T4.5 落地时用普通 HTTP 客户端对 `agent-runner:{AGENT_RUNNER_HTTP_PORT}` 发请求即可，不需要额外的服务发现逻辑
- 验证方式：`uv run pytest`（`agent-runner/` 目录下全量 52 个用例全过，含此前 36 个 + 本次新增 16 个）；`uv run python -c "from app.server.main import app"` 确认路由能正常加载（无循环 import/依赖缺失）；本地 `docker compose up -d postgres redis minio` 均已在跑的前提下跑通了 `test_execution_context.py`（真实 Postgres）和 `test_execute_endpoint.py`/`test_agent_lock.py`（真实 Redis），`test_workspace_cache.py`/`test_workspace_archive.py` 纯本地文件系统 + monkeypatch 不依赖外部服务

## [T4.3 补充] 真实 SDK 端到端验证 —— 2026-08-31

**状态**：已完成

**背景**：用户在本机 `~/.zshrc` 配置好了 `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`（注意：这两个变量只在交互式 shell 里通过 `source ~/.zshrc` 生效，agent 工具的非交互 Bash 会话默认读不到，每次起新进程前都要显式 `source ~/.zshrc`），要求补做 T4.3 完成时遗留的"真实 SDK 调用"验证。

**完成内容**（跑完即清理，仓库里没有留下任何验证脚本/临时文件）：
1. 起了真实的 `uv run uvicorn app.server.main:app --host 127.0.0.1 --port 8100` 进程（后台）
2. 用一次性脚本直接往真实本地 Postgres/MinIO 插入了一个临时 Agent（`permission_mode='acceptEdits'`，`status='ready'`）+ 空的仓库快照/输出快照（`workspace_id` 前缀 `e2e-`，与正式业务用的 `ws-` 前缀区分，避免和已有测试数据混淆）
3. `curl -N POST /agents/{id}/execute` 发第一次真实请求（prompt 要求在当前目录创建 `hello.txt`），收到真实的 `SystemMessage(init)` → `AssistantMessage`（工具调用）→ ... → `ResultMessage` 完整 SSE 流，拿到真实 `session_id`
4. 带着上一步的 `session_id` 通过 `resume_session_id` 发第二次请求，模型确认记得上下文并成功在 `cwd` 内创建了 `hello.txt`（`本地缓存目录/output/hello.txt` 内容正确）
5. 下载 MinIO 里回写的 `output-v3.zip`，解压确认内容是 `hello.txt`，`workspace_snapshots.output_snapshot_version` 正确从 1 递增到 3（两次执行各 +1）
6. 并发对同一 Agent 发两个 `execute` 请求，验证第二个立刻拿到 `409 {"detail": "Agent ... 正忙，请稍后再试"}`（不排队），第一个正常执行完成
7. 执行结束后确认 Redis 里 `agent_lock:*` 无残留 key
8. 清理：`DELETE FROM agents WHERE id = ...`（级联清了 `workspace_snapshots`）、MinIO 删除该 workspace 下 5 个测试对象（`output-v1~v4.zip` + `repo-v1.zip`）、删除本地缓存目录 `.cache/agent-runner/e2e-.../`，停掉 uvicorn 进程；跑完全量 `uv run pytest` 确认 52 个用例仍然全过（本次验证不涉及代码改动，纯运行时验证）

**关键发现**（已回写到 [TASKS.md](../TASKS.md) T4.3 决策记录，非代码 bug）：
- 第一次请求模型没有把文件写到 SDK 配置的 `cwd`，而是尝试写绝对路径 `/Users/peng/Me/Ai/agent-builder/hello.txt`（我们自己这个项目仓库的根目录），被 SDK 自带的 `workingDir` 权限检查正确拦截（`permission_denied`）——**这恰恰证明了 T4.3 组装的 `cwd`/`add_dirs` 沙箱边界生效**，不是安全问题。根因是本地开发时 `RUNNER_LOCAL_CACHE_DIR` 落在 `agent-runner/` 这个真实 git 仓库内部，`claude` CLI 子进程会向上找 `.git`/`CLAUDE.md` 识别"项目根"，找到的是 `agent-builder` 仓库根而不是我们指定的深层 output 目录，导致模型对"当前项目"的路径认知出现偏差。生产部署（cache 目录挂在独立 volume，不在任何 git 仓库内）不会有这个问题；把 prompt 改成明确要求相对路径后，模型第二次就正确执行了

**给下一个任务的建议**：
- 以后如果要在本地（而不是容器里）复现"最贴近生产"的验证效果，建议把 `RUNNER_LOCAL_CACHE_DIR` 临时指到仓库外的目录（如 `/tmp/agent-runner-cache`），避免 `claude` CLI 的项目根探测跟我们自己的开发仓库产生干扰
- **T4.4/T4.5** 落地后建议也各自补一次同样方式的真实端到端验证（复用本次这套"插入临时 Agent → 起服务 → curl 验证 → 清理"的流程），尤其 T4.4 的 SIGTERM 兜底保存，mock 测试很难覆盖"进程真的被信号杀死那一刻数据是否写完整"这种时序敏感的场景
- 环境提醒：这台机器上 `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` 只在 `~/.zshrc` 里，agent 工具默认的非交互 Bash 不会自动加载，每次需要真实调用 SDK 的验证前都要 `source ~/.zshrc`（或在起服务的那条命令里一并 source）

## [T4.4] 异常退出兜底保存 —— 2026-09-01

**状态**：已完成

**完成内容**：
- 新增 `agent-runner/app/execution/registry.py`：`ActiveExecution`（持有 `context`/`lock`/`cwd`，`finalize()` 做"打包上传输出快照 + 释放 Agent 互斥锁"，内部 `asyncio.Lock` + `_finalized` 标记保证幂等）+ 模块级注册表（`register`/`unregister`/`snapshot`）
- `agent-runner/app/server/execute.py` 的 `_execute_stream` 改为开始时 `registry.register`，`finally` 块只调 `entry.finalize()` + `registry.unregister`，原来内联的打包上传/释放锁逻辑整体搬进了 `ActiveExecution.finalize()`
- `agent-runner/app/server/main.py` 的 `lifespan` 里新增 `loop.add_signal_handler(signal.SIGTERM, ...)` 挂载 `_emergency_shutdown()`：遍历 `registry.snapshot()`，对每条记录并发 `finalize(update_source="emergency_fallback")`，最后 `os._exit(0)`
- 新增测试：`tests/test_execution_registry.py`（4 个，覆盖 finalize 的同步+释放锁、幂等、注册/注销、cwd 为 None 时仍释放锁）、`tests/test_shutdown.py`（1 个，验证 `_emergency_shutdown` 对所有活跃记录调用 finalize 并退出进程）

**关键决策与偏差**：
- 已回写到 [TASKS.md](../TASKS.md) T4.4 的"决策记录"小节，核心要点：① 幂等靠 `ActiveExecution` 自带 `asyncio.Lock`+标记位做互斥，不复用 Redis 锁；② `_emergency_shutdown` 最后用 `os._exit(0)` 直接终止进程而不是走 uvicorn 优雅关闭——因为 `add_signal_handler` 对同一信号只能注册一个回调，注册自己的处理器会覆盖 uvicorn 内置的 SIGTERM 处理，不主动退出进程会挂住不退出；③ 明确不处理 SIGKILL/断电（TECH_DESIGN 4.5 已有局限性说明），依赖 T4.2 的 Redis 锁短 TTL 自动过期兜底
- 与 T4.3 交接记录预告的方案一致（"给 `_execute_stream` 加一个模块级的当前正在执行的任务注册表"），没有偏离

**遗留问题**：
- 无新增遗留问题；沿用 T4.3 遗留的"Runner 每次数据库/MinIO 操作都是独立连接，没有连接池"这一条

**给下一个任务的建议**：
- **T4.5（Conversation Service）** 不需要关心本任务的信号处理细节——backend-api 侧只是普通 HTTP 客户端调用 Runner 的 `execute` 接口，Runner 进程被 SIGTERM 时会自己完成兜底同步再退出，backend-api 收到的是这次 HTTP 连接被服务端关闭（连接中断），按普通"执行异常中断"处理即可（不需要特殊区分"是不是因为 Runner 收到了 SIGTERM"）
- 验证方式：`uv run pytest`（`agent-runner/` 目录下全量 57 个用例全过，含此前 52 个 + 本次新增 5 个）；本地起了真实 uvicorn（`RUNNER_LOCAL_CACHE_DIR` 指到仓库外目录）+ 真实 Postgres/MinIO/Redis + 真实 `ANTHROPIC_API_KEY`，对一个临时 Agent 发起真实 `execute` 请求并在执行进行中对服务进程 `kill -TERM`，确认日志按预期顺序输出（`sigterm_received` → `output_snapshot_synced[update_source=emergency_fallback]` → `emergency_shutdown_complete`）、进程退出、Redis 无残留 `agent_lock:*`、MinIO 新版本快照对象内容与终止前状态一致；验证完清理了临时 Agent 行、MinIO 测试对象、本地缓存目录

## [T4.5] Conversation Service —— 2026-09-01

**状态**：已完成

**完成内容**：
- 新增 backend-api `app/modules/conversations/` 三个文件：`service.py`（`create_conversation`/`get_conversation`，操作 T1.1 已建好的 `Conversation` 表）、`runner_client.py`（`build_client`/`open_execute_stream`，httpx 直连调用 agent-runner 的 `execute` 接口，非 200 时统一转成 `RunnerRequestError`）、`router.py`（`POST /agents/{agent_id}/conversations`、`GET /conversations/{conversation_id}`、`POST /conversations/{conversation_id}/messages`，最后一个接口做 SSE 转发 + 流结束后从 `ResultMessage` 里取 `session_id` 落库）；`app/main.py` 注册了新路由
- `app/config.py` 新增 `agent_runner_host`/`agent_runner_http_port`/`agent_runner_connect_timeout_seconds`/`agent_runner_base_url`；`docker-compose.yml` 给 `backend-api` 服务补了 `AGENT_RUNNER_HOST: agent-runner` 环境覆盖（同其他依赖服务一致的模式：容器内用 compose 服务名代替 `.env` 里给宿主机本地开发用的 `localhost`）
- 新增测试 `backend-api/tests/test_conversations.py`（7 个用例）

**关键决策与偏差**：
- 已回写到 [TASKS.md](../TASKS.md) T4.5 的"决策记录"小节，核心要点（详见该文档）：① **backend-api 不重复实现 Agent 互斥锁**——TECH_DESIGN 4.4 步骤 2 提到的"Conversation Service 用 Redis 对该 Agent 加互斥锁"实际上锁已经在 T4.2/T4.3 落在了 agent-runner 一侧，本任务原样透传 Runner 的 409，不新增第二把锁；② SSE 转发是手动逐行透传（httpx 流式 `aiter_lines()` 重建 `data: ...\n\n` 格式），不是简单管道字节流，因为要在中途窥探 `ResultMessage` 取 `session_id`；③ 落库延迟到流结束的 `finally` 块，不在流进行中途写，且用独立短生命周期 DB session（不复用请求最初查 conversation 时的 session，也不让一个 DB 连接跨越整个可能很久的 SSE 生命周期）
- 这是对 TECH_DESIGN 4.4 表述的一处必要偏差（锁的归属），已经记录在 TASKS.md 决策记录里，不需要回写 TECH_DESIGN 本身（该文档只到系统级粒度）

**遗留问题**：
- `Conversation.status` 字段目前只有 `create_conversation` 时写死的 `"active"`，本任务没有定义其他状态流转（比如对话被归档/关闭）——如果 T5.1/T5.2 需要"关闭对话"之类的操作，需要另外定义状态机，本任务没有预留
- 没有做"列出某 Agent 下所有对话"的接口（比如对话历史列表页可能需要）——T4.5 验收标准只要求"基于已有 conversation_id 续接"，没有要求列表浏览，留给 T5.1 前端落地时如果需要再补
- 与历次任务一致：backend-api 每次调用 Runner 都是新建一个 `httpx.AsyncClient`（用完关闭），没有做连接复用/连接池；如果后续发现高并发下这里成为瓶颈需要专门评估

**给下一个任务的建议**：
- **T5.1（对话页面前端）** 直接调用本任务的三个接口即可：先 `POST /agents/{agent_id}/conversations` 拿 `conversation_id`（或者如果前端要支持"继续上次对话"，需要自己想办法记住/查出上次的 `conversation_id`——本任务没有提供"按 agent 列出历史对话"的接口，见上面遗留问题），然后对 `POST /conversations/{conversation_id}/messages` 发起 SSE 请求持续渲染；遇到 HTTP 4xx（包括 409 Agent 正忙、404 对话不存在）要在页面上给出清晰提示而不是空白/卡死，这是 T5.1 验收标准明确要求的
- **T5.2（对外 API）** 可以直接复用这三个接口对外暴露（TASKS 原文就是这么设计的："复用 Conversation Service 的核心编排逻辑"），不需要另外包一层，只是需要补充非浏览器客户端消费 SSE 的文档说明
- 验证方式：`uv run pytest`（backend-api 目录下全量 28 个用例全过，含此前 21 个 + 本次新增 7 个；agent-runner 目录下 57 个用例不受影响）；本地起了真实 backend-api + agent-runner + 真实 Postgres/MinIO/Redis + 真实 `ANTHROPIC_API_KEY`，对一个临时 ready Agent 走完整闭环验证：新建对话 → 发消息收到真实 SSE 流 → `session_id` 正确回写 → 带同一 conversation_id 续接（Runner 侧 `workspace_cache_hit` + `resume_session_id` 与前一轮一致）→ 执行过程中并发发消息，确认清晰收到 `409 Agent 正忙`（不阻塞不排队）且原请求不受影响正常完成。验证完清理了临时 Agent 行与 MinIO 测试对象
