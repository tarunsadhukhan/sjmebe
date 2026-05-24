"""
SQLAlchemy ORM models for jute tables (jute_*).
Auto-generated from database schema: sls
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Double,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    TIMESTAMP,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all jute models."""
    pass


# =============================================================================
# JUTE QUALITY MASTER
# =============================================================================

class JuteQualityMst(Base):
    """DEPRECATED: Jute quality master table.
    
    Quality is now managed via item_mst hierarchy:
    item_grp_mst (Jute parent) → item_grp_mst (subgroups) → item_mst (items = old qualities).
    This model is kept for backward compatibility / data migration only.
    """
    __tablename__ = "jute_quality_mst"

    jute_qlty_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_quality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# YARN QUALITY MASTER
# =============================================================================

class YarnQualityMst(Base):
    """Yarn quality master table - stores quality information for yarn products."""
    __tablename__ = "yarn_quality_master"

    yarn_quality_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quality_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    item_grp_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    twist_per_inch: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    std_count: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    std_doff: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    std_wt_doff: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_eff: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    


# =============================================================================
# MACHINE SPG DETAILS
# =============================================================================

class MachineSpgDetails(Base):
    """Machine SPG details table - stores spindle details for spinning machines."""
    __tablename__ = "mechine_spg_details"

    mc_spg_det_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mechine_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    frame_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default=None)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    no_of_spindle: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weight_per_spindle: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# SPINNING QUALITY MASTER
# =============================================================================

class SpinningQualityMst(Base):
    """Spinning quality master table - stores spinning quality specifications."""
    __tablename__ = "spinning_quality_mst"

    spg_quality_mst_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spg_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    spg_quality: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    speed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tpi: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    std_count: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    no_of_spindles: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frame_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    target_eff: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# TROLLY MASTER
# =============================================================================

class TrollyMst(Base):
    """Trolly master table - stores trolly definitions per branch/department."""
    __tablename__ = "trolly_mst"

    trolly_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trolly_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    trolly_weight: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)
    busket_weight: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE MR (MATERIAL RECEIPT) MODELS
# =============================================================================

class JuteMr(Base):
    """Jute Material Receipt table - stores MR information (combined gate entry + MR).

    Updated based on dev3 schema (2026-01-15).
    Gate entry table was merged into MR - this table now handles both gate entry and material receipt.
    Fields include: gate entry info, weights, QC, bill pass, invoice, and file uploads.
    """
    __tablename__ = "jute_mr"

    jute_mr_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Gate Entry identification (merged from jute_gate_entry)
    jute_gate_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    jute_gate_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # MR identification
    branch_mr_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    jute_mr_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # PO reference
    po_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Supplier/Party information
    jute_supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    party_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    party_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    src_com_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Challan details
    challan_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    challan_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    challan_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Weight measurements (from gate entry)
    gross_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tare_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    variable_shortage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    actual_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    mr_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Vehicle and transport details (from gate entry)
    vehicle_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transporter: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    driver_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Time tracking (from gate entry) - Note: in_time, out_time are TIME type
    in_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    out_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    out_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Location and unit
    mukam_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # QC and status
    qc_check: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    marketing_slip: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Freight
    frieght_paid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Bill pass details
    bill_pass_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bill_pass_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bill_pass_complete: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    # Financial amounts
    total_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    claim_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    roundoff: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_total: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tds_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Invoice details
    invoice_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_amount: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    payment_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_received_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # File uploads
    invoice_upload: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    challan_upload: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Audit fields
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    # Relationships
    line_items: Mapped[List["JuteMrLi"]] = relationship(
        "JuteMrLi", back_populates="jute_mr", foreign_keys="JuteMrLi.jute_mr_id"
    )


