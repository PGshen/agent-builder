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

## [T2.2] Agent Builder 前端页面 —— 2026-08-30

**状态**：已完成

**完成内容**：
- `frontend/src/lib/agentsApi.ts`：新增 `listAgents`/`getAgent`/`createAgent`/`updateAgent`/`deleteAgent` 请求封装，`REPO_CREDENTIAL_MASK` 常量、`AgentAuthType`/`AgentStatus`/`PermissionMode` 类型、`PERMISSION_MODE_OPTIONS` 选项表
- `frontend/src/components/agents/RepositoryListEditor.tsx`：仓库列表编辑器（新增/删除行、URL/分支输入、鉴权方式 Select、凭证输入）
- 三个页面替换掉 T0.4 留的 `AgentBuilderPage.tsx` 占位页（已删除）：
  - `pages/AgentsPage.tsx` —— 列表页（名称/状态/权限模式/绑定计数/更新时间）
  - `pages/AgentFormPage.tsx` —— 创建（`/agents/new`）与编辑（`/agents/:id/edit`）复用的表单页，`useParams().id` 是否存在区分模式
  - `pages/AgentDetailPage.tsx` —— 详情页（状态/权限模式/仓库刷新周期/workspace_id/skills·MCP·仓库绑定明细），带"刷新状态"/"编辑"/"删除"三个操作
- `App.tsx` 路由改为四条：`/agents`、`/agents/new`、`/agents/:id`、`/agents/:id/edit`
- 新增 shadcn 组件 `checkbox`/`select`（`pnpm dlx shadcn@latest add checkbox select`）

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T2.2 的"决策记录"小节，要点：创建/编辑不用 Sheet 抽屉、改用独立路由页面（TASKS 原文要求"创建后跳转到详情页"，跟 T1.3/T1.5 的抽屉模式不兼容）；`permissionMode` 在本任务落地时决定直接暴露 SDK 原生四个取值（`default`/`acceptEdits`/`bypassPermissions`/`plan`），不做产品层封装，这个决策同时解决了 TECH_DESIGN 8 节遗留的"待确认"项；仓库鉴权凭证的打码占位符交互与 T1.5 MCP 表单一致（未修改原样提交，后端自动识别保留旧值）
- 详情页状态展示只做手动"刷新状态"按钮，没有自动轮询也没有失败重试入口——这两项 TASKS 原文明确留给 T2.4，本任务只需要满足"创建后能在详情页看到初始化状态"这一条验收标准

**遗留问题**：
- T2.4 需要在 `AgentDetailPage.tsx` 补上：状态自动轮询（初始化中时定期重新拉取）+ 失败状态下的"重试"按钮（调用一个新的重试接口，T2.1 交接记录建议直接复用 `trigger_workspace_init`）
- 目前详情页看到的 `status` 永远是创建时的 `"initializing"`（因为 T2.3 Workspace 初始化任务还没有 worker 消费，状态不会自动流转），需要等 T2.3/T2.4 落地后才能验证"就绪"/"失败"两种状态在页面上的实际展示效果，本任务只验证了字段渲染逻辑本身（用当前唯一可能出现的 `initializing` 状态跑通了闭环）
- `AgentFormPage.tsx` 里 skills/MCP 是简单的勾选列表（无分页/搜索），如果后续 Skill/MCP 数量变多，可能需要加搜索框或分页，本任务没有考虑这个规模问题

**给下一个任务的建议**：
- T2.3（Workspace 初始化任务）落地后，可以用真实的 clone 失败场景验证 `AgentDetailPage.tsx` 的"失败"状态展示（`status_message` 已经在页面上接好了展示位置，红色提示框，`agent.status === 'failed' && agent.status_message` 条件渲染）
- T2.4 实现自动轮询时，注意 `AgentDetailPage.tsx` 目前的 `useEffect` 只在 `id` 变化时拉取一次；加轮询时应该用 `setInterval`/`setTimeout` 循环调用现成的 `handleRefresh()` 逻辑（已经是可复用的独立函数），并在状态变成 `ready`/`failed`（终态）后停止轮询，避免无意义的持续请求
- `PERMISSION_MODE_OPTIONS`（`lib/agentsApi.ts`）如果后续要改成产品层封装的语义（而不是直接透传 SDK 枚举），这是唯一需要改的地方，表单和详情页都是从这个常量数组渲染的，不需要改页面组件

