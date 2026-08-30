# AgentBuilder 任务清单

> 每个任务描述本次目标、关键实现决策、验收标准，不写代码。所有决策均承接 [PRD.md](./PRD.md) 与 [TECH_DESIGN.md](./TECH_DESIGN.md)，这里只做任务粒度的落地说明；实现中如遇到这两份文档未覆盖的新决策点，先补充到对应文档再开工。进度状态记录在 [PROGRESS.md](./PROGRESS.md)。

---

## Phase 0：基础设施与骨架

### T0.1 Docker Compose 基础设施
**目标**：搭好 Postgres、Redis、MinIO 三个基础组件的 Compose 编排，为后续所有服务提供依赖底座，本任务不含任何业务代码。

**关键实现决策**：
- 三个组件各自用官方镜像，数据用具名 volume 持久化，不用匿名 volume
- 统一放在一个内部 Compose network 里，业务服务后续通过服务名互相访问
- MinIO 启动后需要预先建好本任务约定的 bucket（skill 包、workspace 快照分开两个 bucket 或用前缀区分，二选一在本任务定下来并写清楚）
  - **决策**：采用两个独立 bucket——`agent-builder-skills`（Skill zip 包）与 `agent-builder-workspaces`（Workspace 快照，仓库快照与输出快照各自用 object key 前缀区分，同一 bucket 内隔离）。由一个一次性 `minio-init` 服务（`minio/mc`）在 `minio` 健康后自动创建，`mc mb --ignore-existing` 保证幂等
- 三个组件的连接参数（地址、账号密码、库名/bucket 名）统一放到一份 `.env` 样例文件里，不硬编码进 compose 文件
  - 本机开发环境上 5432 / 6379 / 9000 三个默认端口均已被其他项目占用，`.env.example` 里将宿主机侧映射改为 5442 / 6389 / 9010(+9011 控制台)，容器内部仍用各组件标准端口，不影响 compose 网络内的服务名访问

**验收标准**：
- `docker compose up` 一键拉起三个组件，都能正常运行且数据卷持久化（重启容器数据不丢）
- 能用对应的客户端工具（psql / redis-cli / mc 或 MinIO 控制台）分别连上三个组件并做基本读写验证
- `.env.example` 文件存在且字段完整，团队新成员按说明可以直接起环境

---

### T0.2 Backend API 项目骨架
**目标**：搭好 FastAPI 项目的最小可运行骨架，包含配置管理、数据库连接、健康检查，尚不含具体业务接口。

**关键实现决策**：
- 项目结构按模块划分预留目录（Skill / MCP / Agent / Conversation / Auth 等），本任务只建骨架不实现逻辑
- 配置通过环境变量读取（对应 T0.1 的 `.env`），本地开发与容器内运行用同一套配置读取方式
- 数据库连接池在启动时建立，提供一个健康检查接口验证数据库连通性
- 日志用结构化输出（哪怕本任务先做简单的），为后续可观测性需求打基础

**决策记录**（实现时落地）：
- 技术选型：`pydantic-settings` 读取环境变量（`app/config.py`，`get_settings()` 带 `lru_cache`，进程内只读一次，改配置需重启进程生效——这是预期行为，不是热更新）；数据库用 SQLAlchemy 2.0 async engine + `asyncpg` 驱动（`app/db.py`）；结构化日志用 `structlog`，JSON 输出到 stdout（`app/logging_config.py`）
- `POSTGRES_HOST`/`REDIS_HOST`/`MINIO_HOST`（以及对应 PORT）在 `.env.example` 里的默认值是"宿主机本地开发"视角（`localhost` + T0.1 里为避免端口冲突改的宿主机映射端口），供本地直接跑 `uvicorn` 时连接 compose 拉起的依赖；`backend-api` 作为 compose service 运行时，`docker-compose.yml` 在该 service 的 `environment` 里用服务名 + 组件标准端口（如 `postgres:5432`）覆盖，两种运行方式共用同一套"从环境变量读配置"的代码路径，只是环境变量的值来源不同（`.env` 文件 vs compose service environment）
- 项目目录独立为 `backend-api/`（而非放进 `docs/` 同级根目录），后续 `agent-runner/`、`frontend/` 同级并列，为多服务 Compose 编排做准备
- 健康检查接口 `/health`：数据库不通时返回 HTTP 503 且 `status: degraded`，而不是笼统的 500，方便调用方（compose healthcheck、运维监控）区分"服务进程活着但依赖不可用"与"服务本身挂了"

**验收标准**：
- 服务能在本地和 Compose 容器内两种方式下正常启动
- 健康检查接口返回状态包含数据库连通性结果
- 修改 `.env` 里的数据库连接参数，服务能相应连到不同的数据库实例（验证配置未硬编码）

**决策更新（2026-08-29 追加）**：Python 依赖管理统一改用 `uv`（`pyproject.toml` + `uv.lock`），弃用 `requirements*.txt` + `pip venv`。本项目及后续所有 Python 服务（T0.3 Agent Runner、Scheduler 等）均遵循此约定：本地开发用 `uv sync` / `uv run`，镜像构建用 `ghcr.io/astral-sh/uv` 基础镜像 + `uv sync --locked --no-dev`。详见 HANDOFF.md 对应记录。

---

### T0.3 Agent Runner 项目骨架
**目标**：搭好 Agent Runner 的 Python 项目骨架，包含 Celery worker 接入和健康检查，尚不含 SDK 调用或 workspace 逻辑。

**关键实现决策**：
- 项目结构预留"后台任务（Celery task）"和"流式执行服务（HTTP 服务端）"两类入口的目录划分，对应 TECH_DESIGN 里 Runner 的双重角色
- Celery worker 能连上 T0.1 的 Redis 并成功消费一个最简单的测试任务（如打印日志），验证 broker 打通
- 预留一个本地临时磁盘挂载路径的配置项，供后续 workspace 相关任务使用
- 健康检查同时覆盖"进程存活"和"能否连上 Redis/MinIO/Postgres"两个层面

**验收标准**：
- Celery worker 启动后能正确注册并消费测试任务，日志可见执行记录
- 健康检查接口能反映出 Redis/MinIO/Postgres 任一依赖不可用时的异常状态
- 容器内运行时，临时磁盘路径确实可写

**决策记录**（实现时落地）：
- 目录划分：`app/worker/`（Celery 入口，`celery_app.py` + `tasks/`）与 `app/server/`（FastAPI 流式执行服务入口，`main.py` + `health.py`）平级，对应 Runner 的双重角色；`app/config.py`/`logging_config.py`/`cache.py` 是两者共用的基础设施
- 容器内**同一个进程组**同时跑 Celery worker 和 FastAPI/uvicorn 两个子进程（`entrypoint.sh` 用 `&` 起两个后台进程 + `wait -n`），任一进程退出则容器整体退出，交给编排层重启，避免"看似健康实际少一半功能"的假活状态；对应 TECH_DESIGN 6 "agent-runner 同时是 Celery worker 和流式执行服务"的单容器双角色设计
- Celery broker/result backend 各用独立 Redis db index（0/1），为后续 T4.2 Agent 互斥锁预留 db 2，避免 key 空间混用；db index 通过 `CELERY_BROKER_DB`/`CELERY_RESULT_DB` 环境变量可配置
- 健康检查 `/health` 一个接口同时覆盖"进程存活"（只要能返回响应就说明进程活着）和"依赖连通性"（Postgres/Redis/MinIO/本地缓存目录可写，分别在 `dependencies` 字段里体现），依赖不通时返回 HTTP 503 + `status: degraded`，不额外拆分 `/health/live` 与 `/health/ready` 两个接口（本任务范围内没有必要）
- 本地临时磁盘缓存目录（`RUNNER_LOCAL_CACHE_DIR`）在 compose 里挂了具名 volume（`agent_runner_cache`），而不是容器内临时文件系统层：因为 T6.1"连续 15 天无活动清理本地缓存"的判断逻辑依赖缓存跨容器重启/重建仍然存在，纯 ephemeral 文件系统每次重建容器就清空，会让 T6.1 的场景很难触发；多副本（`--scale agent-runner=N`）共享同一个具名 volume 的并发语义问题留到 T2.3/T4.3 实现 workspace 拉取/合并逻辑时再评估（本任务只是建目录，不涉及并发读写）
- Runner 的 HTTP 服务端口（`AGENT_RUNNER_HTTP_PORT`，默认 8100）在 compose 里只用 `expose` 不对外发布宿主机端口，因为 Backend API 是通过 compose 服务名 DNS 轮询直连各副本（TECH_DESIGN 2），多副本没法共享同一个宿主机端口映射；本地单进程调试/跑测试时才需要直接访问这个端口

