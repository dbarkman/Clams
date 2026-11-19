"""clams-admin: server-side chores.

  clams-admin migrate              create any missing tables
  clams-admin grant EMAIL          make an account an admin
  clams-admin revoke EMAIL         remove admin
"""

from __future__ import annotations

import sys

from . import db, users


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    if cmd == "migrate":
        db.create_all()
        print("schema current")
        return 0
    if cmd in ("grant", "revoke") and len(args) == 2:
        ok = users.set_admin(args[1], cmd == "grant")
        print("done" if ok else f"no account for {args[1]}")
        return 0 if ok else 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
