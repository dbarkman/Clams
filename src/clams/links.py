"""Creating, finding, changing and claiming Clams, and recording clicks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError

from . import codes, safebrowsing, urls
from .db import blocked_domains, clicks, links, tx, utcnow
from .security import keyed_hash, new_token, token_hash

PAGE_SIZE = 100


class LinkError(ValueError):
    pass


@dataclass(slots=True)
class Created:
    link: dict[str, Any]
    claim_token: str | None  # only for anonymous Clams
    reused: bool


def _row(r) -> dict[str, Any] | None:
    return dict(r._mapping) if r is not None else None


def is_blocked(url: str) -> bool:
    host = urls.host_of(url)
    with tx() as conn:
        hit = conn.execute(
            select(blocked_domains.c.domain).where(blocked_domains.c.domain.in_(urls.domain_candidates(host)))
        ).first()
    return hit is not None


def create(
    raw_url: str,
    *,
    user_id: int | None,
    title: str | None = None,
    alias: str | None = None,
    source: str = "web",
    creator_ip: str | None = None,
) -> Created:
    try:
        url = urls.normalize(raw_url)
    except urls.BadURL as exc:
        raise LinkError(str(exc)) from exc
    if is_blocked(url) or safebrowsing.is_unsafe(url):
        raise LinkError("Sorry, we can't shorten links to that site.")
    title = (title or "").strip()[:300] or None
    alias = (alias or "").strip() or None
    h = urls.url_hash(url)

    if alias:
        if user_id is None:
            raise LinkError("Sign in to choose a custom name.")
        problem = codes.alias_problem(alias)
        if problem:
            raise LinkError(problem)

    # A signed-in user shortening the same URL again gets their existing Clam back.
    if user_id is not None and not alias:
        with tx() as conn:
            existing = conn.execute(
                select(links)
                .where(
                    links.c.user_id == user_id,
                    links.c.url_hash == h,
                    links.c.is_custom.is_(False),
                    links.c.deleted_at.is_(None),
                    links.c.disabled_at.is_(None),
                )
                .order_by(links.c.id)
            ).first()
        if existing is not None:
            row = _row(existing)
            if title and not row["title"]:
                set_title(row["id"], title)
                row["title"] = title
            return Created(row, None, True)

    claim_token = new_token("clc_") if user_id is None else None
    values = dict(
        url=url,
        url_hash=h,
        title=title,
        user_id=user_id,
        is_custom=bool(alias),
        claim_hash=token_hash(claim_token) if claim_token else None,
        source=source,
        created_at=utcnow(),
        updated_at=utcnow(),
        creator_hash=keyed_hash("creator", creator_ip) if creator_ip else None,
    )
    attempts = 1 if alias else 8
    for _ in range(attempts):
        code = alias or codes.random_code()
        if codes.is_reserved(code):
            continue
        try:
            with tx() as conn:
                res = conn.execute(links.insert().values(code=code, **values))
                link_id = res.inserted_primary_key[0]
                row = _row(conn.execute(select(links).where(links.c.id == link_id)).first())
            return Created(row, claim_token, False)
        except IntegrityError:
            if alias:
                raise LinkError("That custom name is taken. Try another.")
    raise LinkError("We couldn't find a free code. Please try again.")


def set_title(link_id: int, title: str | None) -> None:
    with tx() as conn:
        conn.execute(update(links).where(links.c.id == link_id).values(title=title, updated_at=utcnow()))


def by_code(code: str) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(conn.execute(select(links).where(links.c.code == code)).first())


def owned(code: str, user_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(
            conn.execute(
                select(links).where(links.c.code == code, links.c.user_id == user_id, links.c.deleted_at.is_(None))
            ).first()
        )


def list_for_user(user_id: int, *, page: int = 1, q: str = "") -> tuple[list[dict[str, Any]], int]:
    conds = [links.c.user_id == user_id, links.c.deleted_at.is_(None)]
    if q:
        like = f"%{q}%"
        conds.append(or_(links.c.url.like(like), links.c.title.like(like), links.c.code.like(like)))
    where = and_(*conds)
    with tx() as conn:
        total = conn.execute(select(func.count()).select_from(links).where(where)).scalar_one()
        rows = conn.execute(
            select(links)
            .where(where)
            .order_by(links.c.created_at.desc(), links.c.id.desc())
            .limit(PAGE_SIZE)
            .offset((max(page, 1) - 1) * PAGE_SIZE)
        ).all()
    return [_row(r) for r in rows], total


def all_for_user(user_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = conn.execute(
            select(links).where(links.c.user_id == user_id, links.c.deleted_at.is_(None)).order_by(links.c.id)
        ).all()
    return [_row(r) for r in rows]


def edit(link: dict[str, Any], *, url: str | None = None, title: str | None = None) -> dict[str, Any]:
    values: dict[str, Any] = {"updated_at": utcnow()}
    if url is not None and url.strip() != link["url"]:
        try:
            new = urls.normalize(url)
        except urls.BadURL as exc:
            raise LinkError(str(exc)) from exc
        if is_blocked(new) or safebrowsing.is_unsafe(new):
            raise LinkError("Sorry, we can't send Clams to that site.")
        values.update(url=new, url_hash=urls.url_hash(new))
    if title is not None:
        values["title"] = title.strip()[:300] or None
    with tx() as conn:
        conn.execute(update(links).where(links.c.id == link["id"]).values(**values))
        return _row(conn.execute(select(links).where(links.c.id == link["id"])).first())


def set_disabled(link_id: int, disabled: bool, reason: str | None = None) -> None:
    with tx() as conn:
        conn.execute(
            update(links)
            .where(links.c.id == link_id)
            .values(
                disabled_at=utcnow() if disabled else None,
                disabled_reason=reason if disabled else None,
                updated_at=utcnow(),
            )
        )


def delete(link_id: int) -> None:
    """Soft delete: the row stays so the code is never reissued."""
    with tx() as conn:
        conn.execute(update(links).where(links.c.id == link_id).values(deleted_at=utcnow(), updated_at=utcnow()))


def claim(user_id: int, claim_tokens: list[str]) -> int:
    hashes = [token_hash(t) for t in claim_tokens if isinstance(t, str) and t.startswith("clc_")]
    if not hashes:
        return 0
    with tx() as conn:
        res = conn.execute(
            update(links)
            .where(links.c.claim_hash.in_(hashes), links.c.user_id.is_(None))
            .values(user_id=user_id, claim_hash=None, updated_at=utcnow())
        )
    return res.rowcount or 0


def record_click(
    link_id: int, *, ip: str | None, user_agent: str | None, referrer: str | None, country: str | None
) -> None:
    from . import useragent

    agent = useragent.parse(user_agent)
    ref_host = None
    if referrer:
        ref_host = urls.host_of(referrer)[:255] or None
    visitor = keyed_hash("visitor", str(link_id), ip or "", user_agent or "", length=32)
    now = utcnow()
    with tx() as conn:
        conn.execute(
            clicks.insert().values(
                link_id=link_id,
                clicked_at=now,
                referrer_host=ref_host,
                country=country,
                device=agent.device,
                browser=agent.browser,
                os=agent.os,
                visitor_hash=visitor,
                is_bot=agent.is_bot,
            )
        )
        if not agent.is_bot:
            conn.execute(
                update(links)
                .where(links.c.id == link_id)
                .values(click_count=links.c.click_count + 1, last_clicked_at=now)
            )


# --- stats -----------------------------------------------------------------

RANGES = {"7d": 7, "30d": 30, "90d": 90, "all": None}


def stats(link: dict[str, Any], range_key: str = "30d") -> dict[str, Any]:
    days = RANGES.get(range_key, 30)
    now = utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0) if days else None
    base = [clicks.c.link_id == link["id"], clicks.c.is_bot.is_(False)]
    if start is not None:
        base.append(clicks.c.clicked_at >= start)
    where = and_(*base)
    day = func.date(clicks.c.clicked_at)
    with tx() as conn:
        total = conn.execute(select(func.count()).select_from(clicks).where(where)).scalar_one()
        unique = conn.execute(
            select(func.count(func.distinct(clicks.c.visitor_hash))).select_from(clicks).where(where)
        ).scalar_one()
        bots = conn.execute(
            select(func.count())
            .select_from(clicks)
            .where(clicks.c.link_id == link["id"], clicks.c.is_bot.is_(True))
            .where(clicks.c.clicked_at >= start if start is not None else true())
        ).scalar_one()
        per_day = {
            str(d): n
            for d, n in conn.execute(select(day, func.count()).where(where).group_by(day)).all()
        }

        def breakdown(col):
            rows = conn.execute(
                select(col, func.count().label("n")).where(where).group_by(col).order_by(func.count().desc(), col)
            ).all()
            return [(k or "", n) for k, n in rows]

        referrers = breakdown(clicks.c.referrer_host)
        countries = breakdown(clicks.c.country)
        devices = breakdown(clicks.c.device)
        browsers = breakdown(clicks.c.browser)
        oses = breakdown(clicks.c.os)
        first_click = conn.execute(
            select(func.min(clicks.c.clicked_at)).where(clicks.c.link_id == link["id"], clicks.c.is_bot.is_(False))
        ).scalar_one()

    if start is None:
        first = first_click or link["created_at"]
        start = datetime.combine(min(first, link["created_at"]).date(), datetime.min.time())
    series = []
    d = start.date()
    while d <= now.date():
        series.append((d, per_day.get(str(d), 0)))
        d += timedelta(days=1)
    return {
        "range": range_key if range_key in RANGES else "30d",
        "total": total,
        "unique": unique,
        "bots": bots,
        "series": series,
        "referrers": referrers,
        "countries": countries,
        "devices": devices,
        "browsers": browsers,
        "oses": oses,
    }
