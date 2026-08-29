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

---

### T1.2 Skill Service（zip 存取 + CRUD API）
**目标**：实现 Skill 的增删改查接口，内容以 zip 包整体形式存取 MinIO。

**关键实现决策**：
- 一个 Skill 对应 MinIO 里一个 zip 对象；Postgres 只存元数据（名称、对象 key、版本、状态），不维护文件级索引
- 编辑接口：拉取现有 zip 解压，返回可编辑的文件树结构给前端；保存接口：接收改动后的内容，重新打包整体覆盖上传
- zip 内目录结构遵循标准 skill 规范（`SKILL.md` + 资源文件），创建时校验基本结构是否符合规范
- 版本号每次保存递增，用于后续 Agent 绑定关系里判断是否需要提示"有更新"（v1 不做自动推送，只是元数据层面的版本记录）

**验收标准**：
- 创建 Skill 时上传符合规范的内容，能在 MinIO 里看到对应 zip 对象生成
- 编辑并保存后，MinIO 对象被覆盖更新，版本号递增，Postgres 元数据同步更新
- 上传不符合规范（缺 `SKILL.md` 等）的内容时，接口能明确拒绝并返回原因
- 删除 Skill 后，MinIO 对象与 Postgres 元数据一并清理

---

### T1.3 Skill 管理前端页面
**目标**：实现 Skills 的可视化管理界面。

**关键实现决策**：
- 列表页展示所有 Skill（名称、版本、状态、更新时间）
- 详情/编辑页能浏览 zip 内的文件树、查看和编辑文件内容，保存时调用 T1.2 的保存接口
- 创建页支持新建 Skill（上传或从模板创建，二选一在本任务定，若上传则前端本地打包成 zip 提交）

**验收标准**：
- 能在页面上完成"新建 Skill → 查看文件内容 → 编辑保存 → 列表看到版本更新"的完整闭环操作
- 编辑保存失败（如格式校验不通过）时页面有明确提示，不会静默失败

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

---

### T1.5 MCP 管理前端页面
**目标**：实现 MCP Server 配置的可视化管理界面。

**关键实现决策**：
- 列表页 + 创建/编辑表单，字段对应 T1.4 的配置结构
- 敏感字段在表单里编辑时按脱敏展示，重新输入才更新

**验收标准**：
- 能在页面上完成 MCP 配置的新建、编辑、删除，且敏感字段不会明文回显

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
