from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """所有配置统一从环境变量读取（与 backend-api/agent-runner 的约定一致）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "agentbuilder"
    postgres_password: str = "agentbuilder_dev_password"
    postgres_db: str = "agentbuilder"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    # 与 agent-runner 共用同一个 broker db，"workspace.refresh_repos" 任务发到这里由 Runner 消费（T3.2）
    celery_broker_db: int = 0
    celery_result_db: int = 1
    # 派发去重锁专用 db index，独立于 broker/result backend 和 T4.2 预留的 db 2，避免 key 空间混用
    scheduler_lock_db: int = 4

    # 固定扫描周期：每隔这么多秒查一次哪些 Agent 到期该刷新仓库了
    scheduler_scan_interval_seconds: int = 60
    # 派发去重锁的 TTL：同一个 Agent 在锁未过期前不会被重复派发，需覆盖典型 clone+打包耗时
    scheduler_dispatch_lock_ttl_seconds: int = 600

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
    def celery_broker_url(self) -> str:
        return self._redis_url(db=self.celery_broker_db)

    @property
    def celery_result_backend(self) -> str:
        return self._redis_url(db=self.celery_result_db)

    @property
    def scheduler_lock_redis_url(self) -> str:
        return self._redis_url(db=self.scheduler_lock_db)


@lru_cache
def get_settings() -> Settings:
    return Settings()
