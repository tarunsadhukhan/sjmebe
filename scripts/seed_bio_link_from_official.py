"""One-time seed: insert 'E' (employee) link rows into tbl_master_bio_link_mst
from hrms_ed_official_details for a single branch, skipping employees that
already have an 'E' link.

Mapping (per tbl_master_bio_link_mst / _upsert_bio_link in src/hrms/employee.py):
    master_data = emp_code
    master_id   = eb_id
    match_type  = 'E'
    bio_data    = bio_metric_id (string)
    bio_dev_id  = bio_metric_id (int, when numeric)

"If not exists" key matches the upsert: match_type='E' AND master_id=eb_id.

Usage:  python scripts/seed_bio_link_from_official.py [db_name] [branch_id]
        defaults: db_name=sjm  branch_id=103
"""
import os
import sys
import pymysql
from dotenv import load_dotenv

load_dotenv()

DB = sys.argv[1] if len(sys.argv) > 1 else "sjm"
BRANCH_ID = int(sys.argv[2]) if len(sys.argv) > 2 else 103

INSERT_SQL = """
    INSERT INTO tbl_master_bio_link_mst
        (master_data, master_id, match_type, bio_data, bio_dev_id)
    SELECT
        o.emp_code,
        o.eb_id,
        'E',
        o.bio_metric_id,
        CASE
            WHEN o.bio_metric_id REGEXP '^[0-9]+$'
            THEN CAST(o.bio_metric_id AS UNSIGNED)
            ELSE NULL
        END
    FROM hrms_ed_official_details o
    WHERE o.branch_id = %s
      AND o.active = 1
      AND NOT EXISTS (
          SELECT 1
          FROM tbl_master_bio_link_mst m
          WHERE m.match_type = 'E'
            AND m.master_id  = o.eb_id
      )
"""


def main() -> None:
    conn = pymysql.connect(
        host=os.getenv("DATABASE_HOST"),
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        port=int(os.getenv("DATABASE_PORT")),
        database=DB,
    )
    try:
        cur = conn.cursor()
        inserted = cur.execute(INSERT_SQL, (BRANCH_ID,))
        conn.commit()
        print(f"[{DB}] branch_id={BRANCH_ID}: 'E' link rows inserted: {inserted}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
