import pytest

from clams import users


def test_provider_login_creates_then_finds():
    u1 = users.provider_login("google", "sub-1", "Person@Gmail.com", True)
    u2 = users.provider_login("google", "sub-1", "person@gmail.com", True)
    assert u1["id"] == u2["id"] and u1["email"] == "person@gmail.com" and u1["email_verified"]


def test_provider_login_links_verified_account():
    u = users.provider_login("google", "g-1", "x@example.com", True)
    a = users.provider_login("apple", "a-1", "x@example.com", True)
    assert a["id"] == u["id"]


def test_provider_login_takes_over_unverified_squatter():
    squatter = users.sign_up("victim@example.com", "attacker-pass")
    token = users.start_session(squatter["id"], "ua")
    api = users.new_api_token(squatter["id"], "x")
    owner = users.provider_login("google", "g-victim", "victim@example.com", True)
    assert owner["id"] == squatter["id"]
    assert owner["password_hash"] is None and owner["email_verified"]
    assert users.session_user(token) is None
    assert users.token_user(api) is None
    assert users.authenticate("victim@example.com", "attacker-pass") is None


def test_provider_login_requires_verified_email():
    with pytest.raises(users.AccountError):
        users.provider_login("google", "g-2", "y@example.com", False)


def test_signup_validation():
    with pytest.raises(users.AccountError):
        users.sign_up("not-an-email", "password123")
    with pytest.raises(users.AccountError):
        users.sign_up("ok@example.com", "short")
    users.sign_up("ok@example.com", "password123")
    with pytest.raises(users.AccountError):
        users.sign_up("OK@example.com", "password123")


def test_email_tokens_single_use():
    u = users.sign_up("r@example.com", "password123")
    t = users.new_email_token(u["id"], "reset", 1)
    assert users.peek_email_token(t, "reset")
    assert users.use_email_token(t, "verify") is None
    assert users.use_email_token(t, "reset") == u["id"]
    assert users.use_email_token(t, "reset") is None


def test_oauth_state_signing():
    from clams import oauth

    v = oauth.sign_state({"state": "s", "nonce": "n"})
    assert oauth.read_state(v)["state"] == "s"
    body, sig = v.rsplit(".", 1)
    assert oauth.read_state(body + "." + sig[:-2] + "AA") is None
    assert oauth.read_state("garbage") is None