class JuteMrLi(Base):
    """Jute MR line item table - stores line items for material receipts.

    Updated based on dev3 schema (2026-01-15).
    Gate entry line item merged into MR line item - this table now handles both.
    Includes challan details, actual received details, QC data, claims, and pricing.
    """
    __tablename__ = "jute_mr_li"

    jute_mr_li_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_mr_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_mr.jute_mr_id"), nullable=True, index=True
    )
    jute_po_li_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Challan details — challan_item_id references item_mst; group is derived via item_mst.item_grp_id
    challan_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    challan_quantity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    challan_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)

    # Actual (received) details — actual_item_id references item_mst; group is derived via item_mst.item_grp_id
    actual_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    actual_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)
    actual_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)
    actual_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)

    # UOM (LOOSE/BALE)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Moisture details
    allowable_moisture: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_moisture: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Claims and adjustments
    claim_dust: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    claim_quality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shortage_kgs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    # Accepted and pricing
    accepted_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)
    claim_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    water_damage_amount: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True, default=0)
    premium_amount: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True, default=0)
    total_price: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # Storage details
    warehouse_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    marka: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    crop_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status and audit
    status: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    updated_date_time: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    # Relationships
    jute_mr: Mapped[Optional["JuteMr"]] = relationship(
        "JuteMr", back_populates="line_items", foreign_keys=[jute_mr_id]
    )
    moisture_readings: Mapped[List["JuteMoistureRdg"]] = relationship(
        "JuteMoistureRdg", back_populates="mr_line_item", foreign_keys="JuteMoistureRdg.jute_mr_li_id"
    )


class JuteMoistureRdg(Base):
    """Jute moisture reading table - stores multiple moisture readings per MR line item.

    Created based on dev3 schema (2026-01-07).
    """
    __tablename__ = "jute_moisture_rdg"

    jute_moisture_rdg_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_mr_li_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_mr_li.jute_mr_li_id"), nullable=True, index=True
    )
    moisture_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Relationships
    mr_line_item: Mapped[Optional["JuteMrLi"]] = relationship(
        "JuteMrLi", back_populates="moisture_readings", foreign_keys=[jute_mr_li_id]
    )


# =============================================================================
# JUTE ISSUE MODELS
# =============================================================================

class JuteIssue(Base):
    """Jute issue table - stores jute issue transactions to production/departments."""
    __tablename__ = "jute_issue"

    issue_no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    fin_year: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Issue details
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    issue_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # Jute details — item_id is the item (was jute_quality), jute_type is the subgroup name
    jute_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Quantity and stock
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    no_bales: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bale_loose: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    total_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_stock: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_stock: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stock_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Location/Assignment
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    godown_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # References
    mr_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yarn_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wastage_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    uom_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Status and audit
    is_active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    create_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    update_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class JuteIssuePrimary(Base):
    """Jute issue primary table - stores primary issue records for jute to production."""
    __tablename__ = "jute_issue_primary"

    jute_issue_primary_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Issue details
    issue_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Jute details — item_id is the item (was jute_quality), jute_type is the subgroup name
    jute_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Quantity and weight
    no_of_bales: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    no_of_bales_issued: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bale_or_loose: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gross_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    tare_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    net_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    # Location/Assignment
    godown_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    trolly_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yarn_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # References
    mr_line_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status and audit
    is_active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auto_date_time_insert: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SUPPLIER MODELS
# =============================================================================

class JuteSupplierMst(Base):
    """Jute supplier master table - stores jute supplier information."""
    __tablename__ = "jute_supplier_mst"

    supplier_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    party_mappings: Mapped[List["JuteSuppPartyMap"]] = relationship(
        "JuteSuppPartyMap", back_populates="jute_supplier"
    )


class JuteSuppPartyMap(Base):
    """Jute supplier to party mapping table - maps jute suppliers to party master."""
    __tablename__ = "jute_supp_party_map"

    map_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_supplier_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_supplier_mst.supplier_id"), nullable=True, index=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    party_id : Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Relationships
    jute_supplier: Mapped[Optional["JuteSupplierMst"]] = relationship(
        "JuteSupplierMst", back_populates="party_mappings"
    )


