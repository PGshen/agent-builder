# AgentBuilder 技术方案（v0.3）

> 承接 [PRD.md](./PRD.md) 的产品决策，本文档给出系统级技术方案。不展开到代码/接口字段级细节，这些留到具体模块开发时补充。

## 1. 技术栈

| 类别 | 选型 |
|---|---|
| 前端 | TypeScript |
| 后端 API / Agent Runner | Python（Claude Agent SDK Python 版本），Web 框架用 FastAPI |
| Backend API ⟷ Agent Runner 数据面协议 | HTTP chunked / SSE（不用 gRPC） |
| 任务队列 | Celery，以 Redis 作为 broker，用于 Agent Runner 后台任务调度 |
| 分布式锁 | Redis |
| 元数据 / SessionStore 存储 | Postgres |
| 对象存储 | MinIO（Skill 文件、Workspace 快照） |
| 部署编排 | Docker Compose，服务间负载均衡暂用 Compose DNS 轮询，不引入反代 |
| 登录鉴权 | 简单登录鉴权（非多租户，仅基础身份校验，无细粒度权限模型） |
| 多租户 | v1 不支持，按单租户设计 |

## 2. 整体架构

架构上明确拆分**控制面**与**数据面**：

- **控制面**（低频、小数据量）：任务派发（Workspace 初始化、仓库定时刷新）、Agent 互斥锁 —— 走 Celery + Redis
- **数据面**（对话执行产生的实时流式内容）：Backend API 与 Agent Runner 之间**直连流式调用**（HTTP chunked/SSE），不经过 Redis 转发。Runner 各副本无状态、可互换（依赖 SessionStore 跨主机 resume + MinIO 快照），Backend API 通过 Compose 服务 DNS 轮询选择任意空闲副本，不需要自建注册表；v1 暂不引入反代，后续如负载分布明显不均衡再评估引入 nginx/traefik

```
┌─────────────┐   SSE    ┌──────────────────┐  直连流式调用（负载均衡到任意副本）  ┌───────────────────────┐
│  Web 前端     │◀────────▶│  Backend API      │◀────────────────────────────────▶│ Agent Runner（N 副本）  │
│ (TypeScript) │          │  (Python)         │                                   │ (Python, 调用 SDK)      │
└─────────────┘          └────────┬─────────┘                                   └───────────┬────────────┘
                                    │ 控制面                                                    │
                                    ▼                                                          │
                          ┌───────────────────┐   后台任务派发   ┌───────────────────┐          │
                          │  Redis              │◀──────────────▶│ Scheduler           │         │
                          │ (Celery broker +    │                │ (仓库定时刷新任务)    │         │
                          │  Agent 互斥锁)       │                └───────────────────┘          │
                          └───────────────────┘                                                │
                                    │                                                           │
                    ┌────────────────┴──────────────────┐                                       │
                    ▼                                     ▼                                      │
           ┌──────────────────┐                ┌────────────────────┐◀────────────────────────────┘
           │ Postgres            │                │ MinIO                 │
           │ 元数据 / Session     │                │ Skill 文件 /           │
           │ 映射                │                │ Workspace 快照        │
           └────────────────────┘                └────────────────────┘
```

## 3. 模块划分

| 模块 | 职责 |
|---|---|
| Skill Service | Skill 元数据增删改查；Skill 整体打包为一个 zip 存入 MinIO（一个 Skill 对应一个对象），Postgres 只存元数据与该对象的 key；展示/编辑时拉取 zip 解压解析，保存时重新打包整体覆盖上传 |
| MCP Service | MCP Server 配置的增删改查 |
| Agent Service | Agent 的创建/编辑（绑定 skills/MCP/一个或多个仓库），编排 Workspace 初始化 |
| Conversation Service | 维护 `conversation_id ↔ (agent_id, session_id)` 映射；用 Redis 对 Agent 加互斥锁；直接向 Agent Runner 发起流式调用（不经 Celery） |
| Scheduler | 定时任务（Celery beat 或等价机制）：轮询触发各 Agent 绑定仓库的刷新，作为 Celery 任务派发给 Runner |
| Agent Runner | 承担两类工作，复用同一套"拉取快照→执行→回写快照"逻辑：(1) 作为 Celery worker 消费后台任务（Workspace 初始化、仓库定时刷新）；(2) 对外暴露流式执行接口，由 Backend API 直连调用处理实时对话。各副本无状态、可互换，不需要注册表 |
| SessionStore Adapter | 对接 Claude Agent SDK 的 SessionStore 接口，读写 Postgres |

