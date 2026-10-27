"""
SQC Reports — read-only daily reports that mirror the QC department's handwritten registers.

Only the Sliver Weight report needs its own endpoint: it stitches six SQC entry tables
(breaker card, carding, drawhead/finisher card, finisher drawing, spreader sliver + roll, morrah) into one
date-wise sheet. Jute Bag Test, Width Check and Yarn Test reports read the existing
`*_by_date` endpoints directly from the UI.
"""

import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteSQC.query import (
    get_breaker_card_swt_by_date_query,
    get_card_sliver_wt_by_date_query,
    get_draw_sliver_wt_by_date_query,
    get_fin_draw_sliver_wt_by_date_query,
    get_spreader_roll_wt_by_date_query,
    get_spreader_sliver_wt_by_date_query,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_STD_MR_PCT = 20.0

SECTION_LABELS = {
    "INTER_CARD": "Inter Card",
    "TOW_BREAKER": "Tow Breaker",
    "HOPPER": "Hopper",
    "DRAWHEAD_SWT": "Drawhead (SWT)",
    "DRAWHEAD_SWP": "Drawhead (SWP)",
    "FINISHER_CARD": "Finisher Card",
    "HESS": "Finisher Drawing (Hessian)",
    "SWP": "Finisher Drawing (SWP)",
    "SWT": "Finisher Drawing (SWT)",
}


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


def _loads(v) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (ValueError, TypeError):
            return []
    return v if isinstance(v, list) else []


def _morrah_by_date_query():
    return text(
        """
        SELECT mw.morrah_wt_id, mw.trolley_no, mw.inspector_name, mw.avg_mr_pct, mw.weights,
               mw.calc_avg_weight, mw.calc_max_weight, mw.calc_min_weight, mw.calc_range,
               mw.calc_cv_pct, mw.count_lt, mw.count_ok, mw.count_hy,
               dm.dept_desc AS department, im.item_name AS jute_quality
        FROM jute_sqc_morrah_wt mw
        LEFT JOIN dept_mst dm ON dm.dept_id = mw.dept_id
        LEFT JOIN item_mst im ON im.item_id = mw.item_id
        WHERE mw.co_id = :co_id
          AND mw.entry_date = :entry_date
          AND mw.active = 1
          AND (:branch_id IS NULL OR mw.branch_id = :branch_id)
        ORDER BY mw.morrah_wt_id
        """
    )


def build_sliver_block(
    stage: str,
    m: dict,
    weights,
    mr_pcts,
    avg_wt=None,
    avg_mr=None,
    avg_corr=None,
    cv_ratio=None,
) -> dict:
    """One machine's readings in the register layout: Sl / Wt / MR% / Regain (corrected) wt.

    Regain wt per reading = wt * (100 + std_mr) / (100 + mr) — same correction the entry
    modules use. Stored aggregates win; they are recomputed only when missing. CV is
    returned as a percent (entry tables store a ratio)."""
    std_mr = _f(m.get("std_mr_pct"))
    std = DEFAULT_STD_MR_PCT if std_mr is None else std_mr
    wts = [_f(w) for w in _loads(weights)]
    mrs = [_f(x) for x in _loads(mr_pcts)]

    readings = []
    for i, w in enumerate(wts):
        mr = mrs[i] if i < len(mrs) else None
        corr = round(w * (100 + std) / (100 + mr), 2) if w is not None and mr is not None else None
        readings.append({"sl_no": i + 1, "wt": w, "mr_pct": mr, "regain_wt": corr})

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    section = m.get("section") or m.get("card_side") or m.get("category")
    return {
        "stage": stage,
        "section": SECTION_LABELS.get(section, section) if section else None,
        "mech_code": m.get("mech_code"),
        "machine_name": m.get("machine_name"),
        "quality": m.get("jute_quality") or m.get("batch_plan_name"),
        "spell_code": m.get("spell_code"),
        "std_mr_pct": std,
        "readings": readings,
        "avg_wt": round(_f(avg_wt), 2) if avg_wt is not None else _mean([r["wt"] for r in readings]),
        "avg_mr_pct": round(_f(avg_mr), 2) if avg_mr is not None else _mean([r["mr_pct"] for r in readings]),
        "avg_regain_wt": round(_f(avg_corr), 2) if avg_corr is not None else _mean([r["regain_wt"] for r in readings]),
        "cv_pct": round(_f(cv_ratio) * 100, 2) if cv_ratio is not None else None,
    }


@router.get("/sqc_report_sliver_weight")
async def sqc_report_sliver_weight(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Daily Sliver Weight Report: every sliver-weight test of the date across all stages,
    plus the morrah weight sheets. {"data": {"blocks": [...], "morrah": [...]}}"""
    co_id = request.query_params.get("co_id")
    raw_date = request.query_params.get("entry_date")
    raw_branch = request.query_params.get("branch_id")
    if not co_id or not raw_date:
        raise HTTPException(status_code=400, detail="co_id and entry_date are required")
    try:
        params = {
            "co_id": int(co_id),
            "entry_date": date.fromisoformat(raw_date),
            "branch_id": int(raw_branch) if raw_branch else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid co_id / branch_id / entry_date")

    try:
        blocks = []
        for stage, query in (
            ("Breaker Card", get_breaker_card_swt_by_date_query),
            ("Carding", get_card_sliver_wt_by_date_query),
            ("Drawhead / Finisher Card", get_draw_sliver_wt_by_date_query),
            ("Finisher Drawing", get_fin_draw_sliver_wt_by_date_query),
        ):
            for r in db.execute(query(), params).fetchall():
                m = dict(r._mapping)
                blocks.append(
                    build_sliver_block(
                        stage, m, m.get("weights"), m.get("mr_pcts"),
                        m.get("calc_wt"), m.get("calc_mr_pct"), m.get("calc_corr_wt"), m.get("calc_cv_pct"),
                    )
                )
        for r in db.execute(get_spreader_sliver_wt_by_date_query(), params).fetchall():
            m = dict(r._mapping)
            blocks.append(
                build_sliver_block(
                    "Spreader", m, m.get("observed_weights"), m.get("mr_pcts"),
                    m.get("calc_avg_obs"), m.get("calc_avg_mr"), m.get("calc_avg_corr"), m.get("calc_cv_pct"),
                )
            )

        for r in db.execute(get_spreader_roll_wt_by_date_query(), params).fetchall():
            m = dict(r._mapping)
            blocks.append(
                build_sliver_block(
                    "Spreader Roll", m, m.get("roll_weights"), m.get("mr_pcts"),
                    m.get("calc_avg_obs"), m.get("calc_avg_mr_pct"), m.get("calc_avg_corr"), m.get("calc_cv_pct"),
                )
            )

        morrah = []
        for r in db.execute(_morrah_by_date_query(), params).fetchall():
            m = dict(r._mapping)
            m["weights"] = _loads(m.get("weights"))
            for k in ("avg_mr_pct", "calc_avg_weight", "calc_max_weight", "calc_min_weight", "calc_range", "calc_cv_pct"):
                m[k] = _f(m.get(k))
            morrah.append(m)

        return {"data": {"blocks": blocks, "morrah": morrah}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error building sliver weight report")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    # ponytail: self-check for the regain/average maths.
    b = build_sliver_block("Breaker Card", {"std_mr_pct": 20}, "[25, 30]", "[25, 20]")
    assert b["readings"][0]["regain_wt"] == 24.0, b
    assert b["readings"][1]["regain_wt"] == 30.0, b
    assert b["avg_wt"] == 27.5 and b["avg_regain_wt"] == 27.0 and b["cv_pct"] is None, b
    b = build_sliver_block("Spreader", {}, [10], [], 10, 20, 9.17, 0.0512)
    assert b["std_mr_pct"] == 20.0 and b["readings"][0]["regain_wt"] is None and b["cv_pct"] == 5.12, b
    print("ok")