# =============================================================================
# JUTE MUKAM MASTER MODEL
# =============================================================================

class JuteMukamMst(Base):
    """Jute mukam master table - stores mukam (location) information for jute."""
    __tablename__ = "jute_mukam_mst"

    mukam_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mukam_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE LORRY MASTER MODEL
# =============================================================================

class JuteLorryMst(Base):
    """Jute lorry master table - stores lorry type and weight information for jute logistics."""
    __tablename__ = "jute_lorry_mst"

    jute_lorry_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lorry_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE AGENT MAP MODEL
# =============================================================================

class JuteAgentMap(Base):
    """Jute agent mapping table - maps agents (party branches) to branches."""
    __tablename__ = "jute_agent_map"

    agent_map_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    agent_branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

# =============================================================================
# JUTE PO MODELS
# =============================================================================

class JutePo(Base):
    """Jute purchase order header table - stores jute PO transactions.

    Updated based on dev3 schema (2026-01-08).
    """
    __tablename__ = "jute_po"

    jute_po_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    party_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_mukam_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_indent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # PO identification
    po_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    po_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    approval_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)

    # Contract details
    contract_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contract_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    channel_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Terms and charges
    credit_term: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    delivery_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    frieght_charge: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    brokrage_rate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    brokrage_percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    penalty: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Vehicle details
    vehicle_type_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vehicle_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Value and weight
    jute_po_value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    jute_uom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Notes and remarks
    remarks: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    internal_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    footer_note: Mapped[Optional[str]] = mapped_column(String(65535), nullable=True)  # longtext

    # Audit fields
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    line_items: Mapped[List["JutePoLi"]] = relationship(
        "JutePoLi", back_populates="jute_po"
    )


class JutePoLi(Base):
    """Jute purchase order line item table - stores individual items in a jute PO.

    Updated based on dev3 schema (2026-01-08).
    """
    __tablename__ = "jute_po_li"

    jute_po_li_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_po_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jute_po.jute_po_id"), nullable=True, index=True
    )

    # Item details — item_id references item_mst; group is derived via item_mst.item_grp_id
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Quantity and pricing
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # Jute details
    marka: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    crop_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    allowable_moisture: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # UOM (LOOSE/BALE) — per line item
    jute_uom: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Status
    active: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Audit
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    jute_po: Mapped[Optional["JutePo"]] = relationship(
        "JutePo", back_populates="line_items"
    )


# =============================================================================
# JUTE YARN TYPE MASTER
# =============================================================================

class JuteYarnTypeMst(Base):
    """DEPRECATED: Jute yarn type master table.
    
    Yarn types have been migrated to item_grp_mst with item_type_id=4.
    This model is kept for backward compatibility / rollback only.
    Do NOT use in new code — use ItemGrpMst with item_type_id=4 instead.
    """
    __tablename__ = "jute_yarn_type_mst"
    __table_args__ = {"extend_existing": True}

    jute_yarn_type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_yarn_type_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


# =============================================================================
# JUTE YARN MASTER
# =============================================================================

class JuteYarnMst(Base):
    """Jute yarn master table - stores yarn-specific details.

    Based on dev3 schema (2026-02-19).
    Each yarn also has a corresponding item_mst record (linked via item_id).
    - item_grp_id: FK to item_grp_mst (item_type_id=4) — the yarn type group.
    - item_id: FK to item_mst — the item record created alongside this yarn.
    - jute_yarn_name / co_id: Deprecated — kept for backward compatibility.
      The authoritative name comes from item_mst.item_name.
    """
    __tablename__ = "jute_yarn_mst"

    jute_yarn_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jute_yarn_count: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    # FK exists in DB but omitted from ORM — item_grp_mst uses a different DeclarativeBase
    item_grp_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    jute_yarn_remarks: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # Deprecated: name now sourced from item_mst.item_name; kept for backward compat
    jute_yarn_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Deprecated: company scoping now via item_grp_mst.co_id; kept for backward compat
    co_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Note: No ORM relationship to ItemGrpMst or ItemMst because they use
    # a different DeclarativeBase. Use raw SQL joins for querying.

