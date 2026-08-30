"""到期判断的纯逻辑，故意不依赖数据库连接，方便单测覆盖。"""

from datetime import datetime, timedelta

from app.db import AgentRepoSyncStatus


def is_due(status: AgentRepoSyncStatus, now: datetime) -> bool:
    """名下仓库最早一次成功同步时间为 NULL（理论上不该出现在 ready Agent 上，兜底按立即到期处理），
    或距今超过该 Agent 配置的刷新周期，判定为到期。
    """

    if status.min_last_synced_at is None:
        return True
    return now - status.min_last_synced_at >= timedelta(minutes=status.repo_refresh_interval_minutes)
