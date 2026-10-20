"""Application construction and HTTP server startup."""

import os
import sys

from . import settings


def _validate_auth_settings():
    if settings.AUTH_ENABLED and not all(
        (
            settings.OIDC_ISSUER,
            settings.OIDC_CLIENT_ID,
            settings.OIDC_CLIENT_SECRET,
            settings.APP_BASE_URL,
        )
    ):
        raise SystemExit(
            "AUTH_ENABLED=true requires OIDC_ISSUER, OIDC_CLIENT_ID, "
            "OIDC_CLIENT_SECRET, and APP_BASE_URL"
        )


def create_app():
    """Create an ASGI app, with session protection when OIDC is enabled."""
    _validate_auth_settings()
    import gradio as gr
    from fastapi import FastAPI

    from .ui.app import build_ui

    app = FastAPI()
    auth_dependency = None
    if settings.AUTH_ENABLED:
        from starlette.middleware.sessions import SessionMiddleware

        from .auth import (
            AuthRequiredMiddleware,
            auth_callback,
            auth_login,
            auth_logout,
            gradio_auth_dependency,
        )

        app.add_route("/auth/login", auth_login, methods=["GET"])
        app.add_route("/auth/callback", auth_callback, methods=["GET"])
        app.add_route("/auth/logout", auth_logout, methods=["GET"])
        # SessionMiddleware runs first so authentication can read request.session.
        app.add_middleware(AuthRequiredMiddleware)
        app.add_middleware(
            SessionMiddleware, secret_key=settings.SESSION_SECRET, same_site="lax"
        )
        auth_dependency = gradio_auth_dependency

    return gr.mount_gradio_app(
        app, build_ui(), path="/", auth_dependency=auth_dependency
    )


def main():
    """Keep both authenticated and standalone startup behavior."""
    _validate_auth_settings()
    if settings.AUTH_ENABLED:
        import uvicorn

        uvicorn.run(
            create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 7865))
        )
    else:
        from .ui.app import build_ui

        print("⚠️ AUTH_ENABLED 未开启，本次启动不启用登录认证保护", file=sys.stderr)
        build_ui().launch(
            server_name="0.0.0.0",
            server_port=int(os.environ.get("PORT", 7865)),
            show_error=True,
        )
