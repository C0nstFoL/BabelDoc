"""OIDC routes, sessions and authentication middleware."""

from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse

from .settings import (
    APP_BASE_URL,
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_ISSUER,
)

# ---- OIDC 认证 ---- #
oauth = OAuth()
oauth.register(
    name="oidc",
    server_metadata_url=f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration",
    client_id=OIDC_CLIENT_ID,
    client_secret=OIDC_CLIENT_SECRET,
    client_kwargs={"scope": "openid profile email"},
)


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("user"))


def gradio_auth_dependency(request: Request) -> str | None:
    """供 gr.mount_gradio_app 使用：从 session 中取用户标识，未登录返回 None"""
    user = request.session.get("user") or {}
    return user.get("name") or user.get("sub")


async def auth_login(request: Request):
    """跳转到 OIDC provider 登录页"""
    redirect_uri = f"{APP_BASE_URL.rstrip('/')}/auth/callback"
    return await oauth.oidc.authorize_redirect(request, redirect_uri)


async def auth_callback(request: Request):
    """OIDC 登录回调：换取 token 并写入 session"""
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception:
        return RedirectResponse(url="/auth/login")
    user = token.get("userinfo") or {}
    request.session["user"] = {
        "sub": user.get("sub"),
        "name": user.get("name") or user.get("preferred_username") or user.get("email"),
        "email": user.get("email"),
    }
    return RedirectResponse(url="/")


async def auth_logout(request: Request):
    """清除本地会话，并跳转到 OIDC provider 登出端点"""
    request.session.pop("user", None)
    metadata = await oauth.oidc.load_server_metadata()
    end_session_endpoint = metadata.get("end_session_endpoint")
    if end_session_endpoint:
        return RedirectResponse(
            url=f"{end_session_endpoint}?post_logout_redirect_uri={APP_BASE_URL.rstrip('/')}"
        )
    return RedirectResponse(url="/")


class AuthRequiredMiddleware:
    """未登录时拦截页面访问，强制跳转到 OIDC provider 登录。
    仅放行登录/回调/登出路由以及 Gradio 静态资源、心跳等接口。
    """

    _PUBLIC_PREFIXES = (
        "/auth/",
        "/static",
        "/gradio_api/heartbeat",
        "/theme.css",
        "/favicon",
    )

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith(self._PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        if _is_logged_in(request):
            await self.app(scope, receive, send)
            return
        response = RedirectResponse(url="/auth/login")
        await response(scope, receive, send)
