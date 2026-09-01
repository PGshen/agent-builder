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

**决策记录**（实现时落地）：
- **触发 Workspace 初始化的方式（T2.3 尚未实现，先约定契约）**：backend-api 新增 `celery[redis]==5.4.0` 依赖，只当 Celery **生产者**用（`app/modules/agents/tasks.py::trigger_workspace_init`，`Celery(...).send_task(...)`，不 `include` 任何任务模块、不配置 result backend），创建 Agent 成功后向名为 **`"workspace.init"`**、参数 `args=[agent_id]`（str）的任务发一条消息到 broker（与 agent-runner 共用同一个 Redis、同一个 `CELERY_BROKER_DB`）。T2.3 落地时，Runner 侧必须注册一个同名（`"workspace.init"`）、接受这个参数签名的任务去消费。发送失败（如 broker 不可达）只记警告日志、不抛异常，不阻塞 Agent 元数据创建——对应 TECH_DESIGN 4.1"Agent Service 只负责触发"的解耦设计。T2.3 上线前，这些消息会在 broker 队列里排队等待，没有副作用
- **仓库凭证加密**：与 T1.4 保持相同方式（Fernet 对称加密），但**没有复用** `MCP_ENCRYPTION_KEY`——新增独立配置项 `AGENT_REPO_ENCRYPTION_KEY`（`app/modules/agents/crypto.py`），原因是这是两个不同模块各自拥有的加密字段，各自独立密钥更符合最小权限原则（轮换一个不影响另一个），产品语义上也没有"必须共用一把钥匙"的要求
- **仓库凭证脱敏方式**：与 T1.4 的 `env`/`headers` 脱敏思路一致但简化——`auth_credential` 是单个字符串字段（不是 key-value dict），所以 `app/modules/agents/masking.py` 只有 `mask_credential`（有值就打码成 `"********"`，`auth_type="none"` 或未设置时返回 `None`）和 `resolve_credential_encrypted`（提交值是占位符时沿用旧密文，否则重新加密）两个函数，没有 T1.4 `merge_secret_fields` 那种按 key 遍历的逻辑
- **编辑仓库列表如何保留凭证**：`AgentRepositoryInput` 增加可选 `id` 字段——编辑时前端把已有仓库原样带上 `id`（凭证字段仍是打码占位符），后端按 `id` 匹配到编辑前的那一行仓库来源密文；不带 `id`（或 `id` 对不上任何现有行）视为新增仓库，此时如果凭证仍是占位符会被当成"未提供凭证"（`auth_credential` 落 `NULL`），这是新增仓库场景下的既有限制，不是遗漏（占位符本来就只有 GET 响应才会产生，新增仓库不可能合法地提交占位符）
- **绑定关系更新策略**：`PUT /agents/{id}` 的 skills/MCP/仓库三类绑定都是"先整体删再整体插入"（不做差量 diff），跟 T1.2/T1.4 的"整体覆盖"风格一致；仓库这一类因为要保留凭证，在删除前先把编辑前的行按 `id` 建好索引供匹配使用（见上一条）
- **PUT 会在仓库绑定实际发生变化时自动重新触发 workspace 初始化**（2026-08-30 修正，原决策见下）：`update_agent` 在删除重建三类绑定前后，分别按 `position` 顺序把仓库列表转成 `(url, branch, auth_type, auth_credential密文)` 元组序列做比较，序列不相等（新增/删除/改地址/改分支/改鉴权方式/真正轮换了凭证/调整了顺序）才判定为"仓库变了"；只有这种情况才把 `Agent.status` 重置为 `initializing`（清空 `status_message`）并调用 `tasks.trigger_workspace_init`，仅编辑名称/描述/权限模式/skills/MCP 绑定不会触发重新初始化（这些跟仓库快照无关，重新 clone 是浪费）。~~原决策~~：最初认为"编辑后是否自动重新初始化"留给 T2.4 或更后面的任务决定，T2.4 也确实只做了"失败状态下手动重试"；但实际使用中发现一个真实 bug 场景——创建 Agent 时不绑仓库（或绑的仓库集合还没确定）触发一次初始化产生空快照，随后编辑加上仓库，Agent 状态还是当初那次的 `ready`，导致 MinIO 里的仓库快照永久停留在编辑前的状态且没有任何入口能刷新（`retry_workspace_init` 只在 `status == "failed"` 时可调用，编辑后状态是 `ready` 不满足），必须补上这个自动触发逻辑
- **补充了 TASKS 原文没写的 `DELETE /agents/{id}`**：为了和已有的 Skill/MCP 管理页保持同样的完整 CRUD 形状（T2.2 大概率需要"删除 Agent"这个操作），补了一个直接删 `agents` 行的接口；子表（`agent_skills`/`agent_mcp_servers`/`agent_repositories`/`workspace_snapshots`）都在 T1.1 建表时定义了 `ondelete="CASCADE"`，数据库层面自动级联删除，不需要应用层手动清理。**已知遗留**：T2.3 落地后 Agent 会在 MinIO 里产生仓库快照/输出快照对象，那时候的 Agent 删除需要同步清理这些 MinIO 对象（参考 Skill 删除的做法），本任务时 MinIO 里还没有东西，暂不需要处理
- **列表接口返回绑定数量而非明细**：`GET /agents` 的 `AgentListItem` 只带 `skill_count`/`mcp_server_count`/`repository_count`（用 `GROUP BY` 聚合查询算，不是 N+1 逐个查），完整的绑定明细（skill/MCP 名称、仓库详情）只有 `GET /agents/{id}` 详情接口才返回，跟 Skill/MCP 列表页"只要轻量元信息"的一贯风格一致
- **仓库鉴权方式的取值**：按 TASKS 原文"具体取值在 T2.1 落地时约束"，定为 `Literal["none", "token", "ssh_key"]`（`AgentRepositoryInput.auth_type`）
- 验证方式：`uv run pytest`（新增 `tests/test_agents.py` 5 个用例，覆盖鉴权拦截、缺字段 422、绑定不存在的 skill/MCP 400、完整生命周期含仓库凭证打码/占位符回填/真正轮换 + 用后门方式解密验证密文、重名 409）；`docker compose build/up backend-api` 重建镜像后用 `curl` 走了一遍真实容器的登录 → 创建 → 列表 → 删除；用 `redis-cli` 确认真实 Celery 消息确实进了 broker 队列（`LLEN celery`），验证 `trigger_workspace_init` 端到端可用，随后清空了这些仅供验证用的队列消息，避免将来 T2.3 worker 上线后消费到测试脏数据

---

### T2.2 Agent Builder 前端页面
**目标**：实现 Agent 的可视化创建/编辑界面。

**关键实现决策**：
- 表单支持从已有 Skill/MCP 列表里勾选绑定（可过滤的穿梭器组件，2026-08-30 交互优化后的决策），仓库地址支持添加多个
- 新建/编辑用侧边抽屉（Sheet）承载，不做独立路由页面——创建成功后抽屉原地切换成编辑态，展示当前 workspace 初始化状态（对应 T2.4），与 T1.3 Skill 管理的交互模式保持一致（2026-08-30 交互优化后的决策，见下方决策记录）

**验收标准**：
- 能在页面上完成"选 skills → 选 MCP → 填仓库地址 → 提交创建"的完整流程
- 创建后能看到该 Agent 的绑定信息和初始化状态

