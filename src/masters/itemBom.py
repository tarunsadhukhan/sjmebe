from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.models import ItemBom
from src.masters.query import (
    get_bom_items_with_children,
    get_bom_children_query,
    get_bom_parents_query,
    get_items_for_bom_dropdown,
    get_bom_uom_list,
)
from src.common.utils import now_ist

router = APIRouter()

MAX_BOM_DEPTH = 15


def has_circular_reference(db: Session, parent_id: int, child_id: int, co_id: int, visited: set = None) -> bool:
    """Check if adding child_id under parent_id would create a cycle."""
    if visited is None:
        visited = set()
    if child_id == parent_id:
        return True
    if child_id in visited:
        return False
    visited.add(child_id)
    children = db.execute(
        get_bom_children_query(),
        {"parent_item_id": child_id, "co_id": co_id}
    ).fetchall()
    for row in children:
        if has_circular_reference(db, parent_id, row._mapping["child_item_id"], co_id, visited):
            return True
    return False


def build_bom_tree(db: Session, item_id: int, co_id: int, depth: int = 0, visited: set = None) -> list:
    """Recursively build BOM tree from an item."""
    if depth >= MAX_BOM_DEPTH:
        return []
    if visited is None:
        visited = set()
    if item_id in visited:
        return []  # circular reference protection
    visited.add(item_id)

    children = db.execute(
        get_bom_children_query(),
        {"parent_item_id": item_id, "co_id": co_id}
    ).fetchall()

    tree = []
    for child in children:
        node = dict(child._mapping)
        node["children"] = build_bom_tree(
            db, node["child_item_id"], co_id, depth + 1, visited.copy()
        )
        node["is_leaf"] = len(node["children"]) == 0
        tree.append(node)
    return tree


@router.get("/get_bom_list")
async def get_bom_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        query = get_bom_items_with_children()
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bom_tree")
async def get_bom_tree(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        item_id = request.query_params.get("item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id is required")

        tree = build_bom_tree(db, int(item_id), int(co_id))
        return {"data": tree}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bom_children")
async def get_bom_children(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        parent_item_id = request.query_params.get("parent_item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not parent_item_id:
            raise HTTPException(status_code=400, detail="parent_item_id is required")

        query = get_bom_children_query()
        result = db.execute(query, {
            "parent_item_id": int(parent_item_id),
            "co_id": int(co_id),
        }).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bom_parents")
async def get_bom_parents(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        child_item_id = request.query_params.get("child_item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not child_item_id:
            raise HTTPException(status_code=400, detail="child_item_id is required")

        query = get_bom_parents_query()
        result = db.execute(query, {
            "child_item_id": int(child_item_id),
            "co_id": int(co_id),
        }).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bom_create_setup")
async def bom_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        items_query = get_items_for_bom_dropdown()
        items = db.execute(items_query, {"co_id": int(co_id), "search": search_param}).fetchall()

        uom_query = get_bom_uom_list()
        uoms = db.execute(uom_query).fetchall()

        return {
            "items": [dict(r._mapping) for r in items],
            "uoms": [dict(r._mapping) for r in uoms],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_add_component")
async def bom_add_component(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        parent_item_id = body.get("parent_item_id")
        child_item_id = body.get("child_item_id")
        qty = body.get("qty")
        uom_id = body.get("uom_id")
        co_id = body.get("co_id")
        sequence_no = body.get("sequence_no", 0)

        if not all([parent_item_id, child_item_id, qty, uom_id, co_id]):
            raise HTTPException(status_code=400, detail="parent_item_id, child_item_id, qty, uom_id, and co_id are required")

        parent_item_id = int(parent_item_id)
        child_item_id = int(child_item_id)
        co_id = int(co_id)

        # Self-reference check
        if parent_item_id == child_item_id:
            raise HTTPException(status_code=400, detail="An item cannot be a component of itself")

        # Circular reference check
        if has_circular_reference(db, parent_item_id, child_item_id, co_id):
            raise HTTPException(status_code=400, detail="Adding this component would create a circular reference")

        # Check for existing row (including soft-deleted) and reactivate if found
        existing = db.query(ItemBom).filter(
            ItemBom.parent_item_id == parent_item_id,
            ItemBom.child_item_id == child_item_id,
            ItemBom.co_id == co_id,
        ).first()

        if existing:
            if existing.active == 1:
                raise HTTPException(status_code=409, detail="This component already exists in the BOM")
            # Reactivate soft-deleted row
            existing.active = 1
            existing.qty = float(qty)
            existing.uom_id = int(uom_id)
            existing.sequence_no = int(sequence_no)
            existing.updated_by = token_data.get("user_id")
            existing.updated_date_time = now_ist()
            db.commit()
            db.refresh(existing)
            response.status_code = 200
            return {"message": "Component reactivated successfully", "bom_id": existing.bom_id}

        new_bom = ItemBom(
            parent_item_id=parent_item_id,
            child_item_id=child_item_id,
            qty=float(qty),
            uom_id=int(uom_id),
            co_id=co_id,
            sequence_no=int(sequence_no),
            active=1,
            updated_by=token_data.get("user_id"),
            updated_date_time=now_ist(),
        )
        db.add(new_bom)
        db.commit()
        db.refresh(new_bom)
        response.status_code = 201
        return {"message": "Component added successfully", "bom_id": new_bom.bom_id}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_edit_component")
async def bom_edit_component(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        bom_id = body.get("bom_id")
        co_id = body.get("co_id")

        if not bom_id:
            raise HTTPException(status_code=400, detail="bom_id is required")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        existing = db.query(ItemBom).filter(
            ItemBom.bom_id == int(bom_id),
            ItemBom.co_id == int(co_id),
            ItemBom.active == 1,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="BOM component not found")

        if "qty" in body and body["qty"] is not None:
            existing.qty = float(body["qty"])
        if "uom_id" in body and body["uom_id"] is not None:
            existing.uom_id = int(body["uom_id"])
        if "sequence_no" in body and body["sequence_no"] is not None:
            existing.sequence_no = int(body["sequence_no"])

        existing.updated_by = token_data.get("user_id")
        existing.updated_date_time = now_ist()
        db.commit()
        return {"message": "Component updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bom_remove_component")
async def bom_remove_component(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        bom_id = body.get("bom_id")
        co_id = body.get("co_id")

        if not bom_id:
            raise HTTPException(status_code=400, detail="bom_id is required")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        existing = db.query(ItemBom).filter(
            ItemBom.bom_id == int(bom_id),
            ItemBom.co_id == int(co_id),
            ItemBom.active == 1,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="BOM component not found")

        existing.active = 0
        existing.updated_by = token_data.get("user_id")
        existing.updated_date_time = now_ist()
        db.commit()
        return {"message": "Component removed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
