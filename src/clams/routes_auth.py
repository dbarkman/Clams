"""Sign up, sign in (password, Google, Apple), sign out, password reset."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from . import mailer, oauth, users
from .ratelimit import limiter
from .settings import settings
from .web import (
    SESSION_COOKIE,
    check_csrf,
    client_ip,
    current_user,
    flash,
    message_page,
    redirect,
    render,
    safe_next,
    sign_in,
)

log = logging.getLogger(__name__)
router = APIRouter()


def _welcome(resp, claimed: int, base: str):
    if claimed:
        s = "" if claimed == 1 else "s"
        flash(resp, f"{base} We saved {claimed} Clam{s} you made earlier to your account. 🐚")
    else:
        flash(resp, base)
    return resp


@router.get("/login")
def login_form(request: Request, next: str = ""):
    if current_user(request):
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "login.html", next=safe_next(next, ""))


@router.post("/login")
async def login(request: Request):
    await check_csrf(request)
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    next_url = safe_next(str(form.get("next", "")))
    if not limiter.hit(f"login:{client_ip(request)}:{email}", settings.login_attempts_per_15min, 900):
        return render(request, "login.html", next=next_url, email=email,
                      error="Too many tries. Take a breather and try again in a few minutes.", status_code=429)
    user = users.authenticate(email, str(form.get("password", "")))
    if user is None:
        return render(request, "login.html", next=next_url, email=email,
                      error="That email and password don't match.", status_code=401)
    resp = RedirectResponse(next_url, status_code=303)
    return _welcome(resp, sign_in(request, resp, user), "Welcome back!")


@router.get("/signup")
def signup_form(request: Request, next: str = ""):
    if current_user(request):
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "signup.html", next=safe_next(next, ""))


@router.post("/signup")
async def signup(request: Request):
    await check_csrf(request)
    form = await request.form()
    email = str(form.get("email", ""))
    next_url = safe_next(str(form.get("next", "")))
    if not limiter.hit(f"signup:{client_ip(request)}", 20, 3600):
        return render(request, "signup.html", next=next_url, email=email,
                      error="Lots of sign-ups from here lately. Try again in a bit.", status_code=429)
    try:
        user = users.sign_up(email, str(form.get("password", "")))
    except users.AccountError as exc:
        return render(request, "signup.html", next=next_url, email=email, error=str(exc), status_code=400)
    if settings.mail_enabled:
        token = users.new_email_token(user["id"], "verify", 72)
        mailer.send_verify(user["email"], f"{settings.base_url}/verify/{token}")
    resp = RedirectResponse(next_url, status_code=303)
    return _welcome(resp, sign_in(request, resp, user), "Welcome to Clams! 🎉")


@router.post("/logout")
async def logout(request: Request):
    await check_csrf(request)
    users.end_session(request.cookies.get(SESSION_COOKIE))
    resp = redirect("/", "You're signed out. See you soon!")
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# --- password reset --------------------------------------------------------


@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "forgot.html")


@router.post("/forgot")
async def forgot(request: Request):
    await check_csrf(request)
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    if not settings.mail_enabled:
        return redirect("/forgot", "Email isn't switched on yet, so we can't send reset links.", "err")
    if limiter.hit(f"forgot:{client_ip(request)}", 10, 3600):
        user = users.by_email(email)
        if user is not None:
            token = users.new_email_token(user["id"], "reset", 1)
            mailer.send_reset(user["email"], f"{settings.base_url}/reset/{token}")
    # Same answer either way, so this page can't be used to test which emails have accounts.
    return redirect("/login", "If that email has an account, a reset link is on its way.")


@router.get("/reset/{token}")
def reset_form(request: Request, token: str):
    if not users.peek_email_token(token, "reset"):
        return message_page(request, "That link has expired", "Reset links work once, for one hour. Ask for a new one.", 400, "⏳")
    return render(request, "reset.html", token=token)


@router.post("/reset/{token}")
async def reset(request: Request, token: str):
    await check_csrf(request)
    form = await request.form()
    password = str(form.get("password", ""))
    from .security import password_problem

    problem = password_problem(password)
    if problem:
        return render(request, "reset.html", token=token, error=problem, status_code=400)
    user_id = users.use_email_token(token, "reset")
    if user_id is None:
        return message_page(request, "That link has expired", "Reset links work once, for one hour. Ask for a new one.", 400, "⏳")
    users.set_password(user_id, password)
    users.mark_verified(user_id)  # they proved they read that inbox
    users.end_all_sessions(user_id)
    resp = RedirectResponse("/links", status_code=303)
    return _welcome(resp, sign_in(request, resp, users.get(user_id)), "Password updated. You're signed in.")


@router.get("/verify/{token}")
def verify(request: Request, token: str):
    user_id = users.use_email_token(token, "verify")
    if user_id is None:
        return message_page(request, "That link has expired", "It may have been used already.", 400, "⏳")
    users.mark_verified(user_id)
    return redirect("/links", "Email confirmed. Thanks!")


# --- Google / Apple --------------------------------------------------------


@router.get("/auth/{provider}")
def oauth_start(request: Request, provider: str, next: str = ""):
    enabled = {"google": settings.google_enabled, "apple": settings.apple_enabled}
    if not enabled.get(provider):
        return redirect("/login", "That sign-in option isn't available yet.", "err")
    url, state_cookie = oauth.begin(provider, safe_next(next))
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(
        oauth.STATE_COOKIE, state_cookie, max_age=oauth.STATE_TTL, secure=True, httponly=True,
        samesite="none", path="/auth/",
    )
    return resp


def _finish(request: Request, provider: str, code: str | None, state_param: str | None, error: str | None):
    state = oauth.read_state(request.cookies.get(oauth.STATE_COOKIE))
    if error:
        return redirect("/login", "Sign-in was cancelled.", "err")
    if not state or state.get("provider") != provider or state.get("state") != state_param or not code:
        return redirect("/login", "That sign-in expired. Please try again.", "err")
    try:
        ident = oauth.finish_google(code, state) if provider == "google" else oauth.finish_apple(code, state)
        user = users.provider_login(ident.provider, ident.subject, ident.email, ident.email_verified)
    except (oauth.OAuthError, users.AccountError) as exc:
        return redirect("/login", str(exc), "err")
    except Exception:  # noqa: BLE001
        log.exception("%s sign-in failed", provider)
        return redirect("/login", "Something went wrong signing in. Please try again.", "err")
    resp = RedirectResponse(safe_next(state.get("next")), status_code=303)
    resp.delete_cookie(oauth.STATE_COOKIE, path="/auth/")
    return _welcome(resp, sign_in(request, resp, user), "You're signed in!")


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    return _finish(request, "google", code, state, error)


@router.post("/auth/apple/callback")
async def apple_callback(request: Request):
    form = await request.form()
    return _finish(request, "apple", form.get("code"), form.get("state"), form.get("error"))
