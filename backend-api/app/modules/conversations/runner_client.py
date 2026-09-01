"""对 Agent Runner 流式执行接口（T4.3 `POST /agents/{agent_id}/execute`）的直连调用封装。

不经 Celery/Redis 转发（TECH_DESIGN 4.4）：Backend API 直接向 Agent Runner 发一次 HTTP 请求，
经 Compose 服务名 DNS 轮询分发到任意空闲副本。Runner 自身已经实现了 Agent 互斥锁（T4.2/T4.3），
获取失败时直接返回 HTTP 409——本模块原样把这个状态码/detail 透传给调用方，不在 Backend API 侧
重复加一层锁（TECH_DESIGN 4.4 步骤 2 提到的"用 Redis 对该 Agent 加互斥锁"由 Runner 一侧落地，
详见 TASKS.md T4.5 决策记录）。
"""

import json
import uuid

import httpx

from app.config import get_settings


class RunnerRequestError(Exception):
    """Runner 返回了非 200（Agent 正忙 409 / Agent 未就绪 409 / 其他异常状态），或连接不上 Runner。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _extract_detail(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    return parsed.get("detail", text) if isinstance(parsed, dict) else text


def build_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.agent_runner_base_url,
        timeout=httpx.Timeout(settings.agent_runner_connect_timeout_seconds, read=None),
    )


async def open_execute_stream(
    client: httpx.AsyncClient, agent_id: uuid.UUID, prompt: str, resume_session_id: str | None
) -> httpx.Response:
    """建立到 Runner `/agents/{agent_id}/execute` 的流式连接。返回值是已经 `stream=True` 发送的
    `httpx.Response`——状态码非 200 时调用方需要自行 `aread()`/`aclose()`（本函数不在这里读取 body，
    因为 200 时 body 就是要转发给前端的 SSE 流，不能提前消费）。连接失败（DNS/网络错误）直接抛
    `RunnerRequestError(502, ...)`。
    """
    try:
        response = await client.send(
            client.build_request(
                "POST",
                f"/agents/{agent_id}/execute",
                json={"prompt": prompt, "resume_session_id": resume_session_id},
            ),
            stream=True,
        )
    except httpx.RequestError as exc:
        raise RunnerRequestError(502, f"无法连接 Agent Runner：{exc}") from exc

    if response.status_code != 200:
        detail = _extract_detail(await response.aread())
        await response.aclose()
        raise RunnerRequestError(response.status_code, detail)

    return response
