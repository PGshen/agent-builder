from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import ensure_local_cache_dir
from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.server.execute import router as execute_router
from app.server.health import router as health_router

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_local_cache_dir()
    logger.info("startup_complete", app_env=settings.app_env)
    yield
    logger.info("shutdown_complete")


# 流式执行服务入口（TECH_DESIGN 4.4：Backend API 直连调用）。
app = FastAPI(title="AgentBuilder Agent Runner", lifespan=lifespan)

app.include_router(health_router)
app.include_router(execute_router)