**决策记录**（实现时落地）：
- **不用抽屉，用独立路由页面**：与 T1.3/T1.5 的 Sheet 模式不同，TASKS 原文明确要求"创建后跳转到 Agent 详情页"，因此拆成四个路由——`/agents`（列表，`AgentsPage.tsx`）、`/agents/new`（创建，`AgentFormPage.tsx`）、`/agents/:id`（详情，`AgentDetailPage.tsx`）、`/agents/:id/edit`（编辑，同样是 `AgentFormPage.tsx`）；创建/编辑复用同一个表单组件，用 `useParams().id` 是否存在区分模式（跟 McpEditorSheet 单表单复用的思路一致，只是载体从 Sheet 换成路由页面）
- **`permissionMode` 的产品层可配置粒度**：这是 TECH_DESIGN 8 节遗留的"待确认"项，本任务落地时必须决定。选择直接暴露 Claude Agent SDK 原生的四个取值（`default`/`acceptEdits`/`bypassPermissions`/`plan`），不做额外的产品层封装/简化——v1 用户就是需要精确控制 SDK 行为的开发者/管理员，原样透传语义最直接、后续 T4.3 组装 SDK 参数时也不需要做映射转换。选择器沿用 McpEditorSheet 里"几个固定选项用一组 Button 做分段控件"的既有风格，不新增 shadcn 组件
- **仓库鉴权凭证的表单交互**：`components/agents/RepositoryListEditor.tsx` 里 `auth_type` 用新增的 shadcn `select` 组件（不是分段 Button——取值语义上更接近"下拉选择一种模式"而不是"来回切换的少数几个选项"，且要跟每行内的凭证输入框在有限宽度里并排布局，Select 比一排 Button 更紧凑）；`auth_credential` 编辑时原样显示后端返回的打码占位符 `********`（不特殊处理，未修改就原样提交回去，后端 `resolve_credential_encrypted` 自动识别并保留旧值，交互逻辑与 T1.5 MCP 表单的 env/headers 完全一致）；新增仓库行、或提交空 URL 的行会在提交前被过滤掉（用户加了行没填写就直接点保存的场景），不强行报错阻塞
- **新增 shadcn 组件**：`checkbox`（skills/MCP 多选绑定列表）与 `select`（仓库鉴权方式），`pnpm dlx shadcn@latest add checkbox select` 生成，风格与已有组件一致（用 `radix-ui` 统一包，不是逐包安装 `@radix-ui/react-*`）
- **详情页状态展示只做手动刷新，不做自动轮询/失败重试**：TASKS 原文把"前端轮询或其他方式获取最新状态"和"失败状态下提供重试"明确留给 T2.4；本任务在 `AgentDetailPage.tsx` 只放一个"刷新状态"按钮（手动重新拉取 `GET /agents/{id}`）满足本任务验收标准"创建后能在详情页看到初始化状态"，失败状态目前只展示 `status_message`，还没有重试按钮，留给 T2.4 补上
- **列表页新增"绑定"列**：复用 `AgentListItem` 已有的 `skill_count`/`mcp_server_count`/`repository_count`，一行文字展示三个计数（跟 T2.1 后端"列表只返回计数不返回明细"的设计对应），完整绑定明细只在详情页展示
- 验证方式：`pnpm run build`/`pnpm run lint` 通过；本地 `pnpm run dev` + 已在跑的 `backend-api` 容器，用临时装的 Playwright（用完删除，遵循既有规矩）跑了两条链路——① 创建 Agent（填名称、切 `acceptEdits`、改刷新周期、加一个 token 鉴权仓库并填凭证）→ 创建后确认跳转到详情页且状态/权限模式/仓库信息都正确显示 → 编辑页确认凭证字段回显打码占位符 → 只改分支保存 → 详情页确认分支已更新 → 点"刷新状态" → 列表页确认能看到 → 删除清理；② 用 curl 直接建一个临时 MCP Server → 创建 Agent 时勾选它 → 详情页确认"绑定 MCP Servers（1）"且名称正确显示 → 删除 Agent 和临时 MCP Server 清理。两条链路全程浏览器控制台无报错

**决策记录（2026-08-30 交互优化追加）**：用户反馈后做了三处改动，取代上面初版"独立路由页面、SDK 权限模式分段按钮、无能力描述字段"的设计——旧决策里"不用抽屉用独立路由页面"这一条已不再成立，其余（`permissionMode` 直接暴露 SDK 四个取值、仓库鉴权凭证的打码占位符交互、新增 shadcn 组件的做法）仍然有效：
  - **创建/编辑改回侧边抽屉（Sheet），撤销"独立路由页面"的决策**：删除 `AgentFormPage.tsx`/`AgentDetailPage.tsx` 和 `/agents/new`、`/agents/:id`、`/agents/:id/edit` 三条路由，新增 `components/agents/AgentEditorSheet.tsx`，`App.tsx` 恢复成只有 `/agents` 一条路由（跟 Skill/MCP 一致）。用户明确要求"和 skill 管理一样"，本任务最初因为 TASKS 原文写"创建后跳转到 Agent 详情页"而选了路由方案，这次改动说明"跳转到详情页"这个字面要求本身要让位于"跟其它模块交互一致"的更高优先级——**满足"创建后能看到初始化状态"这条验收标准的方式，不是必须靠路由跳转，抽屉原地切换同样成立**。具体做法完全照搬 `SkillEditorSheet.tsx` 的模式：组件内部维护 `workingId`（初始值等于 props 传入的 `agentId`，创建成功后 `setWorkingId(result.data.id)`），标题栏在 `workingId` 非空时显示状态 Badge + "刷新状态"按钮，创建/保存后都不关闭抽屉（只重置 `saveMessage` 提示"已创建"/"已保存"），用户主动点右上角关闭按钮或按 Escape 才关闭；抽屉每次打开仍然靠 `AgentsPage.tsx` 里 `key={editingId-openSeq}` 强制整体重新挂载拿到干净状态（同 Skill/MCP 列表页模式）
  - **新增"能力描述"字段**：这是本任务范围外的新需求，牵动了后端——`agents` 表加 `description`（Text，nullable）列（Alembic 迁移 `dbf10ea831f1_agent_description.py`，`uv run alembic revision --autogenerate` 生成，本地用 `uv run alembic upgrade head` + 重建 `backend-api` 镜像应用），`AgentCreateRequest`/`AgentListItem`/`AgentDetail` 三个 schema 加字段，`create_agent`/`update_agent` service 函数签名加 `description` 参数。列表页也展示描述（截断成一行），跟 Skill/MCP 列表"只要轻量元信息"不完全一样——因为能力描述本身就是给管理员快速识别一堆 Agent 用途的关键信息，值得在列表页就露出，不是要点开才能看到的细节
  - **skills/MCP 绑定改成可过滤的穿梭器（Transfer List）**，取代原来的纯 Checkbox 竖直列表：新增 `components/agents/TransferList.tsx`（v1 自研，shadcn 没有对应组件），左侧是全量列表（搜索框 + "全选"复选框 + 当前筛选命中的项数），右侧是已选列表（"清除"按钮清空全部 + 已选计数，每项 hover 出现 × 单独移除）。选择"自研而非引入第三方穿梭器库"的原因：需求本身不复杂（单一层级、无拖拽排序要求），且要跟项目现有 Tailwind + shadcn 基础组件（`Checkbox`/`Input`）风格保持一致，引入专门的 Transfer 组件库反而要处理样式覆盖问题；这个组件跟 Skill/MCP 无关的选择集合都能复用（纯 `{id, label}[]` + 受控 `value`/`onChange`），不绑定 Agent 模块的具体类型
  - 验证方式：本地 `pnpm run build`/`pnpm run lint` 通过；后端改动 `uv run pytest`（18 个用例全过，`test_agents.py` 原有用例因为 `description` 是可选字段未受影响）+ `docker compose build/up backend-api` 重建镜像应用迁移；前端用临时装的 Playwright（用完删除）跑了一条完整链路：点"新建 Agent"确认抽屉打开且 URL 仍是 `/agents`（不是 `/agents/new`）→ 填名称+能力描述 → 在 MCP 穿梭器里搜索关键字过滤出目标项并勾选，确认右侧"已选 1 项"→ 提交创建 → 确认抽屉原地切换成编辑态（标题变成 Agent 名称、出现状态 Badge、"刷新状态"/"删除 Agent"按钮），能力描述和 MCP 绑定都保留 → 按 Escape 关闭 → 列表页确认新 Agent 出现且描述摘要正确显示、绑定计数显示"1 MCP"→ 重新点开确认穿梭器里 MCP 项仍是已选状态、能力描述字段正确回显 → 删除清理。全程浏览器控制台无报错

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

