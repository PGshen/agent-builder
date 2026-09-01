import asyncio
import os
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import ensure_local_cache_dir
from app.config import get_settings
from app.execution import registry
from app.execution.output_sync import SOURCE_EMERGENCY_FALLBACK
from app.logging_config import configure_logging, get_logger
from app.server.execute import router as execute_router
from app.server.health import router as health_router

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


async def _emergency_shutdown() -> None:
    """SIGTERM 兜底处理（TASKS.md T4.4）：暂停正常流程，把所有仍在执行中的对话请求的输出目录
    强制打包上传回 MinIO、释放各自的 Agent 互斥锁，再终止进程。

    覆盖不到的场景（对应 TECH_DESIGN 4.5 的局限性说明）：SIGKILL、断电——进程没有机会执行任何
    代码，只能依赖 Agent 锁的短 TTL 自动过期兜底（`app/locks/agent_lock.py`），本机制不试图解决。
    """
    active = registry.snapshot()
    logger.warning("sigterm_received", active_executions=len(active))
    await asyncio.gather(
        *(entry.finalize(update_source=SOURCE_EMERGENCY_FALLBACK) for entry in active),
        return_exceptions=True,
    )
    logger.warning("emergency_shutdown_complete")
    os._exit(0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_local_cache_dir()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(_emergency_shutdown()))
    logger.info("startup_complete", app_env=settings.app_env)
    yield
    logger.info("shutdown_complete")


# 流式执行服务入口（TECH_DESIGN 4.4：Backend API 直连调用）。
app = FastAPI(title="AgentBuilder Agent Runner", lifespan=lifespan)

app.include_router(health_router)
app.include_router(execute_router)
