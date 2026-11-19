"""Schema and engine. SQLAlchemy Core only: no ORM, explicit statements.

MariaDB in production, SQLite in tests. The one dialect detail that matters is
the Clam code column: MariaDB compares strings case-insensitively by default,
so `code` uses a binary collation there. Without it `aB3xY9` and `ab3xy9`
would be the same Clam.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool
from sqlalchemy import Table

from .settings import settings

metadata = MetaData()

# Binary (case-sensitive) on MariaDB; SQLite's default comparison is already case-sensitive.
CodeString = String(32).with_variant(String(32, collation="utf8mb4_bin"), "mysql", "mariadb")
Id = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    """Naive UTC, which is how every timestamp is stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


users = Table(
    "users",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("email_verified", Boolean, nullable=False, default=False),
    Column("password_hash", String(255)),
    Column("display_name", String(120)),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("last_login_at", DateTime),
    mysql_charset="utf8mb4",
)

oauth_identities = Table(
    "oauth_identities",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("user_id", Id, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(16), nullable=False),
    Column("subject", String(255), nullable=False),
    Column("email", String(254)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    UniqueConstraint("provider", "subject", name="uq_oauth_provider_subject"),
    mysql_charset="utf8mb4",
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("user_id", Id, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("last_seen_at", DateTime, nullable=False, default=utcnow),
    Column("expires_at", DateTime, nullable=False),
    Column("user_agent", String(255)),
    mysql_charset="utf8mb4",
)

api_tokens = Table(
    "api_tokens",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("user_id", Id, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("label", String(120), nullable=False),
    Column("kind", String(16), nullable=False, default="api"),  # 'extension' or 'api'
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("last_used_at", DateTime),
    Column("revoked_at", DateTime),
    mysql_charset="utf8mb4",
)

email_tokens = Table(
    "email_tokens",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("user_id", Id, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(16), nullable=False),  # 'reset' or 'verify'
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("expires_at", DateTime, nullable=False),
    Column("used_at", DateTime),
    mysql_charset="utf8mb4",
)

links = Table(
    "links",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("code", CodeString, nullable=False, unique=True),
    Column("url", Text, nullable=False),
    Column("url_hash", String(64), nullable=False),
    Column("title", String(300)),
    Column("user_id", Id, ForeignKey("users.id", ondelete="SET NULL")),
    Column("is_custom", Boolean, nullable=False, default=False),
    # Anonymous links carry a claim token (hashed) so the creator can attach them to an account later.
    Column("claim_hash", String(64)),
    Column("source", String(16), nullable=False, default="web"),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("updated_at", DateTime, nullable=False, default=utcnow),
    Column("disabled_at", DateTime),
    Column("disabled_reason", String(255)),
    # Deleted Clams keep their row so the code is never handed out again.
    Column("deleted_at", DateTime),
    Column("click_count", BigInteger, nullable=False, default=0),
    Column("last_clicked_at", DateTime),
    Column("creator_hash", String(64)),
    Index("ix_links_user_created", "user_id", "created_at"),
    Index("ix_links_user_urlhash", "user_id", "url_hash"),
    Index("ix_links_claim", "claim_hash"),
    mysql_charset="utf8mb4",
)

clicks = Table(
    "clicks",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("link_id", Id, ForeignKey("links.id", ondelete="CASCADE"), nullable=False),
    Column("clicked_at", DateTime, nullable=False, default=utcnow),
    Column("referrer_host", String(255)),
    Column("country", String(2)),
    Column("device", String(16)),
    Column("browser", String(32)),
    Column("os", String(32)),
    Column("visitor_hash", String(32)),
    Column("is_bot", Boolean, nullable=False, default=False),
    Index("ix_clicks_link_time", "link_id", "clicked_at"),
    mysql_charset="utf8mb4",
)

reports = Table(
    "reports",
    metadata,
    Column("id", Id, primary_key=True, autoincrement=True),
    Column("code", CodeString, nullable=False),
    Column("reason", String(32), nullable=False),
    Column("details", Text),
    Column("reporter_email", String(254)),
    Column("reporter_hash", String(64)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("resolved_at", DateTime),
    Column("resolution", String(32)),
    mysql_charset="utf8mb4",
)

blocked_domains = Table(
    "blocked_domains",
    metadata,
    Column("domain", String(255), primary_key=True),
    Column("reason", String(255)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    mysql_charset="utf8mb4",
)

_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600, pool_size=5, max_overflow=5)


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(settings.sqlalchemy_url)
    return _engine


def set_engine(new: Engine) -> None:
    """Tests swap in a SQLite engine."""
    global _engine
    _engine = new


@contextmanager
def tx() -> Iterator[Connection]:
    with engine().begin() as conn:
        yield conn


def create_all() -> None:
    metadata.create_all(engine())
