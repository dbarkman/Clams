# Clams (cla.ms)

URL shortener; short links are "Clams". See README.md for features, dev and deploy steps.

- Python 3.12, uv, exact pins. FastAPI + Jinja2 + SQLAlchemy Core (no ORM). MariaDB in production, SQLite in tests.
- `links.code` uses a binary collation on MariaDB: codes are case-sensitive. Keep it that way.
- Deleted Clams are soft-deleted and their codes are never reissued.
- Never store raw IPs; use `security.keyed_hash`.
- Forms use post/redirect/get and the double-submit CSRF cookie (`clams_csrf`). Every POST form includes `csrf`.
- Optional integrations (Google, Apple, Resend email, Safe Browsing) switch on by env vars only.
- Production: web2, `/var/www/html/clams`, service `clams` on 127.0.0.1:8012, DB `clams`. Never edit on the server:
  change locally → commit → push → pull on web2.
- The extension (`extension/`) talks only to https://cla.ms. After changes, run `scripts/build-extension.sh`.
