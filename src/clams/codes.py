"""Clam codes: six random base62 characters, case-sensitive.

62^6 is about 56.8 billion codes. Custom aliases (signed-in users) may be
3-32 characters of letters, digits, hyphen and underscore. Codes that collide
with the site's own paths are reserved for everyone.
"""

from __future__ import annotations

import re
import secrets
import string

ALPHABET = string.ascii_letters + string.digits
LENGTH = 6

ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,31}$")

# Compared case-insensitively so nobody can register "Login" either.
RESERVED = frozenset(
    w.lower()
    for w in """
    about account accounts admin api app apple assets auth blog clam clams contact dashboard delete
    docs edit export extension extensions faq favicon google healthz help home index links login
    logout me new oauth password privacy qr report reset robots settings shorten signin signout
    signup static stats status support terms tos user users www
    """.split()
)


def random_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def is_reserved(code: str) -> bool:
    return code.lower() in RESERVED


def alias_problem(alias: str) -> str | None:
    if not ALIAS_RE.match(alias):
        return "Custom names use 3–32 letters, numbers, hyphens or underscores, starting with a letter or number."
    if is_reserved(alias):
        return "That name is reserved. Try another."
    return None
