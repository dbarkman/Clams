from clams import links, users
from conftest import csrf_of, signup


def test_anonymous_api_shorten_then_claim(client):
    r = client.post("/api/v1/shorten", json={"url": "https://example.com/page", "title": "A page"},
                    headers={"X-Clams-Extension": "1"})
    assert r.status_code == 201
    body = r.json()
    assert body["saved"] is False and body["claim_token"].startswith("clc_")
    assert body["short_url"] == f"https://cla.ms/{body['code']}"
    assert links.by_code(body["code"])["source"] == "extension"

    signup(client)
    user = users.by_email("a@example.com")
    token = users.new_api_token(user["id"], "test", "extension")
    auth = {"Authorization": f"Bearer {token}"}
    claimed = client.post("/api/v1/links/claim", json={"claim_tokens": [body["claim_token"], "junk"]}, headers=auth)
    assert claimed.json() == {"claimed": 1}
    again = client.post("/api/v1/links/claim", json={"claim_tokens": [body["claim_token"]]}, headers=auth)
    assert again.json() == {"claimed": 0}
    listed = client.get("/api/v1/links", headers=auth).json()
    assert listed["total"] == 1 and listed["links"][0]["title"] == "A page"


def test_signed_in_api_shorten(client):
    signup(client)
    token = users.new_api_token(users.by_email("a@example.com")["id"], "t")
    auth = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/shorten", json={"url": "example.com/x"}, headers=auth)
    assert r.status_code == 201 and r.json()["saved"] is True and "claim_token" not in r.json()
    r2 = client.post("/api/v1/shorten", json={"url": "example.com/x"}, headers=auth)
    assert r2.status_code == 200 and r2.json()["reused"] and r2.json()["code"] == r.json()["code"]
    detail = client.get(f"/api/v1/links/{r.json()['code']}", headers=auth).json()
    assert detail["stats"]["clicks"] == 0
    assert client.get("/api/v1/me", headers=auth).json()["email"] == "a@example.com"


def test_revoked_or_bad_token(client):
    r = client.post("/api/v1/shorten", json={"url": "https://example.com"}, headers={"Authorization": "Bearer clm_bogus"})
    assert r.status_code == 401
    signup(client)
    token = users.new_api_token(users.by_email("a@example.com")["id"], "t")
    client.request("DELETE", "/api/v1/extension/token", headers={"Authorization": f"Bearer {token}"})
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_bad_url_api(client):
    r = client.post("/api/v1/shorten", json={"url": "chrome://extensions"})
    assert r.status_code == 400 and "http" in r.json()["error"]


def test_extension_token_from_session(client):
    assert client.post("/api/v1/extension/token", headers={"X-Clams-Extension": "1"}).status_code == 401
    signup(client)
    assert client.post("/api/v1/extension/token").status_code == 400  # header required
    r = client.post("/api/v1/extension/token", headers={"X-Clams-Extension": "1", "X-Clams-Browser": "Chrome"})
    assert r.status_code == 200 and r.json()["token"].startswith("clm_")


def test_connect_page_token(client):
    signup(client)
    assert client.get("/extension/connect").status_code == 200
    bad = client.post("/extension/connect/token", headers={"X-CSRF-Token": "nope"})
    assert bad.status_code == 400
    ok = client.post("/extension/connect/token", headers={"X-CSRF-Token": csrf_of(client), "X-Clams-Browser": "Safari"})
    assert ok.status_code == 200 and ok.json()["email"] == "a@example.com"
    assert any(t["label"] == "Safari extension" for t in users.list_tokens(users.by_email("a@example.com")["id"]))
