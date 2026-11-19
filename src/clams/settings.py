"""Configuration from the environment.

The server keeps its values in `.env` at the repo root (mode 600, apache-owned,
gitignored). Locally the same file works for development. Every optional
integration (Google, Apple, email, Safe Browsing) is off until its variables
are set, and the site hides whatever is off.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    path = REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(slots=True)
class Settings:
    # Database: a full SQLAlchemy URL wins (tests use SQLite); otherwise MariaDB parts.
    database_url: str = field(default_factory=lambda: _env("CLAMS_DATABASE_URL"))
    db_host: str = field(default_factory=lambda: _env("CLAMS_DB_HOST", "127.0.0.1"))
    db_port: int = field(default_factory=lambda: int(_env("CLAMS_DB_PORT", "3306")))
    db_name: str = field(default_factory=lambda: _env("CLAMS_DB_NAME", "clams"))
    db_user: str = field(default_factory=lambda: _env("CLAMS_DB_USER", "clams"))
    db_password: str = field(default_factory=lambda: _env("CLAMS_DB_PASSWORD"))

    base_url: str = field(default_factory=lambda: _env("CLAMS_BASE_URL", "https://cla.ms").rstrip("/"))
    # Signs CSRF tokens and salts visitor hashes. Required in production.
    secret_key: str = field(default_factory=lambda: _env("CLAMS_SECRET_KEY", "dev-only-secret"))
    secure_cookies: bool = field(default_factory=lambda: _env("CLAMS_SECURE_COOKIES", "1") == "1")

    # Abuse protection for anonymous visitors (per IP, per hour).
    anon_links_per_hour: int = field(default_factory=lambda: int(_env("CLAMS_ANON_LINKS_PER_HOUR", "30")))
    login_attempts_per_15min: int = field(default_factory=lambda: int(_env("CLAMS_LOGIN_ATTEMPTS_PER_15MIN", "10")))

    google_client_id: str = field(default_factory=lambda: _env("CLAMS_GOOGLE_CLIENT_ID"))
    google_client_secret: str = field(default_factory=lambda: _env("CLAMS_GOOGLE_CLIENT_SECRET"))

    apple_client_id: str = field(default_factory=lambda: _env("CLAMS_APPLE_CLIENT_ID"))  # the Services ID
    apple_team_id: str = field(default_factory=lambda: _env("CLAMS_APPLE_TEAM_ID"))
    apple_key_id: str = field(default_factory=lambda: _env("CLAMS_APPLE_KEY_ID"))
    apple_private_key_path: str = field(default_factory=lambda: _env("CLAMS_APPLE_PRIVATE_KEY_PATH"))

    resend_api_key: str = field(default_factory=lambda: _env("CLAMS_RESEND_API_KEY"))
    mail_from: str = field(default_factory=lambda: _env("CLAMS_MAIL_FROM", "Clams <hello@cla.ms>"))

    safe_browsing_key: str = field(default_factory=lambda: _env("CLAMS_SAFE_BROWSING_KEY"))
    geoip_path: str = field(default_factory=lambda: _env("CLAMS_GEOIP_PATH", str(REPO / "data" / "geoip-country.mmdb")))

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        from urllib.parse import quote_plus

        return (
            f"mysql+pymysql://{self.db_user}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def apple_enabled(self) -> bool:
        return bool(self.apple_client_id and self.apple_team_id and self.apple_key_id and self.apple_private_key_path)

    @property
    def mail_enabled(self) -> bool:
        return bool(self.resend_api_key)

    @property
    def short_host(self) -> str:
        return self.base_url.split("://", 1)[-1]


settings = Settings()