---

### T0.4 前端项目骨架
**目标**：搭好 TypeScript 前端项目的最小可运行骨架，包含路由结构和与 Backend API 的请求封装，尚不含具体业务页面。

**关键实现决策**：
- 路由预留 Skills 管理、MCP 管理、Agent Builder、对话页面四个一级入口（页面内容后续任务填充）
- 统一封装一个请求客户端（处理 Backend API 基础地址、鉴权头注入的位置预留，具体鉴权逻辑在 T0.5 实现）
- 基础布局（导航栏 + 内容区）先行搭好，后续页面往里填充即可

**验收标准**：
- 项目能本地启动并通过 Compose 一起跑起来
- 四个一级路由都能访问到（哪怕内容是占位符），导航切换正常
- 请求客户端能成功调用 T0.2 骨架里的健康检查接口并在页面上展示结果，验证前后端联通

**决策记录**（实现时落地）：
- 技术选型：Vite + React + TypeScript + `react-router-dom`（`npm create vite@latest -- --template react-ts` 脚手架起步），不用 Next.js 之类的全栈框架——本项目是纯 SPA + 独立 Backend API，不需要 SSR/文件路由
- 路由结构：`App.tsx` 里 `Routes`/`Route` 声明 `/skills`、`/mcp`、`/agents`、`/conversations` 四个一级路由，共用 `layout/AppLayout.tsx`（导航栏 + `<Outlet/>` 内容区）；根路径 `/` `Navigate` 到 `/skills`（四个入口本任务都是占位页，选哪个做默认落地页不影响后续任务）
- 请求客户端 `lib/apiClient.ts`：`apiRequest()` 不对非 2xx 状态抛异常，返回 `{ok, status, data}` 三元组——因为 `/health` 依赖不可用时会返回 503 但 body 仍然有效，调用方需要能拿到这个 body 展示，而不是被当异常吞掉；鉴权头注入点用注释预留在 `apiRequest` 内部，T0.5 落地时直接在这里加
- 健康检查结果展示做成常驻的 `layout/BackendStatus.tsx` 小部件（挂在 `AppLayout` 页头右侧，所有页面都能看到），而不是单独开一个"首页仪表盘"路由，本任务只要求"能展示"，不需要额外路由
- **前后端跨源问题**：本地开发时前端（`:5173`）和 backend-api（`:8080`）端口不同，浏览器视为跨源请求，需要 backend-api 显式放行 CORS——回溯给 backend-api 加了 `CORSMiddleware`（`app/main.py`）和 `CORS_ALLOW_ORIGINS` 配置项（`app/config.py`，逗号分隔，默认 `http://localhost:5173`），这是 T0.2 交付时遗漏的点，本任务验证前端联通时才发现并补上，`.env.example` 同步加了这一项
- `VITE_API_BASE_URL` 固定填 `http://localhost:8080`（宿主机地址），不管 frontend 本身是本地跑还是跑在 compose 容器里都不变——因为发请求的是用户浏览器，浏览器访问不到 compose 内部服务名 `backend-api`，这跟 backend-api/agent-runner 那种"容器内部访问用服务名覆盖"的模式是两回事，`docker-compose.yml` 里 `frontend` service 不覆盖这个环境变量
- 容器内运行方式：`Dockerfile` 跑 `npm run dev`（Vite dev server，`vite.config.ts` 里配了 `server.host: true`），没有引入生产构建 + nginx 静态托管的流程——本任务只是骨架，暂不需要生产部署形态，后续如果要正式生产部署再补
- 本地 npm 源（`~/.npmrc` 里配的清华 tuna 镜像）在脚手架当时对 `create-vite`/`vite` 等包返回 404（镜像同步问题，非本项目导致），加了 `frontend/.npmrc` 固定指向官方 `registry.npmjs.org`，保证团队成员/CI 里 `npm install`/`npm ci` 不受个人全局 npm 源配置影响

**决策更新（2026-08-29 追加）**：包管理器由 `npm` 改为 `pnpm`（`pnpm-lock.yaml` 提交进仓库，`frontend/Dockerfile` 用 `corepack prepare pnpm@10.12.4 --activate` + `pnpm install --frozen-lockfile`）；UI 组件库引入 `shadcn/ui`（基于 Tailwind CSS v4 + `@tailwindcss/vite` 插件，`@` → `./src` 路径别名，`pnpm dlx shadcn@latest add <component>` 按需添加组件，已有 `button`/`card`/`badge`/`separator`），骨架页面（`AppLayout`/`BackendStatus`/四个占位页）已改用 shadcn 组件 + Tailwind class 渲染。详见 HANDOFF.md 对应记录（`[T0.4 补充]`）。

---

### T0.5 简单登录鉴权
**目标**：实现 v1 约定的简单登录鉴权（非多租户，仅基础身份校验），作为后续所有业务接口的前置能力。

**关键实现决策**：
- 采用单一管理员账号或极简账号体系（不做多租户、不做细粒度权限），具体是 session/cookie 还是 token 在本任务落地时定（TECH_DESIGN 待确认项之一）
- Backend API 提供登录接口和鉴权中间件/依赖项，未登录状态下业务接口一律拒绝
- 前端提供登录页，登录态在前端持久化（刷新页面不丢登录状态），未登录时路由守卫拦截并跳转登录页

**验收标准**：
- 未登录状态下直接访问业务接口返回未授权错误
- 登录成功后能正常访问业务接口，登出后鉴权失效
- 前端刷新页面登录态保持，未登录访问业务页面会被拦截到登录页

