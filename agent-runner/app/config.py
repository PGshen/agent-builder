from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有配置统一从环境变量读取（本地开发与容器内运行同一套读取方式，参照 backend-api 的约定）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    agent_runner_http_port: int = 8100

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "agentbuilder"
    postgres_password: str = "agentbuilder_dev_password"
    postgres_db: str = "agentbuilder"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    # Celery broker/result backend 各用独立 db index，与 T4.2 的 Agent 互斥锁（db 2）分开，避免 key 混用
    celery_broker_db: int = 0
    celery_result_db: int = 1
    agent_lock_db: int = 2

    # Agent 互斥锁：单次续期后的存活时长；持锁方每隔 renew_interval 续期一次，
    # ttl 需明显大于 renew_interval，避免网络抖动导致续期还没到就已经过期被别的请求抢走
    agent_lock_ttl_seconds: int = 60
    agent_lock_renew_interval_seconds: int = 20

    minio_host: str = "localhost"
    minio_port: int = 9000
    minio_root_user: str = "agentbuilder"
    minio_root_password: str = ""
    minio_bucket_skills: str = "agent-builder-skills"
    minio_bucket_workspaces: str = "agent-builder-workspaces"

    # Workspace clone/快照合并期间使用的本地临时磁盘路径（本任务只预留配置项，不含 workspace 逻辑）
    runner_local_cache_dir: str = "./.cache/agent-runner"

    # Agent 绑定仓库鉴权凭证（auth_credential）的对称加密密钥，与 backend-api 共用同一个值
    # （T2.1 决策：独立于 MCP_ENCRYPTION_KEY 的专属密钥），Runner 侧用它解密后才能 clone 私有仓库
    agent_repo_encryption_key: str = ""
    # 单个仓库 clone 的超时时间（秒），超时视为该仓库 clone 失败，整体 workspace 初始化任务标记失败
    workspace_clone_timeout_seconds: int = 300

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def _redis_url(self, db: int) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{db}"

    @property
    def redis_url(self) -> str:
        return self._redis_url(db=0)

    @property
    def celery_broker_url(self) -> str:
        return self._redis_url(db=self.celery_broker_db)

    @property
    def celery_result_backend(self) -> str:
        return self._redis_url(db=self.celery_result_db)

    @property
    def agent_lock_redis_url(self) -> str:
        return self._redis_url(db=self.agent_lock_db)

    @property
    def minio_endpoint(self) -> str:
        return f"{self.minio_host}:{self.minio_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
