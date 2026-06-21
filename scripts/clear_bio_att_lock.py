"""clear_bio_att_lock.py — One-shot tool to clear a STALE bio_att_auto lock.

The bio-attendance pipeline guards itself with the MySQL named lock
``bio_att_auto`` (GET_LOCK). That lock is connection-scoped, so a run that was
killed mid-flight can leave its connection lingering server-side as an idle
"Sleep", holding the lock for hours and blocking every later run.

This script finds the lock holder and, ONLY IF that connection is idle (Sleep),
kills it to release the lock. It refuses to touch a connection that is actively
running a query, so it can never interrupt a real in-progress run.

Usage:
    python -m scripts.clear_bio_att_lock --tenant sjm
    # or
    .\\.venv\\Scripts\\python.exe scripts\\clear_bio_att_lock.py --tenant sjm
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `src.*` importable when run as a plain script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text
from src.hrms.bio_att_scheduler import make_session

_LOCK = "bio_att_auto"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Clear a stale bio_att_auto MySQL lock.")
    p.add_argument("--tenant", default="sjm", help="MySQL tenant/DB name (default: sjm)")
    p.add_argument(
        "--force",
        action="store_true",
        help="Kill the holder even if it is NOT idle (use with care).",
    )
    args = p.parse_args(argv)

    db = make_session(args.tenant)
    try:
        holder = db.execute(text(f"SELECT IS_USED_LOCK('{_LOCK}')")).first()[0]
        if holder is None:
            print(f"Lock '{_LOCK}' is already free — nothing to do.")
            return 0

        info = db.execute(
            text("SELECT COMMAND, TIME, USER, HOST FROM information_schema.PROCESSLIST WHERE ID = :i"),
            {"i": holder},
        ).first()
        if info is None:
            print(f"Lock holder {holder} not found in processlist — re-check; it may have just cleared.")
            return 0

        command, time_s, user, host = info.COMMAND, info.TIME, info.USER, info.HOST
        print(f"Lock '{_LOCK}' held by connection {holder}: "
              f"COMMAND={command}, idle TIME={time_s}s, user={user}, host={host}")

        if command != "Sleep" and not args.force:
            print("Holder is ACTIVE (not 'Sleep') — refusing to kill it. "
                  "If you are certain it is stuck, re-run with --force.")
            return 2

        db.execute(text(f"KILL {int(holder)}"))
        print(f"Killed connection {holder}.")

        # Verify
        still = db.execute(text(f"SELECT IS_USED_LOCK('{_LOCK}')")).first()[0]
        if still is None:
            print(f"Lock '{_LOCK}' is now FREE.")
            return 0
        print(f"Lock still held by {still} — re-run to clear the new holder.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
