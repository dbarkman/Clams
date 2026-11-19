"""Google Safe Browsing Lookup API (v4). Off until CLAMS_SAFE_BROWSING_KEY is set.

A lookup failure never blocks shortening: the check is a filter, not a gate
that takes the site down with it.
"""

from __future__ import annotations

import logging

import httpx

from .settings import settings

log = logging.getLogger(__name__)

ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"


def is_unsafe(url: str) -> bool:
    if not settings.safe_browsing_key:
        return False
    body = {
        "client": {"clientId": "clams", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        r = httpx.post(ENDPOINT, params={"key": settings.safe_browsing_key}, json=body, timeout=3)
        r.raise_for_status()
        return bool(r.json().get("matches"))
    except Exception:  # noqa: BLE001 - see module docstring
        log.warning("safe browsing lookup failed", exc_info=True)
        return False