**决策记录**（实现时落地）：
- **Runner 侧数据库访问方式**：不引入 SQLAlchemy ORM（那是 backend-api 的模型/迁移职责，两边各自维护一套 ORM 模型有同步负担），沿用 T0.3 `app/server/health.py` 已经建立的 `asyncpg` 原生连接 + 手写 SQL 模式（新增 `agent-runner/app/workspace/db.py`），字段名与 backend-api `app/modules/agents/models.py` 表结构保持一致；Celery 任务本身是同步函数，内部用 `asyncio.run()` 跑一段 async 逻辑（DB/MinIO 都是 async 接口），不引入 Celery 的 asyncio 任务支持
- **仓库凭证解密**：Runner 新增 `agent_repo_encryption_key` 配置项（`agent-runner/app/config.py`），复用 backend-api 已有的同名环境变量 `AGENT_REPO_ENCRYPTION_KEY`（两侧 `env_file` 都指向同一个 `.env`，不需要额外配置同步机制），`agent-runner/app/workspace/crypto.py::decrypt_credential` 只做解密（加密仍然只发生在 backend-api 保存仓库配置时）；agent-runner 新增 `cryptography==44.0.0` 依赖
- **auth_type 三种取值的 clone 方式**：`none` 直接 clone；`token` 把解密后的凭证明文拼进 https URL 的 netloc（`https://<token>@host/...`，适配 GitHub/GitLab 等主流托管的 PAT 约定）；`ssh_key` 把解密后的私钥内容写入一个仅当前 clone 调用期间存在的临时文件（0600 权限），通过 `GIT_SSH_COMMAND` 环境变量让 git 使用它，用完（含异常路径）立即删除。凭证只在 `git_ops.clone_repository` 这一次调用栈内以明文形式短暂存在；clone 失败时 git 输出的 stderr 会先做一次字符串替换脱敏（把凭证明文替换成 `***`）再写入 `Agent.status_message`，避免凭证明文泄露到会被前端展示的字段里
- **仓库目录命名与快照打包结构**：`agent-runner/app/workspace/git_ops.py::repo_dir_name` 取 URL 最后一段（去掉 `.git`）做 sanitize（非 `[A-Za-z0-9_.-]` 字符替换成 `_`），结果为空则回退成 `repo-{position}`；同名冲突（如两个不同域名但 basename 相同的仓库）追加 `-2`/`-3` 后缀。打包时压缩包内路径固定是 `repos/<repo-dir-name>/...`（`agent-runner/app/workspace/archive.py::zip_directory`），clone 完成后立即删除每个仓库的 `.git` 目录再打包——仓库在 workspace 里只读展示，不需要保留完整版本历史/对象库，也避免快照体积随 git 历史膨胀
- **MinIO object key 与版本号规则**：`{workspace_id}/repo-v{version}.zip` / `{workspace_id}/output-v{version}.zip`（`agent-runner/app/workspace/storage.py`），版本号取当前 `workspace_snapshots` 表里记录的版本 +1（首次初始化时表里还没有该 Agent 的行，版本按 0 处理，所以首次落地是 v1）；与 Skill 版本历史的"新增而不覆盖旧对象"风格一致，`workspace_snapshots` 表用 `INSERT ... ON CONFLICT (agent_id) DO UPDATE` upsert 最新版本号和 object_key（旧版本号对应的 MinIO 对象不删除，只是不再被引用，比照 T2.1 遗留问题——Agent 删除时机的 MinIO 清理仍未处理，这里同样不处理历史版本对象的清理）
- **`output_snapshot_update_source` 补充第三个取值 `workspace_init`**：T2.1 定义该字段时只写了 `conversation_sync`/`emergency_fallback`（T4.4）两种，本任务产生的是"初始化生成的空快照"，语义上不属于这两种，回写补充了第三个取值，`backend-api/app/modules/agents/models.py` 的字段注释已同步更新
- **失败判定与重试**：整个 `_run()` 用一个 try/except 包住"clone 所有仓库 + 打包 + 上传 + 写快照元信息"这一整段——任何一个仓库 clone 失败（`git_ops.WorkspaceInitError`，包含地址不可达、鉴权失败、超时）或任何未预期异常，都直接把 `Agent.status` 置为 `failed` 并把原因写进 `status_message`，不会写入任何 `workspace_snapshots` 记录，也不会上传任何 MinIO 对象——本地打包发生在 `tempfile.TemporaryDirectory()` 里，只有全部仓库都 clone 成功才会执行打包/上传步骤，天然保证"整体失败、不留部分产物"。任务本身不做重试（Celery `max_retries` 用默认值 0），"重试"是指同一个任务可以被安全地重复触发（T2.1 已实现的 `trigger_workspace_init` 直接复用即可，T2.4 负责接一个"重试"按钮调用它）——重复触发只会产生新版本号的快照，不依赖上一次的中间状态，天然幂等
- **单个仓库 clone 超时**：新增 `WORKSPACE_CLONE_TIMEOUT_SECONDS`（默认 300 秒）配置项，超时视为该仓库 clone 失败（走同样的整体失败路径）
- **Dockerfile 补充系统依赖**：`agent-runner/Dockerfile` 新增 `apt-get install git openssh-client ca-certificates`（bookworm-slim 基础镜像不带这些，clone https/ssh 仓库都需要）
- 验证方式：`uv run pytest`（新增 3 个测试文件共 11 个用例：`test_workspace_archive.py` 打包逻辑、`test_workspace_git_ops.py` 目录命名/token 注入/对本地临时仓库做真实 clone 的成功与失败路径、`test_workspace_task.py` 用 mock 掉 db/git_ops/storage 验证 Celery 任务在成功/clone失败/agent不存在 三种场景下的状态流转与"失败时不写快照"）；`docker compose build/up agent-runner` 后跑了三条真实链路验证：① 单仓库（容器内临时 git 仓库，`auth_type=none`）→ Agent 状态变 `ready`，MinIO 出现 `repo-v1.zip`（296B，内含 `repos/test-repo/README.md` 等）与 `output-v1.zip`（22B 空 zip），`agent_repositories.last_synced_commit` 与仓库实际 HEAD 一致；② 不可达仓库（`https://example.invalid/...`）→ Agent 状态变 `failed`，`status_message` 含 git 报错信息，`workspace_snapshots` 无记录；③ 双仓库 Agent → 两个仓库各自独立同步、各自 commit 正确记录，`repo-v1.zip` 内同时包含 `repos/test-repo/` 与 `repos/test-repo-2/` 两个独立目录。验证完清理了新建的三个测试 Agent 及其 MinIO 快照对象

---

### T2.4 Agent 状态管理与展示
**目标**：让 Agent 的状态（初始化中/就绪/失败）在后端准确流转，并在前端可见、可操作（重试）。

**关键实现决策**：
- 状态流转：创建后进入"初始化中" → T2.3 任务成功后转"就绪"、失败后转"失败"；"失败"状态下提供重试操作重新触发 T2.3
- 前端轮询或其他方式获取最新状态（本任务不要求实时推送，简单轮询即可，与后续对话场景的实时流式是两回事）

**验收标准**：
- Agent 详情页能看到当前状态，状态变化后刷新/轮询能看到最新结果
- "失败"状态下点击重试，能重新触发初始化并观察到状态回到"初始化中"直至最终结果

**决策记录**（实现时落地）：
- **后端新增 `POST /agents/{agent_id}/retry` 接口**：TASKS 原文和 T2.1/T2.3 交接记录都只约定了"重试直接复用 `trigger_workspace_init(agent_id)`"，但没有落地成 HTTP 接口——本任务补上。`service.retry_workspace_init` 只允许在 `status == "failed"` 时执行（否则抛 `AgentNotFailedError` → HTTP 409，防止初始化中/已就绪时被误触发打断），执行时把 `status` 重置为 `"initializing"`、清空 `status_message`，再调用已有的 `tasks.trigger_workspace_init`，不重新实现发送逻辑
- **前端轮询挂在 `AgentEditorSheet` 组件而非详情页**（详情页在 T2.2 交互优化时已经改成抽屉，不存在独立详情页组件）：`useEffect` 依赖 `[open, workingId, status]`，只在抽屉打开、`status === 'initializing'` 时启动 `setInterval`（4 秒一次，`STATUS_POLL_INTERVAL_MS`），状态变成终态（`ready`/`failed`）或抽屉关闭时通过 effect cleanup 自动停止，不会产生无意义的持续请求
- **重试按钮只在 `status === 'failed'` 时渲染**，位置紧挨着已有的状态 Badge 和"刷新状态"按钮；点击后复用 `applyDetail` 回填最新状态（同创建/保存/手动刷新三处的模式），不单独维护一份状态更新逻辑

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

