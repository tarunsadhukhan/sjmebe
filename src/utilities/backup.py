"""Database backup utility.

Streams a full SQL dump of the tenant database as a downloadable file.
Pure-Python (pymysql) so it works on Windows hosts and slim Docker images
without a mysqldump binary.

ponytail: dumps tables + views only — no triggers/routines/events; add
mysqldump via subprocess if those are ever needed.
"""

import os
import pymysql
from fastapi import Depends, Request, HTTPException, APIRouter
from fastapi.responses import StreamingResponse

from src.config.db import extract_subdomain_from_request
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist

router = APIRouter()

BATCH_ROWS = 500


def _iter_dump(db_name: str):
    """Yield the SQL dump of db_name chunk by chunk (streaming, low memory)."""
    conn = pymysql.connect(
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT", "3306")),
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        database=db_name,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW FULL TABLES")
            all_tables = cur.fetchall()
        tables = [r[0] for r in all_tables if r[1] == "BASE TABLE"]
        views = [r[0] for r in all_tables if r[1] == "VIEW"]

        yield (
            f"-- Backup of `{db_name}` generated {now_ist()}\n"
            "SET NAMES utf8mb4;\n"
            "SET FOREIGN_KEY_CHECKS=0;\n\n"
        )

        for t in tables:
            with conn.cursor() as cur:
                cur.execute(f"SHOW CREATE TABLE `{t}`")
                create_stmt = cur.fetchone()[1]
            yield f"DROP TABLE IF EXISTS `{t}`;\n{create_stmt};\n\n"

            # SSCursor streams rows instead of loading the whole table
            cur = conn.cursor(pymysql.cursors.SSCursor)
            try:
                cur.execute(f"SELECT * FROM `{t}`")
                batch = []
                for row in cur:
                    batch.append("(" + ",".join(conn.escape(v) for v in row) + ")")
                    if len(batch) >= BATCH_ROWS:
                        yield f"INSERT INTO `{t}` VALUES\n" + ",\n".join(batch) + ";\n"
                        batch = []
                if batch:
                    yield f"INSERT INTO `{t}` VALUES\n" + ",\n".join(batch) + ";\n"
                yield "\n"
            finally:
                cur.close()

        for v in views:
            with conn.cursor() as cur:
                cur.execute(f"SHOW CREATE TABLE `{v}`")
                create_stmt = cur.fetchone()[1]
            yield f"DROP VIEW IF EXISTS `{v}`;\n{create_stmt};\n\n"

        yield "SET FOREIGN_KEY_CHECKS=1;\n"
    finally:
        conn.close()


@router.get("/backup_download")
async def backup_download(
    request: Request,
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Stream a full SQL dump of the tenant database as an attachment."""
    try:
        db_name = extract_subdomain_from_request(request)
        if not db_name or db_name == "default":
            raise HTTPException(status_code=400, detail="Could not resolve tenant database")

        filename = f"{db_name}_{now_ist().strftime('%Y%m%d_%H%M%S')}.sql"
        return StreamingResponse(
            _iter_dump(db_name),
            media_type="application/sql",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"backup_download error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
