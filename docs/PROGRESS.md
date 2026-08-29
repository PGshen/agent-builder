# AgentBuilder 实施进度

> 状态取值：未开始 / 进行中 / 已完成 / 阻塞。每个任务的目标、关键实现决策、验收标准见 [TASKS.md](./TASKS.md)（ID 一一对应）。开发过程中如决策有调整，先回到 [PRD.md](./PRD.md) / [TECH_DESIGN.md](./TECH_DESIGN.md) 更新，再回来改任务内容。

最后更新：2026-08-29（T0.5 完成后）

## Phase 0：基础设施与骨架

| ID | 任务 | 状态 | 备注 |
|---|---|---|---|
| T0.1 | Docker Compose 基础设施（Postgres/Redis/MinIO） | 已完成 | 详见 [归档记录](./handoff-archive/phase0-2026-08-29.md) |
| T0.2 | Backend API 项目骨架（FastAPI） | 已完成 | 详见 [归档记录](./handoff-archive/phase0-2026-08-29.md) |
| T0.3 | Agent Runner 项目骨架 | 已完成 | 详见 [归档记录](./handoff-archive/phase0-2026-08-29.md) |
| T0.4 | 前端项目骨架（TypeScript） | 已完成 | 包管理器改为 pnpm，UI 改用 shadcn/ui，详见 [归档记录](./handoff-archive/phase0-2026-08-29.md) |
| T0.5 | 简单登录鉴权 | 已完成 | 详见 [归档记录](./handoff-archive/phase0-2026-08-29.md) |

## Phase 1：元数据管理（Skill / MCP）

| ID | 任务 | 状态 | 备注 |
|---|---|---|---|
| T1.1 | 数据模型与数据库迁移 | 未开始 | |
| T1.2 | Skill Service（zip 存取 + CRUD API） | 未开始 | |
| T1.3 | Skill 管理前端页面 | 未开始 | |
| T1.4 | MCP Service（CRUD API） | 未开始 | |
| T1.5 | MCP 管理前端页面 | 未开始 | |

## Phase 2：Agent 构建器与 Workspace 初始化

| ID | 任务 | 状态 | 备注 |
|---|---|---|---|
| T2.1 | Agent Service | 未开始 | |
| T2.2 | Agent Builder 前端页面 | 未开始 | |
| T2.3 | Workspace 初始化任务 | 未开始 | |
| T2.4 | Agent 状态管理与展示 | 未开始 | |

## Phase 3：仓库定时刷新

| ID | 任务 | 状态 | 备注 |
|---|---|---|---|
| T3.1 | Scheduler 服务（Celery beat） | 未开始 | |
| T3.2 | 仓库刷新任务 | 未开始 | |

## Phase 4：对话执行核心链路

| ID | 任务 | 状态 | 备注 |
|---|---|---|---|
| T4.1 | SessionStore Adapter | 未开始 | |
| T4.2 | Agent 互斥锁（Redis） | 未开始 | |
| T4.3 | Agent Runner 流式执行接口 | 未开始 | |
| T4.4 | 异常退出兜底保存 | 未开始 | |
| T4.5 | Conversation Service | 未开始 | |

## Phase 5：对话页面与对外 API

| ID | 任务 | 状态 | 备注 |
|---|---|---|---|
| T5.1 | 对话页面前端 | 未开始 | |
| T5.2 | 对外 API | 未开始 | |

## Phase 6：收尾与运维能力

| ID | 任务 | 状态 | 备注 |
|---|---|---|---|
| T6.1 | Runner 本地缓存清理任务 | 未开始 | |
| T6.2 | 端到端联调与验收 | 未开始 | |