**决策记录**（实现时落地，对应 TECH_DESIGN 第 8 节"待确认"项的落地选择）：
- **token 而非 session/cookie**：前端 SPA 与 backend-api 本就是跨源部署（T0.4 已经因此加了 CORS），cookie 方案还要额外处理 `SameSite`/跨源带 cookie 的问题，不如 token 直接；T0.4 交付时 `apiRequest()` 已经预留了 `Authorization` header 注入点，本任务直接落地在这个位置，不引入 cookie
- **opaque token + Redis 存储，而非无状态 JWT**：验收标准明确要求"登出后鉴权失效"——无状态 JWT 在服务端没有可撤销的存根，登出只能是前端丢弃 token，token 本身在过期前仍然有效，不满足这条验收标准的字面要求；改用随机 opaque token（`secrets.token_urlsafe(32)`）作为 key 存进 Redis（value 是用户名，`SETEX` 设置 TTL），登出即 `DEL` 这个 key，做到服务端真撤销。Redis db index 用 3（db 0/1 是 agent-runner 的 Celery broker/result，db 2 预留给 T4.2 Agent 互斥锁，backend-api 这边单独占 db 3，避免以后 key 空间混用）
- **极简单账号体系**：不建 users 表（T1.1 数据模型任务尚未开始，本任务不引入新迁移），管理员账号密码直接来自 `.env`（`ADMIN_USERNAME`/`ADMIN_PASSWORD`），与 Postgres/MinIO 密码一样明文存在 `.env` 里，登录时 `secrets.compare_digest` 常量时间比较；token 有效期 `AUTH_TOKEN_TTL_SECONDS` 默认 7 天（604800 秒）
- **鉴权依赖项而非全局中间件**：`app/api/deps.py` 里的 `get_current_admin`（FastAPI `Depends`）是"后续所有业务接口的前置能力"的具体落地方式——T1.x 起新建业务 router 时，在 `APIRouter(dependencies=[Depends(get_current_admin)])` 或单个路由上接入即可自动要求登录；没有做成 ASGI 中间件，是因为 `/health` 必须保持公开（compose healthcheck 探活不带 token），中间件形态需要额外写路径白名单，不如依赖项精确到路由更直接
- **验收标准里"业务接口"的验证载体**：T0.5 落地时 T1.x 系列业务接口都还没实现，无法直接拿真实业务接口验证"未登录返回 401"。本任务新增了 `GET /auth/me`（返回当前登录用户名，本身要求鉴权）作为验证鉴权机制本身是否工作的载体，`POST /auth/login`/`POST /auth/logout` 两个入口接口不鉴权。T1.x 落地业务 router 时记得真的接上 `get_current_admin`，不要假设"写了鉴权机制"就等于"业务接口已经保护"
- 前端登录态持久化用 `localStorage`（`src/lib/auth.ts`），刷新页面不丢；`apiRequest()` 收到 401 响应时会主动清掉本地 token，配合路由守卫 `RequireAuth`（包裹除 `/login` 外的所有路由）在下次导航时跳回登录页

---

## Phase 1：元数据管理（Skill / MCP）

### T1.1 数据模型与数据库迁移
**目标**：落地 TECH_DESIGN 数据模型一节里的实体到 Postgres 表结构，建立数据库迁移机制。

**关键实现决策**：
- 覆盖实体：Skill、MCPServerConfig、Agent（含绑定的 skill/MCP/仓库列表、仓库刷新周期、权限模式、workspace 标识、状态）、Conversation、WorkspaceSnapshot 元信息（仓库快照 + 输出快照两部分）、SessionStore 记录表
- 使用迁移工具管理 schema 变更（而不是手工建表），后续每次模型调整都走迁移脚本，保证环境间一致
- Agent 与 Skill / MCP 的绑定关系用关联表还是字段内嵌数组，在本任务定下来并统一

**验收标准**：
- 迁移脚本能从空库一次性建出完整 schema，也能在已有库上增量应用
- 每个实体的字段能覆盖 TECH_DESIGN 第 5 节列出的信息，不遗漏关键字段
- 能通过迁移工具查看当前 schema 版本和迁移历史

**决策记录**（实现时落地）：
- 迁移工具选 Alembic（`uv add alembic`），异步引擎模板（`alembic init -t async`），`alembic/env.py` 不在 `alembic.ini` 里硬编码连接串，而是运行时从 `app.config.get_settings().database_url` 读取，复用项目统一的环境变量配置方式；`alembic.ini` 本身保持纯 ASCII（Windows 下 `configparser` 用 locale 编码读取 ini 文件，本机是 GBK，写入中文注释会导致 `UnicodeDecodeError`，这是本任务踩到的坑，记录以避免下次复现）
- ORM 模型不集中放一个 `app/models/` 目录，而是分散到各业务模块自己的 `app/modules/<name>/models.py`（`skills`/`mcp`/`agents`/`conversations`），与已有的模块划分保持一致；新增 `app/db_base.py` 存放共用的 `Base`（`DeclarativeBase`）、`UUIDPKMixin`（UUID 主键，`server_default=gen_random_uuid()`，PG16 内置无需 pgcrypto 扩展）、`TimestampMixin`（`created_at`/`updated_at`）三个模块间共用的基础设施；`alembic/env.py` 汇总 import 各模块 `models.py` 以获得完整 `Base.metadata` 供 autogenerate 使用
- 新增 `app/modules/sessions/` 模块目录（此前不存在），专门承载 SessionStore 记录表 `sdk_sessions`，对应 TECH_DESIGN 里独立的 "SessionStore Adapter" 模块；本任务只落 `session_id`（SDK 管理，非本项目内部 UUID）+ `agent_id` + 不透明 `data` JSONB 三个字段，真正的读写接口留给 T4.1 按 SDK 实际的 SessionStore 接口实现时再细化/如需再迁移加字段
- Agent 绑定关系用关联表而非内嵌数组：`agent_skills`/`agent_mcp_servers`（复合主键 `agent_id`+`skill_id`/`mcp_server_id`，均 `ondelete=CASCADE`）。仓库列表也用独立表 `agent_repositories`（而非 JSON 数组），因为每项仓库有 `last_synced_at`/`last_synced_commit` 等需要独立更新的字段，关系型表比 JSON 数组更适合单条更新
- Workspace 两段式模型：`workspace_snapshots` 表与 Agent 一对一（`agent_id` 直接做主键），仓库快照与输出快照的 object_key/version/updated_at 三元组各自独立一份列，`output_snapshot_update_source` 区分 `conversation_sync`（正常同步）与 `emergency_fallback`（T4.4 异常兜底）
- Agent 新增了 TECH_DESIGN 未明确列出的 `status_message`（Text，nullable）字段：T2.4 验收标准要求"失败"状态要能让前端展示原因，仅有 `status` 三态字符串不够表达具体失败信息，遂在数据模型阶段一并加上，避免 T2.4 时再补迁移
- `workspace_id`（Agent 的 workspace 标识）没有直接复用主键 `id`，而是独立生成（`uuid.uuid4().hex`，唯一约束）：让"对外可见的 workspace 标识"与"内部数据库主键"解耦，即使以后 id 生成策略调整也不影响已落地的 workspace 命名
- MCP 敏感字段加密方式、仓库凭证（`agent_repositories.auth_credential`）加密方式均未在本任务决定，`config`/`auth_credential` 先按明文列落地（类型定好），留给 T1.4/T2.1 实现时决定是否加密及如何脱敏展示，不阻塞 schema 先行
- Backend API 容器启动流程新增 `entrypoint.sh`（`alembic upgrade head` 后再 `exec uvicorn`），`Dockerfile`/`docker-compose.yml` 未变但镜像构建多拷贝 `alembic.ini`/`alembic/`/`entrypoint.sh` 三项：保证每次容器启动都自动把 schema 应用到最新版本，环境间不会因为忘记手动跑迁移而不一致

---

### T1.2 Skill Service（zip 存取 + CRUD API）
**目标**：实现 Skill 的增删改查接口，内容以 zip 包整体形式存取 MinIO。

**关键实现决策**：
- 一个 Skill 对应 MinIO 里一个 zip 对象；Postgres 只存元数据（名称、对象 key、版本、状态），不维护文件级索引
- 编辑接口：拉取现有 zip 解压，返回可编辑的文件树结构给前端；保存接口：接收改动后的内容，重新打包整体覆盖上传
- zip 内目录结构遵循标准 skill 规范（`SKILL.md` + 资源文件），创建时校验基本结构是否符合规范
- 版本号每次保存递增，用于后续 Agent 绑定关系里判断是否需要提示"有更新"（v1 不做自动推送，只是元数据层面的版本记录）；保存历史版本而非覆盖更新，支持回滚到任意历史版本（2026-08-30 追加，见下方决策记录）

**验收标准**：
- 创建 Skill 时上传符合规范的内容，能在 MinIO 里看到对应 zip 对象生成
- 编辑并保存后，MinIO 里新增一个版本对象（旧版本对象不受影响），版本号递增，Postgres 元数据同步更新
- 上传不符合规范（缺 `SKILL.md` 等）的内容时，接口能明确拒绝并返回原因
- 能查看某个 Skill 的历史版本列表，并把任意历史版本重新设为当前激活版本（回滚）
- 删除 Skill 后，其所有版本的 MinIO 对象与 Postgres 元数据一并清理

