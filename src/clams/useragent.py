"""Just enough user-agent parsing for click stats: device, browser, OS, bot."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Link-preview fetchers (chat apps, social sites) and crawlers. Their hits are
# recorded but kept out of the click counts people see.
_BOT = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|quora link|whatsapp|telegram|"
    r"discord|slack|skypeuripreview|vkshare|pinterest|bitlybot|curl/|wget/|python-|httpx|"
    r"go-http-client|okhttp|java/|headless|lighthouse|monitor|uptime|feedfetcher",
    re.I,
)


@dataclass(frozen=True, slots=True)
class Agent:
    device: str
    browser: str
    os: str
    is_bot: bool


def parse(ua: str | None) -> Agent:
    ua = ua or ""
    if not ua or _BOT.search(ua):
        return Agent("bot", _browser(ua) if ua else "Unknown", _os(ua) if ua else "Unknown", True)
    return Agent(_device(ua), _browser(ua), _os(ua), False)


def _device(ua: str) -> str:
    if re.search(r"iPad|Tablet|Nexus (7|9|10)|SM-T|Kindle|Silk", ua) or (
        "Android" in ua and "Mobile" not in ua
    ):
        return "tablet"
    if re.search(r"Mobi|iPhone|iPod|Android.*Mobile|Windows Phone", ua):
        return "mobile"
    return "desktop"


def _browser(ua: str) -> str:
    checks = (
        (r"Edg(e|A|iOS)?/", "Edge"),
        (r"OPR/|Opera", "Opera"),
        (r"SamsungBrowser/", "Samsung Internet"),
        (r"Firefox/|FxiOS/", "Firefox"),
        (r"CriOS/|Chrome/|Chromium/", "Chrome"),
        (r"Safari/", "Safari"),
    )
    for pattern, name in checks:
        if re.search(pattern, ua):
            return name
    return "Other"


def _os(ua: str) -> str:
    checks = (
        (r"iPhone|iPad|iPod", "iOS"),
        (r"Android", "Android"),
        (r"Windows", "Windows"),
        (r"CrOS", "ChromeOS"),
        (r"Mac OS X|Macintosh", "macOS"),
        (r"Linux", "Linux"),
    )
    for pattern, name in checks:
        if re.search(pattern, ua):
            return name
    return "Other"