## 4. 关键流程

### 4.1 创建 Agent
1. 用户提交：名称、绑定的 skills、绑定的 MCP servers、一个或多个代码仓库地址、权限模式
2. Agent Service 落库，分配唯一 workspace 标识
3. 触发 Workspace 初始化任务：逐个 clone 绑定的仓库（只读）→ 按约定目录结构打包 → 上传 MinIO 作为该 Agent 的仓库快照；同时初始化一个空的输出/暂存目录快照（用于承载后续对话产出，见 4.3）
4. 初始化完成置为"就绪"；失败标记失败并保留重试入口

### 4.2 Skill 创建/编辑
Skill 内容遵循标准 skill 目录规范（`SKILL.md` + 资源文件），整体打包为一个 zip 作为单个 MinIO 对象存储（一个 Skill 对应一个 zip）。管理台展示/编辑时，Backend API 拉取该 zip 解压解析出文件树供前端展示编辑；保存时将改动后的内容重新打包整体覆盖上传，Postgres 只更新对象 key/版本号，不维护文件级索引。Agent 使用某个 Skill 时，Runner 在准备 workspace 阶段拉取对应 zip，解压到本地 workspace 内约定路径（如 `.claude/skills/<skill-name>/`）。

### 4.3 Workspace 的两段式模型与仓库定时刷新
Agent 绑定的仓库在 workspace 中是**只读**参考资料——Agent 执行过程中不会向仓库目录写入或提交变更；对话产出的文件写入 workspace 内单独的**输出/暂存目录**。仓库快照与输出快照在 MinIO 中分开存储、独立版本化，Runner 组装本地工作目录时把两者合并挂载。这样设计让"仓库刷新"和"对话产出同步"互不干扰，也不需要处理本地改动与仓库上游更新之间的合并冲突（因为仓库本身不存在本地分叉）。

- 仓库刷新：Scheduler 每隔固定周期（默认 30 分钟，可配置）为每个绑定仓库的 Agent 触发刷新任务，重新拉取最新代码 → 打包 → 更新 MinIO 中的仓库快照。刷新是独立进行的，不依赖、不等待 Agent 互斥锁空闲
- 输出/暂存同步：按 4.4 节流程，只在每轮对话执行完成或异常退出时同步（见 4.5）

### 4.4 发起/续接一轮对话
数据在三段连接上流动：`前端 ⟷(SSE)⟷ Backend API ⟷(直连流式调用)⟷ Agent Runner`。

1. 前端选定 Agent，发起新对话或续接已有对话，与 Backend API 建立 SSE 连接
2. Conversation Service：查/建 `conversation_id → (agent_id, session_id)` 映射；用 Redis 对该 Agent 加互斥锁
3. Backend API 直接向 Agent Runner 服务发起一次流式调用（经负载均衡分发到任意空闲副本）
4. Runner 从 MinIO 拉取该 Agent 最新的仓库快照与输出快照到本地临时磁盘，合并为本次执行的工作目录（本地热缓存且版本未变可跳过）
5. Runner 组装 SDK 调用参数：`cwd` 指向本地工作目录，`resume=session_id`（若续接），按 Agent 配置生成 `mcpServers`/`additionalDirectories`/`permissionMode`，`sessionStore` 指向 Postgres adapter
6. Runner 边执行边通过直连流式连接把消息实时推送给 Backend API，Backend API 经 SSE 转发给前端
7. 正常执行完成：记录/更新 session_id；本地输出目录变更同步回 MinIO（仓库部分只读，不回写）；若实现复杂度可控，尝试对输出快照做增量同步，否则先用整包同步，后续再优化；释放互斥锁

### 4.5 异常退出兜底保存
Runner 进程注册优雅关闭钩子（如 SIGTERM handler），一旦收到终止信号，在退出前**强制将当前本地输出目录打包上传 MinIO**（仓库部分只读，无需回写），再释放互斥锁并退出。

