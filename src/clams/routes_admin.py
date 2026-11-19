"""Admin: abuse reports, turning Clams off, blocking whole domains."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, select, update

from . import links, urls
from .db import blocked_domains, reports, tx, utcnow
from .db import links as links_t
from .web import check_csrf, redirect, render, require_user

router = APIRouter(prefix="/admin")


def _admin(request: Request):
    user = require_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=404, detail="Not found")
    return user


@router.get("")
def admin_home(request: Request, code: str = ""):
    _admin(request)
    with tx() as conn:
        open_reports = [dict(r._mapping) for r in conn.execute(
            select(reports).where(reports.c.resolved_at.is_(None)).order_by(reports.c.created_at.desc())
        )]
        blocked = [dict(r._mapping) for r in conn.execute(select(blocked_domains).order_by(blocked_domains.c.domain))]
    found = links.by_code(code.strip().rstrip("+").rsplit("/", 1)[-1]) if code.strip() else None
    for r in open_reports:
        r["link"] = links.by_code(r["code"])
    return render(request, "admin.html", reports=open_reports, blocked=blocked, found=found, code=code)


@router.post("/links/{code}/toggle")
async def admin_toggle(request: Request, code: str):
    await check_csrf(request)
    _admin(request)
    link = links.by_code(code)
    if link is None:
        return redirect("/admin", "No such Clam.", "err")
    off = link["disabled_at"] is None
    links.set_disabled(link["id"], off, "admin:abuse" if off else None)
    return redirect(f"/admin?code={code}", f"{code} turned {'off' if off else 'on'}.")


@router.post("/reports/{report_id}/resolve")
async def admin_resolve(request: Request, report_id: int):
    await check_csrf(request)
    _admin(request)
    form = await request.form()
    with tx() as conn:
        conn.execute(update(reports).where(reports.c.id == report_id).values(
            resolved_at=utcnow(), resolution=str(form.get("resolution", "dismissed"))[:32]))
    return redirect("/admin", "Report closed.")


@router.post("/block")
async def admin_block(request: Request):
    await check_csrf(request)
    _admin(request)
    form = await request.form()
    raw = str(form.get("domain", "")).strip().lower()
    domain = urls.host_of(raw if "://" in raw else "https://" + raw)
    if not domain or "." not in domain:
        return redirect("/admin", "Enter a domain like example.com.", "err")
    now = utcnow()
    with tx() as conn:
        if conn.execute(select(blocked_domains).where(blocked_domains.c.domain == domain)).first() is None:
            conn.execute(blocked_domains.insert().values(
                domain=domain, reason=str(form.get("reason", ""))[:255] or None, created_at=now))
        # Turn off every live Clam pointing at that domain or its subdomains.
        candidates = conn.execute(
            select(links_t.c.id, links_t.c.url).where(links_t.c.disabled_at.is_(None), links_t.c.deleted_at.is_(None),
                                                      links_t.c.url.like(f"%{domain}%"))
        ).all()
        hit = [r.id for r in candidates if domain in urls.domain_candidates(urls.host_of(r.url))]
        if hit:
            conn.execute(update(links_t).where(links_t.c.id.in_(hit)).values(
                disabled_at=now, disabled_reason="admin:blocked-domain", updated_at=now))
    return redirect("/admin", f"Blocked {domain} and turned off {len(hit)} Clam(s).")


@router.post("/unblock")
async def admin_unblock(request: Request):
    await check_csrf(request)
    _admin(request)
    form = await request.form()
    with tx() as conn:
        conn.execute(delete(blocked_domains).where(blocked_domains.c.domain == str(form.get("domain", ""))))
    return redirect("/admin", "Unblocked. (Clams already turned off stay off.)")
