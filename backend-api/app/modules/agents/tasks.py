"""Agent Service 触发 Workspace 初始化的 Celery 生产者客户端。

backend-api 只负责把任务发到 broker（Redis），不消费、不注册任务实现——真正的任务处理器
（clone 仓库、打包快照上传 MinIO）由 agent-runner 在 T2.3 实现并注册同名任务
`"workspace.init"`（约定见 docs/TASKS.md T2.1 决策记录）。T2.3 落地前，这里发出的任务会在
broker 里排队等待，没有 worker 消费；因此发送失败或 T2.3 尚未上线都不应该阻塞 Agent 元数据的创建/编辑。
"""

from functools import lru_cache

from celery import Celery

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

WORKSPACE_INIT_TASK_NAME = "workspace.init"


@lru_cache
def _celery_producer() -> Celery:
    settings = get_settings()
    return Celery("agent-builder-backend-api", broker=settings.celery_broker_url)


def trigger_workspace_init(agent_id: str) -> None:
    """发出 workspace 初始化任务，异步执行，不等待结果。发送本身失败（如 broker 不可达）只记日志，
    不抛出——Agent 的创建/编辑接口不应该因为触发后台任务失败而失败，T2.4 会提供状态展示与手动重试入口。
    """
    try:
        _celery_producer().send_task(WORKSPACE_INIT_TASK_NAME, args=[agent_id])
    except Exception:
        logger.warning("trigger_workspace_init_failed", agent_id=agent_id, exc_info=True)
