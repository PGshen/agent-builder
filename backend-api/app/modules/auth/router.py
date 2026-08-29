from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from app.api.deps import extract_bearer_token, get_current_admin
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import LoginRequest, LoginResponse, MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    if not auth_service.authenticate(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    token, expires_in = await auth_service.create_token(payload.username)
    return LoginResponse(token=token, expires_in=expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(authorization: str | None = Header(default=None)) -> Response:
    # 登出即撤销 token：不要求 token 仍然有效才能登出，重复调用/token 已过期时同样幂等返回 204
    token = extract_bearer_token(authorization)
    if token:
        await auth_service.revoke_token(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(username: str = Depends(get_current_admin)) -> MeResponse:
    return MeResponse(username=username)
