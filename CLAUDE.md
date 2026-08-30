# AgentBuilder

基于 Claude Agent SDK 的 Agent 管理平台：可视化管理 Skills、MCP、Agent（绑定 skills/MCP/代码仓库），提供对话页面与 API，容器化部署。

## 文档地图

- [docs/PRD.md](docs/PRD.md) —— 产品需求与关键架构决策（部署形态、状态分层、workspace 存储方案等）
- [docs/TECH_DESIGN.md](docs/TECH_DESIGN.md) —— 系统级技术方案（技术栈、模块划分、关键流程、数据模型、部署拓扑）
- [docs/TASKS.md](docs/TASKS.md) —— 任务清单，每个任务含目标、关键实现决策、验收标准
- [docs/PROGRESS.md](docs/PROGRESS.md) —— 任务进度跟踪表
- [docs/HANDOFF.md](docs/HANDOFF.md) —— 任务交接记录，按时间顺序追加，每条记录写完成内容、关键决策与偏差、遗留问题、给下一个任务的建议

五份文档的关系：PRD/TECH_DESIGN 是"决策记录"，TASKS 是决策落到可执行的任务粒度，PROGRESS 是任务状态的实时记录，HANDOFF 是每个任务结束时留给下一个任务的交接说明。**任何一份文档过时都可能导致后续工作建立在错误前提上**，所以必须维护同步。

## 执行流程

开始工作前：
1. 读 [docs/PROGRESS.md](docs/PROGRESS.md)，确认当前应该做哪个/哪些任务（按 Phase 顺序推进，不要跳过前置依赖任务；同一 Phase 内没有依赖关系的任务可以并行）
2. 读 [docs/TASKS.md](docs/TASKS.md) 里对应任务的"目标 / 关键实现决策 / 验收标准"
3. 读 [docs/HANDOFF.md](docs/HANDOFF.md) 末尾最近几条记录，尤其是前置任务的"遗留问题"和"给下一个任务的建议"，避免重复踩坑或漏掉别人已经交代过的注意事项
4. 若任务描述里的关键实现决策与 PRD/TECH_DESIGN 已有决策冲突或有遗漏，先回到 PRD/TECH_DESIGN 补充/修正决策，再回来更新 TASKS 里的任务描述，然后才开始实现——不要在代码里悄悄绕过或重新发明设计

实现过程中：
- 严格对照该任务的"验收标准"自查，标准里写的是可观察/可验证的行为，不是"写完代码"就算完成
- 遇到文档未覆盖的新决策点（哪怕很小），先记录到 PRD/TECH_DESIGN 或任务描述里，再继续写代码，保持"文档是决策的唯一来源"

**每次执行完一个任务后（包括中途受阻的情况），必须做三件事**：
1. 更新 [docs/PROGRESS.md](docs/PROGRESS.md) 对应任务的状态（未开始 / 进行中 / 已完成 / 阻塞），备注列可以简短，指向 HANDOFF.md 里的详细记录
2. 如果实现过程中做出了任务描述之外的新决策，同步更新 [docs/TASKS.md](docs/TASKS.md)（以及必要时 PRD/TECH_DESIGN），不要让文档与实际实现脱节
3. 在 [docs/HANDOFF.md](docs/HANDOFF.md) 末尾按模板追加一条交接记录：完成内容、关键决策与偏差、遗留问题、给下一个任务的建议——哪怕任务是顺利完成的，也要写，方便下一个任务/下一次会话快速接手而不用重新读代码猜实现细节

一个任务只完成一部分、或者中途受阻时，也要如实更新状态为"进行中"或"阻塞"并写清楚卡在哪里，不要等任务全部做完才更新。

**每次任务结束后的最终总结，必须使用中文回复。**
