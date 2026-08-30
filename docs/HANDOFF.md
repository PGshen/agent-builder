# AgentBuilder 任务交接记录

> 每完成（或阶段性中断）一个任务，在本文件末尾追加一条记录，方便下一个任务/下一次会话接手时不用重新翻代码或猜实现细节。按时间顺序追加，不要修改或删除历史记录（发现旧记录有误，用新记录说明更正，而不是回去改旧的）。

## 归档记录

> 本文件太长时，按 Phase 边界把已完成 Phase 的记录整体搬到 `docs/handoff-archive/`，本文件只保留归档索引 + 尚未归档（通常是当前 Phase）的记录。归档只搬运、不改写内容；接手任务前，除了看本文件末尾的最近记录，也要检查下面的归档索引里是否有相关 Phase 的历史决策。

| Phase | 归档文件 | 归档时间 | 覆盖任务 |
|---|---|---|---|
| Phase 0（基础设施与骨架，T0.1~T0.5） | [handoff-archive/phase0-2026-08-29.md](./handoff-archive/phase0-2026-08-29.md) | 2026-08-29 | T0.1 Docker Compose、T0.2 Backend API 骨架（+ uv 迁移补充）、T0.3 Agent Runner 骨架、T0.4 前端骨架（+ pnpm/shadcn 补充）、T0.5 登录鉴权 |

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

Phase 0（T0.1~T0.5）已全部完成并归档，见上方归档索引。当前进入 Phase 1（元数据管理：Skill / MCP）。

## [T1.1] 数据模型与数据库迁移 —— 2026-08-29

**状态**：已完成

**完成内容**：
- `backend-api` 新增 Alembic（`uv add alembic`），异步模板初始化在 `alembic/`（`alembic.ini` + `alembic/env.py` + `alembic/versions/`）
- 新增 `app/db_base.py`：`Base`（DeclarativeBase）+ `UUIDPKMixin`（UUID 主键，`gen_random_uuid()` 服务端默认）+ `TimestampMixin`（`created_at`/`updated_at`），供各模块模型共用
- 各业务模块新增 `models.py`：
  - `app/modules/skills/models.py` —— `Skill`（name/object_key/version/status）
  - `app/modules/mcp/models.py` —— `MCPServerConfig`（name/config JSONB/status）
  - `app/modules/agents/models.py` —— `Agent`（含 workspace_id/permission_mode/repo_refresh_interval_minutes/status/status_message）、`AgentSkill`/`AgentMCPServer`（多对多关联表）、`AgentRepository`（每个 Agent 可绑定多仓库，含鉴权字段与最近同步信息）、`WorkspaceSnapshot`（与 Agent 一对一，仓库快照/输出快照两段各自独立版本化）
  - `app/modules/conversations/models.py` —— `Conversation`（agent_id/session_id/status）
  - 新增 `app/modules/sessions/` 模块目录 + `models.py` —— `SDKSession`（`sdk_sessions` 表，SessionStore 记录，为 T4.1 预留）
- 生成并验证首个迁移 `alembic/versions/191e1f381995_initial_schema.py`（`alembic revision --autogenerate`），本地针对 T0.1 的 Postgres 实例验证：`upgrade head` 建出全部 10 张表（含 `alembic_version`）→ `alembic check` 确认模型与已应用 schema 无差异 → `downgrade base` 干净清空回到 1 张表 → 再次 `upgrade head` 复原，验证"空库一次性建出" + "增量应用" + "可回滚"三点
- `backend-api` 新增 `entrypoint.sh`（`alembic upgrade head` 后 `exec uvicorn`），`Dockerfile` 相应拷贝 `alembic.ini`/`alembic/`/`entrypoint.sh` 并把 `CMD` 换成该脚本；`docker compose build backend-api` + `up -d` + `restart` 验证过容器启动会自动把 schema 迁到最新且幂等（重启不报错、不重复建表）
- `uv run pytest -q` 5 个既有用例（T0.5 auth）全部仍通过，确认新增模型/迁移未破坏现有功能

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.1 的"决策记录"小节，要点：模型分散到各模块 `models.py`（而非集中 `app/models/`）；Agent 的 skill/MCP 绑定用关联表、仓库列表用独立表（都不用内嵌 JSON 数组）；Workspace 快照做成与 Agent 一对一的单表，仓库快照/输出快照字段各自一套；新增了 TASKS/TECH_DESIGN 都没明确写的 `Agent.status_message` 字段（为 T2.4 展示失败原因预留，避免后补迁移）；`workspace_id` 独立生成不复用主键；容器启动流程接入自动迁移
- Windows 本机 `alembic.ini` 一开始写了中文注释，触发 `configparser` 用 GBK locale 编码读取时的 `UnicodeDecodeError`，已改成纯 ASCII 注释，见 TASKS.md 决策记录里的具体说明——**以后凡是 alembic/pytest.ini 之类会被 Python 标准库 `configparser`/纯文本按 locale 编码读取的配置文件，本机环境下注释一律用英文**，避免重复踩坑