## [T2.2 补充] Agent Builder 交互优化 —— 2026-08-30

**状态**：已完成

**完成内容**：
- 用户反馈三点，详见已回写到 [TASKS.md](../TASKS.md) T2.2 的"决策记录（2026-08-30 交互优化追加）"小节，这里只列文件变更：
  - 创建/编辑从独立路由页面改回侧边抽屉：删除 `pages/AgentFormPage.tsx`/`AgentDetailPage.tsx`，新增 `components/agents/AgentEditorSheet.tsx`，`App.tsx` 路由收敛回只有 `/agents` 一条，`pages/AgentsPage.tsx` 改用 `key={editingId-openSeq}` 强制重挂载的抽屉模式（跟 Skill/MCP 列表页一致）
  - 新增 Agent 能力描述字段：`backend-api/app/modules/agents/models.py` 加 `description` 列 + 新迁移 `dbf10ea831f1_agent_description.py`；`schemas.py`（`AgentCreateRequest`/`AgentListItem`/`AgentDetail`）、`service.py`（`create_agent`/`update_agent`）、`router.py` 三处同步加字段；`docker compose build/up backend-api` 已重建镜像并跑过迁移
  - skills/MCP 绑定从 Checkbox 竖直列表改成可过滤穿梭器：新增 `components/agents/TransferList.tsx`（自研，非第三方库）
- `frontend/src/lib/agentsApi.ts` 加 `description` 字段（`AgentListItem`/`AgentDetail`/`AgentFormInput`）

**关键决策与偏差**：
- 详见 TASKS.md 决策记录，要点：Sheet 模式下"创建后能看到初始化状态"这条验收标准靠"抽屉原地切换成编辑态"满足，不再需要路由跳转；`TransferList` 是通用组件（`{id,label}[]` + 受控 value/onChange），不绑定 Agent 具体类型，未来其它模块如果有类似"从一堆选项里挑几个"的需求可以直接复用，不需要重新造

**遗留问题**：
- 与 T2.2 初版遗留问题一致，仍未解决：状态自动轮询、失败重试按钮留给 T2.4；`status` 目前只能看到 `initializing`（T2.3 worker 还没实现，不会真正流转到 `ready`/`failed`）
- `TransferList` 没有做虚拟滚动，Skill/MCP 数量如果涨到几百上千条，`max-h-56/64 overflow-y-auto` 的简单滚动列表可能会有性能问题，v1 暂不处理

**给下一个任务的建议**：
- T2.4 实现状态轮询时，改动位置在 `components/agents/AgentEditorSheet.tsx` 而不是某个独立的详情页组件了——`handleRefreshStatus`（已经是可复用的独立函数）可以直接被一个 `setInterval` 循环调用，抽屉打开且 `workingId` 非空、状态是 `initializing` 时启动轮询，变成终态（`ready`/`failed`）或抽屉关闭时停止
- 如果后续还有其它地方需要"从一批选项里多选几个，带搜索"的交互（比如 T5.x 对外 API 权限范围选择之类），优先复用 `components/agents/TransferList.tsx`，必要时把它挪到更通用的位置（比如 `components/common/`），而不是重新写一个

## [T2.3] Workspace 初始化任务 —— 2026-08-30

**状态**：已完成

**完成内容**：
- `agent-runner` 新增 `app/workspace/` 模块（五个文件）：
  - `db.py` —— `asyncpg` 原生 SQL 读写（不引入 SQLAlchemy ORM），`load_agent_context`/`mark_agent_status`/`save_workspace_snapshot`/`update_repository_sync_info`
  - `crypto.py` —— `decrypt_credential`，与 backend-api 共用同一个 `AGENT_REPO_ENCRYPTION_KEY`
  - `git_ops.py` —— `clone_repository`（三种 auth_type 的 clone 方式）、`repo_dir_name`（快照内目录命名与去重）、`WorkspaceInitError`
  - `archive.py` —— `zip_directory`/`empty_zip`
  - `storage.py` —— MinIO 存取，`repo_snapshot_key`/`output_snapshot_key` 两个 object key 生成函数
