# AgentBuilder 产品需求文档（v0.2，决策记录版）

> 本文档记录当前阶段已经拍板的关键决策和产品范围，细节留到具体开发时再补充。

## 1. 产品定位

基于 Claude Agent SDK 构建的 Agent 管理平台：可视化管理 Skills、MCP、Agent（绑定 skills/MCP/代码仓库），提供对话页面与 API，容器化部署。

用户使用流程：**创建 Agent（配置绑定）→ 系统自动开辟独立工作空间 → 使用时先选 Agent → 在该 Agent 的工作空间内对话执行**。

## 2. 核心概念

| 概念 | 说明 |
|---|---|
| Skill | 可复用的技能包，由多个文件组成，整体打包为一个 zip 存储在 MinIO（一个 Skill 对应一个对象）；展示/编辑时解压解析，修改后重新打包整体上传；可被多个 Agent 绑定 |
| MCP Server | 外部工具/数据源接入，可被多个 Agent 绑定 |
| Agent | 用户创建的实体，绑定一组 skills + MCP servers + （可选）一个或多个代码仓库（只读，定时刷新保持最新）+ 权限模式等配置 |
| Workspace | 每个 Agent 对应一个独立工作空间，由两部分组成：只读的仓库代码（定时刷新）+ 可写的 agent 产出目录（跨对话持久保留） |
| Conversation / Session | 一个 Agent 下的一次对话，对应 SDK 的一个 session_id，可续接（resume） |

## 3. 功能范围（v1）

- Skills 可视化管理：增删改查、上传/编辑
- MCP 可视化管理：增删改查 MCP server 配置
- Agent 构建器：创建/编辑 Agent，绑定 skills、MCP servers、一个或多个代码仓库地址、权限模式
- Agent 创建后自动初始化专属 Workspace（含多仓库 clone，如已绑定），并有定时任务刷新仓库内容保持最新
- 对话页面：先选 Agent，再进入该 Agent 的对话界面，支持历史对话续接
- 对外 API：与对话页面能力对等，供程序化调用
- 简单登录鉴权（v1 不做多租户，仅基础身份校验）

## 4. 关键架构决策

### 4.1 部署形态
容器化部署，编排使用 **Docker Compose**。容器本身视为**无状态计算单元**，不依赖容器本地磁盘保存长期状态。

### 4.2 状态分三层管理

| 层 | 内容 | 存储方式 | 关键机制 |
|---|---|---|---|
| 对话历史层 | session transcript（对话/工具调用记录） | 自定义 SessionStore adapter，写到自有 DB/对象存储 | SDK 原生支持 resume across hosts，容器可无状态调度接手任意对话 |
| Agent 配置层 | 绑定的 skills、MCP servers、permissionMode 等 | 自有业务 DB | resume 时这些配置不会自动恢复，每次对话由后端从 DB 读出后重新组装成 SDK options 传入 |
| 工作空间层 | 仓库代码（只读）、agent 产出文件 | 对象存储（MinIO）+ 快照同步，仓库快照与产出快照分开独立版本化 | 会话开始时将该 Agent 的仓库快照与产出快照从 MinIO 拉取/解压到容器本地临时磁盘并合并为工作目录（`cwd`）；仓库部分只读不回写，产出部分在会话结束或每轮后同步回 MinIO；仓库另有定时刷新任务独立维护（默认 30 分钟，可配置） |

**决策**：工作空间存储采用**对象存储快照同步方案**（MinIO），不使用共享网络文件系统（NFS/EFS/CephFS），也不使用 per-agent 持久卷 + sticky 调度。

- 不直接挂载对象存储作为实时工作目录（FUSE 类方案对 git 高频小文件读写、原子 rename、文件锁支持差，有仓库损坏风险）
- 容器仍需一块本地临时磁盘承载会话期间的实际文件操作，MinIO 只做持久化落地，不是实时文件系统
- 优点：比共享网络存储更便宜、运维更简单，符合容器无状态调度思路；代价是需要自行实现 pull-in/push-out 的同步逻辑，以及同步时机/增量策略的设计

### 4.3 会话续接
- 后端维护 `conversation_id → (agent_id, session_id)` 映射
- 新消息到达时：查映射 → 读 Agent 配置 → 组装 SDK options（含 `resume: session_id`、`cwd` 指向该 Agent workspace、mcpServers、additionalDirectories、permissionMode）→ 执行
- 不直接读写 SDK 本地 session 文件（格式不保证稳定），只通过 SessionStore/SDK 提供的 API 访问

### 4.4 并发策略
**v1 明确不支持同一 Agent 的并行对话**。同一 Agent 同一时间只允许一个活跃对话占用其 workspace，避免仓库文件并发修改冲突。（后续若要支持并行，需引入 per-conversation git worktree，此版本不做）

## 5. 非目标 / 明确排除（v1）

- 同一 Agent 多对话并行执行
- per-agent 独立持久卷 + sticky 路由
- 共享网络文件系统（NFS/EFS/CephFS）方案
- 直接 FUSE 挂载对象存储作为实时工作目录
- 直接解析/迁移 SDK 本地 session 文件
- 多租户（v1 按单租户设计）

## 6. 待细化项（开发时补充）

- SessionStore 具体接口实现与存储选型（DB 表结构，是否也落 MinIO）
- MinIO 产出快照的增量同步实现（尽力而为，若复杂度过高先用整包同步）
- Agent workspace 初始化流程细节（clone 失败重试、仓库鉴权方式）
- 容器池调度与路由实现（拉取/解压对应 Agent 快照的具体机制）
- 异常场景处理：同步中途容器崩溃/网络中断如何保证不丢失最新改动（技术方案见 [TECH_DESIGN.md](./TECH_DESIGN.md) 4.5，仍有未覆盖场景）
- 简单登录鉴权的具体实现方式（session/cookie 还是 token）
- 权限模式（permissionMode）在产品层的可配置粒度
- Skills/MCP 配置的版本管理与 Agent 绑定后的变更传播策略
