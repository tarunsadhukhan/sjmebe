"""
Tests for Hessian (invoice_type_id=2) functionality in Sales Order.
Covers: query functions, create/update payload handling, get-by-id response.
"""

import pytest
from sqlalchemy import text
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.sales.query import (
    insert_sales_order_dtl_hessian,
    delete_sales_order_dtl_hessian,
    get_sales_order_hessian_by_id_query,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# ---------------------------------------------------------------------------
# Query function tests
# ---------------------------------------------------------------------------

class TestHessianQueryFunctions:
    """Tests for hessian SQL query functions in query.py."""

    def test_insert_hessian_returns_text_object(self):
        result = insert_sales_order_dtl_hessian()
        assert isinstance(result, type(text("")))

    def test_insert_hessian_contains_required_binds(self):
        result = insert_sales_order_dtl_hessian()
        sql_str = str(result)
        for param in [
            ":sales_order_dtl_id", ":qty_bales", ":rate_per_bale",
            ":billing_rate_mt", ":billing_rate_bale",
            ":updated_by", ":updated_date_time",
        ]:
            assert param in sql_str, f"Missing bind parameter {param}"

    def test_delete_hessian_returns_text_object(self):
        result = delete_sales_order_dtl_hessian()
        assert isinstance(result, type(text("")))

    def test_delete_hessian_contains_sales_order_id_bind(self):
        result = delete_sales_order_dtl_hessian()
        sql_str = str(result)
        assert ":sales_order_id" in sql_str

    def test_get_hessian_by_id_returns_text_object(self):
        result = get_sales_order_hessian_by_id_query()
        assert isinstance(result, type(text("")))

    def test_get_hessian_by_id_contains_sales_order_id_bind(self):
        result = get_sales_order_hessian_by_id_query()
        sql_str = str(result)
        assert ":sales_order_id" in sql_str

    def test_get_hessian_by_id_selects_required_columns(self):
        result = get_sales_order_hessian_by_id_query()
        sql_str = str(result)
        for col in ["qty_bales", "rate_per_bale", "billing_rate_mt", "billing_rate_bale"]:
            assert col in sql_str, f"Missing column {col}"


# ---------------------------------------------------------------------------
# ORM model tests
# ---------------------------------------------------------------------------

class TestHessianOrmModel:
    """Tests for SalesOrderDtlHessian ORM model."""

    def test_model_exists(self):
        from src.models.sales import SalesOrderDtlHessian
        assert SalesOrderDtlHessian is not None

    def test_model_tablename(self):
        from src.models.sales import SalesOrderDtlHessian
        assert SalesOrderDtlHessian.__tablename__ == "sales_order_dtl_hessian"

    def test_model_has_required_columns(self):
        from src.models.sales import SalesOrderDtlHessian
        mapper = SalesOrderDtlHessian.__table__
        col_names = {c.name for c in mapper.columns}
        expected = {
            "sales_order_dtl_hessian_id", "sales_order_dtl_id",
            "qty_bales", "rate_per_bale",
            "billing_rate_mt", "billing_rate_bale",
            "updated_by", "updated_date_time",
        }
        assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"

    def test_dtl_model_has_hessian_relationship(self):
        from src.models.sales import SalesOrderDtl
        assert hasattr(SalesOrderDtl, "hessian"), "SalesOrderDtl should have 'hessian' relationship"


# ---------------------------------------------------------------------------
# Create endpoint — hessian payload handling
# ---------------------------------------------------------------------------

class TestCreateSalesOrderHessian:
    """Tests that the create endpoint processes hessian data when invoice_type=2."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_create_with_hessian_calls_hessian_insert(self):
        """When invoice_type=2 and items have hessian data, hessian insert should be invoked."""
        # Mock DB calls:
        # 1. branch lookup
        # 2. INSERT sales_order header → returns lastrowid
        # 3. INSERT sales_order_dtl → returns lastrowid
        # 4. INSERT sales_order_dtl_gst
        # 5. INSERT sales_order_dtl_hessian
        mock_insert_hdr = MagicMock()
        mock_insert_hdr.lastrowid = 100
        mock_insert_dtl = MagicMock()
        mock_insert_dtl.lastrowid = 200
        branch_row = _mock_row({"co_id": 1, "branch_prefix": "TST", "co_prefix": "CO"})

        self._mock_session.execute.side_effect = [
            MagicMock(fetchone=lambda: branch_row),  # branch lookup
            mock_insert_hdr,                          # header insert
            mock_insert_dtl,                          # dtl insert
            MagicMock(),                              # gst insert
            MagicMock(),                              # hessian insert
        ]
        self._mock_session.commit = MagicMock()

        payload = {
            "branch": "1",
            "date": "2025-06-01",
            "invoice_type": 2,
            "items": [{
                "item": "10",
                "quantity": "2.0",
                "uom": "5",
                "rate": "50000",
                "gst": {"igst_amount": 0, "cgst_amount": 0, "sgst_amount": 0, "gst_total": 0},
                "hessian": {
                    "qty_bales": 10,
                    "rate_per_bale": 12000,
                    "billing_rate_mt": 50000,
                    "billing_rate_bale": 10000,
                },
            }],
        }

        response = client.post("/api/salesOrder/create_sales_order?co_id=1", json=payload)

        # Verify the hessian insert was called (should be the 5th execute call)
        assert self._mock_session.execute.call_count >= 5, (
            f"Expected at least 5 DB calls (including hessian insert), got {self._mock_session.execute.call_count}"
        )

    def test_create_without_hessian_skips_hessian_insert(self):
        """When invoice_type=1 (Regular), hessian insert should NOT be invoked."""
        mock_insert_hdr = MagicMock()
        mock_insert_hdr.lastrowid = 100
        mock_insert_dtl = MagicMock()
        mock_insert_dtl.lastrowid = 200
        branch_row = _mock_row({"co_id": 1, "branch_prefix": "TST", "co_prefix": "CO"})

        self._mock_session.execute.side_effect = [
            MagicMock(fetchone=lambda: branch_row),  # branch lookup
            mock_insert_hdr,                          # header insert
            mock_insert_dtl,                          # dtl insert
            MagicMock(),                              # gst insert
        ]
        self._mock_session.commit = MagicMock()

        payload = {
            "branch": "1",
            "date": "2025-06-01",
            "invoice_type": 1,
            "items": [{
                "item": "10",
                "quantity": "5",
                "uom": "5",
                "rate": "100",
                "gst": {"igst_amount": 0, "cgst_amount": 0, "sgst_amount": 0, "gst_total": 0},
            }],
        }

        response = client.post("/api/salesOrder/create_sales_order?co_id=1", json=payload)

        # Should have exactly 4 execute calls (no hessian)
        assert self._mock_session.execute.call_count == 4


# ---------------------------------------------------------------------------
# Get-by-id — hessian response
# ---------------------------------------------------------------------------

class TestGetSalesOrderByIdHessian:
    """Tests that get_sales_order_by_id includes hessian data in line items."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_get_by_id_includes_hessian_in_lines(self):
        """When hessian data exists, each line should have a 'hessian' sub-object."""
        header = _mock_row({
            "sales_order_id": 1,
            "sales_no": "SO-001",
            "sales_order_date": "2025-06-01",
            "sales_order_expiry_date": None,
            "branch_id": 1,
            "branch_name": "Main",
            "party_id": 10,
            "party_name": "Customer A",
            "party_branch_id": None,
            "quotation_id": None,
            "quotation_no": None,
            "invoice_type": 2,
            "broker_id": None,
            "broker_name": None,
            "broker_commission_percent": 5.0,
            "billing_to_branch_id": None,
            "shipping_to_branch_id": None,
            "transporter_id": None,
            "transporter_name": None,
            "delivery_terms": None,
            "payment_terms": None,
            "delivery_days": None,
            "freight_charges": None,
            "gross_amount": 100000,
            "net_amount": 100000,
            "footer_note": None,
            "internal_note": None,
            "terms_conditions": None,
            "status_id": 21,
            "status_name": "Draft",
            "approval_level": None,
            "max_approval_level": None,
            "updated_by": None,
            "updated_date_time": None,
        })

        detail = _mock_row({
            "sales_order_dtl_id": 200,
            "quotation_lineitem_id": None,
            "hsn_code": None,
            "item_grp_id": 1,
            "item_id": 10,
            "item_name": "Hessian Cloth",
            "item_make_id": None,
            "quantity": 2.0,
            "qty_uom_id": 5,
            "qty_uom_name": "MT",
            "rate": 50000,
            "rate_uom_id": 5,
            "rate_uom_name": "MT",
            "discount_type": None,
            "discounted_rate": None,
            "discount_amount": None,
            "net_amount": 100000,
            "total_amount": 100000,
            "remarks": None,
        })

        gst_row = _mock_row({
            "sales_order_dtl_id": 200,
            "igst_amount": 0,
            "igst_percent": 0,
            "cgst_amount": 0,
            "cgst_percent": 0,
            "sgst_amount": 0,
            "sgst_percent": 0,
            "gst_total": 0,
        })

        hessian_row = _mock_row({
            "sales_order_dtl_id": 200,
            "qty_bales": 10,
            "rate_per_bale": 12000,
            "billing_rate_mt": 50000,
            "billing_rate_bale": 10000,
        })

        # Mock approval permissions
        approval_perm = _mock_row({"max_level": 1})

        self._mock_session.execute.side_effect = [
            MagicMock(fetchone=lambda: header),           # header query
            MagicMock(fetchall=lambda: [detail]),          # details query
            MagicMock(fetchall=lambda: [gst_row]),         # gst query
            MagicMock(fetchall=lambda: [hessian_row]),     # hessian query
            MagicMock(fetchone=lambda: approval_perm),     # approval permissions
        ]

        response = client.get("/api/salesOrder/get_sales_order_by_id/1?co_id=1")

        assert response.status_code == 200
        data = response.json()
        assert "lines" in data
        assert len(data["lines"]) == 1

        line = data["lines"][0]
        assert line["hessian"] is not None
        assert line["hessian"]["qtyBales"] == 10
        assert line["hessian"]["ratePerBale"] == 12000
        assert line["hessian"]["billingRateMt"] == 50000
        assert line["hessian"]["billingRateBale"] == 10000

    def test_get_by_id_hessian_null_when_no_data(self):
        """When no hessian data exists (Regular invoice), hessian should be None."""
        header = _mock_row({
            "sales_order_id": 2,
            "sales_no": "SO-002",
            "sales_order_date": "2025-06-01",
            "sales_order_expiry_date": None,
            "branch_id": 1,
            "branch_name": "Main",
            "party_id": 10,
            "party_name": "Customer A",
            "party_branch_id": None,
            "quotation_id": None,
            "quotation_no": None,
            "invoice_type": 1,
            "broker_id": None,
            "broker_name": None,
            "broker_commission_percent": None,
            "billing_to_branch_id": None,
            "shipping_to_branch_id": None,
            "transporter_id": None,
            "transporter_name": None,
            "delivery_terms": None,
            "payment_terms": None,
            "delivery_days": None,
            "freight_charges": None,
            "gross_amount": 500,
            "net_amount": 500,
            "footer_note": None,
            "internal_note": None,
            "terms_conditions": None,
            "status_id": 21,
            "status_name": "Draft",
            "approval_level": None,
            "max_approval_level": None,
            "updated_by": None,
            "updated_date_time": None,
        })

        detail = _mock_row({
            "sales_order_dtl_id": 300,
            "quotation_lineitem_id": None,
            "hsn_code": None,
            "item_grp_id": 1,
            "item_id": 20,
            "item_name": "Regular Item",
            "item_make_id": None,
            "quantity": 5,
            "qty_uom_id": 1,
            "qty_uom_name": "PCS",
            "rate": 100,
            "rate_uom_id": 1,
            "rate_uom_name": "PCS",
            "discount_type": None,
            "discounted_rate": None,
            "discount_amount": None,
            "net_amount": 500,
            "total_amount": 500,
            "remarks": None,
        })

        gst_row = _mock_row({
            "sales_order_dtl_id": 300,
            "igst_amount": 0, "igst_percent": 0,
            "cgst_amount": 0, "cgst_percent": 0,
            "sgst_amount": 0, "sgst_percent": 0,
            "gst_total": 0,
        })

        approval_perm = _mock_row({"max_level": 1})

        self._mock_session.execute.side_effect = [
            MagicMock(fetchone=lambda: header),
            MagicMock(fetchall=lambda: [detail]),
            MagicMock(fetchall=lambda: [gst_row]),
            MagicMock(fetchall=lambda: []),             # empty hessian
            MagicMock(fetchone=lambda: approval_perm),
        ]

        response = client.get("/api/salesOrder/get_sales_order_by_id/2?co_id=1")

        assert response.status_code == 200
        data = response.json()
        line = data["lines"][0]
        assert line["hessian"] is None
