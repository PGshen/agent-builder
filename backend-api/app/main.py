from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.config import get_settings
from app.db import dispose_engine, get_engine
from app.logging_config import configure_logging, get_logger
from app.modules.agents.router import router as agents_router
from app.modules.auth.router import router as auth_router
from app.modules.mcp.router import router as mcp_router
from app.modules.skills.router import router as skills_router
from app.redis_client import close_redis_client, get_redis_client

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时建立数据库连接池 / Redis 客户端（登录 token 存取用）
    get_engine()
    get_redis_client()
    logger.info("startup_complete", app_env=settings.app_env)
    yield
    await dispose_engine()
    await close_redis_client()
    logger.info("shutdown_complete")


app = FastAPI(title="AgentBuilder Backend API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(skills_router)
app.include_router(mcp_router)
app.include_router(agents_router)
