"""SQL Server connection helper for the Etrack bio-attendance source.

Reads credentials from `.env.sqlserver` at the project root (falling back
to process environment if the file is missing). Returns a live
`pyodbc.Connection` ready for queries against `DeviceLogs_<month>_<year>`
tables.

Required env vars (in `.env.sqlserver`):
    ETRACK_SQLSERVER_HOST       e.g. 192.168.0.50
    ETRACK_SQLSERVER_PORT       e.g. 1433  (optional, default 1433)
    ETRACK_SQLSERVER_DB         e.g. Etrack
    ETRACK_SQLSERVER_USER       e.g. sa
    ETRACK_SQLSERVER_PASSWORD   the password
    ETRACK_SQLSERVER_DRIVER     e.g. ODBC Driver 17 for SQL Server
    ETRACK_SQLSERVER_TRUST_CERT yes|no  (optional, default yes)
"""

from __future__ import annotations

import os
from pathlib import Path

import pyodbc

try:
    from dotenv import load_dotenv as _load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    _load_dotenv = None

_ENV_FILE_NAME = ".env.sqlserver"
_loaded_env_path: str | None = None


def _load_env_file() -> None:
    """Load ETRACK_* values from .env.sqlserver if present.

    Searches the current working dir and parents of this file so it works
    whether the server is started from the project root or elsewhere.
    Values from the file override existing process env vars.
    """
    global _loaded_env_path
    if _loaded_env_path is not None or _load_dotenv is None:
        return

    candidates = []
    here = Path(__file__).resolve()
    for parent in [Path.cwd(), *here.parents]:
        candidates.append(parent / _ENV_FILE_NAME)

    seen: set[str] = set()
    for path in candidates:
        s = str(path)
        if s in seen:
            continue
        seen.add(s)
        if path.is_file():
            _load_dotenv(dotenv_path=path, override=True)
            _loaded_env_path = s
            return


def _required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Missing required env var: {name} (expected in {_ENV_FILE_NAME})"
        )
    return val


def get_etrack_connection() -> pyodbc.Connection:
    """Open a fresh pyodbc connection to the Etrack SQL Server."""
    _load_env_file()

    host = _required("ETRACK_SQLSERVER_HOST")
    port = os.getenv("ETRACK_SQLSERVER_PORT", "1433")
    db = _required("ETRACK_SQLSERVER_DB")
    user = _required("ETRACK_SQLSERVER_USER")
    pwd = _required("ETRACK_SQLSERVER_PASSWORD")
    driver = os.getenv(
        "ETRACK_SQLSERVER_DRIVER", "ODBC Driver 17 for SQL Server"
    )
    trust = os.getenv("ETRACK_SQLSERVER_TRUST_CERT", "yes").lower()
    trust_flag = "yes" if trust in ("1", "yes", "true") else "no"

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={db};"
        f"UID={user};"
        f"PWD={pwd};"
        f"TrustServerCertificate={trust_flag};"
        f"Encrypt=no;"
    )
    return pyodbc.connect(conn_str, timeout=15)


def device_logs_table_name(d) -> str:
    """Return DeviceLogs_<month>_<year> for the given date.

    Example: date(2026, 4, 15) -> 'DeviceLogs_4_2026'.
    """
    return f"DeviceLogs_{d.month}_{d.year}"
