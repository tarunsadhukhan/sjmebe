from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
import os
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import ItemGrpMst, ItemTypeMaster, ItemMst, ItemMake, PartyMst, PartyBranchMst
from src.masters.query import get_party_table, get_party_types, get_country_list, get_state_list
from src.masters.query import get_entity_list, get_party_by_id, get_party_branch_by_party_id
from src.masters.query import get_party_types_with_prefix, get_city_list
from datetime import datetime

router = APIRouter()


@router.get("/get_party_table")
async def get_party(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        query = get_party_table(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        querypartytype = get_party_types()
        resultpartytype = db.execute(querypartytype).fetchall()
        data = [dict(row._mapping) for row in result]
        party_types = [dict(row._mapping) for row in resultpartytype]
        return {"data": data, "party_types": party_types}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/party_create_setup")
async def party_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        querypartytype = get_party_types()
        resultpartytype = db.execute(querypartytype).fetchall()
        party_types = [dict(row._mapping) for row in resultpartytype]
        querycountry = get_country_list()
        resultcountry = db.execute(querycountry).fetchall()
        countries = [dict(row._mapping) for row in resultcountry]
        querystate = get_state_list()
        resultstate = db.execute(querystate).fetchall()
        states = [dict(row._mapping) for row in resultstate]
        queryentity = get_entity_list()
        resultentity = db.execute(queryentity).fetchall()
        entities = [dict(row._mapping) for row in resultentity]
        return {"party_types": party_types, "countries": countries, "states": states, "entities": entities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/party_edit_setup")
async def party_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        co_id = request.query_params.get("co_id")
        party_id = request.query_params.get("party_id")

        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not party_id:
            raise HTTPException(status_code=400, detail="Party ID (party_id) is required")

        try:
            party_id_int = int(party_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid party_id")

        # Fetch party details
        querypartydetails = get_party_by_id(party_id_int)
        resultpartydetails = db.execute(querypartydetails, {"party_id": party_id_int}).fetchall()
        partydetails = [dict(row._mapping) for row in resultpartydetails]

        # Fetch party branches
        querypartybranches = get_party_branch_by_party_id(party_id_int)
        try:
            resultpartybranches = db.execute(querypartybranches, {"party_id": party_id_int}).fetchall()
        except Exception as branch_err:
            err_text = str(branch_err)
            if "Unknown column 'pbm.state_id'" not in err_text:
                raise

            legacy_querypartybranches = text("""
SELECT
  pbm.active,
  pbm.party_mst_branch_id,
  pbm.gst_no,
  pbm.address,
  pbm.address_additional,
  pbm.zip_code,
  cm.state_id,
  sm.state,
  pbm.contact_no,
  pbm.contact_person
FROM party_branch_mst pbm
LEFT JOIN city_mst cm ON cm.city_id = pbm.city_id
LEFT JOIN state_mst sm ON sm.state_id = cm.state_id
WHERE pbm.party_id = :party_id;
""")
            resultpartybranches = db.execute(legacy_querypartybranches, {"party_id": party_id_int}).fetchall()

        party_branches = [dict(row._mapping) for row in resultpartybranches]

        # Lookup lists
        querypartytype = get_party_types()
        resultpartytype = db.execute(querypartytype).fetchall()
        party_types = [dict(row._mapping) for row in resultpartytype]

        querycountry = get_country_list()
        resultcountry = db.execute(querycountry).fetchall()
        countries = [dict(row._mapping) for row in resultcountry]

        querystate = get_state_list()
        resultstate = db.execute(querystate).fetchall()
        states = [dict(row._mapping) for row in resultstate]

        queryentity = get_entity_list()
        resultentity = db.execute(queryentity).fetchall()
        entities = [dict(row._mapping) for row in resultentity]

        return {
            "party_types": party_types,
            "party_details": partydetails,
            "party_branches": party_branches,
            "countries": countries,
            "states": states,
            "entities": entities,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/party_create")
async def party_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        # read request body first; allow co_id to come from payload or query param
        payload = await request.json()
        co_id_query = request.query_params.get("co_id")
        co_id = payload.get("co_id") if payload.get("co_id") is not None else co_id_query
        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # derive updated_by from token - required field, default to 0 if not available
        updated_by = 0
        if token_data and token_data.get("user_id"):
            try:
                updated_by = int(token_data.get("user_id"))
            except (ValueError, TypeError):
                updated_by = 0

        # Build PartyMst
        # normalize party_type into DB format like {3,2}
        def _format_party_type(val):
            if val is None:
                return None
            if isinstance(val, list):
                return "{" + ",".join(str(x) for x in val) + "}"
            if isinstance(val, int):
                return "{" + str(val) + "}"
            s = str(val).strip()
            if s.startswith("{") and s.endswith("}"):
                return s
            if "," in s:
                parts = [p.strip() for p in s.split(",") if p.strip()]
                return "{" + ",".join(parts) + "}"
            return "{" + s + "}"

        party_type_id_val = _format_party_type(payload.get("party_type") if payload.get("party_type") is not None else payload.get("party_type_id"))

        party = PartyMst(
            active=1 if payload.get("active") else 0,
            prefix=payload.get("prefix"),
            updated_by=updated_by,
            phone_no=payload.get("phone_no"),
            cin=payload.get("cin"),
            co_id=int(co_id) if co_id is not None else None,
            supp_contact_person=payload.get("supp_contact_person"),
            supp_contact_designation=payload.get("supp_contact_designation"),
            supp_email_id=payload.get("supp_email_id"),
            supp_code=payload.get("supp_code"),
            party_pan_no=payload.get("party_pan_no"),
            entity_type_id=int(payload.get("entity_type_id")) if payload.get("entity_type_id") else None,
            supp_name=payload.get("supp_name"),
            msme_certified=payload.get("msme_certified"),
            country_id=int(payload.get("country_id")) if payload.get("country_id") else None,
            party_type_id=party_type_id_val
        )

        db.add(party)
        db.commit()
        db.refresh(party)

        # Create branches if provided
        branches = payload.get("branches") or []
        for b in branches:
            branch = PartyBranchMst(
                party_id=party.party_id,
                active=1 if b.get("active") else 0,
                address=b.get("address"),
                address_additional=b.get("address_additional"),
                zip_code=int(b.get("zip_code")) if b.get("zip_code") else None,
                state_id=int(b.get("state")) if b.get("state") else None,
                gst_no=b.get("gst_no"),
                contact_no=b.get("contact_no"),
                contact_person=b.get("contact_person"),
                updated_by=updated_by
            )
            db.add(branch)

        db.commit()
        return {"message": "Party created successfully", "party_id": party.party_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        print(f"party_create error: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/party_edit")
async def party_edit(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        # allow co_id from query param or payload
        payload = await request.json()
        co_id_query = request.query_params.get("co_id")
        co_id = payload.get("co_id") if payload.get("co_id") is not None else co_id_query
        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        party_id = payload.get("party_id")
        if not party_id:
            raise HTTPException(status_code=400, detail="party_id is required in payload")
        try:
            party_id_int = int(party_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid party_id")

        # derive updated_by from token - required field, default to 0 if not available
        updated_by = 0
        if token_data and token_data.get("user_id"):
            try:
                updated_by = int(token_data.get("user_id"))
            except (ValueError, TypeError):
                updated_by = 0

        # Fetch existing party
        party = db.query(PartyMst).filter(PartyMst.party_id == party_id_int, PartyMst.co_id == int(co_id)).one_or_none()
        if not party:
            raise HTTPException(status_code=404, detail="Party not found")

        # Update PartyMst fields from payload (only keys present)
        updatable_fields = [
            "active", "prefix", "phone_no", "cin", "supp_contact_person",
            "supp_contact_designation", "supp_email_id", "supp_code", "party_pan_no",
            "entity_type_id", "supp_name", "msme_certified", "country_id", "party_type_id", "party_type"
        ]
        for key in updatable_fields:
            if key in payload:
                val = payload.get(key)
                # convert boolean active to int if necessary
                if key == "active":
                    setattr(party, key, 1 if val else 0)
                elif key in ("entity_type_id", "country_id") and val is not None and str(val).isdigit():
                    setattr(party, key, int(val))
                elif key in ("party_type_id", "party_type"):
                    # Normalize incoming party_type or party_type_id to DB '{a,b}' format
                    if isinstance(val, list):
                        setattr(party, 'party_type_id', "{" + ",".join(str(x) for x in val) + "}")
                    elif val is None:
                        setattr(party, 'party_type_id', None)
                    else:
                        s = str(val).strip()
                        if s.startswith("{") and s.endswith("}"):
                            setattr(party, 'party_type_id', s)
                        elif "," in s:
                            parts = [p.strip() for p in s.split(",") if p.strip()]
                            setattr(party, 'party_type_id', "{" + ",".join(parts) + "}")
                        else:
                            setattr(party, 'party_type_id', "{" + s + "}")
                else:
                    setattr(party, key, val)

        # set updated_by if available
        if updated_by is not None:
            party.updated_by = updated_by

        # Replace branches: delete existing and insert provided ones
        branches = payload.get("branches") or []
        # Delete existing branches for this party
        db.query(PartyBranchMst).filter(PartyBranchMst.party_id == party_id_int).delete(synchronize_session=False)

        for b in branches:
            branch = PartyBranchMst(
                party_id=party_id_int,
                active=1 if b.get("active") else 0,
                address=b.get("address"),
                address_additional=b.get("address_additional"),
                zip_code=int(b.get("zip_code")) if b.get("zip_code") else None,
                state_id=int(b.get("state")) if b.get("state") else None,
                gst_no=b.get("gst_no"),
                contact_no=b.get("contact_no"),
                contact_person=b.get("contact_person"),
                updated_by=updated_by
            )
            db.add(branch)

        db.commit()
        return {"message": "Party updated successfully", "party_id": party_id_int}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Supplier Registration (party_mst + jute_supp_party_map + party_branch_mst) ──

# Fixed jute supplier the registered parties are mapped to.
JUTE_SUPPLIER_ID = 2397

# Branch fields that must be unique across suppliers — checked as a soft warning.
_BRANCH_DUP_FIELDS = [
    ("whatsapp_no", "WhatsApp No"),
    ("bank_acc_no", "Bank Account No"),
    ("upi_code", "UPI Code"),
]


def _gen_supp_code(db: Session, co_id: int, prefix_word: str) -> str:
    """Continue the <Letter>#### running sequence per company. Leading letter is
    the first letter of the party type's prefix, uppercased (jutesupp -> J)."""
    letter = (prefix_word or "X").strip()[:1].upper() or "X"
    rows = db.execute(
        text("SELECT supp_code FROM party_mst WHERE co_id = :co_id AND supp_code REGEXP :pat"),
        {"co_id": co_id, "pat": f"^{letter}[0-9]+$"},
    ).fetchall()
    max_n = 0
    for (code,) in rows:
        try:
            n = int(str(code)[1:])
            max_n = max(max_n, n)
        except (ValueError, TypeError):
            continue
    return f"{letter}{max_n + 1:04d}"


@router.get("/supplier_registration_setup")
async def supplier_registration_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        party_types = [dict(r._mapping) for r in db.execute(get_party_types_with_prefix()).fetchall()]
        countries = [dict(r._mapping) for r in db.execute(get_country_list()).fetchall()]
        states = [dict(r._mapping) for r in db.execute(get_state_list()).fetchall()]
        entities = [dict(r._mapping) for r in db.execute(get_entity_list()).fetchall()]
        cities = [dict(r._mapping) for r in db.execute(get_city_list()).fetchall()]
        return {
            "party_types": party_types,
            "countries": countries,
            "states": states,
            "entities": entities,
            "cities": cities,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/supplier_register")
async def supplier_register(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Register a supplier in one transaction: party_mst -> jute_supp_party_map -> party_branch_mst.

    - supp_name must be unique per company (hard error).
    - Branch whatsapp_no / bank_acc_no / upi_code already used by another supplier returns a
      soft warning ({duplicate: true, conflicts: [...]}) and saves nothing, unless force=true.
    """
    try:
        payload = await request.json()
        co_id_raw = payload.get("co_id") or request.query_params.get("co_id")
        if co_id_raw is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        co_id = int(co_id_raw)

        updated_by = 0
        if token_data and token_data.get("user_id"):
            try:
                updated_by = int(token_data.get("user_id"))
            except (ValueError, TypeError):
                updated_by = 0

        supp_name = (payload.get("supp_name") or "").strip()
        if not supp_name:
            raise HTTPException(status_code=400, detail="Party name is required")

        # 1) Unique party name per company (hard block)
        dup_name = db.execute(
            text(
                "SELECT party_id FROM party_mst "
                "WHERE co_id = :co_id AND active = 1 "
                "AND LOWER(TRIM(supp_name)) = LOWER(TRIM(:name)) LIMIT 1"
            ),
            {"co_id": co_id, "name": supp_name},
        ).first()
        if dup_name:
            raise HTTPException(status_code=409, detail="Party name already exists")

        branches = payload.get("branches") or []

        # 2) Soft duplicate check on branch unique fields (skipped when force=true)
        if not payload.get("force"):
            conflicts = []
            for b in branches:
                for col, label in _BRANCH_DUP_FIELDS:
                    val = (str(b.get(col)).strip() if b.get(col) not in (None, "") else "")
                    if not val:
                        continue
                    hit = db.execute(
                        text(
                            f"SELECT pm.supp_name FROM party_branch_mst pbm "
                            f"JOIN party_mst pm ON pm.party_id = pbm.party_id "
                            f"WHERE pbm.active = 1 AND pbm.{col} = :val LIMIT 1"
                        ),
                        {"val": val},
                    ).first()
                    if hit:
                        conflicts.append({
                            "field": col,
                            "label": label,
                            "value": val,
                            "supplier": hit[0],
                        })
            if conflicts:
                return {"duplicate": True, "conflicts": conflicts}

        # 3) Resolve party type + generate supp_code
        party_type_id = payload.get("party_type") if payload.get("party_type") is not None else payload.get("party_type_id")
        prefix_word = ""
        if party_type_id not in (None, ""):
            pt = db.execute(
                text("SELECT party_types_mst_prefix FROM party_type_mst WHERE party_types_mst_id = :id"),
                {"id": int(party_type_id)},
            ).first()
            if pt:
                prefix_word = pt[0] or ""
        supp_code = _gen_supp_code(db, co_id, prefix_word)

        # 4) Insert party_mst
        party = PartyMst(
            active=1,
            prefix=prefix_word or None,
            updated_by=updated_by,
            phone_no=payload.get("phone_no"),
            cin=payload.get("cin"),
            co_id=co_id,
            supp_contact_person=payload.get("supp_contact_person"),
            supp_contact_designation=payload.get("supp_contact_designation"),
            supp_email_id=payload.get("supp_email_id"),
            supp_code=supp_code,
            party_pan_no=payload.get("party_pan_no"),
            entity_type_id=int(payload["entity_type_id"]) if payload.get("entity_type_id") else None,
            supp_name=supp_name,
            msme_certified=payload.get("msme_certified"),
            country_id=int(payload["country_id"]) if payload.get("country_id") else None,
            party_type_id=("{" + str(int(party_type_id)) + "}") if party_type_id not in (None, "") else None,
        )
        db.add(party)
        db.flush()  # get party_id without ending the transaction
        party_id = party.party_id

        # 5) Insert jute_supp_party_map
        db.execute(
            text(
                "INSERT INTO jute_supp_party_map (co_id, updated_by, jute_supplier_id, party_id) "
                "VALUES (:co_id, :updated_by, :jute_supplier_id, :party_id)"
            ),
            {
                "co_id": co_id,
                "updated_by": updated_by,
                "jute_supplier_id": JUTE_SUPPLIER_ID,
                "party_id": party_id,
            },
        )

        # 6) Insert branches
        def _int_or_none(v):
            try:
                return int(v) if v not in (None, "") else None
            except (ValueError, TypeError):
                return None

        for b in branches:
            branch = PartyBranchMst(
                party_id=party_id,
                active=1,
                created_date=datetime.now(),
                created_by=updated_by,
                gst_no=b.get("gst_no"),
                address=b.get("address"),
                address_additional=b.get("address_additional"),
                zip_code=_int_or_none(b.get("zip_code")),
                state_id=_int_or_none(b.get("state") if b.get("state") is not None else b.get("state_id")),
                city_id=_int_or_none(b.get("city") if b.get("city") is not None else b.get("city_id")),
                contact_no=b.get("contact_no"),
                contact_person=b.get("contact_person"),
                email_id=b.get("email_id"),
                bank_acc_no=b.get("bank_acc_no"),
                ifsc_code=b.get("ifsc_code"),
                bank_name=b.get("bank_name"),
                bank_branch=b.get("bank_branch"),
                whatsapp_no=b.get("whatsapp_no"),
                upi_code=b.get("upi_code"),
                updated_by=updated_by,
            )
            db.add(branch)

        db.commit()
        return {"message": "Supplier registered successfully", "party_id": party_id, "supp_code": supp_code}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        print(f"supplier_register error: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
