"""
HRMS Bio-Employee Master Link endpoints.

CRUD for `tbl_master_bio_link_mst` rows with match_type = 'E', which link an
employee (master_id = eb_id, master_data = emp_code) to a biometric device id
(bio_dev_id, mirrored as string in bio_data). These links are used by the bio
attendance processing to resolve device punches to employees.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()


# ─── Helpers ────────────────────────────────────────────────────────


def _parse_branch_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for tok in str(raw).split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid branch_id: {tok}")
    return out


def _to_int(value, field: str):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid integer for {field}")


def _validate_payload(db: Session, body: dict) -> dict:
    eb_id = _to_int(body.get("master_id"), "master_id")
    if not eb_id:
        raise HTTPException(status_code=400, detail="Employee (master_id) is required")
    bio_dev_id = _to_int(body.get("bio_dev_id"), "bio_dev_id")
    if bio_dev_id is None:
        raise HTTPException(status_code=400, detail="Bio device id is required")

    # master_data mirrors the employee's emp_code
    emp = db.execute(
        text("""
            SELECT o.emp_code
            FROM hrms_ed_official_details o
            WHERE o.eb_id = :eb_id AND COALESCE(o.active, 1) = 1
            LIMIT 1
        """),
        {"eb_id": eb_id},
    ).fetchone()
    if not emp:
        raise HTTPException(status_code=400, detail="Employee not found")

    return {
        "master_id": eb_id,
        "master_data": str(emp.emp_code) if emp.emp_code is not None else None,
        "bio_dev_id": bio_dev_id,
        "bio_data": str(bio_dev_id),
    }


def _check_duplicates(db: Session, data: dict, exclude_id: int | None = None) -> None:
    exclude_sql = "AND tbl_mst_bio_link_id <> :exclude_id" if exclude_id else ""
    params: dict = {"master_id": data["master_id"], "bio_dev_id": data["bio_dev_id"]}
    if exclude_id:
        params["exclude_id"] = exclude_id

    dup_emp = db.execute(
        text(f"""
            SELECT COUNT(*) AS cnt FROM tbl_master_bio_link_mst
            WHERE match_type = 'E' AND master_id = :master_id {exclude_sql}
        """),
        params,
    ).fetchone()
    if dup_emp and dup_emp.cnt > 0:
        raise HTTPException(status_code=400, detail="This employee already has a bio link")

    dup_bio = db.execute(
        text(f"""
            SELECT COUNT(*) AS cnt FROM tbl_master_bio_link_mst
            WHERE match_type = 'E' AND bio_dev_id = :bio_dev_id {exclude_sql}
        """),
        params,
    ).fetchone()
    if dup_bio and dup_bio.cnt > 0:
        raise HTTPException(
            status_code=400,
            detail="This bio device id is already linked to another employee",
        )


# ─── SQL ────────────────────────────────────────────────────────────


def _list_query(branch_filter_sql: str = ""):
    return text(f"""
        SELECT
            l.tbl_mst_bio_link_id,
            l.master_data,
            l.master_id,
            l.bio_data,
            l.bio_dev_id,
            CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS employee_name,
            o.branch_id,
            b.branch_name
        FROM tbl_master_bio_link_mst l
        LEFT JOIN hrms_ed_personal_details p ON p.eb_id = l.master_id
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = l.master_id AND COALESCE(o.active, 1) = 1
        LEFT JOIN branch_mst b ON b.branch_id = o.branch_id
        WHERE l.match_type = 'E'
          {branch_filter_sql}
          AND (:search IS NULL
               OR l.master_data LIKE :search
               OR l.bio_data LIKE :search
               OR CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) LIKE :search)
        ORDER BY l.tbl_mst_bio_link_id DESC
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/bio_emp_link_setup")
async def bio_emp_link_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Setup endpoint returning active employees (filtered by branch)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        branch_filter_sql = ""
        params: dict = {}
        if branch_ids:
            placeholders = ",".join(f":b{i}" for i in range(len(branch_ids)))
            branch_filter_sql = f"AND o.branch_id IN ({placeholders})"
            params = {f"b{i}": bid for i, bid in enumerate(branch_ids)}

        employees = db.execute(
            text(f"""
                SELECT
                    p.eb_id,
                    o.emp_code,
                    CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ', COALESCE(p.last_name, '')) AS full_name,
                    l.tbl_mst_bio_link_id AS link_id,
                    l.bio_dev_id
                FROM hrms_ed_personal_details p
                JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND COALESCE(o.active, 1) = 1
                LEFT JOIN tbl_master_bio_link_mst l ON l.master_id = p.eb_id AND l.match_type = 'E'
                WHERE COALESCE(p.active, 1) = 1
                  {branch_filter_sql}
                ORDER BY o.emp_code
            """),
            params,
        ).fetchall()

        return {"employees": [dict(r._mapping) for r in employees]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bio_emp_link_table")
async def get_bio_emp_link_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of employee bio links (match_type = 'E')."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        params: dict = {"search": search_param}
        branch_filter_sql = ""
        if branch_ids:
            placeholders = ",".join(f":b{i}" for i in range(len(branch_ids)))
            branch_filter_sql = f"AND o.branch_id IN ({placeholders})"
            for i, bid in enumerate(branch_ids):
                params[f"b{i}"] = bid

        result = db.execute(_list_query(branch_filter_sql), params).fetchall()

        all_data = [dict(r._mapping) for r in result]
        total = len(all_data)
        start = (page - 1) * limit
        return {
            "data": all_data[start : start + limit],
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bio_emp_link_by_id/{record_id}")
async def get_bio_emp_link_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Single employee bio link row by id."""
    try:
        row = db.execute(
            text("""
                SELECT tbl_mst_bio_link_id, master_data, master_id, bio_data, bio_dev_id
                FROM tbl_master_bio_link_mst
                WHERE tbl_mst_bio_link_id = :id AND match_type = 'E'
                LIMIT 1
            """),
            {"id": record_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bio_emp_link_create")
async def bio_emp_link_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new employee bio link (match_type = 'E')."""
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        data = _validate_payload(db, body)
        _check_duplicates(db, data)

        result = db.execute(
            text("""
                INSERT INTO tbl_master_bio_link_mst
                    (master_data, master_id, match_type, bio_data, bio_dev_id)
                VALUES
                    (:master_data, :master_id, 'E', :bio_data, :bio_dev_id)
            """),
            data,
        )
        db.commit()
        return {
            "message": "Bio link created successfully",
            "tbl_mst_bio_link_id": result.lastrowid,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/bio_emp_link_edit/{record_id}")
async def bio_emp_link_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing employee bio link."""
    try:
        body = await request.json()
        existing = db.execute(
            text("""
                SELECT tbl_mst_bio_link_id FROM tbl_master_bio_link_mst
                WHERE tbl_mst_bio_link_id = :id AND match_type = 'E'
            """),
            {"id": record_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Record not found")

        data = _validate_payload(db, body)
        _check_duplicates(db, data, exclude_id=record_id)

        params = dict(data)
        params["id"] = record_id
        db.execute(
            text("""
                UPDATE tbl_master_bio_link_mst SET
                    master_data = :master_data,
                    master_id   = :master_id,
                    bio_data    = :bio_data,
                    bio_dev_id  = :bio_dev_id
                WHERE tbl_mst_bio_link_id = :id
            """),
            params,
        )
        db.commit()
        return {"message": "Bio link updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/bio_emp_link_delete/{record_id}")
async def bio_emp_link_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Delete an employee bio link (hard delete — table has no active flag)."""
    try:
        row = db.execute(
            text("""
                SELECT tbl_mst_bio_link_id FROM tbl_master_bio_link_mst
                WHERE tbl_mst_bio_link_id = :id AND match_type = 'E'
            """),
            {"id": record_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")

        db.execute(
            text("DELETE FROM tbl_master_bio_link_mst WHERE tbl_mst_bio_link_id = :id"),
            {"id": record_id},
        )
        db.commit()
        return {"message": "Bio link deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
