from clams import codes, urls, useragent
import pytest


def test_random_codes_are_six_base62():
    seen = {codes.random_code() for _ in range(2000)}
    assert all(len(c) == 6 and c.isalnum() for c in seen)
    assert len(seen) == 2000


def test_reserved_and_aliases():
    assert codes.is_reserved("Login")
    assert codes.alias_problem("login")
    assert codes.alias_problem("ab")  # too short
    assert codes.alias_problem("has space")
    assert codes.alias_problem("my-launch") is None


@pytest.mark.parametrize("raw,expected", [
    ("example.com", "https://example.com/"),
    ("HTTPS://Example.COM/Path?Q=1", "https://example.com/Path?Q=1"),
    ("http://example.com/a#frag", "http://example.com/a#frag"),
])
def test_normalize(raw, expected):
    assert urls.normalize(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "javascript:alert(1)", "ftp://example.com", "http://localhost/x", "http://127.0.0.1/",
    "http://10.0.0.5/", "https://cla.ms/abc123", "notaurl", "http://exa mple.com",
])
def test_normalize_rejects(raw):
    with pytest.raises(urls.BadURL):
        urls.normalize(raw)


def test_user_agents():
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
    a = useragent.parse(iphone)
    assert (a.device, a.browser, a.os, a.is_bot) == ("mobile", "Safari", "iOS", False)
    mac_chrome = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    assert useragent.parse(mac_chrome).browser == "Chrome"
    assert useragent.parse("Slackbot-LinkExpanding 1.0").is_bot
    assert useragent.parse("facebookexternalhit/1.1").is_bot
    assert useragent.parse("").is_bot
