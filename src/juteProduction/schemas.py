"""Pydantic schemas for jute production - spreader reports."""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class SpreaderReportParams(BaseModel):
    """Query params for spreader report endpoints."""
    branch_id: int = Field(..., gt=0)
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "SpreaderReportParams":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be <= to_date")
        return self


class SpreaderSummaryRow(BaseModel):
    report_date: str
    opening: float
    production: float
    issue: float
    closing: float


class SpreaderSummaryResponse(BaseModel):
    data: List[SpreaderSummaryRow]


class SpreaderDateProductionRow(BaseModel):
    report_date: str
    quality_id: int
    quality_name: str
    opening: float
    production: float
    issue: float
    closing: float


class SpreaderDateProductionResponse(BaseModel):
    data: List[SpreaderDateProductionRow]


class SpreaderDateIssueRow(BaseModel):
    report_date: str
    quality_id: int
    quality_name: str
    issue: float


class SpreaderDateIssueResponse(BaseModel):
    data: List[SpreaderDateIssueRow]


class SpreaderQualityDetailsRow(BaseModel):
    quality_id: int
    quality_name: str
    total_production: float
    total_issue: float
    balance: float


class SpreaderQualityDetailsResponse(BaseModel):
    data: List[SpreaderQualityDetailsRow]


# =============================================================================
# Drawing Reports — daily_drawing_transaction (machine-wise output meters)
# =============================================================================


class DrawingReportParams(BaseModel):
    """Query params for drawing report endpoints."""
    branch_id: int = Field(..., gt=0)
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "DrawingReportParams":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be <= to_date")
        return self


class DrawingSummaryRow(BaseModel):
    report_date: str
    opening: float
    production: float
    issue: float
    closing: float


class DrawingSummaryResponse(BaseModel):
    data: List[DrawingSummaryRow]


class DrawingDateProductionRow(BaseModel):
    report_date: str
    quality_id: int
    quality_name: str
    opening: float
    production: float
    issue: float
    closing: float


class DrawingDateProductionResponse(BaseModel):
    data: List[DrawingDateProductionRow]


class DrawingDateIssueRow(BaseModel):
    report_date: str
    quality_id: int
    quality_name: str
    issue: float


class DrawingDateIssueResponse(BaseModel):
    data: List[DrawingDateIssueRow]


class DrawingQualityDetailsRow(BaseModel):
    quality_id: int
    quality_name: str
    total_production: float
    total_issue: float
    balance: float


class DrawingQualityDetailsResponse(BaseModel):
    data: List[DrawingQualityDetailsRow]


class DrawingShiftMatrixRow(BaseModel):
    mc_id: int
    mc_short_name: str
    shed_type: Optional[str] = None
    drg_type: Optional[int] = None
    spell_id: int
    spell_name: str
    op: float
    cl: float
    unit: float
    eff: float


class DrawingShiftMatrixResponse(BaseModel):
    data: List[DrawingShiftMatrixRow]


# =============================================================================
# Spinning Reports
# =============================================================================


class SpinningReportParams(BaseModel):
    """Query params for spinning report endpoints."""
    branch_id: int = Field(..., gt=0)
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "SpinningReportParams":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be <= to_date")
        return self


class SpinningProductionEffRow(BaseModel):
    report_date: str
    quality_id: Optional[int] = None
    quality_name: Optional[str] = None
    spell_id: Optional[int] = None
    spell_name: Optional[str] = None
    frames: Optional[float] = 0.0
    production: Optional[float] = 0.0
    tarprod: Optional[float] = 0.0


class SpinningProductionEffResponse(BaseModel):
    data: List[SpinningProductionEffRow]


class SpinningMcDateRow(BaseModel):
    report_date: str
    mc_id: Optional[int] = None
    mc_name: Optional[str] = None
    frames: Optional[float] = 0.0
    production: Optional[float] = 0.0
    tarprod: Optional[float] = 0.0


class SpinningMcDateResponse(BaseModel):
    data: List[SpinningMcDateRow]


class SpinningEmpDateRow(BaseModel):
    report_date: str
    emp_id: Optional[int] = None
    emp_name: Optional[str] = None
    production: Optional[float] = 0.0
    eff: Optional[float] = 0.0


class SpinningEmpDateResponse(BaseModel):
    data: List[SpinningEmpDateRow]


class SpinningFrameRunningRow(BaseModel):
    report_date: str
    mc_id: Optional[int] = None
    mc_name: Optional[str] = None
    running_hours: Optional[float] = 0.0
    total_hours: Optional[float] = 0.0


class SpinningFrameRunningResponse(BaseModel):
    data: List[SpinningFrameRunningRow]


class SpinningRunningHoursEffRow(BaseModel):
    mc_id: Optional[int] = None
    mc_name: Optional[str] = None
    quality_id: Optional[int] = None
    quality_name: Optional[str] = None
    production: Optional[float] = 0.0
    running_hours: Optional[float] = 0.0
    eff: Optional[float] = 0.0


class SpinningRunningHoursEffResponse(BaseModel):
    data: List[SpinningRunningHoursEffRow]


# =============================================================================
# Winding Reports
# =============================================================================


class WindingReportParams(BaseModel):
    """Query params for winding report endpoints."""
    branch_id: int = Field(..., gt=0)
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "WindingReportParams":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be <= to_date")
        return self


class WindingEmpPeriodRow(BaseModel):
    emp_id: Optional[int] = None
    emp_code: Optional[str] = None
    emp_name: Optional[str] = None
    period_key: str
    period_label: str
    production: Optional[float] = 0.0
    total_hours: Optional[float] = 0.0


class WindingEmpPeriodResponse(BaseModel):
    data: List[WindingEmpPeriodRow]


class WindingDailyRow(BaseModel):
    report_date: str
    quality_id: Optional[int] = None
    quality_name: Optional[str] = None
    spell_id: Optional[int] = None
    spell_name: Optional[str] = None
    winders: Optional[float] = 0.0
    production: Optional[float] = 0.0


class WindingDailyResponse(BaseModel):
    data: List[WindingDailyRow]


# =============================================================================
# Other Entries Report
# =============================================================================


class OtherReportParams(BaseModel):
    """Query params for other-entries report endpoints."""
    branch_id: int = Field(..., gt=0)
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "OtherReportParams":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be <= to_date")
        return self


class OtherEntriesRow(BaseModel):
    report_date: str
    looms: Optional[float] = 0.0
    cuts: Optional[float] = 0.0
    cutting_hemming_bdl: Optional[float] = 0.0
    heracle_bdl: Optional[float] = 0.0
    branding: Optional[float] = 0.0
    h_sewer_bdl: Optional[float] = 0.0
    bales_production: Optional[float] = 0.0
    bales_issue: Optional[float] = 0.0


class OtherEntriesResponse(BaseModel):
    data: List[OtherEntriesRow]


# =============================================================================
# Bales Report
# =============================================================================


class BalesReportParams(BaseModel):
    """Query params for bales report endpoints."""
    branch_id: int = Field(..., gt=0)
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "BalesReportParams":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be <= to_date")
        return self


class BalesEntryRow(BaseModel):
    report_date: str
    quality_id: Optional[int] = None
    quality_name: Optional[str] = None
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    opening: Optional[float] = 0.0
    production: Optional[float] = 0.0
    issue: Optional[float] = 0.0
    closing: Optional[float] = 0.0


class BalesEntryResponse(BaseModel):
    data: List[BalesEntryRow]
