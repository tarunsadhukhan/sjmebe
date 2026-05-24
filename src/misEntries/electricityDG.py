"""MIS Entries - Electricity / DG endpoints (tbl_other_entries)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import bindparam
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()


def _parse_branch_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


@router.get("/electricity_dg_setup")
async def electricity_dg_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return branches (branch_mst) for the dialog."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        branch_extra_filter = "AND branch_id IN :branch_ids" if branch_ids else ""
        branch_query = text(
            f"""
            SELECT branch_id, branch_name
            FROM branch_mst
            WHERE co_id = :co_id
            {branch_extra_filter}
            ORDER BY branch_name
            """
        )
        if branch_ids:
            branch_query = branch_query.bindparams(
                bindparam("branch_ids", expanding=True)
            )
        params: dict = {"co_id": int(co_id)}
        if branch_ids:
            params["branch_ids"] = branch_ids
        branches = [
            dict(r._mapping)
            for r in db.execute(branch_query, params).fetchall()
        ]

        return {"branches": branches}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/electricity_dg_list")
async def electricity_dg_list(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of electricity/DG entries from tbl_other_entries."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))
        offset = (page - 1) * limit
        search = request.query_params.get("search")
        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        where_parts: list = ["b.co_id = :co_id"]
        params: dict = {
            "co_id": int(co_id),
            "limit": limit,
            "offset": offset,
        }

        if branch_ids:
            where_parts.append("o.branch_id IN :branch_ids")
            params["branch_ids"] = branch_ids

        if search:
            where_parts.append("b.branch_name LIKE :search")
            params["search"] = f"%{search}%"

        where_clause = "WHERE " + " AND ".join(where_parts)

        base_from = """
            FROM tbl_other_entries o
            LEFT JOIN branch_mst b ON b.branch_id = o.branch_id
        """

        list_sql = f"""
            SELECT
                o.tbl_other_ent_id,
                DATE_FORMAT(o.tran_date, '%Y-%m-%d') AS tran_date,
                o.elec_unit,
                o.dg_unit,
                o.wip_data,
                o.dust_boiler,
                o.branch_id,
                COALESCE(b.branch_name, '') AS branch_name
            {base_from}
            {where_clause}
            ORDER BY o.tbl_other_ent_id DESC
            LIMIT :limit OFFSET :offset
        """
        list_query = text(list_sql)
        if branch_ids:
            list_query = list_query.bindparams(bindparam("branch_ids", expanding=True))

        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        count_sql = f"SELECT COUNT(*) AS total {base_from} {where_clause}"
        count_query = text(count_sql)
        if branch_ids:
            count_query = count_query.bindparams(bindparam("branch_ids", expanding=True))

        total = db.execute(count_query, count_params).scalar() or 0
        rows = db.execute(list_query, params).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {"data": data, "total": total, "page": page, "page_size": limit}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/electricity_dg_by_id/{ent_id}")
async def electricity_dg_by_id(
    ent_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return a single tbl_other_entries row by id."""
    try:
        query = text(
            """
            SELECT
                o.tbl_other_ent_id,
                DATE_FORMAT(o.tran_date, '%Y-%m-%d') AS tran_date,
                o.elec_unit,
                o.dg_unit,
                o.wip_data,
                o.dust_boiler,
                o.branch_id,
                COALESCE(b.branch_name, '') AS branch_name
            FROM tbl_other_entries o
            LEFT JOIN branch_mst b ON b.branch_id = o.branch_id
            WHERE o.tbl_other_ent_id = :ent_id
            LIMIT 1
            """
        )
        row = db.execute(query, {"ent_id": ent_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/electricity_dg_create")
async def electricity_dg_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert a tbl_other_entries row."""
    try:
        body = await request.json()

        tran_date = body.get("tran_date")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")
        try:
            parsed_date = datetime.strptime(str(tran_date), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="tran_date must be YYYY-MM-DD")

        branch_id = body.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        user_id = token_data.get("user_id") if token_data else None

        insert_query = text(
            """
            INSERT INTO tbl_other_entries (
                tran_date, elec_unit, dg_unit, wip_data, dust_boiler,
                branch_id, updated_by, updated_date_time
            ) VALUES (
                :tran_date, :elec_unit, :dg_unit, :wip_data, :dust_boiler,
                :branch_id, :updated_by, NOW()
            )
            """
        )
        db.execute(
            insert_query,
            {
                "tran_date": parsed_date,
                "elec_unit": int(body.get("elec_unit") or 0),
                "dg_unit": int(body.get("dg_unit") or 0),
                "wip_data": float(body.get("wip_data") or 0),
                "dust_boiler": int(body.get("dust_boiler") or 0),
                "branch_id": int(branch_id),
                "updated_by": int(user_id) if user_id else None,
            },
        )
        db.commit()
        return {"message": "Entry saved successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/electricity_dg_update/{ent_id}")
async def electricity_dg_update(
    ent_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing tbl_other_entries row."""
    try:
        body = await request.json()

        tran_date = body.get("tran_date")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")
        try:
            parsed_date = datetime.strptime(str(tran_date), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="tran_date must be YYYY-MM-DD")

        branch_id = body.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        user_id = token_data.get("user_id") if token_data else None

        update_query = text(
            """
            UPDATE tbl_other_entries
            SET tran_date = :tran_date,
                elec_unit = :elec_unit,
                dg_unit = :dg_unit,
                wip_data = :wip_data,
                dust_boiler = :dust_boiler,
                branch_id = :branch_id,
                updated_by = :updated_by,
                updated_date_time = NOW()
            WHERE tbl_other_ent_id = :ent_id
            """
        )
        result = db.execute(
            update_query,
            {
                "tran_date": parsed_date,
                "elec_unit": int(body.get("elec_unit") or 0),
                "dg_unit": int(body.get("dg_unit") or 0),
                "wip_data": float(body.get("wip_data") or 0),
                "dust_boiler": int(body.get("dust_boiler") or 0),
                "branch_id": int(branch_id),
                "updated_by": int(user_id) if user_id else None,
                "ent_id": ent_id,
            },
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Entry not found")

        db.commit()
        return {"message": "Entry updated successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
