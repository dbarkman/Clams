"""Home page, shortening, the redirect itself, previews, QR codes and info pages."""

from __future__ import annotations

import io

import segno
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

from . import geo, links
from .db import reports, tx, utcnow
from .ratelimit import limiter
from .security import keyed_hash
from .settings import settings
from .web import (
    add_claim,
    check_csrf,
    client_ip,
    current_user,
    message_page,
    redirect,
    render,
    short_url,
)

router = APIRouter()


@router.get("/")
def home(request: Request):
    user = current_user(request)
    recent = links.list_for_user(user["id"])[0][:10] if user else []
    return render(request, "home.html", recent=recent)


@router.post("/shorten")
async def shorten(request: Request):
    await check_csrf(request)
    form = await request.form()
    user = current_user(request)
    ip = client_ip(request)
    if user is None and not limiter.hit(f"anon:{ip}", settings.anon_links_per_hour, 3600):
        return redirect("/", "You've made a lot of Clams this hour! Sign in for more, or try again later.", "err")
    try:
        created = links.create(
            str(form.get("url", "")),
            user_id=user["id"] if user else None,
            alias=str(form.get("alias", "")) if user else None,
            title=str(form.get("title", "")) or None,
            source="web",
            creator_ip=ip,
        )
    except links.LinkError as exc:
        return redirect("/", str(exc), "err")
    code = created.link["code"]
    if user:
        msg = "You already had a Clam for that link — here it is." if created.reused else None
        return redirect(f"/links/{code}?new=1", msg)
    resp = redirect(f"/new/{code}")
    if created.claim_token:
        add_claim(request, resp, created.claim_token)
    return resp


@router.get("/new/{code}")
def new_link(request: Request, code: str):
    link = links.by_code(code)
    if link is None or link["deleted_at"]:
        return message_page(request, "No Clam here", "We couldn't find that Clam.", 404, "🦀")
    return render(request, "new.html", link=link)


@router.get("/healthz")
def healthz():
    from sqlalchemy import text

    with tx() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nAllow: /$\nAllow: /about\nAllow: /extension\nAllow: /privacy\nAllow: /terms\nDisallow: /\n"


@router.get("/favicon.ico")
def favicon():
    return RedirectResponse("/static/favicon.svg", status_code=301)


@router.get("/about")
def about(request: Request):
    return render(request, "about.html")


@router.get("/privacy")
def privacy(request: Request):
    return render(request, "privacy.html")


@router.get("/terms")
def terms(request: Request):
    return render(request, "terms.html")


@router.get("/extension")
def extension(request: Request):
    return render(request, "extension.html")


@router.get("/report")
def report_form(request: Request, code: str = ""):
    return render(request, "report.html", code=code)


@router.post("/report")
async def report_submit(request: Request):
    await check_csrf(request)
    form = await request.form()
    raw = str(form.get("code", "")).strip()
    # Accept a full short URL or just the code.
    code = raw.rstrip("/+").rsplit("/", 1)[-1]
    reason = str(form.get("reason", "other"))[:32]
    ip = client_ip(request)
    if not limiter.hit(f"report:{ip}", 20, 3600):
        return redirect("/report", "Thanks — we've got a lot of reports from you already. Try again later.", "err")
    if not code or links.by_code(code) is None:
        return redirect("/report", "We couldn't find that Clam. Paste the full cla.ms link.", "err")
    with tx() as conn:
        conn.execute(
            reports.insert().values(
                code=code,
                reason=reason,
                details=str(form.get("details", ""))[:5000] or None,
                reporter_email=str(form.get("email", "")).strip()[:254] or None,
                reporter_hash=keyed_hash("reporter", ip or ""),
                created_at=utcnow(),
            )
        )
    return redirect("/", "Thanks for the report. We'll take a look.")


def _qr(code: str):
    link = links.by_code(code)
    if link is None or link["deleted_at"] or link["disabled_at"]:
        return None
    return segno.make(short_url(code), error="m")


@router.get("/qr/{code}.svg")
def qr_svg(code: str):
    qr = _qr(code)
    if qr is None:
        return Response(status_code=404)
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=8, border=2, dark="#0b2a3a", xmldecl=False)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/qr/{code}.png")
def qr_png(code: str, download: int = 0):
    qr = _qr(code)
    if qr is None:
        return Response(status_code=404)
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=16, border=2, dark="#0b2a3a")
    headers = {"Cache-Control": "public, max-age=86400"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="clam-{code}.png"'
    return Response(buf.getvalue(), media_type="image/png", headers=headers)


def _log_click(link_id: int, ip, ua, ref) -> None:
    links.record_click(link_id, ip=ip, user_agent=ua, referrer=ref, country=geo.country(ip))


@router.api_route("/{code}", methods=["GET", "HEAD"])
def follow(request: Request, code: str, background: BackgroundTasks):
    preview = code.endswith("+")
    code = code.rstrip("+")
    link = links.by_code(code)
    if link is None:
        return message_page(request, "No Clam here", "That short link doesn't exist. Check for a typo — Clams are case-sensitive.", 404, "🦀")
    if link["deleted_at"]:
        return message_page(request, "This Clam is gone", "Its owner deleted this short link.", 410, "🫧")
    if link["disabled_at"]:
        return message_page(
            request,
            "This Clam is closed",
            "This short link has been turned off.",
            410,
            "🔒",
        )
    if preview:
        return render(request, "preview.html", link=link)
    if request.method == "GET":
        background.add_task(
            _log_click, link["id"], client_ip(request), request.headers.get("user-agent"), request.headers.get("referer")
        )
    return RedirectResponse(link["url"], status_code=302, headers={"Cache-Control": "private, no-store"})
