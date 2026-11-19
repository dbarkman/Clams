"""Signed-in pages: your Clams, one Clam's stats, account settings, extension connect."""

from __future__ import annotations

import csv
import io
import math

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import links, users
from .security import csrf_valid
from .web import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    check_csrf,
    cookie_kwargs,
    message_page,
    redirect,
    render,
    require_user,
    short_url,
)

router = APIRouter()


@router.get("/links")
def my_links(request: Request, q: str = "", page: int = 1):
    user = require_user(request)
    rows, total = links.list_for_user(user["id"], page=page, q=q.strip())
    pages = max(1, math.ceil(total / links.PAGE_SIZE))
    return render(request, "links.html", links=rows, total=total, q=q, page=page, pages=pages)


@router.get("/links/export.csv")
def export_csv(request: Request):
    user = require_user(request)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["short_url", "destination", "title", "clicks", "created_utc", "last_click_utc", "status"])
    for r in links.all_for_user(user["id"]):
        w.writerow([
            short_url(r["code"]), r["url"], r["title"] or "", r["click_count"],
            r["created_at"].isoformat(sep=" ", timespec="seconds"),
            r["last_clicked_at"].isoformat(sep=" ", timespec="seconds") if r["last_clicked_at"] else "",
            "off" if r["disabled_at"] else "on",
        ])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="my-clams.csv"'})


def _chart(series):
    """Bars for the clicks-per-day chart, sized in SVG units (600 x 160)."""
    if not series:
        return {"bars": [], "max": 0, "labels": []}
    peak = max(n for _, n in series) or 1
    w = 600 / len(series)
    bars = []
    for i, (d, n) in enumerate(series):
        h = 0 if n == 0 else max(2.0, 150 * n / peak)
        bars.append({"x": round(i * w + w * 0.12, 2), "w": round(max(w * 0.76, 0.6), 2), "h": round(h, 2),
                     "y": round(160 - h, 2), "n": n, "d": d})
    step = max(1, len(series) // 6)
    labels = [{"x": round(i * w + w / 2, 2), "t": d.strftime("%b %-d")} for i, (d, _) in enumerate(series)
              if i % step == 0]
    return {"bars": bars, "max": peak, "labels": labels}


@router.get("/links/{code}")
def link_detail(request: Request, code: str, range: str = "30d", new: int = 0):
    user = require_user(request)
    link = links.owned(code, user["id"])
    if link is None:
        return message_page(request, "Not one of your Clams", "We couldn't find that Clam in your account.", 404, "🦀")
    st = links.stats(link, range)
    return render(request, "link.html", link=link, stats=st, chart=_chart(st["series"]), new=new)


@router.post("/links/{code}/edit")
async def link_edit(request: Request, code: str):
    await check_csrf(request)
    user = require_user(request)
    link = links.owned(code, user["id"])
    if link is None:
        return redirect("/links", "We couldn't find that Clam.", "err")
    form = await request.form()
    try:
        links.edit(link, url=str(form.get("url", link["url"])), title=str(form.get("title", "")))
    except links.LinkError as exc:
        return redirect(f"/links/{code}", str(exc), "err")
    return redirect(f"/links/{code}", "Saved.")


@router.post("/links/{code}/toggle")
async def link_toggle(request: Request, code: str):
    await check_csrf(request)
    user = require_user(request)
    link = links.owned(code, user["id"])
    if link is None:
        return redirect("/links", "We couldn't find that Clam.", "err")
    if link["disabled_reason"] and link["disabled_reason"].startswith("admin:"):
        return redirect(f"/links/{code}", "This Clam was turned off for breaking our rules.", "err")
    turning_off = link["disabled_at"] is None
    links.set_disabled(link["id"], turning_off, "owner" if turning_off else None)
    return redirect(f"/links/{code}", "Clam turned off. It won't redirect until you turn it back on."
                    if turning_off else "Clam is back on.")


@router.post("/links/{code}/delete")
async def link_delete(request: Request, code: str):
    await check_csrf(request)
    user = require_user(request)
    link = links.owned(code, user["id"])
    if link is None:
        return redirect("/links", "We couldn't find that Clam.", "err")
    links.delete(link["id"])
    return redirect("/links", f"Deleted {code}. That short link no longer works.")


# --- account ---------------------------------------------------------------


@router.get("/account")
def account(request: Request):
    user = require_user(request)
    new_token = request.cookies.get("clams_new_token")
    resp = render(
        request, "account.html",
        tokens=users.list_tokens(user["id"]), identities=users.identities(user["id"]), new_token=new_token,
    )
    if new_token:
        resp.delete_cookie("clams_new_token", path="/account")
    return resp


@router.post("/account/password")
async def account_password(request: Request):
    await check_csrf(request)
    user = require_user(request)
    form = await request.form()
    from .security import verify_password

    if user["password_hash"] and not verify_password(user["password_hash"], str(form.get("current", ""))):
        return redirect("/account", "Your current password didn't match.", "err")
    try:
        users.set_password(user["id"], str(form.get("password", "")))
    except users.AccountError as exc:
        return redirect("/account", str(exc), "err")
    return redirect("/account", "Password saved.")


@router.post("/account/tokens")
async def account_token_new(request: Request):
    await check_csrf(request)
    user = require_user(request)
    form = await request.form()
    token = users.new_api_token(user["id"], str(form.get("label", "")) or "API token", "api")
    resp = redirect("/account", "New API token created. Copy it now — it's only shown once.")
    # One-time display survives the redirect (post/redirect/get) and is cleared on first view.
    resp.set_cookie("clams_new_token", token, max_age=120, **cookie_kwargs(samesite="strict", path="/account"))
    return resp


@router.post("/account/tokens/{token_id}/revoke")
async def account_token_revoke(request: Request, token_id: int):
    await check_csrf(request)
    user = require_user(request)
    users.revoke_token(user["id"], token_id)
    return redirect("/account", "Access removed.")


@router.post("/account/delete")
async def account_delete(request: Request):
    await check_csrf(request)
    user = require_user(request)
    form = await request.form()
    if str(form.get("confirm", "")).strip().lower() != user["email"]:
        return redirect("/account", "Type your email exactly to confirm deleting your account.", "err")
    users.delete_account(user["id"])
    resp = redirect("/", "Your account and its Clams are deleted. Take care!")
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# --- browser extension connect ---------------------------------------------


@router.get("/extension/connect")
def extension_connect(request: Request):
    require_user(request)
    return render(request, "connect.html")


@router.post("/extension/connect/token")
async def extension_connect_token(request: Request):
    """Called by the connect page's own script; the extension's content script relays the token."""
    user = require_user(request)
    if not csrf_valid(request.cookies.get(CSRF_COOKIE), request.headers.get("x-csrf-token")):
        return JSONResponse({"error": "csrf"}, status_code=400)
    browser = (request.headers.get("x-clams-browser") or "Browser")[:40]
    token = users.new_api_token(user["id"], f"{browser} extension", "extension")
    return JSONResponse({"token": token, "email": user["email"]})
