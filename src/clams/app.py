"""The cla.ms application."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import routes_account, routes_admin, routes_api, routes_auth, routes_public
from .web import CSRF_COOKIE, HERE, LoginRequired, cookie_kwargs, message_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.middleware("http")
    async def csrf_cookie_and_headers(request: Request, call_next):
        response = await call_next(request)
        new = getattr(request.state, "new_csrf", None)
        if new:
            response.set_cookie(CSRF_COOKIE, new, max_age=60 * 60 * 24 * 30, **cookie_kwargs())
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
                "form-action 'self' https://accounts.google.com https://appleid.apple.com; "
                "frame-ancestors 'none'; base-uri 'none'",
            )
        return response

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired):
        from urllib.parse import quote

        return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        if exc.status_code == 404:
            return message_page(
                request, "No Clam here", "We couldn't find that page. Double-check the link?", 404, "🦀"
            )
        return message_page(request, "Hmm, that didn't work", str(exc.detail), exc.status_code, "🌊")

    app.include_router(routes_api.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_account.router)
    app.include_router(routes_admin.router)
    # Public last: it owns the /{code} catch-all.
    app.include_router(routes_public.router)
    return app


app = create_app()

__all__ = ["app", "FastAPIHTTPException"]