- `app/worker/tasks/workspace.py` —— Celery 任务 `workspace.init`（对应 backend-api T2.1 已经在发的任务名/参数签名），`init_workspace(agent_id)` 同步入口内部 `asyncio.run()` 跑异步逻辑
- `app/worker/celery_app.py` 的 `include` 列表加上这个新任务模块；`app/config.py` 新增 `agent_repo_encryption_key`/`workspace_clone_timeout_seconds` 两个配置项
- `pyproject.toml` 新增 `cryptography==44.0.0` 依赖（`uv lock` 已重新生成）；`Dockerfile` 新增系统依赖 `git`/`openssh-client`/`ca-certificates`
- `backend-api/app/modules/agents/models.py` 的 `output_snapshot_update_source` 字段注释补充第三个取值 `workspace_init`（T2.1 只定义了 `conversation_sync`/`emergency_fallback` 两种）
- `.env.example` 补充 `WORKSPACE_CLONE_TIMEOUT_SECONDS` 说明及 `AGENT_REPO_ENCRYPTION_KEY` 被 agent-runner 复用的提示
- 新增 3 个测试文件（`test_workspace_archive.py`/`test_workspace_git_ops.py`/`test_workspace_task.py`，共 11 个用例）

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T2.3 的"决策记录"小节，要点：Runner 侧 DB 访问延续 T0.3 health check 建立的 `asyncpg` 原生 SQL 模式而非引入第二套 SQLAlchemy ORM；`token` 鉴权把凭证明文拼进 https URL netloc，`ssh_key` 鉴权把私钥写临时文件用完即删且用 `GIT_SSH_COMMAND` 注入；clone 失败的 git stderr 会先脱敏（替换掉凭证明文）才写入 `Agent.status_message`；快照内仓库目录名基于 URL basename sanitize + 去重后缀；MinIO object key 是 `{workspace_id}/repo-v{version}.zip`/`output-v{version}.zip`，版本号不覆盖旧对象（历史版本对象的清理和 T2.1 遗留的"Agent 删除不清理 MinIO"是同一类未解决问题，本任务同样没有处理）；整个 clone+打包+上传+写快照元信息包在一个 try/except 里，任何失败都不会产生部分快照记录或部分上传对象，本地打包全程发生在 `tempfile.TemporaryDirectory()` 里保证这一点；任务本身天然幂等（重复触发只产生新版本号），"重试"入口留给 T2.4 接 UI，不需要 Runner 侧新增代码
- Windows 开发环境下 `shutil.rmtree` 删 `.git` 目录会因为 git 对象文件只读属性报错，加了 `onerror` 回调清除只读位再重试删除（这个修复同时也让代码在容器/Linux 环境下更健壮，虽然那边通常不会触发这个分支）

**遗留问题**：
- 与 T2.1 一致的已知遗留：Agent 删除仍然只删 Postgres 行，不清理 MinIO 里的仓库快照/输出快照对象（这次是真的会产生对象了，之前 T2.1 时 MinIO 里还没有东西）；旧版本号对应的快照对象也不会在写入新版本后被清理——这两类"MinIO 对象生命周期管理"问题目前都还没有任务认领，后续需要找个任务（可能是 T2.4 或更后面的运维任务）补上
- `token` 鉴权方式假设的是"把 token 塞进 URL 就能免密 clone"这种主流托管商都支持的约定（GitHub PAT/GitLab 都可以），没有做成"按域名适配不同托管商的具体拼接格式"（比如 GitLab 惯用 `oauth2:<token>@`），v1 先用最通用的 `<token>@host` 格式，如果后续有具体托管商拼接格式不兼容的报告，再针对性调整 `git_ops._inject_token`
- 只验证了 `auth_type=none` 的 clone 路径（本地临时仓库），`token`/`ssh_key` 两种鉴权方式的 clone 逻辑本身有单元测试覆盖（`_inject_token`），但没有对着真实私有仓库做端到端验证（沙箱环境没有可用的私有仓库/token 可测）
- 定时刷新（T3.x）目前完全没有实现，`agent_repositories.last_synced_at`/`last_synced_commit` 只会在"创建 Agent 触发初始化"或"手动重试初始化"时更新一次，不会自动保持最新

