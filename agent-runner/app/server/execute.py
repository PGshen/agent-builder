"""Runner 对外暴露的流式执行接口（TASKS.md T4.3，TECH_DESIGN 4.4）：Backend API 直连调用，
处理一次完整的对话执行请求，边执行边把 SDK 消息通过这条 HTTP 连接实时推送（SSE）。

执行步骤：① 读 Agent 执行期上下文（workspace 快照版本/绑定 skills/MCP/权限模式）② 取 Agent 互斥锁，
拿不到立刻返回 409（不排队）③ 本地热缓存命中则跳过重新拉取，否则从 MinIO 拉取仓库/输出快照 + Skill zip
解压到本地 ④ 组装 SDK 参数调用执行，边跑边推流 ⑤ 执行结束（正常/异常/客户端断开都一样）把输出目录打包
同步回 MinIO、释放互斥锁。
"""

import dataclasses
import json
import uuid

from claude_agent_sdk import query
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from app.execution import context as context_module
from app.execution import registry, sdk_options, workspace_cache
from app.locks.agent_lock import AgentLock
from app.logging_config import get_logger

router = APIRouter(tags=["execution"])
logger = get_logger(__name__)


class ExecuteRequest(BaseModel):
    prompt: str
    resume_session_id: str | None = None


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"


def _message_to_event(message) -> str:
    payload = {"type": type(message).__name__, **dataclasses.asdict(message)}
    return _sse_event(payload)


@router.post("/agents/{agent_id}/execute")
async def execute(agent_id: uuid.UUID, body: ExecuteRequest) -> StreamingResponse:
    try:
        context = await context_module.load_execution_context(agent_id)
    except context_module.AgentNotReadyError as exc:
        raise HTTPException(status_code=409, detail=exc.reason) from exc

    lock = AgentLock(agent_id)
    if not await lock.acquire():
        await lock.close()
        raise HTTPException(status_code=409, detail=f"Agent {agent_id} 正忙，请稍后再试")
    lock.begin_renewal()

    return StreamingResponse(_execute_stream(context, body, lock), media_type="text/event-stream")


async def _execute_stream(context: context_module.ExecutionContext, body: ExecuteRequest, lock: AgentLock):
    entry = registry.register(context, lock)
    try:
        prepared = await workspace_cache.prepare_workspace(context)
        entry.cwd = prepared.cwd
        options = sdk_options.build_options(context, prepared, resume_session_id=body.resume_session_id)

        async for message in query(prompt=body.prompt, options=options):
            yield _message_to_event(message)
    except Exception as exc:  # noqa: BLE001 — 任何未预期异常都要让前端明确知道本次执行失败，而不是连接静默断开
        logger.exception("agent_execution_failed", agent_id=str(context.agent_id))
        yield _sse_event({"type": "ExecutionError", "message": str(exc)})
    finally:
        # 正常完成/SDK 异常/客户端断开都走到这里；进程被 SIGTERM 提前终止的场景由
        # `app/server/main.py` 的信号处理器通过 `registry.snapshot()` 兜底调用 `entry.finalize()`。
        # `entry.finalize()` 自身做了幂等处理，两边谁先执行都不会导致重复上传/重复释放锁。
        await entry.finalize()
        registry.unregister(entry)
