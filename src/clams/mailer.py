"""Outgoing email through Resend's HTTP API. Off until CLAMS_RESEND_API_KEY is set."""

from __future__ import annotations

import logging

import httpx

from .settings import settings

log = logging.getLogger(__name__)


def send(to: str, subject: str, text: str) -> bool:
    if not settings.mail_enabled:
        return False
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.mail_from, "to": [to], "subject": subject, "text": text},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception:  # noqa: BLE001
        log.warning("email send failed", exc_info=True)
        return False


def send_reset(to: str, link: str) -> bool:
    return send(
        to,
        "Reset your Clams password",
        f"Hi!\n\nSomeone (hopefully you) asked to reset the password for your Clams account.\n\n"
        f"Reset it here (the link works for one hour):\n{link}\n\n"
        f"If you didn't ask, you can ignore this email.\n\n— Clams, cla.ms",
    )


def send_verify(to: str, link: str) -> bool:
    return send(
        to,
        "Confirm your email for Clams",
        f"Welcome to Clams! 🐚\n\nConfirm your email so you can always get back into your account:\n{link}\n\n— Clams, cla.ms",
    )