**给下一个任务的建议**：
- T2.4（Agent 状态管理与展示）：状态流转的后端部分本任务已经完整实现（`initializing`→`ready`/`failed`，`status_message` 已经在失败时写入可读的中文错误信息），T2.4 只需要做前端轮询 + "失败状态下调用 `trigger_workspace_init` 重新触发"这个按钮，不需要改动 Runner 或 backend-api 代码
- T3.2（仓库刷新任务）落地时，`agent-runner/app/workspace/` 下的 `db.py`/`git_ops.py`/`archive.py`/`storage.py` 都可以直接复用——刷新逻辑本质是"针对已有 Agent 的仓库重新跑一遍 clone+打包+上传"，只是不需要同时处理输出快照（仓库刷新只更新 `repo_snapshot_*`，`output_snapshot_*` 保持不变），可以考虑把 `_clone_and_pack` 里 clone+打包这部分抽出来给两边共用，但也不必现在就抽象，等 T3.2 实际写的时候看是否真的重复再决定
- 如果后续要实现"Agent 删除时清理 MinIO 对象"，需要同时清理 `workspace_snapshots` 表里记录的当前版本对象，以及所有历史版本对象（历史版本号目前没有在任何地方被索引/列出，可能需要用 `mc`/MinIO SDK 的 `list_objects` 按 `{workspace_id}/` 前缀整体删除，而不是只删表里记的那一个 key）
- 验证方式：`uv run pytest`（agent-runner 目录下，新增 11 个用例全部通过，加上原有 2 个共 13 个）；`docker compose build/up agent-runner` 后用 `curl` 走了创建 Agent → 观察状态自动流转到 `ready`/`failed` → 检查 MinIO 对象（用一次性 `minio/mc` 容器 `mc ls`/`mc cp` 出来再用 Python `zipfile` 校验内部目录结构）→ 检查 Postgres `workspace_snapshots`/`agent_repositories` 字段的完整链路，覆盖了 TASKS.md 三条验收标准（单仓库成功、不可达仓库失败、双仓库各自独立目录），验证完删除了这三个测试 Agent 并清理了对应的 MinIO 对象

## [T2.4] Agent 状态管理与展示 —— 2026-08-30

**状态**：已完成

**完成内容**：
- 后端补上 T2.1/T2.3 交接记录里提到但一直没有落地成接口的"重试"：
  - `backend-api/app/modules/agents/service.py` 新增 `AgentNotFailedError` 异常 + `retry_workspace_init(db, agent_id)`：只允许在 `Agent.status == "failed"` 时执行，重置 `status="initializing"`/`status_message=None` 后提交，再调用已有的 `tasks.trigger_workspace_init`（不重新实现发送逻辑）
  - `backend-api/app/modules/agents/router.py` 新增 `POST /agents/{agent_id}/retry`（404 未找到 Agent、409 当前状态非 `failed`）
  - `backend-api/tests/test_agents.py` 新增两个用例：`test_retry_init_requires_failed_status`（覆盖"初始化中时重试返回 409"→"手动改数据库模拟失败态"→"重试成功返回 200 且状态回到 initializing、status_message 清空"）、`test_retry_init_missing_agent_returns_404`
- 前端 `frontend/src/lib/agentsApi.ts` 新增 `retryAgentInit(id)` 请求封装
- 前端 `frontend/src/components/agents/AgentEditorSheet.tsx`：
  - 新增状态轮询：`useEffect` 依赖 `[open, workingId, status]`，仅当抽屉打开且 `status === 'initializing'` 时启动 4 秒间隔的 `setInterval`（`STATUS_POLL_INTERVAL_MS`），复用已有的 `applyDetail` 回填数据，状态变成终态或抽屉关闭时通过 effect cleanup 自动停止
  - 新增"重试初始化"按钮：只在 `status === 'failed'` 时渲染（紧挨状态 Badge/"刷新状态"按钮），点击调用 `retryAgentInit` 并用 `applyDetail` 回填结果，失败时复用已有的 `saveError` 提示位

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T2.4 的"决策记录"小节，要点同上"完成内容"，无额外偏差——本任务严格按 T2.1/T2.2/T2.3 交接记录里已经约定好的方案落地（重试复用 `trigger_workspace_init`、轮询挂在 `AgentEditorSheet` 而不是详情页，因为详情页在 T2.2 交互优化时已经改回抽屉）

