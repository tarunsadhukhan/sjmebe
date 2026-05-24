# src/test/test_procurement_sr_approve.py
"""
Tests for POST /storesReceipt/approve_sr endpoint.

Validates that debit_credit_note_id is correctly passed when auto-creating
DRCR notes during SR approval.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, call, patch
from datetime import datetime, date
from sqlalchemy import text

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


def _mock_row(mapping):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestApproveSREndpoint:
    """Tests for the approve_sr endpoint."""

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_approve_sr_with_rejected_qty_passes_debit_credit_note_id(self):
        """
        When SR has rejected quantities, the auto-created debit note detail
        must include debit_credit_note_id linking it to the header.
        """
        # Setup: line item with rejected qty
        line_row = _mock_row({
            "inward_dtl_id": 16,
            "po_rate": 200.0,
            "rate": 200.0,
            "accepted_rate": 200.0,
            "rejected_qty": 2.0,
            "approved_qty": 8.0,
        })

        # Mock LAST_INSERT_ID result for the note header
        note_id_row = MagicMock()
        note_id_row.id = 42

        # Configure mock: first call returns line items, second returns note_id,
        # third is the detail insert, fourth is the status update
        self.mock_session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[line_row])),  # get line items
            MagicMock(),  # insert note header
            MagicMock(fetchone=MagicMock(return_value=note_id_row)),  # LAST_INSERT_ID
            MagicMock(),  # insert detail line
            MagicMock(),  # update SR status
        ]

        response = client.post(
            "/api/storesReceipt/approve_sr",
            json={"inward_id": 7},
        )

        assert response.status_code == 200

        # Verify the detail insert call includes debit_credit_note_id
        detail_insert_call = self.mock_session.execute.call_args_list[3]
        detail_params = detail_insert_call[0][1]
        assert "debit_credit_note_id" in detail_params
        assert detail_params["debit_credit_note_id"] == 42

    def test_approve_sr_with_rate_increase_creates_credit_note_with_note_id(self):
        """
        When SR has a rate increase (accepted_rate > po_rate), a credit note
        detail is created with debit_credit_note_id.
        """
        line_row = _mock_row({
            "inward_dtl_id": 20,
            "po_rate": 100.0,
            "rate": 100.0,
            "accepted_rate": 120.0,
            "rejected_qty": 0,
            "approved_qty": 10.0,
        })

        note_id_row = MagicMock()
        note_id_row.id = 55

        self.mock_session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[line_row])),  # get line items
            MagicMock(),  # insert credit note header
            MagicMock(fetchone=MagicMock(return_value=note_id_row)),  # LAST_INSERT_ID
            MagicMock(),  # insert detail line
            MagicMock(),  # update SR status
        ]

        response = client.post(
            "/api/storesReceipt/approve_sr",
            json={"inward_id": 7},
        )

        assert response.status_code == 200

        # Verify credit note detail includes debit_credit_note_id
        detail_insert_call = self.mock_session.execute.call_args_list[3]
        detail_params = detail_insert_call[0][1]
        assert "debit_credit_note_id" in detail_params
        assert detail_params["debit_credit_note_id"] == 55

    def test_approve_sr_no_drcr_when_rates_match_and_no_rejection(self):
        """
        When there's no rate difference and no rejected qty,
        no DRCR note should be created.
        """
        line_row = _mock_row({
            "inward_dtl_id": 30,
            "po_rate": 100.0,
            "rate": 100.0,
            "accepted_rate": 100.0,
            "rejected_qty": 0,
            "approved_qty": 10.0,
        })

        self.mock_session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[line_row])),  # get line items
            MagicMock(),  # update SR status (no DRCR inserts)
        ]

        response = client.post(
            "/api/storesReceipt/approve_sr",
            json={"inward_id": 7},
        )

        assert response.status_code == 200
        # Only 2 execute calls: get line items + update SR status
        assert self.mock_session.execute.call_count == 2


class TestInsertDrcrNoteDtlQuery:
    """Tests for the insert_drcr_note_dtl query function."""

    def test_query_contains_debit_credit_note_id_bind(self):
        """The INSERT query must include :debit_credit_note_id bind parameter."""
        from src.procurement.query import insert_drcr_note_dtl
        query = insert_drcr_note_dtl()
        sql_str = str(query)
        assert ":debit_credit_note_id" in sql_str
        assert "debit_credit_note_id" in sql_str

    def test_query_contains_all_required_binds(self):
        """Query should have all expected bind parameters."""
        from src.procurement.query import insert_drcr_note_dtl
        query = insert_drcr_note_dtl()
        sql_str = str(query)
        expected_binds = [
            ":debit_credit_note_id",
            ":inward_dtl_id",
            ":debitnote_type",
            ":quantity",
            ":rate",
            ":discount_mode",
            ":discount_value",
            ":discount_amount",
            ":updated_by",
            ":updated_date_time",
        ]
        for bind in expected_binds:
            assert bind in sql_str, f"Missing bind parameter {bind}"

    def test_query_returns_text_object(self):
        """Query function should return a sqlalchemy text object."""
        from src.procurement.query import insert_drcr_note_dtl
        result = insert_drcr_note_dtl()
        assert isinstance(result, type(text("")))


class TestDrcrNoteDtlModel:
    """Tests for the DrcrNoteDtl ORM model."""

    def test_model_has_debit_credit_note_id_column(self):
        """ORM model should include debit_credit_note_id FK column."""
        from src.models.procurement import DrcrNoteDtl
        mapper = DrcrNoteDtl.__table__
        column_names = [col.name for col in mapper.columns]
        assert "debit_credit_note_id" in column_names

    def test_model_debit_credit_note_id_is_not_nullable(self):
        """debit_credit_note_id should be a required (NOT NULL) column."""
        from src.models.procurement import DrcrNoteDtl
        col = DrcrNoteDtl.__table__.columns["debit_credit_note_id"]
        assert col.nullable is False