**决策记录**（实现时落地）：
- **新增独立服务 `scheduler/`**：目录结构比照 backend-api/agent-runner 骨架（`uv` 管理、`pyproject.toml`/`Dockerfile`/`entrypoint.sh`/`app/config.py`/`app/logging_config.py`，`logging_config.py` 直接复制 agent-runner 那份不改），但**不需要 FastAPI/HTTP 业务 API**——这是一个只跑 Celery 常驻进程的服务，对应 TECH_DESIGN 6 节"scheduler：Python，仓库定时刷新（可与 Celery beat 合并部署）"
- **"固定间隔扫描"而不是"每个 Agent 一条 beat schedule 条目"**：Celery 原生 `beat_schedule` 是进程启动时的静态配置，没法随 Agent 增减、或用户修改某个 Agent 的 `repo_refresh_interval_minutes` 后动态调整（除非引入 `django-celery-beat` 这类数据库驱动的 beat scheduler，属于本项目现阶段不需要的额外基础设施）。落地方式：`celery -A app.celery_app worker --beat --loglevel=info`（`-B` 内嵌 beat，单进程，不需要独立 beat 容器），只注册**一条**固定周期的周期任务 `scheduler.scan_due_agents`（周期用新增配置项 `SCHEDULER_SCAN_INTERVAL_SECONDS`，默认 60 秒），每次触发时自己查 Postgres 判断"现在有哪些 Agent 到期该刷新了"，逐个按需派发——这样任何 Agent 的刷新周期改动，下一次扫描（至多 `SCHEDULER_SCAN_INTERVAL_SECONDS` 之后）就自动生效，不需要重启/重新加载 beat 配置
- **到期判断口径**：只考虑 `agents.status = 'ready'` 且 `agent_repositories` 至少一行的 Agent；用该 Agent 名下所有仓库 `last_synced_at` 的 **`MIN`**（而不是 `MAX` 或 Agent 级单一时间戳——`agents`/`workspace_snapshots` 都没有"仓库快照整体更新时间"这个字段，且各仓库可能是不同时间点通过编辑加进来的，last_synced_at 天然是逐仓库记录的）与 `now()` 比较，超过 `agents.repo_refresh_interval_minutes` 判定到期；某个仓库 `last_synced_at` 为 `NULL`（理论上不应该出现在 `status='ready'` 的 Agent 上，因为 ready 意味着 T2.3/编辑触发的初始化已经跑完并回写过，但作为兜底）视为立即到期。选 `MIN` 是为了保证"名下所有仓库都不会超过各自 Agent 配置的 interval 太久没同步"，不会因为某一个仓库刷新失败反复卡住而被 `MAX` 掩盖
- **派发的任务契约（T3.2 尚未实现，先约定，参照 T2.1 定义 `"workspace.init"` 契约的先例）**：任务名 **`"workspace.refresh_repos"`**，参数 `args=[agent_id]`（str），与 `"workspace.init"` 共用同一个 broker（`agent-runner`/`backend-api`/`scheduler` 三方通过同一个 `CELERY_BROKER_DB` 指向同一个 Redis db）。T3.2 落地时 Runner 侧要注册同名任务消费；上线前这些消息会在 broker 队列里排队等待，没有副作用
- **刷新期间不改变 Agent 状态**：不像 `workspace.init` 那样把 Agent 打成 `initializing`——对应 PRD/TECH_DESIGN"刷新独立于对话执行的互斥锁进行""不影响 Agent 当前可用性"的既定策略，刷新中的 Agent 应该继续展示 `ready`、可以正常发起新对话，不能因为后台在刷新就挡住前台
- **防止同一个 Agent 被重复派发**：单次 clone+打包耗时可能明显长于 60 秒的扫描间隔，若不做防护，同一个到期 Agent 会在还没刷新完时被下一轮扫描重复派发。做法：`scheduler.scan_due_agents` 派发前先对 `scheduler:dispatching:{agent_id}` 这个 key 做 Redis `SET NX EX`（TTL 用新增配置项 `SCHEDULER_DISPATCH_LOCK_TTL_SECONDS`，默认 600 秒，覆盖典型 clone 耗时），成功才真正派发，已存在（说明上一次派发的刷新大概率还没跑完）则跳过本轮；不要求 T3.2 的刷新任务主动清除这个 key——TTL 到期自动放行下一次派发即可，避免刷新任务本身还要感知/维护 scheduler 内部的锁细节（scheduler 侧自己建立、自己靠 TTL 兜底，不产生跨服务的清理依赖）
- **健康检查**：`scheduler` 容器不跑 HTTP server，`docker-compose.yml` 里的 healthcheck 改用 `celery -A app.celery_app inspect ping -d celery@$$HOSTNAME`（Celery 自带的存活探测），而不是 backend-api/agent-runner 那种 HTTP `/health` 方式
- **配置**：复用根 `.env` 已有的 Postgres/Redis 连接信息（跟 agent-runner 一样，不新增独立账号密码）；`CELERY_BROKER_DB` 与 agent-runner/backend-api 保持同一个值（同一个 broker）；新增 `SCHEDULER_SCAN_INTERVAL_SECONDS`（默认 60）、`SCHEDULER_DISPATCH_LOCK_TTL_SECONDS`（默认 600）
- **落地时发现并修复的问题：三方共用同一个 Celery 默认队列会互相"偷"任务**——scheduler 上线前，`backend-api`（生产者）/`agent-runner`（消费者）之间只有一对一的任务流转，都走 Celery 默认队列 `"celery"` 没出过问题；但 scheduler 的 worker 与 agent-runner 的 worker 现在共用同一个 broker（同一个 `CELERY_BROKER_DB`）且都是消费者，若不显式指定队列，两边都会监听默认队列 `"celery"`，导致 `scheduler.scan_due_agents` 可能被 agent-runner 抢走、`workspace.init`/`workspace.refresh_repos` 也可能被 scheduler 抢走——抢到的一方因为没注册对应任务名，会把消息直接丢弃（`Received unregistered task`，非重试、非重新入队），造成刷新任务静默丢失。本地 `docker compose up` 联调时已经复现（`agent-runner` 日志里出现 `Received unregistered task of type 'workspace.refresh_repos'`，说明 workspace.init 也有同样的潜在风险，只是运气好之前一直被 agent-runner 自己的 worker 抢到）。修复：改成显式队列路由——`agent-runner` 只监听队列 `"agent-runner"`（`agent-runner/entrypoint.sh` 及本地 `make local-runner`/`local-up` 补上 `-Q agent-runner`），`scheduler` 只监听队列 `"scheduler"`（`scheduler/entrypoint.sh` 及 `make local-scheduler`/`local-up` 补上 `-Q scheduler`，`beat_schedule` 里 `scan-due-agents` 条目加 `"options": {"queue": "scheduler"}`）；两处发往 Runner 的 `send_task` 调用都补上 `queue="agent-runner"`——`scheduler/app/tasks.py` 的 `workspace.refresh_repos`，以及**回头修正了 T2.1 遗留的 `backend-api/app/modules/agents/tasks.py::trigger_workspace_init`**（`workspace.init` 发送时补上同样的 `queue="agent-runner"`，此前该函数发消息到默认队列，只是因为过去没有第二个 worker 共用 broker 才没暴露问题）。这个修复不影响 T2.1/T2.3 已经验收通过的行为，只是让路由显式化、消除隐藏的竞态
- 验证方式：`uv run pytest`（`scheduler/tests/`，11 个用例，覆盖到期判断的纯逻辑——多仓库 MIN 口径、NULL 兜底、未到期不派发、Redis 派发锁 NX 语义、以及 `scan_due_agents` 任务本身对到期/未到期/被锁定三种场景的派发行为）；`backend-api/tests/test_agents.py`（21 个用例，`queue="agent-runner"` 改动后回归全过）；`docker compose build/up backend-api agent-runner scheduler` 后用真实环境验证——用数据库里既有的一个 `status='ready'` 且仓库早已过期未同步的 Agent（`repo_refresh_interval_minutes` 默认 30 分钟，`last_synced_at` 是数小时前）观察到 `scheduler` 日志按 `SCHEDULER_SCAN_INTERVAL_SECONDS`（60 秒）周期触发 `scan_due_agents` 并成功派发一次（`scheduler_dispatch_refresh` 日志 + `send_task` 命中 `queue="agent-runner"`）；确认 `agent-runner` 端收到的消息 `delivery_info.routing_key` 确实是 `"agent-runner"`（不是共用队列 `"celery"`）；下一轮扫描确认同一 Agent 因为 Redis 派发锁未过期被跳过（`scheduler_dispatch_skipped_locked`）；手动 `redis-cli -n 4 DEL` 清掉锁 key 后确认能立即重新派发，验证锁的 NX+TTL 语义符合预期。全程只观察真实数据，未新建/删除测试数据（T3.2 还没有消费者，`agent-runner` 侧目前会把收到的 `workspace.refresh_repos` 当作 unregistered task 丢弃，这是预期中的过渡状态，等同于 T2.1 定义 `workspace.init` 契约到 T2.3 落地之间的空档期）

