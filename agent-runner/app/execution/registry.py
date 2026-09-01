"""正在执行中的对话请求注册表（TASKS.md T4.4）。

`app/server/execute.py` 的 `_execute_stream` 在开始时注册一条 `ActiveExecution`，正常/异常/客户端
断开退出时都会调用 `finalize()` 做"输出目录同步回 MinIO + 释放互斥锁"并从注册表摘除。

进程收到 SIGTERM 时（见 `app/server/main.py`），遍历本注册表，对每一条仍在执行中的记录强制调用
`finalize(update_source=SOURCE_EMERGENCY_FALLBACK)`，覆盖"进程被信号终止前来不及走到自己 finally
块"的场景。`finalize()` 内部用每条记录自己的 `asyncio.Lock` 做互斥 + `_finalized` 标记做幂等，
保证同一条执行的输出同步/锁释放只会真正发生一次，不会因为正常路径和信号路径同时触发而重复上传。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.execution import output_sync
from app.execution.context import ExecutionContext
from app.execution.output_sync import SOURCE_CONVERSATION_SYNC
from app.locks.agent_lock import AgentLock
from app.logging_config import get_logger

logger = get_logger(__name__)


class ActiveExecution:
    def __init__(self, context: ExecutionContext, lock: AgentLock):
        self.context = context
        self.lock = lock
        self.cwd: Path | None = None
        self._finalized = False
        self._guard = asyncio.Lock()

    async def finalize(self, *, update_source: str = SOURCE_CONVERSATION_SYNC) -> None:
        async with self._guard:
            if self._finalized:
                return
            self._finalized = True

            if self.cwd is not None:
                try:
                    if update_source == SOURCE_CONVERSATION_SYNC:
                        await output_sync.sync_output_snapshot(self.context, self.cwd)
                    else:
                        await output_sync.sync_output_snapshot(
                            self.context, self.cwd, update_source=update_source
                        )
                except Exception:  # noqa: BLE001 — 同步失败不应该阻止锁释放，否则会把 Agent 卡死
                    logger.exception(
                        "output_snapshot_sync_failed",
                        agent_id=str(self.context.agent_id),
                        update_source=update_source,
                    )

            await self.lock.end_renewal()
            try:
                await self.lock.release()
            finally:
                await self.lock.close()


_active: set[ActiveExecution] = set()


def register(context: ExecutionContext, lock: AgentLock) -> ActiveExecution:
    entry = ActiveExecution(context, lock)
    _active.add(entry)
    return entry


def unregister(entry: ActiveExecution) -> None:
    _active.discard(entry)


def snapshot() -> list[ActiveExecution]:
    """返回当前所有仍在执行中的记录（用于 SIGTERM 兜底处理）。"""
    return list(_active)
