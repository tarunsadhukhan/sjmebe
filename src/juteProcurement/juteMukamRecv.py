"""
Jute Mukam Received API endpoints.
Single create/edit screen — entries are editable only within 30 minutes of creation.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.juteProcurement.query import get_mukam_list_query

router = APIRouter()
logger = logging.getLogger(__name__)

# Minutes an entry stays editable after creation.
EDIT_WINDOW_MINUTES = 30

_PARTIES_SQL = text("""
    SELECT DISTINCT pm.party_id, pm.supp_name AS party_name
    FROM jute_supp_party_map jspm
    JOIN party_mst pm ON pm.party_id = jspm.party_id
    WHERE jspm.co_id = :co_id AND (pm.active = 1 OR pm.active IS NULL)
    ORDER BY pm.supp_name
""")

_QUALITIES_SQL = text("""
    SELECT jute_qlty_id, jute_quality
    FROM jute_quality_mst
    ORDER BY jute_quality
""")

_RECVD_LIST_SQL = text("""
    SELECT jute_mukam_recvd, jute_mukam_recvd_no, recvd_date
    FROM jute_mukam_recvd
    ORDER BY jute_mukam_recvd_no DESC
""")

_RECVD_BY_NO_SQL = text("""
    SELECT jute_mukam_recvd, recvd_date, party_id, mukam_id,
           gross_weight, tare_weight, `net_weight(10,3)` AS net_weight,
           quality_id, geo_location, geo_place, remarks, mukam_photo,
           jute_mukam_recvd_no, update_date_time, updated_by
    FROM jute_mukam_recvd
    WHERE jute_mukam_recvd_no = :recvd_no
""")

_INSERT_SQL = text("""
    INSERT INTO jute_mukam_recvd
        (recvd_date, party_id, mukam_id, gross_weight, tare_weight,
         `net_weight(10,3)`, quality_id, geo_location, geo_place,
         updated_by, remarks, mukam_photo, jute_mukam_recvd_no)
    VALUES
        (:recvd_date, :party_id, :mukam_id, :gross_weight, :tare_weight,
         :net_weight, :quality_id, :geo_location, :geo_place,
         :updated_by, :remarks, :mukam_photo, :recvd_no)
""")

# geo_location / geo_place / mukam_photo are intentionally NOT updated — they are
# captured once at entry and shown read-only afterwards.
_UPDATE_SQL = text("""
    UPDATE jute_mukam_recvd SET
        recvd_date = :recvd_date,
        party_id = :party_id,
        mukam_id = :mukam_id,
        gross_weight = :gross_weight,
        tare_weight = :tare_weight,
        `net_weight(10,3)` = :net_weight,
        quality_id = :quality_id,
        remarks = :remarks,
        updated_by = :updated_by
    WHERE jute_mukam_recvd = :id
""")


def _dec(v):
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _net_weight(gross, tare):
    g = _dec(gross) or Decimal(0)
    t = _dec(tare) or Decimal(0)
    # Column is int — store the rounded difference.
    return int((g - t).to_integral_value())


def _row_payload(body: dict, updated_by: int) -> dict:
    return {
        "recvd_date": body.get("recvd_date") or None,
        "party_id": _int(body.get("party_id")),
        "mukam_id": _int(body.get("mukam_id")),
        "gross_weight": _dec(body.get("gross_weight")),
        "tare_weight": _dec(body.get("tare_weight")),
        "net_weight": _net_weight(body.get("gross_weight"), body.get("tare_weight")),
        "quality_id": _int(body.get("quality_id")),
        "geo_location": (body.get("geo_location") or None),
        "geo_place": (body.get("geo_place") or None),
        "remarks": (body.get("remarks") or None),
        "mukam_photo": (body.get("mukam_photo") or None),
        "updated_by": updated_by,
    }


@router.get("/jute_mukam_recvd_setup")
async def jute_mukam_recvd_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(co_id)
        parties = [dict(r._mapping) for r in db.execute(_PARTIES_SQL, {"co_id": co_id}).fetchall()]
        mukams = [dict(r._mapping) for r in db.execute(get_mukam_list_query()).fetchall()]
        qualities = [dict(r._mapping) for r in db.execute(_QUALITIES_SQL).fetchall()]
        recvd = []
        for r in db.execute(_RECVD_LIST_SQL).fetchall():
            d = dict(r._mapping)
            if d.get("recvd_date"):
                d["recvd_date"] = str(d["recvd_date"])
            recvd.append(d)
        return {"parties": parties, "mukams": mukams, "qualities": qualities, "recvd_list": recvd}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("jute_mukam_recvd_setup error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_mukam_recvd/{recvd_no}")
async def jute_mukam_recvd_get(
    recvd_no: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(_RECVD_BY_NO_SQL, {"recvd_no": recvd_no}).first()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        d = dict(row._mapping)
        # Editable only within the window after creation (update_date_time set at insert).
        editable = False
        udt = d.get("update_date_time")
        if udt is not None:
            editable = (now_ist() - udt) <= timedelta(minutes=EDIT_WINDOW_MINUTES)
        for k in ("recvd_date", "update_date_time"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        return {"data": d, "editable": editable}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("jute_mukam_recvd_get error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_mukam_recvd_create")
async def jute_mukam_recvd_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        updated_by = int(token_data.get("user_id") or 0)
        next_no = int(
            db.execute(text("SELECT COALESCE(MAX(jute_mukam_recvd_no), 0) + 1 FROM jute_mukam_recvd")).scalar() or 1
        )
        params = _row_payload(body, updated_by)
        params["recvd_no"] = next_no
        db.execute(_INSERT_SQL, params)
        db.commit()
        return {"message": "Saved successfully", "jute_mukam_recvd_no": next_no}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("jute_mukam_recvd_create error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_mukam_recvd_update")
async def jute_mukam_recvd_update(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        updated_by = int(token_data.get("user_id") or 0)
        recvd_no = _int(body.get("jute_mukam_recvd_no"))
        if not recvd_no:
            raise HTTPException(status_code=400, detail="jute_mukam_recvd_no is required")

        existing = db.execute(_RECVD_BY_NO_SQL, {"recvd_no": recvd_no}).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Entry not found")
        ex = dict(existing._mapping)

        # Enforce the 30-minute edit window server-side.
        udt = ex.get("update_date_time")
        if udt is None or (now_ist() - udt) > timedelta(minutes=EDIT_WINDOW_MINUTES):
            raise HTTPException(
                status_code=403,
                detail=f"This entry can no longer be edited (allowed only within {EDIT_WINDOW_MINUTES} minutes of entry).",
            )

        params = _row_payload(body, updated_by)
        params["id"] = ex["jute_mukam_recvd"]
        db.execute(_UPDATE_SQL, params)
        db.commit()
        return {"message": "Updated successfully", "jute_mukam_recvd_no": recvd_no}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("jute_mukam_recvd_update error")
        raise HTTPException(status_code=500, detail=str(e))