---

### T3.2 仓库刷新任务
**目标**：实现仓库快照的定时刷新逻辑：拉取最新代码、打包、更新 MinIO 仓库快照。

**关键实现决策**：
- 刷新独立于对话执行的互斥锁进行（对应 TECH_DESIGN 4.3 的决策：仓库只读，不存在本地分叉，不需要等待锁空闲）
- 刷新只更新仓库快照部分，不触碰输出快照，两者版本独立
- 刷新失败（如仓库地址失效）时保留上一次成功的快照不变，并记录失败信息，不影响 Agent 当前可用性
- **到期不等于一定要重新打包上传**：刷新前先轻量判断仓库是否真的有新提交，没有变化就跳过 clone+打包+写 MinIO，只刷新"已检查过"的时间戳；否则每个仓库到期都无条件产生一份新版本快照，长期不更新的仓库也会让 `workspace_snapshots` 版本号和 MinIO 存储空间无意义膨胀

**验收标准**：
- 到达刷新周期后，若仓库确有新提交，MinIO 里的仓库快照更新时间和内容确实反映了仓库最新提交
- **到达刷新周期但仓库没有新提交时，不产生新的 MinIO 对象、`workspace_snapshots.repo_snapshot_version` 不变**，但下一次到期判断的时间基准（`last_synced_at`）仍要推进，不能因为跳过打包就导致该 Agent 一直"到期"、每次扫描都被重新判定需要刷新
- 模拟仓库地址失效的情况，刷新失败但不影响已有快照可用、Agent 仍可正常发起对话
- 一次对话执行期间触发刷新，不会相互阻塞或报错（验证读写不冲突的设计）

**决策记录**（实现时落地）：
- **消费方直接复用 T2.3 `agent-runner/app/workspace/` 下的 `git_ops.py`/`archive.py`/`storage.py`/`crypto.py`（原样不改），新增 `agent-runner/app/worker/tasks/refresh.py` 注册 `@celery_app.task(name="workspace.refresh_repos")`**——契约在 T3.1 就已经约定好（`args=[agent_id]`，同一个 `agent-runner` 队列），Runner 侧只需要新增消费逻辑；`load_agent_context`/`RepositoryRecord`/`AgentInitContext` 也直接复用（虽然名字带"Init"，但字段——workspace_id/repositories/repo_snapshot_version——刷新同样需要，没有另起一套 dataclass 的必要）
- **`app/workspace/db.py` 新增两个刷新专用的写函数，不复用 `save_workspace_snapshot`**：`update_repo_snapshot(agent_id, repo_snapshot_object_key, repo_snapshot_version)` 只 UPDATE `workspace_snapshots` 的 `repo_snapshot_*` 三列（刷新时该行必然已存在，不需要 UPSERT）；`update_repository_sync_error(repo_id, error_message)` 只写 `agent_repositories.last_sync_error`，不动 `last_synced_at`/`last_synced_commit`。`update_repository_sync_info`（init/refresh 共用）顺带在成功时把 `last_sync_error` 清空，避免旧的失败信息在下次成功后仍然展示
- **失败信息落地到新增字段 `agent_repositories.last_sync_error`（Text，nullable）**，而不是只写日志：TASKS.md 原文"记录失败信息"没有约束具体落地位置，但 Agent 表的 `status_message` 只在失败态才有意义、且刷新不改 Agent 状态，没有合适的地方存；给 repo 级加一列更符合"哪个仓库刷新失败"的粒度，backend-api `AgentRepositoryDetail` 一并加了这个字段方便前端后续展示（本任务不含前端改动，只加了 API 字段）。对应新增 Alembic 迁移 `7c2a4e1f9b3d_agent_repository_last_sync_error`
- **多仓库场景下任意一个仓库 clone 失败，整体放弃本次刷新**（不做部分快照），与 `workspace.init` 的"整体失败、不做部分成功"策略一致；用内部异常 `_RepoRefreshError` 把失败的具体 `repo_id` 带出 `_clone_and_pack`，只标记那一个仓库的 `last_sync_error`，其余仓库这轮"陪跑失败"但自身 `last_sync_error`/`last_synced_at` 不受影响（它们本身没出错，只是所在的这次刷新被回滚）
- **`mark_agent_status` 全程不调用**：`_run` 里没有任何一条路径会碰 `Agent.status`/`status_message`，成功/失败/agent_not_found/no_repositories/unchanged 五种返回值都只影响 repo 级和 `workspace_snapshots` 的仓库快照部分，直接满足"刷新不影响 Agent 当前可用性"
- **更新检查用 `git ls-remote`，不是"先 clone 再比较"**：`git_ops.py` 新增 `remote_head_commit(repo)`，只查询远程 `HEAD`（或 `repo.branch` 指定分支）当前指向的 commit，不下载任何内容，跟 `agent_repositories.last_synced_commit` 比对；clone 需要的凭证准备逻辑（token 拼 URL / ssh_key 落临时文件）从 `clone_repository` 里抽成 `_prepared_auth` 上下文管理器给两边共用。为此 Runner 侧 `RepositoryRecord`（`app/workspace/db.py`）新增了 `last_synced_commit` 字段、`load_agent_context` 的 SQL 一并查出来
- **多仓库任意一个变了就整体重新 clone+打包全部仓库**（不是只重新 clone 变化的那个）：快照是"全部绑定仓库"的一个组合 zip，没有对单仓库做增量更新的粒度，逐仓库精细化留到后续如果真的有性能问题再优化；全部仓库都没变时才真正跳过，返回值 `"unchanged"`
- **跳过打包的分支仍然调用 `update_repository_sync_info` 刷新 `last_synced_at`**（commit 值不变，只是时间戳往前推）：`scheduler` 的到期判断只看 `last_synced_at`，如果跳过时完全不写库，这个 Agent 会在下一次 60 秒扫描时立刻又被判定到期、重新派发，变成"每 60 秒查一次远程"而不是尊重用户配置的 `repo_refresh_interval_minutes`

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

**决策记录**（实现时落地，2026-08-31）：
- **`sdk_sessions` 表结构在本任务重新设计**：T1.1 落地时只按 `session_id` 单列做主键；本任务查阅 SDK 实际的 `SessionStore` Protocol（`claude_agent_sdk.types.SessionStore`，pip 包 `claude-agent-sdk`）才发现 `SessionKey` 是 `{project_key, session_id, subpath}` 三元组——`subpath`（如 `subagents/agent-{id}`）用来区分主会话与子代理各自独立的 transcript，同一 `session_id` 下会有多行。因为该表在 T1.1 之后到本任务之前没有任何写入代码路径（纯 schema 先行），直接用新迁移 drop/recreate（`backend-api/alembic/versions/9d3b6a2c1e4f_*.py`），不需要数据迁移。新结构：复合主键 `(project_key, session_id, subpath)`（`subpath` 主会话为空串 `''`，不用 NULL——NULL 在复合唯一约束下语义不稳定）、`agent_id`（FK CASCADE，用于 Agent 删除时级联清理，与 `project_key` 取值含义无关，是 adapter 实例化时由调用方另外传入的）、`entries`（JSONB 数组，SDK transcript 条目的不透明追加存储）、`mtime_ms`（Unix 毫秒，供 `list_sessions` 排序，同时是 `SessionStoreListEntry.mtime` 的来源）
- **adapter 代码放在 agent-runner，不是 backend-api**：`app/modules/sessions/` 只保留 SQLAlchemy 模型（供 Alembic 迁移用）；真正实现 `SessionStore` 方法的 `PostgresSessionStore` 类落在 `agent-runner/app/sessions/store.py`。原因：SDK 是在 agent-runner 进程内被调用的（T4.3），`sessionStore` 要以 Python 对象形式传给 `ClaudeAgentOptions`，必须和 SDK 调用同进程；backend-api 没有理由持有这个对象。`agent-runner` 新增 `claude-agent-sdk==0.2.144` 依赖（仅用于导入 `SessionKey`/`SessionStoreEntry` 等 TypedDict 做类型标注，不在本任务实际调用 SDK 执行——那是 T4.3 的范围）
- **duck-typed Protocol，只实现必需 + 部分可选方法**：`append`/`load` 是 SDK 唯一要求的必需方法；`list_sessions`/`delete`/`list_subkeys` 一并实现（前端 T5.1 对话列表、Agent 删除级联、resume 时发现子代理 transcript 都用得到）；`list_session_summaries` 依赖 SDK 内部 `fold_session_summary` 帮助函数维护增量摘要，v1 不实现，未定义在类上（SDK 用 `hasattr` 探测方法是否存在，而不是 `isinstance`，所以不能定义成 `raise NotImplementedError` 占位——那样会被探测成"已实现"）
- **`append` 的 upsert 语义**：按 SDK 文档要求，带 `uuid` 字段的条目视为幂等键，重复 `append` 相同 `uuid` 的条目不重复落盘；没有 `uuid` 的条目（如 title/tag/mode marker）直接追加不去重。实现上用 `SELECT ... FOR UPDATE` 锁行读出现有 `entries` 数组、在 Python 里做去重合并、再整体 `UPDATE` 写回（而不是用 Postgres jsonb 原地追加运算符）——因为去重逻辑（按 `uuid` 判断是否已存在）用纯 SQL 表达比较绕，entries 数组单次 `append` 批量通常很小（SDK 文档：~100ms 一批），整体读改写的开销可接受
- **`project_key` 的取值由调用方（T4.3）决定，本任务不下决策**：`PostgresSessionStore.__init__(agent_id)` 只固定 `agent_id`（用于落 FK 列），`project_key` 是每次调用时通过 `SessionKey` 参数传入的，T4.3 组装 SDK 参数时会决定具体传什么值（大概率是 `str(agent_id)`，但留给 T4.3 决定，不在本任务里预设）

