"""Add supplier-registration columns to party_branch_mst if missing.

The PartyBranchMst model (src/masters/models.py) declares columns that the
sjm tenant DB never received (email_id, bank_acc_no, ...). SQLAlchemy INSERTs
every model column, so party_edit / party_create / supplier_register 500 with
"Unknown column 'email_id' in 'field list'" until these exist.

Run from repo root:  .venv\Scripts\python.exe dbqueries\migrations\add_party_branch_supplier_cols.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import create_engine, text
from src.config.db import get_db_names  # noqa: F401  (ensures env is loaded the same way the app does)
from dotenv import load_dotenv

load_dotenv()

TENANT = os.environ.get("STATIC_TENANT", "sjm")
URL = (
    f"mysql+pymysql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD'].replace('#', '%23')}"
    f"@{os.environ['DATABASE_HOST']}:{os.environ.get('DATABASE_PORT', '3306')}/{TENANT}"
)

# column name -> DDL type, mirroring PartyBranchMst
EXPECTED = {
    "created_date": "DATETIME NULL",
    "created_by": "INT NULL",
    "state_id": "INT NULL",
    "city_id": "INT NULL",
    "email_id": "VARCHAR(100) NULL",
    "bank_acc_no": "VARCHAR(100) NULL",
    "ifsc_code": "VARCHAR(100) NULL",
    "bank_name": "VARCHAR(100) NULL",
    "bank_branch": "VARCHAR(100) NULL",
    "whatsapp_no": "VARCHAR(100) NULL",
    "upi_code": "VARCHAR(100) NULL",
}


def main() -> None:
    engine = create_engine(URL)
    with engine.begin() as conn:
        existing = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :db AND table_name = 'party_branch_mst'"
                ),
                {"db": TENANT},
            )
        }
        print(f"existing columns: {sorted(existing)}")
        missing = [c for c in EXPECTED if c not in existing]
        if not missing:
            print("nothing to do — all expected columns present")
            return
        for col in missing:
            ddl = f"ALTER TABLE party_branch_mst ADD COLUMN {col} {EXPECTED[col]}"
            print(ddl)
            conn.execute(text(ddl))
        print(f"added {len(missing)} column(s): {missing}")


if __name__ == "__main__":
    main()
