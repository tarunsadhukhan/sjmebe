"""HRMS Pay Register endpoints — list, create, update, setup, salary data, process payroll."""
import logging
import math
import re
from collections import OrderedDict
from decimal import ROUND_HALF_EVEN, ROUND_DOWN, ROUND_UP, Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.hrms import PayPeriod, PayEmployeePayroll, PayEmployeePayperiod
from .query import (
    get_pay_register_list,
    get_pay_register_list_count,
    get_pay_register_by_id,
    check_duplicate_pay_register,
    get_pay_register_salary,
    get_payscheme_mapped_employees,
    get_pay_scheme_details_by_id,
    get_all_pay_components_for_company,
    get_employee_pay_structure,
    get_custom_component_values,
    delete_existing_payroll_for_period,
    delete_existing_payperiod_entries,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Pay Register List ──────────────────────────────────────────────

@router.get("/pay_register_list")
async def pay_register_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        search_raw = request.query_params.get("search")
        search = f"%{search_raw}%" if search_raw else None
        from_date = request.query_params.get("from_date") or None
        to_date = request.query_params.get("to_date") or None
        status_raw = request.query_params.get("status")
        status_id = int(status_raw) if status_raw else None

        params = {
            "co_id": int(co_id),
            "search": search,
            "from_date": from_date,
            "to_date": to_date,
            "status_id": status_id,
            "page_size": page_size,
            "offset": (page - 1) * page_size,
        }

        rows = db.execute(get_pay_register_list(), params).fetchall()
        data = [dict(r._mapping) for r in rows]

        count_row = db.execute(get_pay_register_list_count(), {
            "co_id": int(co_id),
            "search": search,
            "from_date": from_date,
            "to_date": to_date,
            "status_id": status_id,
        }).fetchone()
        total = count_row._mapping["total"] if count_row else 0

        return {"data": data, "total": total, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Register By ID ────────────────────────────────────────────

@router.get("/pay_register_by_id/{period_id}")
async def pay_register_by_id(
    period_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        row = db.execute(
            get_pay_register_by_id(),
            {"id": period_id, "co_id": int(co_id)},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Pay register not found")

        detail = dict(row._mapping)

        # Approval button check: if status is pending approval (20) or open (1),
        # the current user might be allowed to approve.
        user_id = token_data.get("user_id", 0)
        approve_button = False
        status = detail.get("status_id")
        if status in (1, 20):
            approve_button = True

        detail["approveButton"] = approve_button

        return {"data": detail}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Register Create Setup ─────────────────────────────────────

@router.get("/pay_register_create_setup")
async def pay_register_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from sqlalchemy import text

        # Pay schemes (TYPE=0 means pay-scheme type component)
        schemes = db.execute(
            text("""
                SELECT ID AS id, CODE AS code, NAME AS name
                FROM pay_components
                WHERE company_id = :co_id AND TYPE = 0 AND STATUS = 1
                ORDER BY NAME
            """),
            {"co_id": int(co_id)},
        ).fetchall()

        # Branches
        branches = db.execute(
            text("""
                SELECT branch_id, branch_name
                FROM branch_mst
                WHERE co_id = :co_id AND active = 1
                ORDER BY branch_name
            """),
            {"co_id": int(co_id)},
        ).fetchall()

        return {
            "data": {
                "pay_schemes": [
                    {"label": r._mapping["name"], "value": str(r._mapping["id"])}
                    for r in schemes
                ],
                "branches": [
                    {"label": r._mapping["branch_name"], "value": str(r._mapping["branch_id"])}
                    for r in branches
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Register Create ───────────────────────────────────────────

@router.post("/pay_register_create")
async def pay_register_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        body = await request.json()
        user_id = token_data.get("user_id", 0)

        from_date = body.get("from_date")
        to_date = body.get("to_date")
        payscheme_id = body.get("payscheme_id")
        branch_id = body.get("branch_id")

        if not from_date or not to_date or not payscheme_id:
            raise HTTPException(
                status_code=400,
                detail="from_date, to_date, and payscheme_id are required",
            )

        # Duplicate check (skip cancelled/rejected/closed statuses)
        dup = db.execute(
            check_duplicate_pay_register(),
            {
                "from_date": from_date,
                "to_date": to_date,
                "payscheme_id": int(payscheme_id),
                "co_id": int(co_id),
            },
        ).fetchone()
        if dup and dup._mapping["cnt"] > 0:
            raise HTTPException(status_code=409, detail="Pay register already exists for this period and scheme")

        period = PayPeriod(
            from_date=from_date,
            to_date=to_date,
            payscheme_id=int(payscheme_id),
            branch_id=int(branch_id) if branch_id else None,
            co_id=int(co_id),
            status_id=1,  # Open
            updated_by=user_id,
        )
        db.add(period)
        db.flush()
        db.commit()

        return {"data": {"id": period.id, "message": "Pay register created successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pay Register Update (status / approval) ───────────────────────

@router.put("/pay_register_update/{period_id}")
async def pay_register_update(
    period_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        body = await request.json()
        user_id = token_data.get("user_id", 0)

        period = db.query(PayPeriod).filter(
            PayPeriod.id == period_id,
            PayPeriod.co_id == int(co_id),
        ).first()
        if not period:
            raise HTTPException(status_code=404, detail="Pay register not found")

        # Allow updating status and basic fields
        for field in ("from_date", "to_date", "payscheme_id", "branch_id", "status_id"):
            if field in body:
                setattr(period, field, body[field])
        period.updated_by = user_id

        db.commit()
        return {"data": {"id": period_id, "message": "Pay register updated successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Monthly Salary Payment Data ───────────────────────────────────

@router.get("/pay_register_salary")
async def pay_register_salary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Returns pivoted salary data: one row per employee, dynamic component columns."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        pay_period_id_raw = request.query_params.get("pay_period_id")
        if not pay_period_id_raw:
            raise HTTPException(status_code=400, detail="pay_period_id is required")

        pay_scheme_id_raw = request.query_params.get("pay_scheme_id")
        if not pay_scheme_id_raw:
            raise HTTPException(status_code=400, detail="pay_scheme_id is required")

        branch_id_raw = request.query_params.get("branch_id")
        branch_id = int(branch_id_raw) if branch_id_raw else None

        params = {
            "co_id": int(co_id),
            "pay_period_id": int(pay_period_id_raw),
            "pay_scheme_id": int(pay_scheme_id_raw),
            "branch_id": branch_id,
        }

        rows = db.execute(get_pay_register_salary(), params).fetchall()

        if not rows:
            return {"data": [], "columns": []}

        # Pivot: group by employee, spread components as columns
        employees: dict[int, OrderedDict] = {}
        component_names: list[str] = []

        for r in rows:
            m = r._mapping
            emp_id = m["employee_id"]
            comp_name = m["component_name"]

            if emp_id not in employees:
                employees[emp_id] = OrderedDict([
                    ("employee_id", emp_id),
                    ("emp_code", m["emp_code"]),
                    ("emp_name", (m["emp_name"] or "").strip()),
                    ("department_name", m["department_name"]),
                ])

            employees[emp_id][comp_name] = float(m["amount"] or 0)

            if comp_name not in component_names:
                component_names.append(comp_name)

        data = list(employees.values())

        # Build dynamic columns for the frontend DataGrid
        columns = [
            {"field": "emp_code", "headerName": "Emp Code", "minWidth": 100},
            {"field": "emp_name", "headerName": "Emp Name", "minWidth": 180},
            {"field": "department_name", "headerName": "Department", "minWidth": 150},
        ]
        for cname in component_names:
            columns.append({
                "field": cname,
                "headerName": cname,
                "minWidth": 120,
                "type": "number",
            })

        return {"data": data, "columns": columns}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Payroll Processing (Calculate & Insert) ───────────────────────

# Status constants matching Java backend
STATUS_PROCESSED = "32"   # Processed status (matches Constants.STATUS_PROCESSED)
STATUS_OPEN = "1"
EMP_PAY_ROLL_SUCCESS = 1


def _round_value(value: float, digits: int | None, round_type: int | None) -> float:
    """Apply rounding matching Java's processScriptValue logic.

    round_type: 0/None = HALF_EVEN, 1 = HALF_EVEN, 2 = DOWN (floor), 3 = UP (ceil)
    """
    if digits is None:
        digits = 0
    if round_type is None:
        round_type = 0

    d = Decimal(str(value))
    # Pre-round to digits+1 to avoid floating-point artefacts
    d = d.quantize(Decimal(10) ** -(digits + 1), rounding=ROUND_HALF_EVEN)

    if round_type in (0, 1):
        d = d.quantize(Decimal(10) ** -digits, rounding=ROUND_HALF_EVEN)
    elif round_type == 2:
        d = d.quantize(Decimal(10) ** -digits, rounding=ROUND_DOWN)
    elif round_type == 3:
        d = d.quantize(Decimal(10) ** -digits, rounding=ROUND_UP)

    return float(d)


_DIV_ZERO_RE = re.compile(r"(\([^()]*\)|[\d.]+)\s*/\s*0\.0")
_ALPHA_RE = re.compile(r"(math\.floor|Math\.floor)|[a-zA-Z_]+")


def _handle_division_by_zero(formula: str) -> str:
    """Replace division-by-zero patterns with 0.0 (mirrors Java handleDivisionByZero)."""
    expr = formula
    # Check if formula still has unresolved alphabetic references (skip math.floor)
    has_unresolved = False
    for m in _ALPHA_RE.finditer(expr):
        if m.group().lower() not in ("math.floor",):
            has_unresolved = True
            break

    if not has_unresolved:
        for old, new in [
            ("/(0.0+0.0)", "/0.0"),
            ("/(0.0-0.0)", "/0.0"),
            ("/(0.0*0.0)", "/0.0"),
            ("(0.0/0.0)", "0.0"),
            ("--", "+"),
        ]:
            expr = expr.replace(old, new)
        expr = _DIV_ZERO_RE.sub("0.0", expr)

    return expr


def _safe_eval(formula: str) -> float:
    """Safely evaluate a numeric formula string using Python's math.

    Only allows numbers, operators, parentheses, and math.floor / math.ceil.
    Rejects any other alphabetic tokens (prevents code injection).
    """
    # Replace Java Math.floor with Python math.floor
    expr = formula.replace("Math.floor", "math.floor").replace("Math.ceil", "math.ceil")

    # Validate: only allow digits, operators, parentheses, dots, whitespace, and math functions
    sanitized = re.sub(r"math\.(floor|ceil)", "", expr)
    if re.search(r"[a-zA-Z_]", sanitized):
        raise ValueError(f"Formula contains unresolved references: {formula}")

    # Evaluate using restricted builtins
    try:
        result = eval(expr, {"__builtins__": {}}, {"math": math})  # noqa: S307
    except ZeroDivisionError:
        return 0.0
    except Exception as e:
        raise ValueError(f"Failed to evaluate formula '{formula}': {e}")

    return float(result)


def _evaluate_employee_formulas(
    component_formulas: dict[int, str],
    components_meta: dict[int, dict],
) -> dict[int, float]:
    """Iterative formula evaluation engine (mirrors Java getEmployeePayStrcure).

    Resolves component dependencies by repeatedly substituting calculated values
    into formulas until all are evaluated, or max iterations reached.
    """
    cooked: dict[int, float] = {}
    resolved: set[int] = set()
    max_iterations = 100

    for iteration in range(max_iterations):
        if len(resolved) == len(component_formulas):
            break

        for comp_id, formula in list(component_formulas.items()):
            if comp_id in resolved:
                continue

            # Step 1: try as plain number
            try:
                val = float(formula)
                cooked[comp_id] = val
                resolved.add(comp_id)
                continue
            except (ValueError, TypeError):
                pass

            # Step 2: substitute resolved component values by code
            current = formula
            all_refs_resolved = True
            for ref_id, meta in components_meta.items():
                code = meta.get("code", "")
                if not code or code not in current:
                    continue
                if ref_id in cooked:
                    current = current.replace(code, str(cooked[ref_id]))
                else:
                    all_refs_resolved = False

            component_formulas[comp_id] = current

            # Step 3: try to evaluate
            current = _handle_division_by_zero(current)
            try:
                val = _safe_eval(current)
            except ValueError:
                # Still has unresolved refs — retry next iteration
                continue

            # Apply rounding
            meta = components_meta.get(comp_id, {})
            val = _round_value(val, meta.get("roundof"), meta.get("roundof_type"))

            if math.isnan(val) or math.isinf(val):
                val = 0.0

            cooked[comp_id] = val
            resolved.add(comp_id)
            component_formulas[comp_id] = str(val)

    return cooked


@router.post("/pay_register_process")
async def pay_register_process(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Calculate payroll for all employees in a pay scheme/period and insert into pay_employee_payroll.

    Mirrors Java PayProcessServiceImpl.processPayToPayRoll2().

    Body: { "pay_period_id": int, "pay_scheme_id": int, "branch_id": int|null }
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        body = await request.json()
        user_id = token_data.get("user_id", 0)
        pay_period_id = body.get("pay_period_id")
        pay_scheme_id = body.get("pay_scheme_id")
        branch_id = body.get("branch_id")

        if not pay_period_id or not pay_scheme_id:
            raise HTTPException(
                status_code=400,
                detail="pay_period_id and pay_scheme_id are required",
            )

        pay_period_id = int(pay_period_id)
        pay_scheme_id = int(pay_scheme_id)
        branch_id = int(branch_id) if branch_id else None

        # ── 1. Validate pay period exists and is processable ────────
        period = db.query(PayPeriod).filter(
            PayPeriod.id == pay_period_id,
            PayPeriod.co_id == int(co_id),
        ).first()
        if not period:
            raise HTTPException(status_code=404, detail="Pay period not found")

        # ── 2. Fetch employees mapped to this pay scheme ────────────
        emp_rows = db.execute(
            get_payscheme_mapped_employees(),
            {"pay_scheme_id": pay_scheme_id, "branch_id": branch_id},
        ).fetchall()

        if not emp_rows:
            raise HTTPException(
                status_code=400,
                detail="No employees found mapped to this pay scheme",
            )

        employee_ids = [r._mapping["eb_id"] for r in emp_rows]

        # ── 3. Fetch pay scheme formulas ────────────────────────────
        formula_rows = db.execute(
            get_pay_scheme_details_by_id(),
            {"pay_scheme_id": pay_scheme_id},
        ).fetchall()

        if not formula_rows:
            raise HTTPException(
                status_code=400,
                detail="No pay scheme details/formulas found for this scheme",
            )

        # Map: component_id → formula string
        scheme_formulas: dict[int, str] = {}
        for r in formula_rows:
            m = r._mapping
            scheme_formulas[m["component_id"]] = m["formula"] or "0"

        # ── 4. Fetch all component metadata ─────────────────────────
        comp_rows = db.execute(
            get_all_pay_components_for_company(),
            {"co_id": int(co_id)},
        ).fetchall()

        # Map: component_id → {code, name, type, roundof, roundof_type, is_custom_component}
        components_meta: dict[int, dict] = {}
        for r in comp_rows:
            m = dict(r._mapping)
            components_meta[m["id"]] = m

        # ── 5. Fetch employee base pay structure ────────────────────
        struct_rows = db.execute(
            get_employee_pay_structure(),
            {"pay_scheme_id": pay_scheme_id},
        ).fetchall()

        # Map: eb_id → {component_id → amount}
        emp_structure: dict[int, dict[int, float]] = {}
        for r in struct_rows:
            m = r._mapping
            emp_structure.setdefault(m["eb_id"], {})[m["component_id"]] = float(m["amount"] or 0)

        # ── 6. Fetch custom component values (from upload) ──────────
        custom_rows = db.execute(
            get_custom_component_values(),
            {"pay_period_id": pay_period_id},
        ).fetchall()

        # Map: eb_id → {component_id → value_string}
        emp_custom: dict[int, dict[int, str]] = {}
        for r in custom_rows:
            m = r._mapping
            emp_custom.setdefault(m["eb_id"], {})[m["component_id"]] = str(m["value"] or "0")

        # ── 7. Delete existing payroll & payperiod entries (re-process) ─
        db.execute(
            delete_existing_payroll_for_period(),
            {"pay_period_id": pay_period_id, "pay_scheme_id": pay_scheme_id},
        )
        db.execute(
            delete_existing_payperiod_entries(),
            {"pay_period_id": pay_period_id, "pay_scheme_id": pay_scheme_id},
        )
        db.flush()

        # ── 8. Process each employee ────────────────────────────────
        payroll_records: list[PayEmployeePayroll] = []
        payperiod_records: list[PayEmployeePayperiod] = []
        errors: list[dict] = []

        for emp_id in employee_ids:
            # Build per-employee formula map (copy from scheme)
            emp_formulas = dict(scheme_formulas)

            # Override with employee base structure values (Type 0 inputs)
            if emp_id in emp_structure:
                for comp_id, amount in emp_structure[emp_id].items():
                    if comp_id in emp_formulas and comp_id in components_meta:
                        meta = components_meta[comp_id]
                        if meta.get("type") == 0:  # Input type
                            emp_formulas[comp_id] = str(amount)

            # Override with custom component values
            if emp_id in emp_custom:
                for comp_id, value in emp_custom[emp_id].items():
                    if comp_id in emp_formulas and comp_id in components_meta:
                        meta = components_meta[comp_id]
                        if meta.get("is_custom_component"):
                            emp_formulas[comp_id] = value

            # Evaluate all formulas for this employee
            try:
                calculated = _evaluate_employee_formulas(
                    emp_formulas, components_meta,
                )
            except Exception as e:
                errors.append({"employee_id": emp_id, "error": str(e)})
                continue

            # Build PayEmployeePayroll records for each component
            basic_val = 0.0
            net_val = 0.0
            gross_val = 0.0

            for comp_id, amount in calculated.items():
                rec = PayEmployeePayroll(
                    eb_id=emp_id,
                    component_id=comp_id,
                    payperiod_id=pay_period_id,
                    payscheme_id=pay_scheme_id,
                    amount=amount,
                    status_id=EMP_PAY_ROLL_SUCCESS,
                    businessunit_id=branch_id,
                    source="PROCESSED",
                    updated_by=user_id,
                )
                payroll_records.append(rec)

                # Track summary values for pay_employee_payperiod
                meta = components_meta.get(comp_id, {})
                comp_name = (meta.get("name") or "").upper()
                if "BASIC" in comp_name:
                    basic_val = amount
                elif "NET" in comp_name:
                    net_val = amount
                elif "GROSS" in comp_name and "DEDUCTION" not in comp_name:
                    gross_val = amount

            # Build pay_employee_payperiod summary record
            pp_rec = PayEmployeePayperiod(
                employeeid=emp_id,
                pay_period_id=pay_period_id,
                pay_scheme_id=pay_scheme_id,
                basic=basic_val,
                net=net_val,
                gross=gross_val,
                status_id=EMP_PAY_ROLL_SUCCESS,
                updated_by=user_id,
            )
            payperiod_records.append(pp_rec)

        # ── 9. Bulk insert ──────────────────────────────────────────
        if payroll_records:
            db.add_all(payroll_records)
            db.add_all(payperiod_records)

        # ── 10. Update pay period status to Processed ───────────────
        period.status_id = int(STATUS_PROCESSED)
        period.updated_by = user_id

        db.commit()

        return {
            "data": {
                "message": "Payroll processed successfully",
                "employees_processed": len(employee_ids) - len(errors),
                "total_employees": len(employee_ids),
                "records_created": len(payroll_records),
                "errors": errors if errors else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Payroll processing failed")
        raise HTTPException(status_code=500, detail=str(e))