**遗留问题**：
- 无新增遗留问题。T2.1/T2.3 交接记录里提到的"Agent 删除不清理 MinIO 对象"仍未解决，与本任务无关，留给后续运维类任务
- 轮询间隔固定 4 秒、无退避策略，若未来 workspace 初始化耗时明显变长（比如仓库很大），轮询请求量会随之增加，v1 未做指数退避或最大轮询次数限制

**给下一个任务的建议**：
- T3.x（仓库定时刷新）：`agent_repositories.last_synced_at`/`last_synced_commit` 目前只在"创建 Agent"或"手动重试初始化"时更新，本任务未改变这一点；重试接口 `retry_workspace_init` 本质是"Agent 级别的整体重新初始化"（会重新处理所有绑定仓库+重建输出快照占位），跟 T3.2 要做的"单个仓库的增量刷新"是两个不同粒度的操作，T3.2 不要复用这个接口
- 验证方式：`uv run pytest tests/test_agents.py`（backend-api 目录下，7 个用例全过，含本任务新增 2 个）；`docker compose build/up backend-api` 重建镜像后用 `curl` 走了真实容器的完整链路——创建一个绑定不可达仓库的 Agent → 确认自动流转到 `failed`（真实 T2.3 worker 消费，非手动模拟）→ 调用 `POST /agents/{id}/retry` 确认返回 200 且状态回到 `initializing`、`status_message` 清空 → 再次调用 retry（此时状态是 `initializing`）确认返回 409 → 删除清理；前端用临时装的 Playwright（用完 `pnpm remove playwright` 卸载、脚本文件已删除，`git status` 确认 `package.json`/`pnpm-lock.yaml` 无残留）跑了一遍真实浏览器链路：创建同样绑定不可达仓库的 Agent → 不点手动刷新，只等轮询，3 秒内自动看到状态变成"失败"且展示 `status_message` 原因 → 点"重试初始化"确认状态变回"初始化中"、按钮消失 → 全程浏览器控制台无报错；复用的开发环境是用户本地已经在跑的 `pnpm run dev`（端口 5173 已占用，未另起新进程）

## [T2.1 补丁] PUT 编辑仓库后自动重新触发 workspace 初始化 —— 2026-08-30

**状态**：已完成

**背景（用户报告的 bug）**：用户用真实可访问的仓库 `https://github.com/PGshen/chat-web.git` 测试，创建 Agent 并绑定该仓库后，在 MinIO 里看到的 `repo-v1.zip` 是空压缩包。排查后确认 **T2.3 的 clone/打包/上传逻辑本身没有问题**（用同一个仓库、同一套代码、真实 docker compose 环境端到端重新跑了一遍，产物是 625KB/59 个文件的正常 zip）。真正原因：该 Agent 创建时数据库里 `agent_repositories` 还没有这条记录（`created_at` 比 `workspace_snapshots` 晚 4 个多小时），也就是说仓库是**创建之后通过编辑（PUT）才加上的**——而 T2.1 当时的决策是"PUT 不会重新触发 workspace 初始化"（留给 T2.4 的失败重试兜底）。但 T2.4 的 `retry_workspace_init` 只在 `Agent.status == "failed"` 时可调用，编辑后状态还是当初那次的 `ready`，导致**没有任何入口能刷新这个过期/空的快照**，页面还一直显示"就绪"，具有误导性。

