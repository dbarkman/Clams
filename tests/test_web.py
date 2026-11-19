from sqlalchemy import select

from clams import db, links, users
from conftest import code_from, csrf_of, shorten, signup


def test_home_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Long links in" in r.text
    assert "clams_csrf" in client.cookies


def test_anonymous_shorten_and_redirect(client):
    r = shorten(client, "example.com/hello")
    code = code_from(r.headers["location"])
    assert r.headers["location"] == f"/new/{code}"
    assert "clams_claims" in client.cookies
    page = client.get(f"/new/{code}")
    assert "Want to keep this one?" in page.text
    hop = client.get(f"/{code}", headers={"user-agent": "Mozilla/5.0 (Macintosh) Chrome/131.0 Safari/537.36",
                                           "referer": "https://news.example.org/post"})
    assert hop.status_code == 302
    assert hop.headers["location"] == "https://example.com/hello"
    link = links.by_code(code)
    assert link["click_count"] == 1
    with db.tx() as conn:
        click = conn.execute(select(db.clicks)).one()
    assert click.referrer_host == "news.example.org" and click.browser == "Chrome" and not click.is_bot


def test_codes_are_case_sensitive(client):
    code = code_from(shorten(client, "https://example.com/a").headers["location"])
    flipped = code.swapcase()
    if flipped != code:
        assert client.get(f"/{flipped}").status_code == 404


def test_bots_not_counted(client):
    code = code_from(shorten(client, "https://example.com/b").headers["location"])
    client.get(f"/{code}", headers={"user-agent": "Slackbot-LinkExpanding 1.0"})
    assert links.by_code(code)["click_count"] == 0


def test_head_does_not_count(client):
    code = code_from(shorten(client, "https://example.com/head").headers["location"])
    assert client.head(f"/{code}").status_code == 302
    assert links.by_code(code)["click_count"] == 0


def test_preview_page(client):
    code = code_from(shorten(client, "https://example.com/preview").headers["location"])
    r = client.get(f"/{code}+")
    assert r.status_code == 200 and "https://example.com/preview" in r.text


def test_missing_and_bad_csrf(client):
    assert client.get("/zzzzzz").status_code == 404
    csrf_of(client)
    r = client.post("/shorten", data={"url": "https://example.com", "csrf": "wrong"})
    assert r.status_code == 400


def test_signup_claims_anonymous_links(client):
    code = code_from(shorten(client, "https://example.com/mine").headers["location"])
    signup(client)
    user = users.by_email("a@example.com")
    assert links.by_code(code)["user_id"] == user["id"]
    assert "clams_claims" not in client.cookies
    r = client.get("/links")
    assert code in r.text


def test_signed_in_shorten_dedupes_and_alias(client):
    signup(client)
    a = code_from(shorten(client, "https://example.com/x").headers["location"])
    b = code_from(shorten(client, "https://example.com/x").headers["location"])
    assert a == b
    r = shorten(client, "https://example.com/y", alias="my-launch")
    assert code_from(r.headers["location"]) == "my-launch"
    r = client.post("/shorten", data={"url": "https://example.com/z", "alias": "my-launch", "csrf": csrf_of(client)})
    assert client.get("/").status_code == 200  # flash shown, nothing broken
    assert links.by_code("my-launch")["url"] == "https://example.com/y"
    # Reserved names refused
    shorten(client, "https://example.com/r", alias="login")
    assert links.by_code("login") is None


def test_anonymous_cannot_alias(client):
    r = shorten(client, "https://example.com/q", alias="sneaky")
    assert links.by_code("sneaky") is None
    assert r.headers["location"].startswith("/new/")


def test_users_cannot_see_each_others_links(client):
    signup(client, "a@example.com")
    code = code_from(shorten(client, "https://example.com/private").headers["location"])
    client.post("/logout", data={"csrf": csrf_of(client)})
    signup(client, "b@example.com")
    assert client.get(f"/links/{code}").status_code == 404
    r = client.post(f"/links/{code}/delete", data={"csrf": csrf_of(client)})
    assert links.by_code(code)["deleted_at"] is None
    assert code not in client.get("/links").text


