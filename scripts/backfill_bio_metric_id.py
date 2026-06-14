"""One-time backfill: populate hrms_ed_official_details.bio_metric_id from
tbl_master_bio_link_mst (match_type='E', master_id=eb_id -> bio_dev_id).

Employees with no matching link row (bio_metric_id still NULL) are exported to
an Excel file so the missing bio ids can be filled in manually.

Usage:  python scripts/backfill_bio_metric_id.py [db_name]   (default: sjm)
"""
import os
import sys
import pymysql
from openpyxl import Workbook
from dotenv import load_dotenv

load_dotenv()

DB = sys.argv[1] if len(sys.argv) > 1 else "sjm"

UPDATE_SQL = """
    UPDATE hrms_ed_official_details o
    JOIN tbl_master_bio_link_mst m
        ON m.match_type = 'E'
       AND m.master_id = o.eb_id
       AND m.bio_dev_id IS NOT NULL
    SET o.bio_metric_id = m.bio_dev_id
    WHERE o.active = 1
"""

# Active employees still missing a bio id after the backfill.
BLANKS_SQL = """
    SELECT o.eb_id,
           o.emp_code,
           TRIM(CONCAT_WS(' ', p.first_name, IFNULL(p.middle_name, ''), IFNULL(p.last_name, ''))) AS employee_name,
           b.branch_name,
           sd.sub_dept_desc AS sub_department,
           des.desig        AS designation
    FROM hrms_ed_official_details o
    LEFT JOIN hrms_ed_personal_details p ON p.eb_id = o.eb_id
    LEFT JOIN branch_mst        b   ON b.branch_id      = o.branch_id
    LEFT JOIN sub_dept_mst      sd  ON sd.sub_dept_id   = o.sub_dept_id
    LEFT JOIN designation_mst   des ON des.designation_id = o.designation_id
    WHERE o.active = 1
      AND o.bio_metric_id IS NULL
    ORDER BY b.branch_name, o.emp_code
"""

HEADERS = ["eb_id", "emp_code", "employee_name", "branch_name", "sub_department", "designation"]


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

        # 1) Backfill
        updated = cur.execute(UPDATE_SQL)
        conn.commit()
        print(f"[{DB}] bio_metric_id updated rows: {updated}")

        # 2) Collect blanks (not found)
        cur.execute(BLANKS_SQL)
        blanks = cur.fetchall()
        print(f"[{DB}] employees still blank (not found): {len(blanks)}")

        # 3) Write Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Bio ID Missing"
        ws.append(HEADERS)
        for row in blanks:
            ws.append(list(row))

        out_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"bio_metric_id_blank_{DB}.xlsx",
        )
        wb.save(out_path)
        print(f"[{DB}] blank report written: {out_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
