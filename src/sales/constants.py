"""
Sales module constants - single source of truth for sales status IDs and document types.
"""

# =============================================================================
# SALES STATUS DEFINITIONS
# =============================================================================

SALES_STATUS_IDS = {
    "DRAFT": 21,
    "OPEN": 1,
    "PENDING_APPROVAL": 20,
    "APPROVED": 3,
    "REJECTED": 4,
    "CLOSED": 5,
    "CANCELLED": 6,
}

SALES_STATUS_LABELS = {
    21: "Draft",
    1: "Open",
    20: "Pending Approval",
    3: "Approved",
    4: "Rejected",
    5: "Closed",
    6: "Cancelled",
}

# =============================================================================
# DOCUMENT TYPE CODES (used in document number generation)
# =============================================================================

SALES_DOC_TYPES = {
    "QUOTATION": "SQ",
    "SALES_ORDER": "SO",
    "DELIVERY_ORDER": "DO",
    "INVOICE": "SI",
}
