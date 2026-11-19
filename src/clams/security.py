"""Secrets, hashes and passwords.

Tokens (sessions, API tokens, claim tokens, email links) are random strings
handed to the client once; only their SHA-256 is stored. IP addresses are
never stored, only keyed hashes of them.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .settings import settings

_hasher = PasswordHasher()

MIN_PASSWORD = 8


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def keyed_hash(*parts: str, length: int = 64) -> str:
    msg = "\x1f".join(parts).encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()[:length]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    if not stored:
        return False
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Passwords need at least {MIN_PASSWORD} characters."
    if len(password) > 256:
        return "That password is longer than we can take."
    return None


def csrf_valid(cookie_value: str | None, form_value: str | None) -> bool:
    if not cookie_value or not form_value:
        return False
    return hmac.compare_digest(cookie_value, form_value)