**决策记录**（实现时落地）：
- 创建接口（`POST /skills`）与编辑/保存接口（`PUT /skills/{id}`）用了两种不同的输入形式，均对应 TASKS 原文语义：创建接口接收 `multipart/form-data`（`name` 字段 + zip 文件），原样存 MinIO，不解包；编辑接口先用 `GET /skills/{id}` 把 zip 解压成 `{路径: 文本内容}` 的文件树 JSON 返给前端，保存时 `PUT /skills/{id}` 接收同样结构的 JSON（不是 zip），后端重新打包整体覆盖上传——直接对应 TASKS 原文"编辑接口拉取现有 zip 解压返回文件树""保存接口接收改动后的内容重新打包"的两句表述
- ~~MinIO 对象 key 固定为 `{skill_id}.zip`，每次保存原地覆盖~~——2026-08-30 改成保留历史版本，不再覆盖，见下方决策记录
- v1 只支持 UTF-8 文本文件（`SKILL.md` + 脚本等），不支持二进制资源文件：解压时按 UTF-8 解码，解码失败直接判为不合法内容拒绝。原因：文件树用 JSON 传输本身不适合塞二进制，真要支持二进制资源留到后续需要时再加 base64 编码的分支，v1 不做
- 校验规则（`app/modules/skills/storage.py::validate_files`）：内容非空、必须包含根路径下的 `SKILL.md`、路径不能是绝对路径或包含 `..`（防 zip slip）；创建（解压上传的 zip）和保存（前端传回的文件树）复用同一套校验函数，保证两个入口标准一致
- 路径分隔符统一归一化成 `/`：实测发现 Windows `PowerShell Compress-Archive` 生成的 zip 条目会用 `\` 而不是 zip 标准的 `/`，解压时统一 `.replace("\\", "/")`，否则同一路径在文件树里可能表现成两种形式、重新打包出的 zip 也不规范
- `name` 唯一性靠 Postgres `skills.name` 的 unique 约束兜底，创建时先 `flush()`（不 `commit()`）拿到 UUID 再传给 MinIO 存储；`IntegrityError` 时回滚并转译成业务异常（HTTP 409），避免"数据库已经报错但还是把 zip 传上去了"这种半成品状态；MinIO 上传失败同样回滚 DB，不留下 `object_key` 为空的孤儿元数据行
- 删除顺序：先删 MinIO 对象，成功后再删 Postgres 行——如果 MinIO 删除失败就保留数据库记录，用户可以重试；不做跨存储的两阶段提交，v1 认为"重试"已经够用
- 敏感字段/鉴权头依赖：`app/api/deps.py` 新增 `get_db_session`（FastAPI 依赖项，包一层 `async with session_factory() as session`），Skill router 整体挂 `Depends(get_current_admin)`，T1.1 交接记录里提到的"补依赖项""业务路由记得接鉴权"两件事在本任务落地
- **顺带修了 T0.2 一个潜在 bug**：`app/db.py` 的 `dispose_engine()` 之前只清空 `_engine` 全局单例，没有同步清空 `_session_factory`（`_session_factory` 是绑定着旧 engine 创建的缓存实例）。生产环境单进程单 event loop 从不触发这个问题，但本任务写多用例的 pytest（`asyncio_mode=auto`，每个测试函数一个新 event loop）时稳定复现：`dispose_engine()` 之后下一个测试仍会拿到绑定旧 engine/旧 loop 的 `_session_factory`，导致该测试内的数据库操作报 `RuntimeError: Event loop is closed`。已修复为 `dispose_engine()` 同时清空两个全局变量；`tests/conftest.py` 相应新增 `_reset_db_engine_per_test` autouse fixture（模式与 T0.5 的 Redis 客户端重置 fixture 一致）

**决策记录（2026-08-30 覆盖更新改为版本历史）**：用户直接反馈"现在是覆盖更新还是保存历史版本"，要求改成保存历史版本，且明确"不用加表，直接在现有表增加两个字段"。改动如下：
  - **不新增表，在 `skills` 表加两个字段**：`active_version`（Integer，当前生效/激活的版本号）、`versions`（JSONB，版本历史记录数组，每条 `{"version": int, "object_key": str, "created_at": iso8601}`，只追加不删除）。原有的 `version` 字段语义调整为"历史上创建过的最新版本号，只增不减"（正常保存时 `version == active_version`，回滚到旧版本后 `active_version < version`）；`object_key` 字段保留，但语义变成"冗余存一份当前激活版本的 object key"，跟 `active_version` 保持同步，这样读内容时不用现解析 `versions` JSON 数组
  - **MinIO key 从固定改成按版本区分**：`{skill_id}/v{version}.zip`，保存（`PUT`）不再覆盖旧对象，而是上传一个新版本对象、把新条目追加进 `versions`、`active_version`/`object_key`/`version` 都指向新版本。历史版本的旧对象永久保留，v1 不做过期清理/存储配额限制
  - **回滚是移动指针，不是新建版本**：新增 `POST /skills/{id}/versions/{version}/activate` 接口，只把 `active_version`/`object_key` 指向历史条目里已经存在的那个版本，`versions` 列表和 `version` 计数器都不变——这样"回滚后再编辑保存"产生的新版本号是接着 `version` 计数器往下走（比如从 v3 回滚到 v1 后编辑保存，新版本是 v4 而不是 v2），版本号历史不会因为回滚被覆盖或复用，语义上更像 git 的"检出旧 commit 再往前走"而不是"删掉后面的历史"
  - **旧数据的迁移**：Alembic 迁移（`d9597aafe1c9_skill_version_history.py`）加列时用 `server_default` 让已有行先有值满足 NOT NULL，再用一条 `UPDATE ... SET active_version = version, versions = jsonb_build_array(...)` 把老数据的"当前状态"回填成 `versions` 列表里唯一的一条记录——因为旧版本代码是覆盖更新，物理上从来没有保留过之前的版本内容，所以老 Skill 的历史只能从"迁移那一刻的状态"开始，这是数据层面的硬限制，不是迁移脚本的疏漏
  - **前端**：`SkillEditorSheet.tsx` 头部新增一个"历史版本"图标按钮（`lucide-react` 的 `History`，新增 shadcn `dropdown-menu` 组件），点开是版本列表（新到旧排序，当前激活的标"当前"且禁用点击），点某个历史版本即调用 activate 接口并重新整体拉取详情（`loadDetail` helper，同时更新 `meta`/`files`/`versions`，被创建/保存/回滚三处复用）；版本徽章从"只显示 `v{version}`"改成"`v{active_version}` + 不等于 `version` 时额外显示`最新 v{version}`"，列表页表格同样处理
  - 验证方式：`uv run pytest` 扩充了 `test_skills.py` 的闭环用例（保存两次产生 v2/v3 → `versions` 列表有 3 条 → 回滚到 v1 内容和 `active_version` 都正确 → 回滚到不存在的版本号返回 404 → 重新激活 v2 恢复）；前端另外用临时 Playwright 跑了一遍"创建 v1 → 连续编辑保存到 v3 → 历史版本下拉里能看到三个版本 → 回滚 v1 且内容/徽章都正确 → 关闭抽屉重开列表页显示`v1（最新 v3）`→ 重新打开抽屉切回 v3 再编辑保存 → 确认新版本号是 v4 而不是 v2（验证回滚不影响版本计数器）→ 删除清理"；测试过程中发现"点完历史版本下拉菜单项后立刻按 Escape 关不掉抽屉"的现象，定位是 Radix 的嵌套 dismissable layer 时序问题（DropdownMenu 刚关闭时自己的 layer 还没从栈里退出，Escape 被它"吃掉"没传到 Sheet），不是本次改动引入的代码问题，真实用户操作节奏下基本不会撞见，未做额外处理

---

### T1.3 Skill 管理前端页面
**目标**：实现 Skills 的可视化管理界面。

**关键实现决策**：
- 列表页展示所有 Skill（名称、版本、状态、更新时间）
- 新建/编辑用侧边抽屉（Sheet）承载，不做独立路由页面——列表页保持挂载，抽屉内完成创建/编辑全流程（2026-08-30 交互优化后的决策，见下方决策记录）
- 详情/编辑页能浏览 zip 内的**嵌套目录树**、查看和编辑文件内容，保存时调用 T1.2 的保存接口；树上支持文件/目录的新建、删除、移动（拖拽或重命名路径）
- 创建页支持新建 Skill（上传或从模板创建，二选一在本任务定，若上传则前端本地打包成 zip 提交）

**验收标准**：
- 能在页面上完成"新建 Skill → 查看文件内容 → 编辑保存 → 列表看到版本更新"的完整闭环操作
- 编辑保存失败（如格式校验不通过）时页面有明确提示，不会静默失败

**决策记录**（实现时落地）：
- 创建页选了"从模板创建"，不做"选择本地 zip 文件上传"：填 名称+描述 两个字段，前端按 skill 规范生成一份最小 `SKILL.md`（`skillsApi.ts::buildSkillTemplate`），用 `fflate`（新增前端依赖，~8KB，零依赖，`zipSync` 同步打包）在浏览器里打包成 zip，走和"上传"同一条 `POST /skills`（multipart）创建接口；创建成功后**原地**（同一个抽屉）切换成编辑态，用户可以继续加文件、改内容，不需要跳转/关闭再打开
- 保存请求发送完整的 `files` map（不是 diff/patch）：跟 T1.2 后端"整体重新打包覆盖上传"的语义对应，前端不需要维护一份"哪些文件被改动过"的脏检查逻辑
- 删除确认、单文件/目录删除确认都用浏览器原生 `window.confirm()`，没有引入 shadcn 的 dialog 组件：v1 只是需要一个"确定/取消"的阻断确认，原生 API 够用，不为此新增一个组件依赖
- `apiClient.ts` 补了 `put`/`delete`/`postForm` 三个方法；`apiRequest` 原有的"有 body 就默认设 `Content-Type: application/json`"逻辑改成排除 `FormData`——文件上传要让浏览器自己生成带 boundary 的 multipart 头，这是本任务在联调时验证到的必要修正，不是预先设计好的
- 手工验证方式：本地 `pnpm run dev` 起 dev server，用临时装的 Playwright（用完删除，未进仓库，遵循 T0.5 交接记录里定下的规矩）跑了一遍完整闭环：登录 → 新建（模板创建）→ 详情页确认 `SKILL.md` 内容含预期文本 → 加一个 `scripts/run.py` 文件并编辑内容 → 保存确认版本号 v1→v2 → 返回列表确认版本号已更新 → 删除 `SKILL.md` 再保存，确认页面原样展示后端"缺少 SKILL.md"的错误提示且不跳转 → 删除整个 Skill，确认从列表消失

**决策记录（2026-08-30 交互优化追加）**：用户反馈后做了三处改动，取代上面"创建页/编辑页各自独立路由、文件树是扁平列表"的初版设计——旧决策里"创建后跳转到详情/编辑页""扁平列表"两条已不再成立，其余（模板创建、files 整体提交、原生 confirm、apiClient 的 FormData 修正）仍然有效：
  - **新建/编辑不再是独立路由页面，改成侧边抽屉（shadcn `Sheet`）**：新增 `components/skills/SkillEditorSheet.tsx`，`SkillsPage.tsx` 里维护 `sheetOpen`/`editingId` 两个 state 控制抽屉，不再有 `/skills/new`、`/skills/:id` 路由（`SkillCreatePage.tsx`/`SkillDetailPage.tsx` 已删除）。抽屉内部分两个阶段：未创建时是"名称+描述"表单，创建成功后原地切到"文件树+编辑器"视图，这个切换逻辑复用同一个组件而不是新建/编辑各自一个组件，因为两者除了"要不要先有一个创建表单步骤"之外，UI 完全一致
  - **抽屉每次打开都要有干净的状态**（不能沿用上次打开时的残留编辑内容）：没有在 `useEffect` 里手动重置一堆 `useState`（那样会触发 oxlint 的 `set-state-in-effect` 警告，本质也确实是反模式），改用 React 官方推荐的"用 `key` 强制重新挂载"方案——`SkillsPage.tsx` 维护一个 `openSeq` 计数器，每次点新建/编辑就 `+1`，`<SkillEditorSheet key={`${editingId ?? 'create'}-${openSeq}`} .../>`，key 变化即重新挂载，组件内部只需要正常的 `useState` 初始值，不需要额外的重置逻辑
  - **文件树从扁平列表改成真正的嵌套目录树**：新增 `lib/fileTree.ts`（纯函数：`buildFileTree` 把 `{路径: 内容}` 建成嵌套 `dir`/`file` 节点树；`renameFile`/`renameDir`/`deleteFile`/`deleteDir`/`addFile` 是操作这个 flat map 的纯函数）+ `components/skills/SkillFileTree.tsx`（递归渲染，目录可折叠/展开）。目录在数据模型里依然不是独立实体——纯粹是文件路径前缀的推导结果，一个目录底下一个文件都没有就不存在于树里，所以**不提供"新建空文件夹"操作**，只提供"在某个目录下新建文件"（文件名可以带 `/` 隐式建出子目录）
  - **树上的新建/删除/移动**：每一行 hover 后露出操作按钮（文件：重命名/移动、删除；目录：新建文件、重命名/移动、删除）。"重命名/移动"统一实现成编辑该节点的**完整路径**（不只是叶子名）——文件改路径前缀就是移动到别的目录，目录改路径前缀会把它下面所有文件的路径一起替换，这样"移动"不需要额外发明一套 API，复用同一个"改路径"操作即可。另外用原生 HTML5 拖放（`draggable` + `dragstart`/`dragover`/`drop`，没引入拖放库）实现"拖到目标目录即移动"，和"重命名路径"是两条互补的移动方式；根目录本身也是一个可见的伪节点（带"新建文件"按钮和拖放目标），否则没有入口能在根目录下新建文件
  - **编辑器高度溢出改为内部滚动**：`SheetContent` 用 `flex flex-col`，文件树区域和编辑器区域各自套一层 `min-h-0 overflow-y-auto`，让抽屉整体高度锁定在视口内、内容超长时只在各自的滚动容器里滚动，而不是把整个抽屉/页面撑高；`Textarea` 组件默认的 `field-sizing: content`（内容多高就撑多高，shadcn 默认行为）会破坏这个布局，本任务用内联 `style={{ fieldSizing: 'fixed' }}` 显式覆盖（没走 `className`，因为 `tailwind-merge` 不一定认识 `field-sizing-*` 这种较新的 Tailwind v4 工具类，走内联样式更保险，不依赖 class 去重是否生效）
  - 验证方式同样是临时装 Playwright（用完删除）跑自动化：登录 → 点"新建 Skill"确认抽屉打开且 URL 仍停在 `/skills`（不是跳转新路由）→ 创建后抽屉原地切换成编辑态 → 用根目录"+"新建 `docs/readme.md`（验证嵌套目录靠路径里的 `/` 隐式产生）→ 再建一个根级 `notes.md` 并通过派发原生 `DragEvent` 拖进 `docs/` 目录（验证拖拽移动，`docs/notes.md`）→ 对 `docs` 目录执行"重命名/移动"改成 `documentation`（验证目录改名连带移动其下所有文件，`documentation/readme.md`+`documentation/notes.md`）→ 往编辑器里填极长内容，断言 `textarea.scrollHeight > clientHeight` 且 `overflow-y: auto`，同时断言 `SheetContent` 的高度没有超出视口（验证"内部滚动"而不是"撑高整个抽屉"）→ 保存看版本号变化 → 树上删除单个文件 → 按 Escape 关闭抽屉确认 URL 仍是 `/skills` 且列表已刷新 → 重新打开该 Skill 并整体删除

**决策记录（2026-08-30 二次交互优化追加）**：用户看到实际效果后又提了两点：
  - **抽屉宽度改成视口的 85%**：`SheetContent` 基础组件的 `data-[side=right]:sm:max-w-sm` 带了属性选择器，特异性比普通 `sm:max-w-*` 工具类高，之前用 `className="sm:max-w-4xl"` 覆盖其实没生效（截图证实抽屉还是默认的 `max-w-sm` 宽度）；改用内联 `style={{ width: '85vw', maxWidth: '85vw' }}` 强制生效，不再依赖 className 的特异性/合并规则
  - **支持在树上新建目录**（不只是靠文件路径带 `/` 隐式建目录）：目录在数据模型里依然不是独立实体（没有改 T1.2 的后端 schema），新建目录时在 `lib/fileTree.ts` 里新增的 `DIR_PLACEHOLDER_FILE = '.gitkeep'` 常量指定的占位文件会被放进这个新目录（如新建 `assets` 目录实际创建的是 `assets/.gitkeep`，空内容），这样目录在保存前后都真实存在于 `files` map 里，不会因为"目录下没有文件"而在下次渲染时消失；`SkillFileTree.tsx` 里 `startCreate`/`commitCreate` 加了 `kind: 'file' | 'dir'` 参数区分两种新建，UI 上根目录和每个目录节点的 hover 操作里"新建文件"（`FilePlus`）旁边加了"新建目录"（`FolderPlus`）按钮。用户后续如果往这个目录里加了真正的文件，`.gitkeep` 依然会留在那里（v1 没有做"目录不再为空时自动清理占位文件"这个便利功能，用户需要时可以手动在树上删除它）
  - 验证方式：Playwright 跑了"新建 Skill → 断言抽屉宽度是视口宽度的 85%（`sheetWidth / viewportWidth` 落在 0.8~0.9 之间）→ 根目录新建目录 `assets`（断言树上出现 `assets` 和它下面的 `.gitkeep`）→ 在 `assets` 下再新建嵌套目录 `icons` → 保存 → 关闭抽屉重新打开（真正从后端 `GET /skills/{id}` 拉一遍，不是看本地未提交的临时状态）→ 断言 `assets`/`icons` 两层空目录都还在 → 删除测试 Skill 收尾"的完整链路

---

### T1.4 MCP Service（CRUD API）
**目标**：实现 MCP Server 配置的增删改查接口。

**关键实现决策**：
- MCP 配置结构对齐 Claude Agent SDK 的 `mcpServers` 选项所需字段，存 Postgres（不涉及 MinIO，配置数据量小）
- 敏感字段（如鉴权密钥）需要考虑是否加密存储，本任务落地时明确处理方式
- 提供一个"测试连接"能力（可选，视 MCP 类型是否方便探活，若实现复杂可先跳过并记录到待细化项）

**验收标准**：
- 能创建、编辑、删除 MCP Server 配置，字段校验完整（缺必填字段时拒绝）
- 敏感字段在列表/详情接口返回时不会明文暴露（如做脱敏展示）

**决策记录**（实现时落地）：
- **配置结构**：对齐 SDK `mcpServers` 里常见的三种 server 类型，用 Pydantic 判别联合（`type` 字段区分）落地在 `app/modules/mcp/schemas.py`：`stdio`（`command`/`args`/`env`）、`sse`（`url`/`headers`）、`http`（`url`/`headers`）。必填字段（如 `command`、`url`）缺失时 Pydantic 直接 422，不需要手写校验逻辑
- **敏感字段加密方式**：不是"挑几个字段名加密"，而是把整份 `config` 当成一个整体，用 Fernet（对称加密，`cryptography` 库）加密后存成 `mcp_servers.config_encrypted`（Text 列，替换掉原来的 `config` JSONB 列）；密钥来自新增配置项 `MCP_ENCRYPTION_KEY`（`.env`，Fernet urlsafe base64 格式）。选整体加密而非"只加密 env/headers 的 value"是因为后者需要在存储层就感知 config 的内部结构（type 判别），加重了存储层复杂度，而整体加密+应用层脱敏可以让存储层完全不关心 config 内部长什么样
- **脱敏展示**：只对约定的两个 dict 字段（`env`、`headers`）的 **value** 打码（固定占位符 `"********"`，`app/modules/mcp/masking.py::mask_config`），**key 不打码**——这样用户在编辑表单里能看到"这个 stdio server 配置了哪些环境变量名"而不需要盲改，只有要更新某个 value 时才需要重新输入。`command`/`args`/`url` 等非密钥字段不脱敏，直接明文返回（这些字段本身不是密钥）
- **编辑时的"未修改字段保留原值"语义**：`PUT /mcp/{id}` 要求整体提交完整 `config`（跟 Skill 保存整体覆盖的模式一致），如果某个 env/header 的 value 原样是占位符 `"********"`（说明用户没有重新输入），后端 `merge_secret_fields`（`masking.py`）会把它替换回解密后的旧值再重新加密存储；如果 value 不是占位符（用户输入了新内容），则视为真正的新值直接采用。这个逻辑跟 T1.5 前端"表单展示脱敏值，重新输入才更新"的交互直接对应
- **不做真实的"测试连接"能力**：TASKS 原文允许"若实现复杂可先跳过"——stdio 类型需要真的起子进程握手、sse/http 需要实际网络请求且要正确处理各种鉴权方式，复杂度和收益不成比例，v1 跳过，留作后续需要时再加
- **status 字段**：延用 T1.1 建表时就有的 `status`（字符串，默认 `"active"`），`PUT` 更新时可以一并传，没有做成独立的"启用/禁用"专用接口，因为改状态和改配置在前端表单里本来就是同一次提交
- 迁移：`4a51fbaabd44_mcp_server_encrypted_config.py`（`autogenerate` 生成，`mcp_servers` 表加 `config_encrypted` 列、删掉 `config` 列）。落地时表里还没有真实数据（T1.4 之前没人写过 MCP 配置），所以 `config_encrypted` 直接 `nullable=False` 且没有做数据回填分支，跟 T1.2 那种"已有数据需要回填"的迁移不是一回事
- 验证方式：`uv run pytest`（新增 `tests/test_mcp.py` 4 个用例，覆盖鉴权拦截、缺字段 422、stdio 全生命周期含 env 打码/回填/真正更新、http 类型 headers 脱敏 + 重名 409）；另外 `docker compose build/up backend-api` 重建镜像后用 `curl` 走了一遍真实容器的创建 → 列表 → 详情 → 删除，确认 `env.API_KEY` 在所有返回里都是 `********`

---

### T1.5 MCP 管理前端页面
**目标**：实现 MCP Server 配置的可视化管理界面。

**关键实现决策**：
- 列表页 + 创建/编辑表单，字段对应 T1.4 的配置结构
- 敏感字段在表单里编辑时按脱敏展示，重新输入才更新

**验收标准**：
- 能在页面上完成 MCP 配置的新建、编辑、删除，且敏感字段不会明文回显

**决策记录**（实现时落地）：
- **单表单，不做两阶段流程**：跟 T1.3 Skill 的"创建后原地切编辑态"不一样，MCP 配置没有文件树那种复杂度，新建/编辑复用同一个表单组件（`components/mcp/McpEditorSheet.tsx`），字段随用户选的 `type`（stdio/sse/http）联动显示——不需要先建后编的两阶段设计
- **类型/状态选择器不引入新 shadcn 组件**：只有三个固定的 type 选项和两个固定的 status 选项，用一组 `Button`（`variant` 在选中态是 `default`、非选中态是 `outline`）做成简易分段控件，没有为此新增 Select/RadioGroup 组件依赖，跟 T1.3"能用原生能力就不引入新组件"的一贯风格一致
- **env/headers 用通用的 key-value 编辑器**：新增 `components/mcp/KeyValueEditor.tsx`（纯 UI，一行一个 key/value 输入框 + 删除按钮 + 底部"添加"按钮），配套的 `pairsToRecord`/`recordToPairs` 两个纯函数放进 `lib/keyValuePairs.ts`（而不是和组件放一个文件），避免触发 oxlint 的 `only-export-components` 警告——这两个字段在 stdio（env）和 sse/http（headers）里结构一样，共用同一个编辑器组件
- **脱敏字段的编辑语义完全交给后端**：前端不需要专门判断"这个 value 是不是打码占位符"——`GET /mcp/{id}` 返回的 env/headers value 本来就是打码值 `"********"`（`lib/mcpApi.ts::MASK_SENTINEL`，需要和后端 `masking.py` 的占位符保持一致），用户不碰这一行就原样提交回去，T1.4 后端的 `merge_secret_fields` 会自动识别并保留旧值；用户重新输入了内容，新值就会被当成真正的更新——前端的 `KeyValueEditor` 对打码值和真实值一视同仁，不做任何特殊渲染（不用 `type="password"`，因为脱敏值本身已经是打码占位符，没必要再遮一层）
- **args 用"每行一个"的多行文本框而不是动态列表**：`args` 是字符串数组但一般只有几个短参数，用 `Textarea`（一行一个）比再造一个"动态增删的字符串列表"组件更省事，提交时按行 split + trim + 过滤空行
- **列表页不展示 type**：`GET /mcp` 列表接口本身不返回 `config`（T1.4 的 `MCPServerListItem` 只有 id/name/status/updated_at，出于跟 Skill 列表一致的"列表页只要轻量元信息"考虑），所以列表表格只展示名称/状态/更新时间，type 只在点开编辑抽屉后才可见，这不是本任务的遗漏而是复用了 T1.4 已经定好的接口形状
- 验证方式：`pnpm run build`/`pnpm run lint` 通过（唯一的 warning 是 shadcn 生成文件自带的已知 warning）；本地 `pnpm run dev` + 已在跑的 `backend-api` 容器，用临时装的 Playwright（用完删除）跑了完整闭环：创建 stdio 类型（含一个 env 变量）→ 重新打开确认 env value 显示为打码占位符 → 只改 args 保存（不碰 env）→ 重新打开改 env 为新值保存 → 创建 http 类型（含 headers）→ 不填必填的 url 验证浏览器原生 `required` 校验拦截提交 → 补填后创建成功 → 用重复名称验证 409 冲突提示正确显示 → 删除两个测试数据清理

---

## Phase 2：Agent 构建器与 Workspace 初始化

### T2.1 Agent Service
**目标**：实现 Agent 的创建/编辑接口，支持绑定 skills、MCP servers、一个或多个代码仓库、权限模式。

**关键实现决策**：
- 创建 Agent 时只做元数据落库和唯一 workspace 标识分配，实际的 Workspace 初始化（clone、打包快照）交给 T2.3 异步处理，Agent Service 只负责触发
- 绑定的仓库列表需要记录鉴权方式（如仓库需要凭证访问），凭证的存储方式与 T1.4 的敏感字段处理保持一致
- 编辑 Agent 绑定关系（增删 skill/MCP/仓库）本任务先支持基础的整体更新，暂不考虑绑定变更后对进行中对话的影响（对应 PRD 里"变更只影响后续新对话"的既定策略）

**验收标准**：
- 能创建 Agent 并成功绑定已存在的 skills/MCP/仓库，绑定关系能正确落库并可查询回显
- 创建请求缺必填字段或绑定了不存在的 skill/MCP 时能明确拒绝
- 编辑保存后再次查询，绑定关系与最新提交一致

---

### T2.2 Agent Builder 前端页面
**目标**：实现 Agent 的可视化创建/编辑界面。

**关键实现决策**：
- 表单支持从已有 Skill/MCP 列表里勾选绑定，仓库地址支持添加多个
- 创建后跳转到 Agent 详情页，展示当前 workspace 初始化状态（对应 T2.4）

**验收标准**：
- 能在页面上完成"选 skills → 选 MCP → 填仓库地址 → 提交创建"的完整流程
- 创建后能在详情页看到该 Agent 的绑定信息和初始化状态

---

### T2.3 Workspace 初始化任务
**目标**：实现 Agent 创建后台任务：clone 绑定仓库、打包仓库快照上传 MinIO，并初始化空的输出快照。

**关键实现决策**：
- 该任务作为 Runner 的 Celery 后台任务实现（对应 TECH_DESIGN 4.1），逐个 clone 绑定仓库到临时目录，按约定目录结构打包为仓库快照上传 MinIO
- 输出快照初始化为一个空的、版本号为初始值的对象，与仓库快照分开存储（对应 workspace 两段式模型）
- clone 失败（如地址不可达、凭证错误）时整体任务标记失败，不做部分成功，Agent 状态回写为失败并保留可重试的入口

**验收标准**：
- 创建一个绑定了可访问仓库的 Agent，任务完成后能在 MinIO 里看到对应的仓库快照和空输出快照对象
- 绑定了不可访问仓库的 Agent，任务失败后 Agent 状态正确反映失败，且提供的重试能重新触发同样的初始化流程
- 绑定多个仓库时，快照包含所有仓库各自独立的目录

---

### T2.4 Agent 状态管理与展示
**目标**：让 Agent 的状态（初始化中/就绪/失败）在后端准确流转，并在前端可见、可操作（重试）。

**关键实现决策**：
- 状态流转：创建后进入"初始化中" → T2.3 任务成功后转"就绪"、失败后转"失败"；"失败"状态下提供重试操作重新触发 T2.3
- 前端轮询或其他方式获取最新状态（本任务不要求实时推送，简单轮询即可，与后续对话场景的实时流式是两回事）

**验收标准**：
- Agent 详情页能看到当前状态，状态变化后刷新/轮询能看到最新结果
- "失败"状态下点击重试，能重新触发初始化并观察到状态回到"初始化中"直至最终结果

---

## Phase 3：仓库定时刷新

### T3.1 Scheduler 服务（Celery beat）
**目标**：搭好定时任务调度框架，为仓库刷新任务提供触发机制。

**关键实现决策**：
- 用 Celery beat（或等价机制）作为定时触发器，扫描所有绑定了仓库且状态为"就绪"的 Agent，按各自配置的刷新周期（默认 30 分钟，可配置）派发刷新任务
- 调度器本身只负责"判断该不该触发"和"派发任务"，具体刷新逻辑在 T3.2 的 Runner 任务里实现

**验收标准**：
- 服务启动后能按 Agent 各自的刷新周期正确触发任务派发，不同周期的 Agent 互不影响
- 修改某个 Agent 的刷新周期配置后，下次调度能按新周期生效

---

### T3.2 仓库刷新任务
**目标**：实现仓库快照的定时刷新逻辑：拉取最新代码、打包、更新 MinIO 仓库快照。

**关键实现决策**：
- 刷新独立于对话执行的互斥锁进行（对应 TECH_DESIGN 4.3 的决策：仓库只读，不存在本地分叉，不需要等待锁空闲）
- 刷新只更新仓库快照部分，不触碰输出快照，两者版本独立
- 刷新失败（如仓库地址失效）时保留上一次成功的快照不变，并记录失败信息，不影响 Agent 当前可用性

**验收标准**：
- 到达刷新周期后，MinIO 里的仓库快照更新时间和内容确实反映了仓库最新提交
- 模拟仓库地址失效的情况，刷新失败但不影响已有快照可用、Agent 仍可正常发起对话
- 一次对话执行期间触发刷新，不会相互阻塞或报错（验证读写不冲突的设计）

---

## Phase 4：对话执行核心链路

### T4.1 SessionStore Adapter
**目标**：实现 Claude Agent SDK 的 SessionStore 接口适配，把 session 数据落到 Postgres。

**关键实现决策**：
- 严格按 SDK 定义的 SessionStore 接口实现，不自行解析/依赖 SDK 本地 session 文件格式
- 验证跨主机 resume 能力：在一台 Runner 实例创建的 session，能在另一台 Runner 实例上正常 resume

**验收标准**：
- 新建对话产生的 session 数据能正确写入 Postgres，字段可查询
- 换一个 Runner 副本用同一个 session_id 发起 resume，能正确续接此前的对话上下文

---

### T4.2 Agent 互斥锁（Redis）
**目标**：实现基于 Redis 的 Agent 级互斥锁，保证同一 Agent 同一时间只有一个活跃对话执行。

**关键实现决策**：
- 锁的粒度是 Agent 级（不是 Conversation 级），锁的持有时间覆盖一次完整的对话执行（从开始到执行完成或异常退出兜底保存完成）
- 需要处理锁的自动过期/续期机制，避免持锁进程异常崩溃导致锁永久占用（死锁风险）
- 获取锁失败（Agent 正忙）时给调用方明确、可判断的反馈，而不是模糊报错

**验收标准**：
- 对同一 Agent 并发发起两次对话请求，第二个请求能明确得知"Agent 正忙"而不是排队卡住或报未知错误
- 模拟持锁进程异常崩溃（不主动释放锁），验证锁能在过期时间后自动释放，不会永久卡死该 Agent

---

### T4.3 Agent Runner 流式执行接口
**目标**：实现 Runner 对外暴露的流式执行接口（HTTP chunked/SSE），处理一次完整的对话执行请求。

**关键实现决策**：
- 接口输入包含 agent 配置（skills/MCP/permissionMode）、cwd 所需的 workspace 信息、resume 的 session_id（若续接）
- 执行步骤严格对应 TECH_DESIGN 4.4：拉取仓库快照+输出快照到本地临时磁盘合并为工作目录 → 组装 SDK 参数（含 T4.1 的 sessionStore）→ 调用 SDK 执行 → 边执行边把消息通过这条连接实时推送 → 执行完成后把输出目录变更同步回 MinIO
- 本地已有热缓存且版本未变时跳过重新拉取，减少不必要的 IO

**验收标准**：
- 发起一次新对话，能收到实时流式返回的消息（不是等全部执行完才一次性返回）
- 对同一 Agent 发起续接对话，Runner 能正确 resume 并延续此前上下文
- 执行完成后 MinIO 里的输出快照确实反映了本次对话产生的文件变更
- 本地已有该 Agent 的热缓存时，验证确实跳过了重复拉取（可通过耗时或日志验证）

---

### T4.4 异常退出兜底保存
**目标**：Runner 进程异常终止前，强制把当前输出目录同步回 MinIO，降低数据丢失窗口。

**关键实现决策**：
- 注册可捕获信号（如 SIGTERM）的优雅关闭钩子，收到信号后暂停正常流程、强制执行一次输出目录打包上传，再释放互斥锁退出
- 明确记录该机制覆盖不到 SIGKILL、断电等场景（对应 TECH_DESIGN 4.5 的局限性说明），不在本任务里试图解决这类场景

**验收标准**：
- 在对话执行过程中人为发送可捕获的终止信号，验证 MinIO 输出快照被更新为终止前的最新状态，且 Agent 互斥锁被正确释放（不会卡死后续对话）
- 验证正常执行完成路径和异常退出路径不会重复触发两次快照上传（幂等或互斥处理得当）

---

### T4.5 Conversation Service
**目标**：实现对话请求的入口编排：维护会话映射、发起流式调用、把结果转发给前端。

**关键实现决策**：
- 维护 `conversation_id ↔ (agent_id, session_id)` 映射，新对话在首次执行成功后记录 session_id
- 发起对话流程：加互斥锁（T4.2）→ 直连调用 Runner 流式接口（T4.3，经 Compose DNS 负载均衡到任意副本）→ 收到的流式消息通过 SSE 转发给前端
- 明确"Agent 正忙"（互斥锁获取失败）时的接口层反馈方式，前端能据此提示用户

**验收标准**：
- 前端发起对话请求后，能通过 SSE 收到与 Runner 执行同步的实时流式内容
- 刷新页面或重新连接后，能基于已有 conversation_id 正确续接同一个 session
- 对同一 Agent 并发发起两次对话，一个正常执行，另一个收到清晰的"Agent 正忙"反馈

---

## Phase 5：对话页面与对外 API

### T5.1 对话页面前端
**目标**：实现对话的可视化界面：先选 Agent，再进入该 Agent 的对话界面。

**关键实现决策**：
- 入口先展示 Agent 列表（仅展示状态为"就绪"的可对话，或对非就绪状态做提示禁用），选中后进入对话界面
- 对话界面通过 SSE 接收流式内容并实时渲染，支持发起新对话和续接历史对话
- "Agent 正忙"等异常状态需要有明确的前端提示，而不是页面卡死无反馈

**验收标准**：
- 能完整走通"选择 Agent → 发起对话 → 实时看到流式回复 → 刷新页面后续接同一对话"的路径
- Agent 处于非就绪或正忙状态时，页面有清晰提示且不会误触发请求

---

### T5.2 对外 API
**目标**：提供与对话页面能力对等的程序化 API，供外部系统调用。

**关键实现决策**：
- 复用 Conversation Service 的核心编排逻辑，只是入口从前端页面换成 API 调用方，鉴权同样走 T0.5 的机制
- 流式返回方式与前端一致（SSE），文档化清楚调用方如何消费流式响应

**验收标准**：
- 用非浏览器的 HTTP 客户端（如脚本）能完整走通"发起对话 → 收到流式响应 → 续接对话"的路径，效果与页面操作一致
- 未携带有效鉴权信息的调用被正确拒绝

---

## Phase 6：收尾与运维能力

### T6.1 Runner 本地缓存清理任务
**目标**：实现本地临时磁盘的清理策略：某 Agent 连续 15 天无对话/刷新活动时清理其本地缓存。

**关键实现决策**：
- 作为后台定时任务实现，判断依据是本地缓存最后一次被访问/更新的时间，而不是 MinIO 上的数据（MinIO 数据不受影响，只清本地）
- 清理只影响本地磁盘副本，下次该 Agent 被使用时能从 MinIO 正常重新拉取，不影响功能正确性

**验收标准**：
- 模拟某 Agent 本地缓存超过 15 天未活动，任务运行后对应本地目录被清理
- 清理后再次对该 Agent 发起对话，功能正常（自动重新从 MinIO 拉取），只是首次耗时略增

---

### T6.2 端到端联调与验收
**目标**：完整走通一遍从零开始的产品主路径，验证各任务集成后系统整体可用。

**关键实现决策**：
- 覆盖路径：注册/登录 → 创建 Skill → 创建 MCP 配置 → 创建 Agent（绑定 skill/MCP/仓库）→ 等待 workspace 就绪 → 发起对话并观察流式返回 → 关闭页面重新打开续接对话 → 验证仓库定时刷新生效 → 验证 Agent 互斥（对同一 Agent 并发发起对话）
- 记录联调中发现的问题，若涉及架构决策调整，回写 PRD/TECH_DESIGN 后再修复，不在代码里悄悄绕过设计

**验收标准**：
- 上述完整路径全部走通，无需人工介入修复
- 联调中发现的所有问题都有明确归属（是哪个任务的实现缺陷）并已闭环
