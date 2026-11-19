# Clams — cla.ms

A small, friendly URL shortener. Short links are called **Clams**.

- **Site:** https://cla.ms (web2, FastAPI on 127.0.0.1:8012 behind Apache, MariaDB `clams`)
- **Extension:** `extension/` (Manifest V3, shared by Chrome and Safari); `safari/` wraps it in a Mac + iOS app.

## Features

- 6-character, case-sensitive base62 codes (`cla.ms/aB3xY9`); custom names for signed-in users.
- Anonymous shortening (rate-limited per IP). Anonymous Clams carry a claim token, so the browser or
  extension that made them can attach them to an account after signing up.
- Accounts: email + password, Sign in with Google, Sign in with Apple (each provider is hidden until configured).
- Dashboard: search, edit destination/title, turn off/on, delete (codes are never reused), CSV export.
- Click stats: clicks per day, unique visitors (keyed hash, no IPs stored), referrers, countries (DB-IP Lite),
  devices, browsers, OS. Link-preview bots are recorded but not counted.
- QR code (SVG/PNG) for every Clam; `cla.ms/<code>+` previews the destination.
- Abuse: report form, admin page (turn off Clams, block domains), optional Google Safe Browsing check.
- JSON API with bearer tokens (`/api/v1/shorten`, `/api/v1/links`, `/api/v1/links/{code}`).

## Develop

```bash
uv sync
uv run pytest -q
```

Local server (SQLite): `CLAMS_DATABASE_URL=sqlite:///dev.db CLAMS_SECURE_COOKIES=0 uv run clams-admin migrate`
then `uv run uvicorn clams.app:app --port 8123` with the same variables.

After changing `extension/`, run `scripts/build-extension.sh` to refresh the downloadable zip.

## Deploy (web2)

Local repo → commit → push → on web2:

```bash
sudo -u apache git -C /var/www/html/clams pull
sudo -u apache bash -c 'cd /var/www/html/clams && /home/david/.local/bin/uv sync --frozen --no-dev && .venv/bin/clams-admin migrate'
sudo systemctl restart clams
```

`deploy/clams.service` → `/etc/systemd/system/clams.service`; `deploy/cla.ms.conf` → `/etc/httpd/conf.d/cla.ms.conf`.
Secrets live in `/var/www/html/clams/.env` (see `.env.example`). GeoIP refreshes monthly via apache's crontab
(`scripts/update-geoip.sh`). Make someone an admin with `.venv/bin/clams-admin grant EMAIL`.
