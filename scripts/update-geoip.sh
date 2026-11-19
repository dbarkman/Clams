#!/usr/bin/env bash
# Fetch DB-IP's free IP-to-Country Lite database (CC BY 4.0, attribution on /privacy).
# Runs monthly from apache's crontab on web2. The app reloads the file when it changes.
set -euo pipefail
dest_dir="$(dirname "$0")/../data"
mkdir -p "$dest_dir"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
for month in "$(date -u +%Y-%m)" "$(date -u -d 'last month' +%Y-%m 2>/dev/null || date -u -v-1m +%Y-%m)"; do
  if curl -fsSL --max-time 120 "https://download.db-ip.com/free/dbip-country-lite-${month}.mmdb.gz" -o "$tmp"; then
    gunzip -c "$tmp" > "$dest_dir/geoip-country.mmdb.new"
    mv "$dest_dir/geoip-country.mmdb.new" "$dest_dir/geoip-country.mmdb"
    echo "geoip updated to ${month}"
    exit 0
  fi
done
echo "geoip download failed" >&2
exit 1
