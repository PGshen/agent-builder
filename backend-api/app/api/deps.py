from fastapi import Header, HTTPException, status

from app.modules.auth import service as auth_service

_BEARER_PREFIX = "Bearer "


def extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        return None
    token = authorization[len(_BEARER_PREFIX) :].strip()
    return token or None


async def get_current_admin(authorization: str | None = Header(default=None)) -> str:
    """所有业务接口的鉴权依赖项：`router = APIRouter(dependencies=[Depends(get_current_admin)])`
    或单个路由 `Depends(get_current_admin)` 均可接入，未登录/token 无效或过期统一返回 401。"""
    token = extract_bearer_token(authorization)
    username = await auth_service.get_username_for_token(token) if token else None
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已过期")
    return username
