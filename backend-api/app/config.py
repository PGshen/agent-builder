from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有配置统一从环境变量读取（本地开发与容器内运行同一套读取方式）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    backend_api_port: int = 8080

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "agentbuilder"
    postgres_password: str = "agentbuilder_dev_password"
    postgres_db: str = "agentbuilder"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    # db 0/1 是 agent-runner 的 Celery broker/result backend，db 2 预留给 T4.2 Agent 互斥锁，
    # 这里单独用 db 3 存登录 token，避免几个用途的 key 空间混在一起
    auth_redis_db: int = 3

    # 极简单账号体系（非多租户）：管理员账号密码直接来自环境变量，与 Postgres/MinIO 密码同样明文存在 .env 里
    admin_username: str = "admin"
    admin_password: str = "1234"
    # 登录 token 有效期（秒），默认 7 天；到期后需要重新登录
    auth_token_ttl_seconds: int = 604800

    minio_host: str = "localhost"
    minio_port: int = 9000
    minio_root_user: str = "agentbuilder"
    minio_root_password: str = ""
    minio_bucket_skills: str = "agent-builder-skills"
    minio_bucket_workspaces: str = "agent-builder-workspaces"

    @property
    def minio_endpoint(self) -> str:
        return f"{self.minio_host}:{self.minio_port}"

    # 前端与 backend-api 不同源（本地开发时端口不同），需要显式放行 CORS；逗号分隔多个 origin
    cors_allow_origins: str = "http://localhost:5173"

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def auth_redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.auth_redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
