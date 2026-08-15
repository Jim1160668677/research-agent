"""JWT 认证与授权模块

提供:
- Token 创建与验证
- 当前用户依赖注入
- 角色权限检查
- 公开路由白名单
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from .app import settings

bearer_scheme = HTTPBearer(auto_error=False)

# 公开路由白名 (不需要认证)
PUBLIC_PATHS = {
    "/health",
    "/api/v1/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/bootstrap",
    "/api/v1/auth/status",
    "/api/v1/auth/setup",
}


def _get_secret() -> str:
    """获取 JWT 密钥，强制验证非默认值"""
    secret = settings.jwt_secret
    if not secret or secret == "dev-secret-key-change-in-production":
        raise RuntimeError(
            "JWT_SECRET 未配置。请在 .env 或环境变量中设置强密钥。"
        )
    return secret


def create_access_token(
    user_id: int,
    username: str,
    role: str = "researcher",
    expires_delta: timedelta | None = None,
) -> str:
    """创建 JWT Access Token"""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=24)
    )
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    secret = _get_secret()
    token = jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)
    return token


def create_refresh_token(
    user_id: int,
    expires_delta: timedelta | None = None,
) -> str:
    """创建 Refresh Token (更长生命周期)"""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=7)
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    secret = _get_secret()
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """解码并验证 JWT"""
    secret = _get_secret()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"无效的 Token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """FastAPI 依赖: 获取当前认证用户

    优先使用中间件注入的用户信息 (debug 模式或已通过 JWT 验证)。
    否则从 Authorization header 解析 JWT。
    """
    # debug 模式: 中间件已注入用户信息
    if settings.debug:
        state_dict = request.scope.get("state", {})
        if "user" in state_dict:
            user = state_dict["user"]
            logger.debug(f"debug 模式: 使用注入用户 {user}")
            return user
        if hasattr(request.state, "user"):
            user = request.state.user
            logger.debug(f"debug 模式: state.user = {user}")
            return user

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Token 类型",
        )

    user_id = int(payload["sub"])
    return {
        "user_id": user_id,
        "username": payload.get("username", ""),
        "role": payload.get("role", "researcher"),
    }


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict | None:
    """可选认证: 如果提供了有效 token 则返回用户信息，否则返回 None"""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            return None
        return {
            "user_id": int(payload["sub"]),
            "username": payload.get("username", ""),
            "role": payload.get("role", "researcher"),
        }
    except HTTPException:
        return None


def require_role(*roles: str):
    """创建角色校验依赖"""
    async def _check(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要角色: {', '.join(roles)}",
            )
        return current_user
    return _check


class AuthMiddleware:
    """FastAPI 中间件: 为所有请求添加认证检查

    公开路径 (PUBLIC_PATHS) 和 OPTIONS 请求跳过认证。
    debug 模式下自动注入测试用户，方便开发与测试。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # 跳过公开路径和 OPTIONS 预检
        if method == "OPTIONS" or self._is_public(path):
            await self.app(scope, receive, send)
            return

        # debug 模式: 跳过 JWT 验证，注入默认测试用户
        if settings.debug:
            user_payload = {
                "user_id": 1,
                "username": "dev_user",
                "role": "admin",
            }
            # 通过中间件注入方式让 get_current_user 依赖可读取
            scope.setdefault("state", {})["user"] = user_payload

            # 包装 send 以将 user 传递到后续中间件/路由
            async def send_with_user(message):
                await send(message)

            # 直接在 scope 上暴露 user，Starlette 会复制到 Request.state
            scope["state"]["user"] = user_payload
            # 注意: Starlette 的 Request 在 ASGI 生命周期早期从 scope 拷贝 state，
            # 因此我们在此处注入并通过自定义方式保证可见性
            await self.app(scope, receive, send)
            return

        # 检查 Authorization header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if not auth_header.startswith("Bearer "):
            response = self._unauthorized_response()
            await response(scope, receive, send)
            return

        token = auth_header[7:]
        try:
            payload = decode_token(token)
            # 将用户信息注入 request state
            scope.setdefault("state", {})["user"] = {
                "user_id": int(payload["sub"]),
                "username": payload.get("username", ""),
                "role": payload.get("role", "researcher"),
            }
        except HTTPException as e:
            response = self._error_response(e.status_code, e.detail)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _is_public(path: str) -> bool:
        # The bundled SPA and its hashed assets must load before a browser can
        # obtain a token. Only API paths are protected by JWT middleware.
        if not path.startswith("/api/"):
            return True
        for public in PUBLIC_PATHS:
            if path == public or path.startswith(public + "/"):
                return True
        return False

    @staticmethod
    def _unauthorized_response():
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "未认证"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @staticmethod
    def _error_response(code: int, detail: str):
        from starlette.responses import JSONResponse
        return JSONResponse(status_code=code, content={"detail": detail})


__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_current_user",
    "get_optional_user",
    "require_role",
    "AuthMiddleware",
    "PUBLIC_PATHS",
    "bearer_scheme",
]
