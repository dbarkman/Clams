"""JSON API used by the browser extensions (and anyone with an API token).

Auth is `Authorization: Bearer clm_...`. The one exception is
POST /api/v1/extension/token, which trades a signed-in browser session for an
extension token; it insists on a custom header so a web page can't trigger it
cross-site.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import links, users
from .ratelimit import limiter
from .settings import settings
from .web import SESSION_COOKIE, client_ip, short_url

router = APIRouter(prefix="/api/v1")


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


def _api_user(request: Request) -> dict[str, Any] | None:
    return users.token_user(_bearer(request))


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _public(link: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": link["code"],
        "short_url": short_url(link["code"]),
        "url": link["url"],
        "title": link["title"],
        "clicks": link["click_count"],
        "created_at": link["created_at"].isoformat() + "Z",
        "last_clicked_at": link["last_clicked_at"].isoformat() + "Z" if link["last_clicked_at"] else None,
        "enabled": link["disabled_at"] is None,
        "stats_url": f"{settings.base_url}/links/{link['code']}",
    }


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


@router.post("/shorten")
async def shorten(request: Request):
    body = await _json(request)
    bearer = _bearer(request)
    user = _api_user(request)
    if bearer and user is None:
        return _err("That sign-in has expired. Please reconnect.", 401)
    ip = client_ip(request)
    if user is None and not limiter.hit(f"anon:{ip}", settings.anon_links_per_hour, 3600):
        return _err("You've made a lot of Clams this hour! Sign in for more, or try again later.", 429)
    source = "extension" if request.headers.get("x-clams-extension") else "api"
    try:
        created = links.create(
            str(body.get("url", "")),
            user_id=user["id"] if user else None,
            title=body.get("title") if isinstance(body.get("title"), str) else None,
            alias=body.get("alias") if isinstance(body.get("alias"), str) else None,
            source=source,
            creator_ip=ip,
        )
    except links.LinkError as exc:
        return _err(str(exc))
    out = _public(created.link)
    out["saved"] = user is not None
    out["reused"] = created.reused
    if created.claim_token:
        out["claim_token"] = created.claim_token
    if user is None:
        out.pop("stats_url")
    return JSONResponse(out, status_code=200 if created.reused else 201)


@router.get("/me")
def me(request: Request):
    user = _api_user(request)
    if user is None:
        return _err("Not signed in.", 401)
    return {"email": user["email"]}


@router.get("/links")
def list_links(request: Request, page: int = 1, q: str = ""):
    user = _api_user(request)
    if user is None:
        return _err("Not signed in.", 401)
    rows, total = links.list_for_user(user["id"], page=page, q=q)
    return {"links": [_public(r) for r in rows], "total": total, "page": page, "page_size": links.PAGE_SIZE}


@router.get("/links/{code}")
def get_link(request: Request, code: str):
    user = _api_user(request)
    if user is None:
        return _err("Not signed in.", 401)
    link = links.owned(code, user["id"])
    if link is None:
        return _err("Not found.", 404)
    st = links.stats(link, "all")
    out = _public(link)
    out["stats"] = {
        "clicks": st["total"],
        "unique_visitors": st["unique"],
        "bot_hits": st["bots"],
        "referrers": dict(st["referrers"]),
        "countries": dict(st["countries"]),
        "devices": dict(st["devices"]),
    }
    return out


@router.post("/links/claim")
async def claim(request: Request):
    user = _api_user(request)
    if user is None:
        return _err("Not signed in.", 401)
    body = await _json(request)
    tokens = body.get("claim_tokens")
    if not isinstance(tokens, list):
        return _err("claim_tokens must be a list.")
    return {"claimed": links.claim(user["id"], [t for t in tokens if isinstance(t, str)])}


@router.post("/extension/token")
def extension_token(request: Request):
    if request.headers.get("x-clams-extension") != "1":
        return _err("Missing extension header.", 400)
    user = users.session_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        return _err("Not signed in.", 401)
    browser = (request.headers.get("x-clams-browser") or "Browser")[:40]
    token = users.new_api_token(user["id"], f"{browser} extension", "extension")
    return {"token": token, "email": user["email"]}


@router.delete("/extension/token")
def extension_signout(request: Request):
    token = _bearer(request)
    if token:
        users.revoke_token_value(token)
    return {"ok": True}
