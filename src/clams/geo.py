"""Country lookup from DB-IP's free IP-to-Country Lite database (CC BY 4.0).

The file is refreshed monthly by scripts/update-geoip.sh. Without it, clicks
are recorded with no country.
"""

from __future__ import annotations

import os
import threading

from .settings import settings

_lock = threading.Lock()
_reader = None
_mtime: float | None = None


def _get_reader():
    global _reader, _mtime
    path = settings.geoip_path
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    with _lock:
        if _reader is None or _mtime != mtime:
            import maxminddb

            old = _reader
            _reader = maxminddb.open_database(path)
            _mtime = mtime
            if old is not None:
                old.close()
        return _reader


def country(ip: str | None) -> str | None:
    if not ip:
        return None
    reader = _get_reader()
    if reader is None:
        return None
    try:
        rec = reader.get(ip)
    except ValueError:
        return None
    if not rec:
        return None
    code = (rec.get("country") or {}).get("iso_code")
    return code if code and len(code) == 2 else None