**遗留问题**：
- MCP 配置的敏感字段加密方式、Agent 绑定仓库凭证（`auth_credential`）的加密方式均未决定，当前 schema 只是预留了明文列（类型已定，内容处理留给 T1.4/T2.1）
- `sdk_sessions` 表的字段是"能跑起来的最小占位"（`session_id`+`agent_id`+不透明 JSONB `data`），T4.1 实现真正的 SessionStore adapter 时如果发现字段不够用（比如 SDK 接口需要额外的索引字段），需要再加一次迁移，不是本任务的遗漏，是有意留白
- 本次验证是针对本机单机 Postgres 做的（`docker compose down` 不会清库，用的是持久化 volume），没有专门起一个全新的空 Postgres 容器验证"从真正全新的空库建表"，但 `downgrade base` 后的库状态等价于全新空库（只剩 alembic 自身的版本表），逻辑上已覆盖这个验收点

**给下一个任务的建议**：
- T1.2（Skill Service）直接在 `app/modules/skills/` 下新增 `service.py`/`schemas.py`/`router.py`，`models.py` 里的 `Skill` 表已经就绪；数据库 session 用 `app/db.py` 的 `get_session_factory()`，目前还没有 FastAPI 依赖项包装成 `Depends`，需要自己在 `app/api/deps.py` 里补一个（如 `get_db_session`），T0.2 交接记录里也提过这一点，一直没有模块需要就没加，现在要用了
- 新建业务 router 记得接 `Depends(get_current_admin)`（`app/api/deps.py`），T0.5 交接记录强调过鉴权目前只保护了 `/auth/me`，业务路由需要自己接入，不要漏
- 以后新增/修改模型字段，流程是：改 `app/modules/<name>/models.py` → `uv run alembic revision --autogenerate -m "..."` → 检查生成的迁移文件（autogenerate 不总是完美，比如改字段类型、加索引名等有时需要手动调整）→ `uv run alembic upgrade head` 本地验证 → 提交时把 `alembic/versions/` 下新文件一并提交
- `agent_repositories`/`mcp_servers` 的敏感信息处理方式在 T1.4 定下来后，如果结论是要加密存储，记得同步回来看 `agent_repositories.auth_credential` 是否要用同样方式改造（TASKS.md T2.1 已经写了"与 T1.4 保持一致"这个约束）
- 本地起 backend-api 验证迁移：`cd backend-api && uv run alembic upgrade head`（连的是 `.env` 里 `localhost:5442`）；容器方式验证：`docker compose up -d --build backend-api`，日志里能看到 alembic 的输出在 uvicorn 启动之前

## [T1.2] Skill Service（zip 存取 + CRUD API） —— 2026-08-29

**状态**：已完成

**完成内容**：
- `backend-api` 新增依赖 `minio==7.2.13`（与 agent-runner 同版本）、`python-multipart==0.0.20`（FastAPI 表单/文件上传需要）
- `app/config.py` 补了 `minio_endpoint` 属性（`{host}:{port}`），之前只有零散的 `minio_*` 字段
- `app/api/deps.py` 新增 `get_db_session`（FastAPI 依赖项，`async with session_factory() as session: yield session`）——T1.1 交接记录里提到缺这个，本任务补上，后续业务 router 统一用它拿 DB session
- `app/modules/skills/` 新增四个文件：
  - `storage.py` —— MinIO 客户端单例（同步 SDK + `asyncio.to_thread` 包装，模式抄 agent-runner 的 `health.py`）；zip 打包/解包（`pack_zip`/`unpack_zip`，UTF-8 文本）；`validate_files`（非空、必须含根路径 `SKILL.md`、路径防 zip slip）；路径分隔符统一归一化成 `/`
  - `schemas.py` —— `SkillListItem`/`SkillDetail`（含 `files` 字典）/`SkillUpdateRequest`
  - `service.py` —— `list_skills`/`create_skill`/`get_skill_detail`/`update_skill`/`delete_skill`，`SkillNotFoundError`/`SkillNameConflictError` 两个业务异常
  - `router.py` —— `GET/POST /skills`、`GET/PUT/DELETE /skills/{id}`，整体挂 `Depends(get_current_admin)`
