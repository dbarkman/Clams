"""Shared request helpers: who is signed in, CSRF, flash messages, rendering."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import users
from .security import csrf_valid
from .settings import settings

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

SESSION_COOKIE = "clams_session"
CSRF_COOKIE = "clams_csrf"
FLASH_COOKIE = "clams_flash"
CLAIMS_COOKIE = "clams_claims"
MAX_CLAIMS_IN_COOKIE = 60  # cookie size, not policy: ~3 KB of tokens


def flag(code: str | None) -> str:
    if not code or len(code) != 2 or not code.isalpha():
        return "🏳️"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


def short_url(code: str) -> str:
    return f"{settings.base_url}/{code}"


def display_short(code: str) -> str:
    return f"{settings.short_host}/{code}"


templates.env.filters["flag"] = flag
templates.env.globals.update(
    settings=settings, short_url=short_url, display_short=display_short, quote=quote
)


def cookie_kwargs(**extra: Any) -> dict[str, Any]:
    return {"secure": settings.secure_cookies, "httponly": True, "samesite": "lax", "path": "/", **extra}


def current_user(request: Request) -> dict[str, Any] | None:
    if not hasattr(request.state, "user"):
        request.state.user = users.session_user(request.cookies.get(SESSION_COOKIE))
    return request.state.user


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user is None:
        raise LoginRequired(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
    return user


class LoginRequired(Exception):
    def __init__(self, next_url: str) -> None:
        self.next_url = next_url


def safe_next(value: str | None, default: str = "/links") -> str:
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return default


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def csrf_token(request: Request) -> str:
    token = request.cookies.get(CSRF_COOKIE) or getattr(request.state, "new_csrf", None)
    if not token:
        token = secrets.token_urlsafe(24)
        request.state.new_csrf = token
    return token


async def check_csrf(request: Request) -> None:
    form = await request.form()
    if not csrf_valid(request.cookies.get(CSRF_COOKIE), form.get("csrf")):
        raise HTTPException(status_code=400, detail="Your form expired. Please go back, refresh and try again.")


def flash(response: Response, message: str, kind: str = "ok") -> Response:
    response.set_cookie(FLASH_COOKIE, quote(json.dumps({"m": message, "k": kind})), max_age=60, **cookie_kwargs())
    return response


def redirect(url: str, message: str | None = None, kind: str = "ok") -> RedirectResponse:
    resp = RedirectResponse(url, status_code=303)
    if message:
        flash(resp, message, kind)
    return resp


def render(request: Request, template: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    from urllib.parse import unquote

    message = None
    raw = request.cookies.get(FLASH_COOKIE)
    if raw:
        try:
            message = json.loads(unquote(raw))
        except ValueError:
            message = None
    ctx.setdefault("user", current_user(request))
    resp = templates.TemplateResponse(
        request, template, {"csrf": csrf_token(request), "flash": message, **ctx}, status_code=status_code
    )
    if raw:
        resp.delete_cookie(FLASH_COOKIE, path="/")
    return resp


def message_page(request: Request, title: str, body: str, status_code: int = 200, emoji: str = "🐚") -> HTMLResponse:
    return render(request, "message.html", status_code=status_code, title=title, body=body, emoji=emoji)


# --- claims cookie: anonymous Clams made in this browser -------------------


def read_claims(request: Request) -> list[str]:
    raw = request.cookies.get(CLAIMS_COOKIE, "")
    return [t for t in raw.split(".") if t.startswith("clc_")] if raw else []


def add_claim(request: Request, response: Response, token: str) -> None:
    tokens = (read_claims(request) + [token])[-MAX_CLAIMS_IN_COOKIE:]
    response.set_cookie(CLAIMS_COOKIE, ".".join(tokens), max_age=60 * 60 * 24 * 365, **cookie_kwargs())


def sign_in(request: Request, response: Response, user: dict[str, Any]) -> int:
    """Start a session on `response`; returns how many anonymous Clams were claimed."""
    from . import links

    token = users.start_session(user["id"], request.headers.get("user-agent"))
    response.set_cookie(SESSION_COOKIE, token, max_age=60 * 60 * 24 * users.SESSION_DAYS, **cookie_kwargs())
    claimed = links.claim(user["id"], read_claims(request))
    response.delete_cookie(CLAIMS_COOKIE, path="/")
    return claimed
