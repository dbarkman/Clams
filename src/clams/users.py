"""Accounts, browser sessions, API/extension tokens and sign-in providers."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update

from .db import api_tokens, email_tokens, links, oauth_identities, sessions, tx, users, utcnow
from .security import hash_password, new_token, password_problem, token_hash, verify_password

SESSION_DAYS = 30


class AccountError(ValueError):
    pass


def _row(r) -> dict[str, Any] | None:
    return dict(r._mapping) if r is not None else None


def clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1] or len(email) > 254 or " " in email:
        raise AccountError("Enter a valid email address.")
    return email


def get(user_id: int) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(conn.execute(select(users).where(users.c.id == user_id)).first())


def by_email(email: str) -> dict[str, Any] | None:
    with tx() as conn:
        return _row(conn.execute(select(users).where(users.c.email == email.strip().lower())).first())


def sign_up(email: str, password: str) -> dict[str, Any]:
    email = clean_email(email)
    problem = password_problem(password)
    if problem:
        raise AccountError(problem)
    if by_email(email):
        raise AccountError("There's already an account for that email. Try signing in.")
    with tx() as conn:
        res = conn.execute(
            users.insert().values(
                email=email, password_hash=hash_password(password), email_verified=False, created_at=utcnow()
            )
        )
        return _row(conn.execute(select(users).where(users.c.id == res.inserted_primary_key[0])).first())


_DUMMY: list[str] = []


def _dummy_hash() -> str:
    if not _DUMMY:
        _DUMMY.append(hash_password("timing-equalizer"))
    return _DUMMY[0]


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    user = by_email(email or "")
    if user is None:
        # Spend the same time as a real check so timing doesn't reveal which emails exist.
        verify_password(_dummy_hash(), password)
        return None
    return user if verify_password(user["password_hash"], password) else None


def set_password(user_id: int, password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise AccountError(problem)
    with tx() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(password_hash=hash_password(password)))


def touch_login(user_id: int) -> None:
    with tx() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(last_login_at=utcnow()))


def set_admin(email: str, admin: bool) -> bool:
    with tx() as conn:
        res = conn.execute(update(users).where(users.c.email == email.strip().lower()).values(is_admin=admin))
    return bool(res.rowcount)


def delete_account(user_id: int) -> None:
    """Remove the account. Its Clams are deleted too (codes stay retired)."""
    now = utcnow()
    with tx() as conn:
        conn.execute(
            update(links)
            .where(links.c.user_id == user_id, links.c.deleted_at.is_(None))
            .values(deleted_at=now, updated_at=now)
        )
        conn.execute(delete(users).where(users.c.id == user_id))


# --- sessions --------------------------------------------------------------


def start_session(user_id: int, user_agent: str | None) -> str:
    token = new_token()
    now = utcnow()
    with tx() as conn:
        conn.execute(
            sessions.insert().values(
                token_hash=token_hash(token),
                user_id=user_id,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(days=SESSION_DAYS),
                user_agent=(user_agent or "")[:255],
            )
        )
    touch_login(user_id)
    return token


def session_user(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    h = token_hash(token)
    now = utcnow()
    with tx() as conn:
        row = conn.execute(
            select(users, sessions.c.id.label("session_id"), sessions.c.last_seen_at.label("session_seen"))
            .join(sessions, sessions.c.user_id == users.c.id)
            .where(sessions.c.token_hash == h, sessions.c.expires_at > now)
        ).first()
        if row is None:
            return None
        user = dict(row._mapping)
        # Sliding expiry, written at most hourly.
        if now - user["session_seen"] > timedelta(hours=1):
            conn.execute(
                update(sessions)
                .where(sessions.c.id == user["session_id"])
                .values(last_seen_at=now, expires_at=now + timedelta(days=SESSION_DAYS))
            )
    return user


def end_session(token: str | None) -> None:
    if token:
        with tx() as conn:
            conn.execute(delete(sessions).where(sessions.c.token_hash == token_hash(token)))


def end_all_sessions(user_id: int) -> None:
    with tx() as conn:
        conn.execute(delete(sessions).where(sessions.c.user_id == user_id))


# --- API / extension tokens ------------------------------------------------


def new_api_token(user_id: int, label: str, kind: str = "api") -> str:
    token = new_token("clm_")
    with tx() as conn:
        conn.execute(
            api_tokens.insert().values(
                user_id=user_id,
                token_hash=token_hash(token),
                label=(label or "API token").strip()[:120] or "API token",
                kind=kind,
                created_at=utcnow(),
            )
        )
    return token


def token_user(token: str | None) -> dict[str, Any] | None:
    if not token or not token.startswith("clm_"):
        return None
    now = utcnow()
    with tx() as conn:
        row = conn.execute(
            select(users, api_tokens.c.id.label("token_id"), api_tokens.c.last_used_at.label("token_used"))
            .join(api_tokens, api_tokens.c.user_id == users.c.id)
            .where(api_tokens.c.token_hash == token_hash(token), api_tokens.c.revoked_at.is_(None))
        ).first()
        if row is None:
            return None
        user = dict(row._mapping)
        if user["token_used"] is None or now - user["token_used"] > timedelta(minutes=10):
            conn.execute(update(api_tokens).where(api_tokens.c.id == user["token_id"]).values(last_used_at=now))
    return user


def list_tokens(user_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = conn.execute(
            select(api_tokens)
            .where(api_tokens.c.user_id == user_id, api_tokens.c.revoked_at.is_(None))
            .order_by(api_tokens.c.created_at.desc())
        ).all()
    return [_row(r) for r in rows]


def revoke_token(user_id: int, token_id: int) -> None:
    with tx() as conn:
        conn.execute(
            update(api_tokens)
            .where(api_tokens.c.id == token_id, api_tokens.c.user_id == user_id)
            .values(revoked_at=utcnow())
        )


def revoke_token_value(token: str) -> None:
    with tx() as conn:
        conn.execute(update(api_tokens).where(api_tokens.c.token_hash == token_hash(token)).values(revoked_at=utcnow()))


def revoke_all_tokens(user_id: int) -> None:
    with tx() as conn:
        conn.execute(
            update(api_tokens)
            .where(api_tokens.c.user_id == user_id, api_tokens.c.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )


# --- sign-in providers -----------------------------------------------------


def identities(user_id: int) -> list[dict[str, Any]]:
    with tx() as conn:
        return [_row(r) for r in conn.execute(select(oauth_identities).where(oauth_identities.c.user_id == user_id))]


def provider_login(provider: str, subject: str, email: str | None, email_verified: bool) -> dict[str, Any]:
    """Find or create the account for a Google/Apple identity.

    Linking by email only happens when the provider vouches for the email. If
    the matching account was never verified, someone may have registered it
    with a stranger's address, so the provider sign-in takes it over: the
    password and every session and token on it are cleared.
    """
    with tx() as conn:
        found = conn.execute(
            select(users)
            .join(oauth_identities, oauth_identities.c.user_id == users.c.id)
            .where(oauth_identities.c.provider == provider, oauth_identities.c.subject == subject)
        ).first()
    if found is not None:
        return _row(found)

    if not email or not email_verified:
        raise AccountError("Your sign-in provider didn't share a verified email address.")
    email = clean_email(email)
    user = by_email(email)
    if user is not None and not user["email_verified"]:
        end_all_sessions(user["id"])
        revoke_all_tokens(user["id"])
        with tx() as conn:
            conn.execute(
                update(users).where(users.c.id == user["id"]).values(password_hash=None, email_verified=True)
            )
        user = get(user["id"])
    if user is None:
        with tx() as conn:
            res = conn.execute(users.insert().values(email=email, email_verified=True, created_at=utcnow()))
        user = get(res.inserted_primary_key[0])
    with tx() as conn:
        conn.execute(
            oauth_identities.insert().values(
                user_id=user["id"], provider=provider, subject=subject, email=email, created_at=utcnow()
            )
        )
    return user


# --- email links (password reset, verification) ----------------------------


def new_email_token(user_id: int, kind: str, hours: int) -> str:
    token = new_token()
    now = utcnow()
    with tx() as conn:
        conn.execute(
            email_tokens.insert().values(
                user_id=user_id,
                kind=kind,
                token_hash=token_hash(token),
                created_at=now,
                expires_at=now + timedelta(hours=hours),
            )
        )
    return token


def use_email_token(token: str, kind: str) -> int | None:
    now = utcnow()
    with tx() as conn:
        row = conn.execute(
            select(email_tokens).where(
                email_tokens.c.token_hash == token_hash(token or ""),
                email_tokens.c.kind == kind,
                email_tokens.c.used_at.is_(None),
                email_tokens.c.expires_at > now,
            )
        ).first()
        if row is None:
            return None
        conn.execute(update(email_tokens).where(email_tokens.c.id == row.id).values(used_at=now))
        return row.user_id


def peek_email_token(token: str, kind: str) -> bool:
    with tx() as conn:
        return (
            conn.execute(
                select(email_tokens.c.id).where(
                    email_tokens.c.token_hash == token_hash(token or ""),
                    email_tokens.c.kind == kind,
                    email_tokens.c.used_at.is_(None),
                    email_tokens.c.expires_at > utcnow(),
                )
            ).first()
            is not None
        )


def mark_verified(user_id: int) -> None:
    with tx() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(email_verified=True))
