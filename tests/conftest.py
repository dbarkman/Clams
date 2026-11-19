import os

os.environ["CLAMS_DATABASE_URL"] = "sqlite://"
os.environ["CLAMS_SECURE_COOKIES"] = "0"
os.environ["CLAMS_SECRET_KEY"] = "test-secret"
os.environ["CLAMS_GEOIP_PATH"] = "/nonexistent.mmdb"

import re  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from clams import db  # noqa: E402
from clams.ratelimit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    engine = db.make_engine("sqlite://")
    db.set_engine(engine)
    db.metadata.create_all(engine)
    limiter.reset()
    yield
    engine.dispose()


@pytest.fixture
def client():
    from clams.app import app

    with TestClient(app, base_url="http://testserver", follow_redirects=False) as c:
        yield c


def csrf_of(client) -> str:
    """Load a page so the CSRF cookie exists, then return it."""
    if "clams_csrf" not in client.cookies:
        client.get("/")
    return client.cookies["clams_csrf"]


def signup(client, email="a@example.com", password="password123"):
    r = client.post("/signup", data={"email": email, "password": password, "csrf": csrf_of(client)})
    assert r.status_code == 303, r.text
    return r


def shorten(client, url, **extra):
    r = client.post("/shorten", data={"url": url, "csrf": csrf_of(client), **extra})
    assert r.status_code == 303, r.text
    return r


def code_from(location: str) -> str:
    m = re.search(r"/(?:new|links)/([^/?]+)", location)
    assert m, location
    return m.group(1)