**完成内容**：
- `backend-api/app/modules/agents/service.py` 的 `update_agent`：在删除重建三类绑定前，把编辑前的仓库列表按 `position` 排序后转成 `(url, branch, auth_type, auth_credential密文)` 元组序列（`old_repo_snapshot`）；重建仓库行的循环里同步收集编辑后的同构元组序列（`new_repo_snapshot`，凭证经 `masking.resolve_credential_encrypted` 解析后的密文，占位符/未提供凭证的情况会保留原密文，因此"没真改凭证"不会被误判为变化）；两个序列不相等（增删仓库、改地址/分支/鉴权方式、真正轮换了凭证、调整了顺序）时判定 `repos_changed = True`，连同其它字段一起提交同一个事务：把 `Agent.status` 重置为 `"initializing"`、清空 `status_message`；提交成功后如果 `repos_changed` 为真，才调用已有的 `tasks.trigger_workspace_init`（不重新实现发送逻辑，跟 create/retry 保持同一套触发路径）
- 只编辑名称/描述/权限模式/skills/MCP 绑定、仓库列表原样不变时，不会触发重新初始化（这些跟仓库快照无关，重新 clone 没有意义，也避免不必要的 Runner 负载）
- `backend-api/tests/test_agents.py` 新增 `test_update_agent_retriggers_init_only_when_repos_changed`：创建时绑定一个仓库 → 手动把状态改成 `ready`（模拟 T2.3 已经跑完）→ PUT 提交完全相同的仓库信息，断言状态仍是 `ready`（没有被误触发）→ PUT 改动仓库的 `branch`，断言状态变回 `initializing` 且 `status_message` 为空
- `docs/TASKS.md` T2.1 决策记录里原来的"PUT 不会重新触发 workspace 初始化"条目已更新为新决策，保留了旧决策的说明作为背景

**关键决策与偏差**：
- 判定"仓库是否变化"用的是编辑前后两份仓库列表的结构化比较，不是简单看请求体里有没有 `repositories` 字段——这样"仓库数量、顺序不变但改了某一个的 branch/鉴权方式"也能正确识别
- 只有仓库这一类绑定的变化会触发重新初始化；skills/MCP 绑定变化不会，因为 workspace 快照只跟仓库内容有关（这两类绑定是运行时对话链路要用的，跟 T2.3 打包的仓库快照/输出快照无关）
- 前端 `AgentEditorSheet.tsx` 不需要改动：保存后本来就会用响应体 `applyDetail(result.data)` 回填最新 `status`，T2.4 已经实现的轮询 `useEffect` 是按 `status === 'initializing'` 触发的，状态一变自动就开始轮询，不需要额外接线

**遗留问题**：
- 用户最初报告问题的那个 Agent（"问题排查"，`76bcc309-9334-4c91-a69f-bd46cb14b267`）保留在数据库里未删除，仓库绑定跟当前状态实际上一致，本补丁的"内容比较"判定不出差异、不会自动帮它补一次初始化；用户需要自己对它做一次真正的变更（比如改一下 branch 再改回来，或者删掉仓库重新加）来触发一次真实的重新初始化，才能让它的快照变成非空
- 与 T2.1/T2.3 一致的已知遗留仍未解决：Agent 删除、以及快照版本号递增后旧版本对象都不清理 MinIO 里的历史对象；这次触发逻辑改动后版本号会因为一次编辑多产生一个新版本对象，进一步放大了这个遗留问题的影响，值得在处理"MinIO 对象生命周期管理"时一并考虑"编辑触发的重新初始化算不算需要清理旧版本"

**给下一个任务的建议**：
- T3.2（仓库刷新任务）如果要做"定时自动刷新"，可以参考这里"结构化比较仓库列表"的思路判断是否真的需要重新 clone，但 T3.2 是单仓库增量刷新、不牵扯 Agent 整体状态流转，不要直接复用 `update_agent` 里这段逻辑
- 验证方式：`uv run pytest tests/test_agents.py`（8 个用例全过，含本次新增 1 个）；`docker compose build/up backend-api` 重建镜像后用 `curl` 复现了完整 bug 场景并验证修复——创建一个不绑仓库的 Agent（产生空 `repo-v1.zip`，对应用户最初遇到的问题）→ PUT 加上 `https://github.com/PGshen/chat-web.git` → 确认响应里状态立即变回 `initializing` → 等真实 T2.3 worker 跑完 → 确认状态回到 `ready`、`agent_repositories.last_synced_commit` 写入了真实 commit hash、MinIO 里新增的 `repo-v2.zip`（625KB/59 个文件）内容正确；同一份 PUT 仓库信息原样再提交一次，确认状态没有被重置（没有误触发）；验证完删除了测试 Agent 并清理了对应的 MinIO 对象（`repo-v1.zip`/`repo-v2.zip`/`output-v1.zip`）