**验证方式**：`uv run pytest`（`agent-runner/` 目录下 31 个用例全过，新增 9 个 `test_sessions_store.py`，用内存假 asyncpg 连接验证 append/load 往返、按 uuid 去重、无 uuid 不去重、subpath 隔离主/子会话、list_sessions 排除 subpath 条目、delete 主 key 级联子 key、delete 单个 subpath 只删自己、空 entries 是 no-op）；`uv run pytest`（`backend-api/` 目录下，`uv run alembic upgrade head` 应用新迁移后 21 个用例全过）；额外用真实 Postgres（`docker compose up -d postgres redis minio` + `minio-init`）跑了一遍端到端脚本验证：插入一个真实 `agents` 行 → `PostgresSessionStore.append` 两批（含重复 uuid）→ 验证 `load` 返回去重后的合并结果 → 验证 `subpath` 隔离（主 transcript 与 `subagents/agent-x` 各自独立）→ 验证 `list_sessions`/`list_subkeys` 返回正确 → **用一个全新的 adapter 实例**（模拟另一个 Runner 副本）`load` 同一个 key，确认能读到同样内容（验证跨主机 resume 能力对应的验收标准）→ 删除该 `agents` 行，确认 `sdk_sessions` 里对应记录被 FK CASCADE 一并清理（0 行残留）

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

**决策记录**（实现时落地，2026-08-31）：
- **锁代码放在 agent-runner，不是 backend-api**：与 T4.1 的 `PostgresSessionStore` 同样的理由——锁要覆盖的是 T4.3 里 SDK 在 Runner 进程内的一次完整执行，获取/续期/释放都要发生在同一个执行流程里，backend-api 没有必要间接持有这把锁；`agent-runner/app/locks/agent_lock.py`，key 用 `agent_lock:{agent_id}`，独立 Redis db 2（`agent_lock_db`，`config.py` 沿用 T0.3/T3.1 已经预留的注释）
- **不做成"排队等待"，直接快速失败**：`AgentLock` 是异步上下文管理器（`async with AgentLock(agent_id): ...`），`__aenter__` 内部只 `SET key token NX PX ttl` 尝试一次，拿不到立刻抛 `AgentBusyError`（带 `agent_id` 属性），不做重试/阻塞等待——对应验收标准"明确得知 Agent 正忙而不是排队卡住"的字面要求，调用方（T4.3 的 HTTP 接口）捕获这个异常后直接返回"Agent 正忙"的响应
- **短 TTL + 后台续期，而不是"获取时设一个覆盖最长可能执行时间的长 TTL"**：单次对话执行时长不可预知（依赖 SDK 侧模型调用/工具执行），长 TTL 设多长都可能不够，而且会让"进程真的崩溃"场景的锁悬挂窗口变得很长。改成默认 TTL 60s（`agent_lock_ttl_seconds`）+ 持锁期间每 20s（`agent_lock_renew_interval_seconds`）用一个后台 `asyncio.Task` 续期一次；执行多久就续期多久，正常退出时取消续期任务并主动释放；进程崩溃时续期任务随进程消失，锁在最后一次续期后最多 60s 内自动过期——对应验收标准"过期时间后自动释放"
- **释放/续期都用 Lua 脚本做"校验 token 匹配后再操作"的原子 check-and-act**（而不是先 `GET` 再 `DEL`/`PEXPIRE` 两步），每把锁持有一个 `uuid4().hex` token：避免 A 的锁已经过期、B 已经抢到新锁之后，A 才姗姗来迟地续期/释放，把 B 的锁给续期/删除了
- 未在 T4.3 之前提供实际的 HTTP 调用入口（T4.3 还没实现），本任务只交付 `AgentLock`/`AgentBusyError` 这两个可复用的构件，T4.3 组装执行流程时用 `async with AgentLock(agent_id) as lock:` 包住"拉取 workspace → 调 SDK → 同步输出快照"整段逻辑，`AgentBusyError` 在 T4.3 的路由层捕获并转成对调用方明确的"Agent 正忙"响应（如 HTTP 409）

**验证方式**：`uv run pytest tests/test_agent_lock.py`（`agent-runner/` 目录下，用真实本地 Redis——`docker compose up -d redis` 已在跑，5 个用例：① 同一 Agent 并发两次 `async with AgentLock` 第二次确认抛 `AgentBusyError` 且 `agent_id` 属性正确；② 正常退出后锁释放，下一次能重新拿到；③ 上下文内抛异常退出后锁同样释放；④ 模拟崩溃——`acquire()` 后不进入 `async with`（不启动续期协程）也不释放，确认此刻仍是"正忙"，`sleep` 超过 TTL 后确认能被新请求拿到；⑤ 验证续期协程确实让锁存活时间超过初始 TTL（ttl=1s + 每 0.3s 续期一次，1.5s 后锁仍存在））；`uv run pytest`（`agent-runner/` 目录下全量 36 个用例全过，含此前 31 个 + 新增 5 个）

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

