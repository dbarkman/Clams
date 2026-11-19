"""Sign in with Google and Sign in with Apple (OpenID Connect, code flow).

The in-flight state (state, nonce, PKCE verifier, where to go next) rides in a
short-lived signed cookie. Apple posts its callback cross-site, so that cookie
is SameSite=None; the session cookie itself stays SameSite=Lax.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from .settings import settings

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

APPLE_AUTH = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN = "https://appleid.apple.com/auth/token"
APPLE_JWKS = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

STATE_COOKIE = "clams_oauth"
STATE_TTL = 600

_jwks: dict[str, jwt.PyJWKClient] = {}


class OAuthError(Exception):
    pass


@dataclass(slots=True)
class Identity:
    provider: str
    subject: str
    email: str | None
    email_verified: bool


# --- signed state cookie ---------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_state(data: dict) -> str:
    body = _b64(json.dumps({**data, "exp": int(time.time()) + STATE_TTL}).encode())
    sig = _b64(hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_state(value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    body, sig = value.rsplit(".", 1)
    expect = _b64(hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        return None
    data = json.loads(_unb64(body))
    if data.get("exp", 0) < time.time():
        return None
    return data


def redirect_uri(provider: str) -> str:
    return f"{settings.base_url}/auth/{provider}/callback"


# --- starting a sign-in ----------------------------------------------------


def begin(provider: str, next_url: str) -> tuple[str, str]:
    """Returns (provider URL to send the browser to, state cookie value)."""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    data = {"provider": provider, "state": state, "nonce": nonce, "next": next_url}
    if provider == "google":
        verifier = secrets.token_urlsafe(48)
        data["verifier"] = verifier
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri("google"),
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH}?{urlencode(params)}", sign_state(data)
    if provider == "apple":
        params = {
            "client_id": settings.apple_client_id,
            "redirect_uri": redirect_uri("apple"),
            "response_type": "code",
            "response_mode": "form_post",
            "scope": "email",
            "state": state,
            "nonce": nonce,
        }
        return f"{APPLE_AUTH}?{urlencode(params)}", sign_state(data)
    raise OAuthError("Unknown sign-in provider.")


# --- finishing a sign-in ---------------------------------------------------


def _verify_id_token(token: str, jwks_url: str, audience: str, issuers, nonce: str) -> dict:
    client = _jwks.setdefault(jwks_url, jwt.PyJWKClient(jwks_url, cache_keys=True))
    key = client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        key.key,
        algorithms=["RS256", "ES256"],
        audience=audience,
        issuer=list(issuers),
        leeway=60,
    )
    if claims.get("nonce") != nonce:
        raise OAuthError("Sign-in check failed (nonce). Please try again.")
    return claims


def _truthy(v) -> bool:
    return v is True or v == "true"


def finish_google(code: str, state: dict) -> Identity:
    r = httpx.post(
        GOOGLE_TOKEN,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri("google"),
            "grant_type": "authorization_code",
            "code_verifier": state["verifier"],
        },
        timeout=10,
    )
    if r.status_code != 200:
        raise OAuthError("Google didn't accept the sign-in. Please try again.")
    claims = _verify_id_token(
        r.json()["id_token"], GOOGLE_JWKS, settings.google_client_id, GOOGLE_ISSUERS, state["nonce"]
    )
    return Identity("google", claims["sub"], claims.get("email"), _truthy(claims.get("email_verified")))


def apple_client_secret() -> str:
    with open(settings.apple_private_key_path) as fh:
        key = fh.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": settings.apple_team_id, "iat": now, "exp": now + 300, "aud": APPLE_ISSUER, "sub": settings.apple_client_id},
        key,
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )


def finish_apple(code: str, state: dict) -> Identity:
    r = httpx.post(
        APPLE_TOKEN,
        data={
            "client_id": settings.apple_client_id,
            "client_secret": apple_client_secret(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri("apple"),
        },
        timeout=10,
    )
    if r.status_code != 200:
        raise OAuthError("Apple didn't accept the sign-in. Please try again.")
    claims = _verify_id_token(
        r.json()["id_token"], APPLE_JWKS, settings.apple_client_id, (APPLE_ISSUER,), state["nonce"]
    )
    return Identity("apple", claims["sub"], claims.get("email"), _truthy(claims.get("email_verified")))