# =============================================================================
# JUTE BATCH PLAN MODELS
# =============================================================================

class JuteBatchPlan(Base):
    """Jute batch plan header table - stores batch plan information.

    Based on dev3 schema (2026-02-02).
    """
    __tablename__ = "jute_batch_plan"

    batch_plan_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    plan_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )

    # Relationships
    line_items: Mapped[List["JuteBatchPlanLi"]] = relationship(
        "JuteBatchPlanLi", back_populates="batch_plan"
    )


class JuteBatchPlanLi(Base):
    """Jute batch plan line item table - stores jute quality percentages for a batch plan.

    Based on dev3 schema (2026-02-02).
    """
    __tablename__ = "jute_batch_plan_li"

    batch_plan_li_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_plan_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("jute_batch_plan.batch_plan_id"), nullable=True, index=True
    )
    jute_quality_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    percentage: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_date_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    # Relationships
    batch_plan: Mapped[Optional["JuteBatchPlan"]] = relationship(
        "JuteBatchPlan", back_populates="line_items"
    )


# =============================================================================
# JUTE ISSUE (DEV3 SCHEMA)
# =============================================================================

class JuteIssueDev3(Base):
    """Jute issue table (dev3 schema) - stores jute issue transactions to production.

    Based on dev3 schema (2026-02-02). This schema is simpler than the legacy
    JuteIssue model and uses different column structure.

    Note: Use this model when working with the dev3 database. The legacy JuteIssue
    model remains for backward compatibility with older databases.
    """
    __tablename__ = "jute_issue"
    __table_args__ = {"extend_existing": True}  # Allow coexistence with legacy model

    jute_issue_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Issue details
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    issue_value: Mapped[Optional[Decimal]] = mapped_column(Double, nullable=True)

    # References — item_id is the item (was jute_quality_id)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_mr_li_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    yarn_type_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Quantity and weight
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Audit fields
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    update_date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# =============================================================================
# JUTE STOCK OUTSTANDING VIEW
# =============================================================================

class VwJuteStockOutstanding(Base):
    """View model for vw_jute_stock_outstanding - shows available MR stock for issue.

    This view calculates balance quantity and weight by subtracting issued amounts
    from the original MR line item amounts.

    Only includes MRs with status_id IN (3, 13) (approved / finalised).
    Issued quantity excludes cancelled issues (status_id <> 4).

    Actual View Definition (from dev3, 2026-02-17):
    SELECT
        jml.jute_mr_li_id,
        jm.out_date            AS inward_date,
        jm.branch_id,
        jm.branch_mr_no,
        jm.jute_gate_entry_no,
        wm.warehouse_name,
        jml.actual_quality,
        jml.actual_item_id,
        jml.actual_qty,
        jml.actual_weight,
        jm.unit_conversion,
        (jml.actual_qty - IFNULL(iss.issqty, 0))                              AS bal_qty,
        ROUND((jml.actual_weight - IFNULL(iss.isswt, 0)), 3)                  AS bal_weight,
        jml.accepted_weight,
        ROUND((jml.accepted_weight / jml.actual_qty) * IFNULL(iss.issqty, 0), 3) AS bal_accepted_weight,
        jml.rate,
        jml.actual_rate
    FROM jute_mr jm
    JOIN jute_mr_li jml ON jm.jute_mr_id = jml.jute_mr_id
    LEFT JOIN warehouse_mst wm ON wm.warehouse_id = jml.warehouse_id
    LEFT JOIN (
        SELECT ji.jute_mr_li_id, SUM(ji.quantity) AS issqty, SUM(ji.weight) AS isswt
        FROM jute_issue ji
        WHERE ji.status_id <> 4
        GROUP BY ji.jute_mr_li_id
    ) iss ON iss.jute_mr_li_id = jml.jute_mr_li_id
    WHERE jm.status_id IN (3, 13)
    """
    __tablename__ = "vw_jute_stock_outstanding"

    # Primary key for ORM (view doesn't have PK, but ORM needs one)
    jute_mr_li_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Inward date (from jm.out_date)
    inward_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Branch and MR info
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    branch_mr_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Gate entry and warehouse info
    jute_gate_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warehouse_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Quality description (text from jute_mr_li.actual_quality)
    actual_quality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Item reference — actual_item_id is the item from item_mst
    actual_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Original quantities from MR
    actual_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Unit conversion (e.g., "LOOSE", "BALE")
    unit_conversion: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Calculated balance (available for issue)
    bal_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bal_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Weight fields
    accepted_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bal_accepted_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Rate fields
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