def test_edit_toggle_delete(client):
    signup(client)
    code = code_from(shorten(client, "https://example.com/e").headers["location"])
    client.post(f"/links/{code}/edit", data={"url": "https://example.org/new", "title": "Hi", "csrf": csrf_of(client)})
    assert client.get(f"/{code}").headers["location"] == "https://example.org/new"
    client.post(f"/links/{code}/toggle", data={"csrf": csrf_of(client)})
    assert client.get(f"/{code}").status_code == 410
    client.post(f"/links/{code}/toggle", data={"csrf": csrf_of(client)})
    assert client.get(f"/{code}").status_code == 302
    client.post(f"/links/{code}/delete", data={"csrf": csrf_of(client)})
    r = client.get(f"/{code}")
    assert r.status_code == 410 and "gone" in r.text


def test_stats_page_and_export(client):
    signup(client)
    code = code_from(shorten(client, "https://example.com/s").headers["location"])
    for ua in ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1",
               "Mozilla/5.0 (Windows NT 10.0) Chrome/131.0 Safari/537.36"):
        client.get(f"/{code}", headers={"user-agent": ua})
    for rng in ("7d", "30d", "90d", "all"):
        r = client.get(f"/links/{code}?range={rng}")
        assert r.status_code == 200
        assert "mobile" in r.text and "Windows" in r.text
    csv = client.get("/links/export.csv")
    assert csv.status_code == 200 and code in csv.text


def test_qr_codes(client):
    code = code_from(shorten(client, "https://example.com/qr").headers["location"])
    svg = client.get(f"/qr/{code}.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg")
    png = client.get(f"/qr/{code}.png")
    assert png.content[:4] == b"\x89PNG"


def test_anonymous_rate_limit(client, monkeypatch):
    from clams.settings import settings

    monkeypatch.setattr(settings, "anon_links_per_hour", 2)
    shorten(client, "https://example.com/1")
    shorten(client, "https://example.com/2")
    r = shorten(client, "https://example.com/3")
    assert r.headers["location"] == "/"


def test_login_logout_and_bad_password(client):
    signup(client)
    client.post("/logout", data={"csrf": csrf_of(client)})
    assert client.get("/links").status_code == 303
    bad = client.post("/login", data={"email": "a@example.com", "password": "nope-nope", "csrf": csrf_of(client)})
    assert bad.status_code == 401
    ok = client.post("/login", data={"email": "A@Example.com", "password": "password123", "csrf": csrf_of(client)})
    assert ok.status_code == 303
    assert client.get("/links").status_code == 200


def test_open_redirect_blocked_on_login(client):
    signup(client)
    client.post("/logout", data={"csrf": csrf_of(client)})
    r = client.post("/login", data={"email": "a@example.com", "password": "password123", "next": "//evil.example",
                                    "csrf": csrf_of(client)})
    assert r.headers["location"] == "/links"


def test_report_and_admin(client):
    code = code_from(shorten(client, "https://bad.example.net/phish").headers["location"])
    r = client.post("/report", data={"code": f"https://cla.ms/{code}", "reason": "phishing", "csrf": csrf_of(client)})
    assert r.status_code == 303
    signup(client, "admin@example.com")
    assert client.get("/admin").status_code == 404
    users.set_admin("admin@example.com", True)
    page = client.get("/admin")
    assert page.status_code == 200 and code in page.text
    client.post("/admin/block", data={"domain": "example.net", "csrf": csrf_of(client)})
    assert client.get(f"/{code}").status_code == 410
    bad = shorten(client, "https://www.example.net/again")
    assert bad.headers["location"] == "/"


def test_delete_account(client):
    signup(client)
    code = code_from(shorten(client, "https://example.com/d").headers["location"])
    client.post("/account/delete", data={"confirm": "a@example.com", "csrf": csrf_of(client)})
    assert users.by_email("a@example.com") is None
    assert client.get(f"/{code}").status_code == 410


def test_static_pages(client):
    for path in ("/about", "/privacy", "/terms", "/extension", "/report", "/login", "/signup", "/forgot", "/robots.txt",
                 "/healthz"):
        assert client.get(path).status_code == 200, path


def test_api_token_one_time_display(client):
    signup(client)
    client.post("/account/tokens", data={"label": "script", "csrf": csrf_of(client)})
    first = client.get("/account")
    assert "clm_" in first.text
    second = client.get("/account")
    assert "shown once):" not in second.text