**决策记录**（实现时落地，2026-08-31）：
- **接口契约**：`POST /agents/{agent_id}/execute`，body `{prompt: str, resume_session_id: str | null}`，响应 `text/event-stream`，每条 SDK 消息序列化成一个 SSE `data:` 事件（`{"type": "<SDK 消息类名>", ...dataclasses.asdict(message)}`，`json.dumps(..., default=str)` 兜底不可直接序列化的字段）；执行异常时不会让连接静默断开，而是先推一条 `{"type": "ExecutionError", "message": ...}` 事件再结束流。获取锁失败（409）/Agent 未就绪（409）这两种"还没开始流式传输就已知会失败"的情况，直接走普通 HTTP 4xx JSON 响应（不进入 SSE），这样调用方不用解析 SSE 流就能拿到明确的失败原因
- **`cwd`/`add_dirs`/`skills` 的映射关系，对应 TECH_DESIGN 4.4 第 5 步**：仓库快照与输出快照**不合并进同一个目录**——`cwd` 只指向输出快照解压得到的 `output/` 目录（唯一可写目录，也是 SDK 据此派生 `SessionStore` `project_key` 的目录），仓库快照解压得到的 `repo/repos/` 目录通过 SDK 的 `add_dirs`（对应 TECH_DESIGN 里的 additionalDirectories）单独暴露为只读参考资料；这样"仓库刷新"和"输出同步"两条独立生命周期互不干扰，不需要处理合并/冲突逻辑，也不需要在同步输出快照时把仓库文件从打包内容里排除掉。绑定的 Skill 各自解压到 `skills/<skill-name>/`，路径列表传给 SDK 的 `skills` 参数
- **`SessionStore` 的 `project_key` 不显式传递，靠 SDK 从 `cwd` 路径自动派生（`project_key_for_directory`）**：这对"跨 Runner 副本 resume"这条验收标准反而有利——只要 `RUNNER_LOCAL_CACHE_DIR` 在所有副本间是同一个绝对路径（compose 挂同一个具名 volume，T0.3 已定），同一个 `workspace_id` 在任意副本上算出的 `cwd` 路径都相同，派生出的 `project_key` 自然一致，不需要额外的参数对齐；T4.1 handoff 里"project_key 建议用 str(agent_id)"这条建议因此不采用（该建议成立的前提是要显式传参，但 SDK 实际不支持在 `ClaudeAgentOptions` 上显式指定 project_key）
- **本地热缓存的命中/未命中判断，粒度拆到"仓库/输出/每个 Skill"各自独立**：`agent-runner/app/execution/workspace_cache.py`，每个 workspace 一个 `.cache_meta.json` 记录当前本地内容对应的版本号（`repo_version`/`output_version`/`skills: {name: version}`），准备执行环境时逐项比较版本号，版本一致且本地目录存在就跳过重新拉取+解压（记 `workspace_cache_hit` 结构化日志），版本不一致或目录缺失才重新拉取（记 `workspace_cache_miss` 日志，附 cached/current 版本号），对应验收标准"可通过耗时或日志验证"；已解绑的 Skill 会在下次准备时把本地残留目录一并清理掉，避免过期 Skill 内容误留在 workspace 里
- **锁的获取时机在"读执行上下文成功之后、真正开始拉取 workspace 之前"，且锁的生命周期跨越整个 SSE 流**：路由函数里手动调用 `AgentLock.acquire()`（不是 `async with`，因为需要在拿到锁之前就能返回 HTTP 409，而 `async with` 拿不到锁时会直接抛异常打断整个函数——两者行为上其实等价，选手动调用只是为了在文档/代码里把"锁获取"和"开始流式响应"这两个阶段的边界写清楚），成功后立刻 `begin_renewal()`，真正的执行逻辑放进 `StreamingResponse` 的异步生成器里，在 `finally` 块里做"同步输出快照 → 结束续期 → 释放锁 → 关闭 Redis 连接"——无论正常完成、SDK 抛异常、还是客户端主动断开连接（Starlette 会对生成器协程发 `CancelledError`），`finally` 都会执行，保证不会有"忘记释放锁"的路径。为此把 T4.2 的 `AgentLock.__aenter__`/`__aexit__` 内部逻辑拆成了可独立调用的 `begin_renewal()`/`end_renewal()`/`close()` 三个公开方法（`async with` 用法不变，仍然可用，两者共享同一套实现）
- **MCP Server 配置解密**：新增 `agent-runner/app/execution/mcp_crypto.py`，与 backend-api `app/modules/mcp/crypto.py` 用同一把 `MCP_ENCRYPTION_KEY`（Runner 侧新增这个配置项，此前只有 `AGENT_REPO_ENCRYPTION_KEY`），组装 `mcp_servers` 参数时解密成明文 dict 直接使用（`MCPServerConfig.config_encrypted` 存储时就已经对齐 SDK `mcp_servers` 所需结构，解密后不需要额外转换）
- **`Agent` 必须处于 `ready` 状态才能执行**：`execution/context.py` 的 `load_execution_context` 在 Agent 不存在、状态非 `ready`、或 `workspace_snapshots` 里输出快照对象 key 为空（意味着 T2.3 workspace 初始化还没跑完）这三种情况下统一抛 `AgentNotReadyError`，路由层转成 409 + 具体原因，不会让 SDK 在一个不完整/不存在的工作目录里跑起来
- **输出快照打包方式与仓库快照不同**：新增 `archive.zip_directory_flat`（压缩包内路径以打包目录本身为基准），区别于原有给仓库快照用的 `archive.zip_directory`（以父目录为基准，解压后多一层目录）——因为输出快照的 `output/` 目录本身就是下次执行要恢复的 `cwd`，解压要求原地还原，不能多包一层目录
- **真实 SDK 执行的端到端验证（2026-08-31 补充，用户提供了本机 `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`）**：起了一个真实 `uv run uvicorn app.server.main:app --port 8100` 进程 + 一条真实插入的 `agents`/`workspace_snapshots` 记录（`permission_mode='acceptEdits'`），跑通了完整链路：① 首次 `execute` 请求收到真实的 `AssistantMessage`/`ResultMessage` 流式事件，拿到真实 `session_id`；② 带着这个 `session_id` 发 `resume_session_id` 请求，模型确认记得上一轮上下文，且在 cwd 内正确创建了 `hello.txt`；③ MinIO 里 `output-v3.zip` 下载后确认内容就是 `hello.txt`，版本号正确递增；④ 并发对同一 Agent 发两个 `execute` 请求，第二个立刻收到 `409 {"detail": "Agent ... 正忙，请稍后再试"}`，不排队不卡住；⑤ 执行结束后 `redis KEYS agent_lock:*` 确认没有残留锁。至此 T4.3 全部四条验收标准都有真实 SDK 调用的证据支撑，不再只是 mock 验证
- **验证过程中的发现（不是本任务代码的 bug，但记录下来避免下次重新踩坑）**：第一次请求里模型没有按预期把文件写到 SDK 配置的 `cwd`（`.cache/agent-runner/{workspace_id}/output/`），而是尝试写到绝对路径 `/Users/peng/Me/Ai/agent-builder/hello.txt`（项目仓库根目录），被 SDK 自带的"只允许写 cwd/add_dirs 范围内"权限检查拦下（`permission_denied`，`decision_reason_type: "workingDir"`）——说明 T4.3 组装的 `cwd`/`add_dirs` 参数本身确实起到了沙箱限制作用（这正是想要的安全边界），但触发原因值得记录：**本地开发时本地缓存目录 `RUNNER_LOCAL_CACHE_DIR`（`./.cache/agent-runner`）落在 `agent-runner/` 这个真实 git 仓库内部**，`claude` CLI 子进程会向上查找 `.git`/`CLAUDE.md` 来识别"项目根目录"，找到的是 `agent-builder` 仓库根（而不是我们指定的深层 `output/` 目录），导致模型的路径判断参照了错误的"项目根"。生产部署（compose 容器内，`RUNNER_LOCAL_CACHE_DIR` 挂到具名 volume 的独立路径，不在任何 git 仓库内）不会有这个问题；本地单进程调试时若要复现"模型总是老实用相对路径"的效果，可以把 `RUNNER_LOCAL_CACHE_DIR` 指到仓库外的临时目录（如 `/tmp/agent-runner-cache`）。第二次请求把 prompt 改成明确要求"用相对路径 `hello.txt`、不要带任何目录前缀"后，模型正确执行、写入了 cwd 内的文件——不是代码需要改的地方，是本地验证环境本身的局限，已经记录在这里供下次直接复现验证时参考

**验证方式**：`uv run pytest`（`agent-runner/` 目录下全量 52 个用例全过，含此前 36 个 + 新增 16 个：`test_execute_endpoint.py` 4 个用真实本地 Redis 验证流式响应/409 忙/409 未就绪/异常路径下锁与输出同步仍执行；`test_workspace_cache.py` 4 个验证首次全量拉取/版本不变跳过/单项版本变化只重拉该项/解绑 Skill 清理本地目录；`test_workspace_archive.py` 新增 4 个验证 `zip_directory_flat`/`extract_zip` 打包解压往返及清理陈旧文件；`test_execution_context.py` 5 个用真实本地 Postgres 验证 Agent 不存在/未就绪/快照缺失三种失败路径 + JOIN 查询绑定的 skills/MCP 正确 + 输出快照回写）；MCP/仓库解密密钥的读取方式与既有 `agent_repo_encryption_key` 一致，未单独追加测试（`cryptography.fernet.Fernet` 本身的加解密正确性已经在 backend-api T1.4/T2.1 的测试里覆盖过）

---

### T4.4 异常退出兜底保存
**目标**：Runner 进程异常终止前，强制把当前输出目录同步回 MinIO，降低数据丢失窗口。

**关键实现决策**：
- 注册可捕获信号（如 SIGTERM）的优雅关闭钩子，收到信号后暂停正常流程、强制执行一次输出目录打包上传，再释放互斥锁退出
- 明确记录该机制覆盖不到 SIGKILL、断电等场景（对应 TECH_DESIGN 4.5 的局限性说明），不在本任务里试图解决这类场景

