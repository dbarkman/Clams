"""Validating the long URLs people shorten.

Only http(s) to a real-looking public host. Links back to cla.ms itself are
refused (they would loop or hide another Clam). No URL is ever fetched by the
server, so there is no request forgery surface here.
"""

from __future__ import annotations

import hashlib
import ipaddress
from urllib.parse import urlsplit, urlunsplit

from .settings import settings

MAX_URL = 8000


class BadURL(ValueError):
    pass


def normalize(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise BadURL("Paste a link to shorten.")
    if len(url) > MAX_URL:
        raise BadURL("That link is too long to shorten (8,000 characters max).")
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise BadURL("That doesn't look like a web address.") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise BadURL("Only http and https links can be shortened.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or any(c.isspace() for c in url):
        raise BadURL("That doesn't look like a web address.")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise BadURL("That link points at a private address.")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
        if "." not in host:
            raise BadURL("That doesn't look like a web address.")
    if ip is not None and not ip.is_global:
        raise BadURL("That link points at a private address.")
    if host == settings.short_host or host == "www." + settings.short_host:
        raise BadURL("That's already a Clam!")
    netloc = parts.netloc
    # Lower-case the host part only; paths and queries are case-sensitive.
    if parts.hostname:
        userinfo, _, hostport = netloc.rpartition("@")
        netloc = (userinfo + "@" if userinfo else "") + hostport.lower()
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def domain_candidates(host: str) -> list[str]:
    """example.co.uk -> [example.co.uk, co.uk, uk]; used to match blocked domains."""
    labels = host.split(".")
    return [".".join(labels[i:]) for i in range(len(labels))]