局限性（需要明确认知）：该机制只能覆盖可捕获信号的退出路径（如容器被正常 stop/重启调度），无法覆盖 SIGKILL、宿主机断电等不可捕获场景。为降低这类场景下的数据丢失窗口，建议常规同步频率也适当提高（例如每轮对话结束都同步，而不是仅在会话彻底结束时同步），而不是仅依赖异常退出兜底。

## 5. 数据模型（实体级，非表结构）

- **Skill**：id、名称、zip 包的 MinIO 对象 key、版本、状态
- **MCPServerConfig**：id、名称、连接配置、状态
- **Agent**：id、名称、绑定的 skill 列表、绑定的 MCP 列表、绑定的仓库列表（每项含 url、分支、鉴权方式、最近同步时间/commit）、仓库刷新周期（默认 30 分钟，可配置）、权限模式、workspace 标识、状态
- **Conversation**：id、agent_id、session_id、状态、创建时间
- **WorkspaceSnapshot 元信息**：拆成两部分独立版本化——仓库快照（agent_id、各仓库版本/commit、更新时间）；输出快照（agent_id、版本号/etag、更新时间、更新来源：对话同步/异常兜底）
- **SessionStore 记录**：由 SDK 定义的 session 数据结构，通过 adapter 落 Postgres

## 6. 部署拓扑（Docker Compose）

服务划分：

- `frontend`：TypeScript 前端
- `backend-api`：Python，对外 API + 元数据管理
- `scheduler`：Python，仓库定时刷新（可与 Celery beat 合并部署）
- `agent-runner`：Python，调用 Claude Agent SDK；同时是 Celery worker（后台任务）和流式执行服务（实时对话，Backend API 直连）；可通过 `docker compose up --scale agent-runner=N` 水平扩展，副本间无状态、可互换
- `redis`：Celery broker + 分布式锁（仅承载控制面数据，不承载对话流式内容）
- `postgres`：元数据 + SessionStore
- `minio`：Skill 文件 + Workspace 快照

Backend API 到 `agent-runner` 的直连流式调用依赖 Compose 服务名 DNS 的轮询分发；若后续发现轮询不够均衡（如长流式对话导致负载倾斜），可在两者之间加一层轻量反代（nginx/traefik）做更智能的负载均衡，属于可选的后续优化，不影响当前架构。

Runner 容器需要出网访问 Claude API、代码仓库、MCP 外部服务；建议通过网络策略/代理与其他内网服务隔离。Runner 执行的是 Agent 触发的文件/命令操作，与 Backend API 保持独立容器是刻意的隔离设计，避免一次异常执行波及承载鉴权与元数据管理的服务。

## 7. 非功能性考虑

- **隔离与安全**：Backend API 与 Agent Runner 拆成独立容器/服务，是刻意的隔离边界——Runner 执行不完全可信的 Agent 行为（文件/命令操作），异常不应波及承载鉴权与元数据管理的 API 服务；Runner 只挂载当前执行所属 Agent 的临时目录；出网建议走白名单/代理
- **互斥控制**：Redis 实现的 Agent 级互斥锁，保证同一 Agent 同一时间只有一个活跃执行
- **调度与扩展性**：控制面（后台任务）用 Celery + Redis；数据面（实时对话流式内容）是 Backend API 与 Runner 之间的直连流式调用，不经 Redis 转发，避免高频小消息给 Redis 带来压力。Runner 副本无状态、可互换，水平扩展只需增加副本数，不需要注册表
- **可观测性**：每次执行需要留存日志/工具调用轨迹，独立于 SessionStore 的对话历史之外
- **数据可靠性**：正常同步 + 异常退出兜底两层机制，但对不可捕获的进程终止场景仍有数据丢失窗口（见 4.5）
- **本地缓存清理**：Runner 节点本地缓存的 workspace 副本（仓库+输出），若某 Agent 连续 15 天无对话/刷新活动，可清理释放本地磁盘空间；MinIO 中的权威快照不受影响，下次使用时重新拉取即可

## 8. 待确认 / 待细化

- 简单登录鉴权的具体实现方式（session/cookie 还是 token）
- 增量同步的具体算法/工具选型；若开发时评估实现复杂度过高，直接退回整包同步
- 仓库刷新失败时的告警/重试策略
- 本地缓存清理的触发机制（周期扫描任务 vs 使用时惰性检查）
- 权限模式（permissionMode）在产品层的可配置粒度