# =============================================================================
# JUTE BATCH DAILY ASSIGNMENT
# =============================================================================

class JuteBatchDailyAssign(Base):
    """Daily assignment of batch plans to yarn types per branch.

    Maps: Date + Branch + Yarn Type → Batch Plan.
    Each day+branch can have multiple yarn types, each assigned exactly one batch plan.
    Unique constraint: (branch_id, assign_date, jute_yarn_id).

    Status workflow: Draft (21) → Open (1) → Approved (3) / Rejected (4).

    Based on design doc 2026-02-20.
    """
    __tablename__ = "jute_batch_daily_assign"
    __table_args__ = (
        UniqueConstraint("branch_id", "assign_date", "jute_yarn_id", name="uq_branch_date_yarn"),
        {"extend_existing": True},
    )

    batch_daily_assign_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assign_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    jute_yarn_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    batch_plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status_id: Mapped[int] = mapped_column(Integer, nullable=False, default=21)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE SQC MORRAH WEIGHT QC
# =============================================================================

class JuteSqcMorrahWt(Base):
    __tablename__ = "jute_sqc_morrah_wt"
    __table_args__ = {"extend_existing": True}

    morrah_wt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    co_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    inspector_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dept_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trolley_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    avg_mr_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    weights: Mapped[str] = mapped_column(String(500), nullable=False)
    calc_avg_weight: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    calc_max_weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    calc_min_weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    calc_range: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    calc_cv_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    count_lt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    count_ok: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    count_hy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.current_timestamp()
    )


# =============================================================================
# JUTE RECEIVED (LEGACY FLAT TABLE)
# =============================================================================

class TblJuteReceived(Base):
    """Flat jute receipt table.

    One row per receipt line. Used by the date-wise jute summary report
    (Purchase column) — weight is summed by recv_date and branch_id.
    """
    __tablename__ = "tbl_jute_received"

    tbl_jute_rcv_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recv_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    quality_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    no_of_bales: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


# =============================================================================
# DAILY SPERDER (LEGACY FLAT TABLE)
# =============================================================================

class TblDailySperder(Base):
    """Daily sperder production / issue table.

    One row per machine-spell-quality entry. Used by the date-wise jute
    summary report (Issue column) — issue weight in kg = SUM(issue) * 60.
    """
    __tablename__ = "tbl_daily_sperder"

    tbl_daily_sprd_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    quality_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    production: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    issue: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    bin_no: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_date_time: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True, server_default=func.current_timestamp()
    )
    tran_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    spell_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    sprd_quality_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)


# =============================================================================
# ASSORTING ENTRY (ISSUE SOURCE)
# =============================================================================

class AssortingEntry(Base):
    """Assorting entry (issue) flat table.

    One row per selector-trolly entry. Used by the jute summary / details /
    day-wise reports as the issue source — `net_wt` is taken as the issue
    weight directly (no multiplier), grouped by `tran_date` and joined to
    quality via `jute_quality_id`.

    Note: this table has no branch_id column, so issue is not branch-scoped.
    """
    __tablename__ = "assorting_entry"

    tbl_daily_sel_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tran_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    selector_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    jute_quality_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    trolly_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    gross_weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tare_wt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    net_wt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)