"""MIS Entries - Yarn Purchase endpoints (tbl_yarn_transaction)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import bindparam
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()

TRAN_TYPE_PURCHASE = 1


def _parse_branch_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


@router.get("/yarn_purchase_setup")
async def yarn_purchase_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return qualities (spinning_quality_mst) and branches (branch_mst) for the dialog."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        quality_branch_filter = "WHERE branch_id IN :branch_ids" if branch_ids else ""
        quality_query = text(
            f"""
            SELECT spg_quality_mst_id, spg_quality
            FROM spinning_quality_mst
            {quality_branch_filter}
            ORDER BY spg_quality
            """
        )
        if branch_ids:
            quality_query = quality_query.bindparams(
                bindparam("branch_ids", expanding=True)
            )
        q_params = {"branch_ids": branch_ids} if branch_ids else {}
        qualities = [
            dict(r._mapping)
            for r in db.execute(quality_query, q_params).fetchall()
        ]

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
        b_params: dict = {"co_id": int(co_id)}
        if branch_ids:
            b_params["branch_ids"] = branch_ids
        branches = [
            dict(r._mapping)
            for r in db.execute(branch_query, b_params).fetchall()
        ]

        return {"qualities": qualities, "branches": branches}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_purchase_list")
async def yarn_purchase_list(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of yarn purchase transactions (tran_type = 1)."""
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
            where_parts.append("y.branch_id IN :branch_ids")
            params["branch_ids"] = branch_ids

        if search:
            where_parts.append(
                "(sq.spg_quality LIKE :search OR b.branch_name LIKE :search)"
            )
            params["search"] = f"%{search}%"

        where_clause = "WHERE " + " AND ".join(where_parts)

        base_from = """
            FROM tbl_yarn_transaction y
            LEFT JOIN spinning_quality_mst sq ON sq.spg_quality_mst_id = y.quality_id
            LEFT JOIN branch_mst b ON b.branch_id = y.branch_id
        """

        list_sql = f"""
            SELECT
                y.tbl_yarn_tran_id,
                DATE_FORMAT(y.tran_date, '%Y-%m-%d') AS tran_date,
                y.tran_type,
                y.quality_id,
                COALESCE(sq.spg_quality, '') AS spg_quality,
                y.weight,
                y.branch_id,
                COALESCE(b.branch_name, '') AS branch_name
            {base_from}
            {where_clause}
            ORDER BY y.tbl_yarn_tran_id DESC
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


@router.get("/yarn_purchase_by_id/{tran_id}")
async def yarn_purchase_by_id(
    tran_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return a single yarn purchase transaction by id."""
    try:
        query = text(
            """
            SELECT
                y.tbl_yarn_tran_id,
                DATE_FORMAT(y.tran_date, '%Y-%m-%d') AS tran_date,
                y.tran_type,
                y.quality_id,
                COALESCE(sq.spg_quality, '') AS spg_quality,
                y.weight,
                y.branch_id,
                COALESCE(b.branch_name, '') AS branch_name
            FROM tbl_yarn_transaction y
            LEFT JOIN spinning_quality_mst sq ON sq.spg_quality_mst_id = y.quality_id
            LEFT JOIN branch_mst b ON b.branch_id = y.branch_id
            WHERE y.tbl_yarn_tran_id = :tran_id
            LIMIT 1
            """
        )
        row = db.execute(query, {"tran_id": tran_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Yarn purchase entry not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/yarn_purchase_create")
async def yarn_purchase_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert a yarn purchase transaction (tran_type defaults to 1)."""
    try:
        body = await request.json()

        tran_date = body.get("tran_date")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")
        try:
            parsed_date = datetime.strptime(str(tran_date), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="tran_date must be YYYY-MM-DD")

        quality_id = body.get("quality_id")
        if not quality_id:
            raise HTTPException(status_code=400, detail="quality_id is required")

        weight = body.get("weight")
        if weight in (None, ""):
            raise HTTPException(status_code=400, detail="weight is required")

        branch_id = body.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        tran_type = body.get("tran_type") or TRAN_TYPE_PURCHASE
        user_id = token_data.get("user_id") if token_data else None

        insert_query = text(
            """
            INSERT INTO tbl_yarn_transaction (
                tran_date, tran_type, quality_id, weight, branch_id,
                updated_by, updated_date_time
            ) VALUES (
                :tran_date, :tran_type, :quality_id, :weight, :branch_id,
                :updated_by, NOW()
            )
            """
        )
        db.execute(
            insert_query,
            {
                "tran_date": parsed_date,
                "tran_type": int(tran_type),
                "quality_id": int(quality_id),
                "weight": float(weight),
                "branch_id": int(branch_id),
                "updated_by": int(user_id) if user_id else None,
            },
        )
        db.commit()
        return {"message": "Yarn purchase saved successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/yarn_purchase_update/{tran_id}")
async def yarn_purchase_update(
    tran_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing yarn purchase transaction."""
    try:
        body = await request.json()

        tran_date = body.get("tran_date")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")
        try:
            parsed_date = datetime.strptime(str(tran_date), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="tran_date must be YYYY-MM-DD")

        quality_id = body.get("quality_id")
        if not quality_id:
            raise HTTPException(status_code=400, detail="quality_id is required")

        weight = body.get("weight")
        if weight in (None, ""):
            raise HTTPException(status_code=400, detail="weight is required")

        branch_id = body.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        user_id = token_data.get("user_id") if token_data else None

        update_query = text(
            """
            UPDATE tbl_yarn_transaction
            SET tran_date = :tran_date,
                quality_id = :quality_id,
                weight = :weight,
                branch_id = :branch_id,
                updated_by = :updated_by,
                updated_date_time = NOW()
            WHERE tbl_yarn_tran_id = :tran_id
            """
        )
        result = db.execute(
            update_query,
            {
                "tran_date": parsed_date,
                "quality_id": int(quality_id),
                "weight": float(weight),
                "branch_id": int(branch_id),
                "updated_by": int(user_id) if user_id else None,
                "tran_id": tran_id,
            },
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Yarn purchase entry not found")

        db.commit()
        return {"message": "Yarn purchase updated successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