**验收标准**：
- 在对话执行过程中人为发送可捕获的终止信号，验证 MinIO 输出快照被更新为终止前的最新状态，且 Agent 互斥锁被正确释放（不会卡死后续对话）
- 验证正常执行完成路径和异常退出路径不会重复触发两次快照上传（幂等或互斥处理得当）

**决策记录**（实现时落地）：
- **新增 `agent-runner/app/execution/registry.py`**：模块级 `ActiveExecution` 注册表，T4.3 的 `_execute_stream` 开始时 `registry.register(context, lock)` 注册一条记录（`cwd` 字段在 workspace 准备完成后才赋值，赋值前 SIGTERM 到达也不会报错，只是没有内容可同步），正常/异常/客户端断开退出时统一走 `entry.finalize()` + `registry.unregister(entry)`；`app/server/execute.py` 原来直接内联在 `finally` 块里的"打包上传 + 释放锁"逻辑整体搬进了 `ActiveExecution.finalize()`，`_execute_stream` 自身的 `finally` 块简化为只调 `entry.finalize()`
- **幂等靠 `ActiveExecution` 自带的 `asyncio.Lock` + `_finalized` 标记**，而不是复用 T4.2 的 Redis 锁做跨路径互斥：正常路径（HTTP 请求自身的 `finally`）和信号路径（SIGTERM 处理器遍历注册表）有可能并发调用同一条记录的 `finalize()`，`_guard` 保证只有一次真正执行"打包上传 + 释放 Redis 锁"，另一次直接返回——两条路径谁先谁后都不会重复上传/重复释放
- **信号处理器挂在 `app/server/main.py` 的 `lifespan` 里**：`loop.add_signal_handler(signal.SIGTERM, ...)` 注册 `_emergency_shutdown()`，逻辑是"遍历 `registry.snapshot()` → 对每条记录并发 `finalize(update_source=SOURCE_EMERGENCY_FALLBACK)` → `os._exit(0)`"。**用 `os._exit(0)` 直接终止进程，不走 uvicorn 自带的优雅关闭流程**——因为 `loop.add_signal_handler` 对同一信号只能注册一个回调，注册我们自己的处理器会覆盖 uvicorn 内部的 SIGTERM 处理逻辑（它自己也是靠 `add_signal_handler` 挂载的），如果不主动退出进程会一直挂着不退出；这个取舍对应 TASKS 原文"收到信号后暂停正常流程、强制执行一次输出目录打包上传，再释放互斥锁退出"里的"退出"二字，是有意为之而不是遗漏
- **明确不覆盖 SIGKILL/断电场景**（TECH_DESIGN 4.5 已有此局限性说明，本任务不重复展开）：这类场景进程没有机会执行任何代码，只能依赖 T4.2 已实现的 Redis 锁短 TTL（默认 60s）自动过期兜底，不会永久卡死该 Agent，但这段时间内的输出快照就是终止前最后一次正常同步的版本，无法做到"终止前最新状态"
- 验证方式：`uv run pytest`（`agent-runner/` 目录下全量 57 个用例全过，含此前 52 个 + 本次新增 `test_execution_registry.py` 4 个 + `test_shutdown.py` 1 个）；本地起了真实 uvicorn 进程（`RUNNER_LOCAL_CACHE_DIR` 指到仓库外目录，规避 T4.3 补充记录里提到的 `claude` CLI 项目根探测干扰）+ 真实 Postgres/MinIO/Redis + 真实 `ANTHROPIC_API_KEY`，往一个临时 Agent 发起真实 `execute` 请求，执行进行中（收到 `workspace_cache_miss` 日志之后、模型输出尚未返回工具调用结果前）对服务进程发 `kill -TERM`：日志显示 `sigterm_received`（`active_executions: 1`）→ `output_snapshot_synced`（`update_source: emergency_fallback`，`version: 2`）→ `emergency_shutdown_complete`，进程随即退出；确认 Redis 里 `agent_lock:*` 无残留 key；下载 `output-v2.zip` 确认是当时输出目录的真实内容（本次因为进程在模型第一次工具调用前就被杀，内容为空 zip，符合"终止前最新状态"预期，不是 bug）。验证完清理了临时 Agent 行、MinIO 三个测试对象、本地缓存目录

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

**决策记录**（实现时落地）：
- **接口落在 backend-api 新增的 `app/modules/conversations/` 模块**：`router.py` 三个接口——`POST /agents/{agent_id}/conversations`（新建对话，`session_id` 为空）、`GET /conversations/{conversation_id}`（查询，供前端刷新页面后判断能否续接）、`POST /conversations/{conversation_id}/messages`（发一轮消息，SSE 转发）；`service.py` 只管 conversation 记录本身的增删查；`runner_client.py` 封装对 Runner `execute` 接口的 httpx 直连调用
- **互斥锁不在 backend-api 侧重复实现**：TECH_DESIGN 4.4 步骤 2 写的是"Conversation Service 用 Redis 对该 Agent 加互斥锁"，但 T4.2/T4.3 落地时已经把这把锁做在了 agent-runner 一侧（`execute` 接口拿不到锁直接返回 HTTP 409）——backend-api 重复加一层锁没有必要，还会引入两把锁一致性的新问题（比如 backend-api 锁拿到了但 Runner 锁没拿到，或者反过来）。本任务的做法是 `runner_client.open_execute_stream` 原样透传 Runner 的状态码/detail（`RunnerRequestError` → `HTTPException`），backend-api 侧不新增任何 Redis 交互。这是对 TECH_DESIGN 表述的一处必要偏差，理由已回写到 TECH_DESIGN 不涉及（该文档只到"系统级"粒度，具体锁归属这种实现细节留给 TASKS 记录即可）
- **SSE 转发用 httpx 流式 + 手动逐行透传**：`_forward_stream` 用 `httpx.AsyncClient(...).send(..., stream=True)` 拿到 Runner 的 `httpx.Response`，`async for line in upstream.aiter_lines(): yield f"{line}\n"` 原样重建 SSE 格式（`aiter_lines()` 会把 `data: {...}\n\n` 拆成 `"data: {...}"` 和 `""` 两行，逐行加回 `\n` 能精确重建）；边转发边用一个正则/JSON 解析检查每个 `data:` 行是不是 `type == "ResultMessage"`，是的话取出 `session_id` 暂存，流结束（`finally` 块）后才落库——不在流进行中途写库，避免半途异常导致的部分写入
- **`session_id` 落库用独立的短生命周期 DB session**，不复用请求最初查 conversation 时用的那个：查 `agent_id`/`resume session_id` 那次用完立刻关闭（`async with session_factory() as db: ...` 出了 `with` 就关），流式转发期间及结束后落库各自开关自己的 session——避免一个 DB 连接跨越整个可能持续很久的 SSE 生命周期占着不放
- **`Conversation.session_id` 有唯一约束**（T1.1 建表时定的），落库前判断"是否与当前值不同"才写，避免同一 session_id 重复 UPDATE 触发不必要的写操作；不同 conversation 之间不会撞 `session_id`（每次新对话在 Runner 侧都是全新 session）
- 验证方式：backend-api 新增 `tests/test_conversations.py`（7 个用例：鉴权拦截、创建/查询 404、创建/查询成功、发消息成功转发+落库+续接用正确的 resume_session_id、Runner 返回 409 时透传、对话不存在时 404），`uv run pytest` 全量 28 个用例全过（backend-api 目录下）；agent-runner 侧无改动，57 个用例仍全过。另外起了真实 backend-api + agent-runner + 真实 Postgres/MinIO/Redis + 真实 `ANTHROPIC_API_KEY`，对一个临时 ready Agent 走完整闭环：① `POST /agents/{id}/conversations` 拿到 `session_id: null` 的新对话 → ② `POST /conversations/{id}/messages` 发第一条消息，SSE 收到真实 `SystemMessage`→`AssistantMessage`→`ResultMessage` 完整流，`GET /conversations/{id}` 确认 `session_id` 已回写 → ③ 带着同一个 `conversation_id` 再发第二条消息，日志确认 Runner 侧走的是 `workspace_cache_hit`（复用第一轮的工作目录）且传给 SDK 的 `resume_session_id` 与第一轮拿到的 `session_id` 一致 → ④ 在第二条消息执行过程中并发发第三条消息，确认立刻收到 backend-api 透传的 `409 {"detail": "Agent ... 正忙，请稍后再试"}`，不阻塞不排队，同时第二条消息正常执行完成。验证完清理了临时 Agent 行、MinIO 测试对象

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