- `app/main.py` 挂载 `skills_router`
- `tests/test_skills.py`（新增，6 个用例）+ `tests/conftest.py` 新增 `_reset_db_engine_per_test` autouse fixture
- 手工全链路验证：`docker compose build/up backend-api` 重建镜像后，用真实 zip 文件（含 Windows `Compress-Archive` 生成的、路径分隔符是 `\` 的 zip）走了一遍 登录 → 创建 → 列表 → 详情（确认路径已归一化成 `/`）→ 编辑保存（版本号 1→2）→ 删除 → 再次 GET 返回 404 的完整闭环

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.2 的"决策记录"小节，要点：创建接口收 zip（multipart），编辑/保存接口收/发 JSON 文件树（不是 zip）；MinIO key 固定 `{skill_id}.zip` 原地覆盖，版本号只是 Postgres 字段；v1 只支持 UTF-8 文本文件，不支持二进制资源；名称唯一性靠 DB unique 约束 + `IntegrityError` 转译成 409；删除顺序是先删 MinIO 对象再删 DB 行
- **顺带修了 T0.2 的一个潜在 bug**（不是本任务范围内的新决策，是排查测试失败时发现的既有缺陷）：`app/db.py::dispose_engine()` 只清空了 `_engine` 全局单例，没有同步清空同样是全局单例、绑定着旧 engine 的 `_session_factory`。生产环境单进程单 event loop 场景下这个 bug 完全不会触发（`_session_factory` 只会被创建一次，从未需要"跟着 engine 一起换新"），但本任务写多用例 pytest 时稳定复现为 `RuntimeError: Event loop is closed`（且必定是整个测试会话里最后一个碰数据库的用例失败，因为前面用例的残留 `_session_factory` 一直没被清干净，直到最后一次 dispose 才会暴露）。已修复，`tests/conftest.py` 同步加了 `_reset_db_engine_per_test` fixture

**遗留问题**：
- 二进制资源文件不支持（v1 范围内的有意限制，见决策记录），如果后续 Skill 规范需要图片/二进制脚本等资源，需要重新设计文件树的传输格式（比如按扩展名分文本/二进制两种编码）
- `SKILL.md` 里的 YAML frontmatter（`name`/`description` 等字段）目前没有做内容级解析和与 Postgres `name` 字段的一致性校验——创建时的 `name` 是调用方显式传的表单字段，和 zip 内 `SKILL.md` frontmatter 里写的 name 可能不一致，本任务没有处理这个潜在的不一致，留给以后如果需要更严格的规范校验时再加
- 删除失败的部分成功场景（MinIO 删除失败）目前只是把错误抛给调用方、DB 行原样保留，没有专门的重试/告警机制，v1 认为手动重试删除已经够用

**给下一个任务的建议**：
- T1.3（Skill 管理前端页面）：`GET /skills/{id}` 返回的 `files` 是 `{路径: 文本内容}` 的 flat map（不是嵌套树结构），前端如果要做文件树 UI，需要自己按路径里的 `/` 分隔符在前端建树；保存时把编辑后的完整 `files` map（不只是改动的文件）整体传给 `PUT /skills/{id}`，因为后端是整体重新打包，不做增量 patch
- 创建页如果走"上传 zip"路线，直接对接 `POST /skills`（`multipart/form-data`：`name` 字段 + `file` 字段）；如果走"从模板创建"路线，则可以考虑前端本地构造一个含 `SKILL.md` 的最小文件树，用同样的 zip 打包后走同一个创建接口，不需要后端另开一个"从模板"专用接口
- `app/api/deps.py` 的 `get_db_session` 现在已经就绪，T1.4（MCP Service）直接复用，不用重新写一遍数据库 session 依赖项
- 以后写新的 async 测试如果又遇到 `RuntimeError: Event loop is closed` 或类似的跨 loop 报错，先检查是不是又出现了"模块级单例缓存了绑定旧 loop/旧资源的对象，但重置函数只清了部分变量"这种模式——这次踩的 `_session_factory` 坑和 T0.5 踩的 Redis 客户端坑是同一类问题，本质是全局单例 + pytest 每测试新 event loop 的组合，跟业务逻辑无关

## [T1.3] Skill 管理前端页面 —— 2026-08-29

**状态**：已完成

**完成内容**：
- 前端新增依赖 `fflate`（客户端打包 zip）；新增 shadcn 组件 `table`/`textarea`
- `src/lib/apiClient.ts`：补了 `put`/`delete`/`postForm` 三个方法；修了 `apiRequest` 对 `FormData` body 误加 `Content-Type: application/json` 导致 multipart boundary 丢失的问题
- 新增 `src/lib/skillsApi.ts`：`listSkills`/`getSkill`/`updateSkill`/`deleteSkill`/`createSkillFromFiles`（浏览器内 `fflate.zipSync` 打包后走 `postForm`）/`buildSkillTemplate`（生成最小 `SKILL.md` 内容）
- 三个页面：
  - `src/pages/SkillsPage.tsx`（重写）—— 列表页，表格展示 名称/版本/状态/更新时间，行内名称可点进详情页，右上角"新建 Skill"
  - `src/pages/SkillCreatePage.tsx`（新增）—— 名称+描述表单，提交即模板生成 `SKILL.md` 并打包创建，成功后跳转详情页；名称冲突（409）/其他失败都有内联错误提示
  - `src/pages/SkillDetailPage.tsx`（新增）—— 左侧扁平文件列表（可加文件/删文件），右侧文本编辑器，保存按钮调用 T1.2 的 `PUT`，成功后更新页面上的版本号徽章，失败时把后端返回的 `detail` 原样展示；页头有"删除 Skill"按钮
- `src/App.tsx` 新增路由 `/skills/new`、`/skills/:id`（`:id` 声明在 `new` 之后，但 react-router 对静态段的匹配优先级天然高于动态参数，顺序不影响结果）
- `pnpm run build`/`pnpm run lint` 均通过（lint 的两条 warning 是 shadcn 生成文件本身的已知 warning，非本次引入）
- 手工端到端验证：本地 `pnpm run dev` + 已跑起来的 `backend-api` 容器，用临时装的 Playwright（用完即删）自动跑了一遍"登录 → 新建 → 详情页确认内容 → 加文件编辑 → 保存看版本号 v1→v2 → 列表页确认版本已更新 → 删 SKILL.md 后保存触发内联报错且不跳转 → 删除整个 Skill 从列表消失"的完整闭环，全部通过

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.3 的"决策记录"小节，要点：创建页走"从模板创建"（不做本地文件/zip 上传选择器），复用 `fflate` 在浏览器打包后调用和"上传"同一个创建接口；文件树是排序后的扁平列表，不是嵌套目录树组件；编辑页不在前端拦截"删除 SKILL.md"，让后端校验报错原样透出，这样"保存失败有明确提示"这条验收标准是真实路径验证的而不是摆设；删除确认用原生 `window.confirm()`，没引入 dialog 组件

**遗留问题**：
- 文件树是扁平列表，Skill 内文件较多时（比如带很多资源文件的场景）体验会不够好，真要做嵌套折叠树可以后续在现有 `files` flat map 基础上纯前端加工，不需要动后端
- 编辑页目前没有"未保存改动"的提示（比如离开页面前 confirm），改了内容但没点保存就跳走会静默丢弃，v1 没有处理这个边界体验
- 二进制资源文件在前端层面同样不支持（T1.2 后端就没支持），文本编辑器对超大文件也没有做任何性能优化或截断保护

**给下一个任务的建议**：
- T1.4（MCP Service）如果前端部分（T1.5）想复用现在这套模式，`src/lib/skillsApi.ts` 的结构（每个业务模块一个 `xxxApi.ts` 文件，包一层 `apiClient` 调用 + 类型定义）可以直接照抄写一个 `mcpApi.ts`
- `apiClient.ts` 的 `put`/`delete`/`postForm` 现在是通用的，T1.5/T2.2/T5.1 等后续业务页面都可以直接复用，不用再加
- 如果后面要给 Skill 详情页加"文件预览高亮"（比如 Markdown 渲染、语法高亮），现在用的是最朴素的 `<Textarea>`，替换成代码编辑器组件（如 CodeMirror/Monaco）时注意要新增依赖，评估一下是否值得为这个体验加这么重的依赖
- 本地跑 UI 冒烟测试的方式：`pnpm run dev`（frontend 目录）+ 确认 `docker compose up -d backend-api` 已经在跑，Playwright 装在 scratchpad 临时目录、用完删除，不要留在 `frontend/` 里，参考 T0.5 交接记录里定下的规矩

## [T1.3 补充] Skill 管理页交互优化：抽屉 + 嵌套树 + 编辑器内部滚动 —— 2026-08-30

**状态**：已完成

**完成内容**（用户直接反馈的三点交互问题，逐一处理）：
- 新建/编辑从独立路由页面改成侧边抽屉：删除 `SkillCreatePage.tsx`/`SkillDetailPage.tsx` 和 `/skills/new`、`/skills/:id` 路由，新增 `components/skills/SkillEditorSheet.tsx`（shadcn `Sheet`，新增依赖）承载"名称表单 → 创建成功原地切编辑态"的完整流程；`SkillsPage.tsx` 用 `sheetOpen`/`editingId`/`openSeq` 三个 state 控制抽屉开关和内容，`key={editingId-openSeq}` 强制每次打开都重新挂载拿到干净状态（React 官方推荐的"key 重置状态"模式，而不是在 `useEffect` 里手动重置一堆 `useState`）
- 文件树从扁平列表改成真正嵌套的目录树：新增 `lib/fileTree.ts`（`buildFileTree` 建树 + `renameFile`/`renameDir`/`deleteFile`/`deleteDir`/`addFile` 操作 flat map 的纯函数）+ `components/skills/SkillFileTree.tsx`（递归渲染，可折叠展开）。树上文件/目录都支持新建、删除、重命名——"移动"复用"改路径"实现（目录改路径前缀会带着它下面所有文件一起移），同时用原生 HTML5 拖放（无额外拖放库）作为另一种移动方式；根目录是一个带"新建文件"按钮的伪节点，否则没法在根目录直接新建
- 编辑器改成内部滚动：`SheetContent` 用 `flex flex-col` + 文件树区/编辑器区各自 `min-h-0 overflow-y-auto`，`Textarea` 默认的 `field-sizing: content`（内容多高撑多高）用内联 `style={{ fieldSizing: 'fixed' }}` 覆盖掉（没用 className，因为不确定 `tailwind-merge` 认不认识这个较新的 Tailwind v4 工具类，内联样式更保险）
- 用临时装的 Playwright（用完删除）验证了完整闭环，包括原生 `DragEvent` 拖拽移动、目录改名带动子文件路径整体更新、长内容下编辑器内部滚动但抽屉本身不超出视口——具体步骤见 [TASKS.md](../TASKS.md) T1.3"决策记录（2026-08-30 交互优化追加）"小节末尾

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.3 决策记录里新增的"2026-08-30 交互优化追加"小节，要点已在上面"完成内容"里覆盖，不重复
- 目录依然不是独立实体（数据模型没变，还是 T1.2 的 `{路径: 内容}` flat map），所以没有"新建空文件夹"操作，只有"在某目录下新建文件"（文件名可以带 `/`）——这是从 T1.2 的数据模型直接推出来的限制，不是本次遗漏

**遗留问题**：
- 拖放操作没有考虑"拖到自己内部"之外更细的边界情况（比如拖到一个刚好同名但不同大小写的路径），真实使用中概率很低，v1 没做额外处理
- 编辑器依然是纯 `<Textarea>`，长文件的滚动问题解决了，但没有行号/语法高亮，T1.3 原始交接记录里提到的"要不要上 CodeMirror/Monaco"评估依然没做，留给后续真的需要时再看

**给下一个任务的建议**：
- `SkillEditorSheet.tsx` 的"抽屉 + `key` 强制重新挂载"模式，T1.5（MCP 管理前端页面）如果也想用抽屉做新建/编辑，可以直接照抄这个模式（避免在 `useEffect` 里手动重置 state 触发 lint 警告）
- `lib/fileTree.ts` 是纯函数、不依赖 Skill 领域的任何东西（只认识 `Record<string,string>` 形式的路径 map），如果以后别处也需要类似的"路径 map 建嵌套树"的能力可以直接复用，不用重新写
- 如果以后要给 `Textarea` 之类组件传新的 Tailwind v4 工具类做覆盖，记得先确认 `tailwind-merge` 版本是否认识这个类名（`clsx`+`tailwind-merge` 组合的 `cn()` helper 依赖 tailwind-merge 内置的类名冲突表，太新的工具类可能没收录，冲突时两个类都会保留，导致覆盖不生效——本次 `field-sizing-*` 就是这种情况，改用内联 `style` 绕开了）

## [T1.3 二次补充] 抽屉宽度改为 85vw + 支持新建目录 —— 2026-08-30

**状态**：已完成

**完成内容**：
- 用户看了实际效果后反馈两点，均已处理：
  1. 抽屉太窄——`SkillEditorSheet.tsx` 的 `SheetContent` 改用内联 `style={{ width: '85vw', maxWidth: '85vw' }}`（原因见下）
  2. 树上不能直接新建目录，只能靠文件路径带 `/` 隐式建出——`lib/fileTree.ts` 新增 `DIR_PLACEHOLDER_FILE = '.gitkeep'` 常量，`SkillFileTree.tsx` 的新建操作加了 `kind: 'file' | 'dir'` 区分，新建目录时实际是在这个目录下放一个空的 `.gitkeep` 文件把目录"落地"；根目录和每个目录节点的 hover 操作栏里"新建文件"旁边加了"新建目录"按钮（`FolderPlus` 图标）
- 用临时装的 Playwright（用完删除）验证：抽屉宽度确实是视口的 85%（此前用 `className="sm:max-w-4xl"` 其实完全没生效，截图能看出抽屉还是默认的窄宽度）；新建嵌套空目录 `assets/icons` → 保存 → 关闭重开（真从后端 `GET` 拉一遍，不是看本地未提交状态）→ 确认两层空目录都持久化下来了

**关键决策与偏差**：
- **抽屉宽度 className 不生效的根因**：shadcn `SheetContent` 基础组件自带 `data-[side=right]:sm:max-w-sm`，这是"属性选择器 + 断点"的组合，比我之前传的普通 `sm:max-w-4xl` 特异性更高，CSS 层面直接把我的覆盖判负——这不是 `tailwind-merge` 去重逻辑的问题（两个类名前缀都是 `max-w-`，`cn()` 其实有把旧的去重掉），是去重之后剩下的那条规则本身选择器优先级更低、赢不过组件自带的属性选择器规则。以后凡是要覆盖 shadcn 组件里带 `data-[...]:` 前缀的样式，光换 className 值不一定够，可能要么内联 `style` 强制生效（本次做法），要么用一模一样的 `data-[side=right]:` 前缀重新写一遍
- **目录用占位文件"落地"而不是改后端 schema**：T1.2 的存储模型（Postgres 只存元数据 + MinIO 一个 zip 对象，zip 内容靠 `{路径:内容}` 解压/打包）没有"空目录"的概念，改这个概念要动 T1.1 的表结构和 T1.2 的 zip 打包/解包逻辑，代价明显大于"放一个占位文件"这个前端本地就能解决的方案，v1 没有必要为了"能建空目录"这一个交互细节去动后端存储模型
- `.gitkeep` 不会在目录变得非空后自动清理，是有意识的简化（避免"什么时候该自动删除占位文件"这类边界判断逻辑），用户需要时自己在树上删掉它即可

**遗留问题**：
- 无新增遗留项，其余同 T1.3 主记录和 T1.3 交互优化记录

**给下一个任务的建议**：
- 以后如果要精确覆盖某个 shadcn 组件在特定 `data-*` 状态下的默认样式（不只是 Sheet，Dialog/Popover/Tooltip 等同源组件基本都是这个套路），先去读一下该组件生成的基础 class 字符串里有没有 `data-[...]:` 前缀，不要想当然地认为传个 className 就一定能覆盖
- `DIR_PLACEHOLDER_FILE` 这个约定（`.gitkeep`）目前只有 `lib/fileTree.ts`/`SkillFileTree.tsx` 知道，纯前端概念，后端完全不感知（后端看到的就是一个普通的空内容文件）；如果以后有其它地方也要展示/编辑 Skill 的文件树，记得这个约定，不要把 `.gitkeep` 当成普通用户文件误处理（比如展示文件数量统计时要不要排除它，看具体场景决定）

## [T1.2/T1.3 补充] Skill 保存改为版本历史（不再覆盖更新）—— 2026-08-30

**状态**：已完成

**完成内容**：
- 用户提问"现在是覆盖更新还是保存历史版本"，确认是覆盖更新后要求改成保存历史版本，并明确"不加表，在现有表加两个字段"。改动范围：
  - **数据模型**（`app/modules/skills/models.py`）：`skills` 表新增 `active_version`（Integer）、`versions`（JSONB 数组）两列；`version` 字段语义调整为"历史最新版本号，只增不减"，`object_key` 语义调整为"冗余存当前激活版本的 MinIO key"
  - **迁移**（`alembic/versions/d9597aafe1c9_skill_version_history.py`）：加列 + 一条 `UPDATE` 把老数据（当时只有覆盖更新，没有历史）的"当前状态"回填成 `versions` 列表里唯一一条记录；已验证 upgrade/downgrade 双向都能跑，且不影响本机已有的 `eli5` 这条真实数据
  - **存储**（`app/modules/skills/storage.py`）：`_object_key` 从固定 `{skill_id}.zip` 改成 `{skill_id}/v{version}.zip`，每次保存新增对象，不覆盖旧的
  - **服务层**（`app/modules/skills/service.py`）：`update_skill` 保存时用 `skill.version + 1` 生成新版本号、新增 MinIO 对象、追加 `versions`、`active_version` 跟着指向新版本；新增 `activate_version`（只移动 `active_version`/`object_key` 指针到某个历史版本，不新建版本、不改 `versions` 列表和 `version` 计数器）；`delete_skill` 改成遍历 `versions` 列表删光所有历史版本对象（原来只删一个）
  - **API**（`app/modules/skills/router.py`）：新增 `POST /skills/{id}/versions/{version}/activate`；`SkillListItem`/`SkillDetail` schema 加了 `active_version`（列表也返回）和 `versions`（详情返回）字段
  - **前端**：`skillsApi.ts` 加 `activateSkillVersion`，类型加 `active_version`/`versions`；`SkillEditorSheet.tsx` 头部加"历史版本"下拉（新增 shadcn `dropdown-menu` 组件），可以看历史版本列表、点击回滚；创建/保存/回滚三处统一走新增的 `loadDetail` helper 重新整体拉取详情，不再各自维护局部 state 更新逻辑；`SkillsPage.tsx` 列表页版本列改成 `v{active_version}`（+ 不等于最新时额外提示"最新 v{version}"）
  - `uv run pytest`（9 个用例，含扩充后的版本历史闭环）全过；前端用临时 Playwright 跑了完整闭环（连续保存产生多版本 → 历史下拉能看到全部版本 → 回滚验证内容和徽章 → 关闭重开列表页显示正确 → 回滚后再编辑验证版本号接着计数器往下走而不是从回滚点重新计）

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.2"决策记录（2026-08-30 覆盖更新改为版本历史）"小节，要点已在上面覆盖，不重复
- 回滚是"移动指针"不是"新建版本"，这个语义选择是本次的核心决策：好处是历史版本号不会因为回滚被覆盖/复用（类似 git checkout 旧 commit 后继续往前走，而不是 reset --hard 抹掉后面的历史），坏处是"当前版本"和"最新版本"可能不一致，前端因此专门加了"最新 v{version}"的提示，不能简单只显示一个版本号

**遗留问题**：
- 老数据（`eli5`）的版本历史只能从这次迁移的那一刻开始算——它之前被覆盖更新过多少次、每次改了什么，物理上已经无法恢复（旧代码从来没保留过旧对象），这是数据层面的硬限制，不是本次遗漏
- 历史版本永久保留，没有清理策略；如果以后 Skill 编辑频繁，MinIO 存储占用会一直增长，v1 没有考虑这个问题（比如"只保留最近 N 个版本"之类的策略），需要时再评估
- Playwright 测试过程中发现"点完历史版本下拉菜单项后立刻按 Escape 关不掉 Sheet"的现象（Radix 嵌套 dismissable layer 时序问题，DropdownMenu 关闭动画还没让出 layer 栈顶，Escape 被它吞了），不是本次改动引入的 bug，真实用户操作节奏基本不会碰到，也不是本次要解决的范围，只是记录一下以防以后有人也踩到觉得奇怪

**给下一个任务的建议**：
- T1.4/T1.5（MCP）如果以后也要做版本历史，`versions` JSONB + `active_version` 指针这套模式可以直接照搬，不需要重新设计
- `loadDetail` 这个"创建/保存/回滚后统一重新整体拉取详情"的模式比"各自手动拼 local state"更不容易出 bug（尤其像回滚这种内容会整体变化的操作），以后类似"操作完之后 UI 要反映服务端最新状态"的场景可以优先考虑这个模式，而不是想着"怎么从接口返回值里抠出该更新哪些 local state"
- MinIO 里现在每个 Skill 会越攒越多历史版本对象，如果以后要做"清理旧版本"之类的运维任务，遍历 `skills.versions` JSONB 数组即可拿到所有对象 key，不需要额外索引

## [T1.4] MCP Service（CRUD API） —— 2026-08-30

**状态**：已完成

**完成内容**：
- `backend-api` 新增依赖 `cryptography==44.0.0`（`uv add cryptography`）
- `app/config.py` 新增 `mcp_encryption_key`（Fernet 密钥，开发默认值已生成好，`.env.example` 同步加了 `MCP_ENCRYPTION_KEY` 及生成方式说明）
- `app/modules/mcp/models.py`：`MCPServerConfig.config`（JSONB）改成 `config_encrypted`（Text，Fernet 密文）
- `app/modules/mcp/` 新增四个文件：
  - `crypto.py` —— `encrypt_config`/`decrypt_config`，Fernet 对整份 config dict 做 JSON 序列化后加解密
  - `masking.py` —— `mask_config`（把 `env`/`headers` 两个约定字段的 value 打码成 `"********"`，key 不打码）、`merge_secret_fields`（更新时把仍是打码占位符的 value 替换回旧值，真正改过的 value 才采用新值）
  - `schemas.py` —— `StdioMCPServerConfig`/`SSEMCPServerConfig`/`HTTPMCPServerConfig` 判别联合（`type` 字段区分）+ `MCPServerCreateRequest`/`MCPServerUpdateRequest`/`MCPServerListItem`/`MCPServerDetail`
  - `service.py` —— `list_mcp_servers`/`create_mcp_server`/`get_mcp_server_detail`/`update_mcp_server`/`delete_mcp_server`，`MCPServerNotFoundError`/`MCPServerNameConflictError`
  - `router.py` —— `GET/POST /mcp`、`GET/PUT/DELETE /mcp/{id}`，整体挂 `Depends(get_current_admin)`
- `app/main.py` 挂载 `mcp_router`
- 迁移 `alembic/versions/4a51fbaabd44_mcp_server_encrypted_config.py`（autogenerate 生成，加 `config_encrypted` 列、删 `config` 列，表里本来就没有真实数据，不需要回填分支）
- `tests/test_mcp.py`（新增 4 个用例）+ `docker compose build/up backend-api` 重建镜像后用 `curl` 走了一遍真实容器的创建 → 列表 → 详情 → 删除全链路，确认所有返回里 `env.API_KEY` 都是 `********`

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.4 的"决策记录"小节，要点：config 结构用 Pydantic 判别联合对齐 SDK `mcpServers` 三种类型（stdio/sse/http）；敏感字段加密方式是"整份 config 整体用 Fernet 加密"而不是挑字段加密，存储层完全不关心 config 内部结构；脱敏展示只打码 `env`/`headers` 两个字段的 value（key 不打码，方便用户在表单里看到有哪些密钥名而不用盲改）；编辑时值仍是占位符的字段会被替换回旧值，这样"重新输入才更新"不需要前端做任何特殊处理，后端 merge 逻辑兜底
- "测试连接"能力按 TASKS 原文允许直接跳过（stdio 起子进程/sse-http 实际网络请求的复杂度和收益不成比例），未实现
- 没有做成"部分更新"接口（`PUT` 要求提交完整 config），跟 T1.2 Skill 保存的整体覆盖模式保持一致，避免维护两套"部分更新的 merge 逻辑"

**遗留问题**：
- MCP 敏感字段现在是"整份 config 加密"，如果以后 Agent Service（T2.1）/Agent Runner（T4.3）需要读取某个 MCP 配置去组装 SDK 参数，需要调用 `crypto.decrypt_config`（内部函数，当前只有 `service.get_mcp_server_detail` 用到），记得这是明文，只应该在服务端组装 SDK 调用参数时使用，不要透传给任何 API 响应
- `MCP_ENCRYPTION_KEY` 是全局单一密钥，没有做密钥轮换机制；如果以后要轮换密钥，需要一次性脚本用旧密钥解密所有 `config_encrypted`、新密钥重新加密，v1 没有考虑这个运维场景
- "测试连接"能力仍然是空白，留给以后真的需要时再评估怎么做（不同 type 的探活方式差异很大）

**给下一个任务的建议**：
- T1.5（MCP 管理前端页面）：`GET /mcp/{id}` 返回的 `config.env`/`config.headers` 里已经是打码值（`"********"`），前端表单展示这些字段时直接显示打码值即可；用户不修改就原样提交打码值回 `PUT`，后端会自动保留旧值——前端不需要自己判断"这个字段改没改过"
- 创建/编辑表单的字段应该按 `config.type` 联动显示（stdio 显示 command/args/env，sse/http 显示 url/headers），可以参考 `app/modules/mcp/schemas.py` 里三个判别联合子类型的字段定义
- `SkillEditorSheet.tsx` 的"抽屉 + key 强制重新挂载"模式（见 T1.3 交接记录）如果 T1.5 也想用抽屉做新建/编辑可以直接照抄
- T2.1（Agent Service）如果要在创建/编辑 Agent 时校验绑定的 MCP server 是否存在，直接查 `mcp_servers` 表即可，不需要解密 config；只有真正要把 MCP 配置组装进 SDK 调用参数时（这是 T4.3 的事）才需要解密

## [T1.5] MCP 管理前端页面 —— 2026-08-30

**状态**：已完成

**完成内容**：
- `frontend/src/lib/mcpApi.ts`（新增）：`StdioMCPServerConfig`/`SSEMCPServerConfig`/`HTTPMCPServerConfig` 联合类型 + `MCPServerListItem`/`MCPServerDetail` + `listMcpServers`/`getMcpServer`/`createMcpServer`/`updateMcpServer`/`deleteMcpServer`；`MASK_SENTINEL` 常量（`"********"`，需要跟后端 `masking.py` 保持一致）
- `frontend/src/lib/keyValuePairs.ts`（新增）：`KeyValuePair` 类型 + `pairsToRecord`/`recordToPairs` 两个纯函数，env/headers 通用
- `frontend/src/components/mcp/KeyValueEditor.tsx`（新增）：env/headers 通用的 key-value 行编辑器（新增/删除行）
- `frontend/src/components/mcp/McpEditorSheet.tsx`（新增）：新建/编辑复用的单表单抽屉，字段按 `type`（stdio/sse/http）联动显示；type/status 用 Button 分段控件实现，没有引入新 shadcn 组件
- `frontend/src/pages/McpPage.tsx`（重写）：列表页（名称/状态/更新时间）+ 右上角"新建 MCP Server"，点击行内名称进编辑，模式跟 `SkillsPage.tsx` 一致（`sheetOpen`/`editingId`/`openSeq` 三个 state + `key` 强制重新挂载）
- `pnpm run build`/`pnpm run lint` 均通过（唯一 warning 是 shadcn 生成文件自带的已知 warning，非本次引入）
- 手工端到端验证：本地 `pnpm run dev` + 已跑起来的 `backend-api` 容器（T1.4 代码），用临时装的 Playwright（用完即删）跑了一遍"创建 stdio（含 env）→ 重新打开确认 env 显示打码值 → 只改 args 保存确认不动 env → 改 env 为新值保存 → 创建 http（含 headers）→ 不填必填 url 被浏览器原生 required 校验拦截 → 补填后创建成功 → 重名创建触发 409 提示 → 删除两条测试数据"的完整闭环，全部通过

**关键决策与偏差**：
- 详见已回写到 [TASKS.md](../TASKS.md) T1.5 的"决策记录"小节，要点：新建/编辑是同一个表单（不像 Skill 那样先建后编两阶段）；type/status 选择器用 Button 分段控件而非新增 Select/RadioGroup 组件；env/headers 的打码值前端不做特殊识别，原样回显原样提交，脱敏语义完全在后端 `merge_secret_fields` 里处理；args 用"每行一个"的多行文本框
- 调试 Playwright 脚本时踩了两个坑，记录避免以后重复：① 用 `page.click('button:has-text("http")')` 选择"类型"分段按钮时，如果页面上已经存在名字含"http"子串的行（如已创建的 `pw-http-mcp`），`:has-text` 是子串匹配，会先匹配到表格里的行按钮而不是表单里的类型按钮，改用精确匹配 `'form button:text-is("http")'` 解决；② 测试脚本本身如果中途断言失败退出，之前几步已经创建的数据不会被清理，导致下一次重跑时"创建同名"变成真的 409 冲突（不是被测的那个 409 用例，而是意外的环境脏数据），后来在脚本开头和 catch 块里都加了一个基于真实 API 的清理步骤（按名称前缀 `pw-`/`debug-` 删除），这不是本任务代码的 bug，是测试脚本自身的幂等性问题，但值得记录避免下次调试时又被这个假象误导去怀疑应用代码有 bug

**遗留问题**：
- 编辑 MCP 配置时允许切换 `type`（比如从 stdio 切到 http），前端没有对"切换类型会丢弃另一类型已填字段"做二次确认提示，属于比较少见的操作路径，v1 没有特殊处理
- 跟 T1.3 一样，编辑表单没有"未保存改动"离开提醒，改了内容不点保存直接关闭抽屉会静默丢弃

**给下一个任务的建议**：
- T2.1/T2.2（Agent Service/Builder）如果要在表单里"勾选已有 MCP"，直接用 `listMcpServers()` 拿列表（`id`/`name`/`status`）即可，不需要关心 `config` 内部结构
- `components/mcp/KeyValueEditor.tsx` 是通用组件，不依赖 MCP 领域的任何东西（只认识 `KeyValuePair[]`），以后别的表单如果也需要"动态 key-value 行编辑"可以直接复用
- 调试这类"抽屉/弹层 + 表格行文本"混合页面的 Playwright 脚本时，涉及"类型/分类"这种可能和已有数据文本重名的按钮选择器，优先用 `text-is()`（精确匹配）或把选择器限定在表单/抽屉容器内，不要用宽泛的 `:has-text()`
