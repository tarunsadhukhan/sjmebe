"""Pydantic schemas for jute procurement reports."""
from datetime import date
from typing import List

from pydantic import BaseModel, Field, model_validator


class JuteSummaryReportParams(BaseModel):
    """Query params for GET /api/juteReports/summary."""
    branch_id: int = Field(..., gt=0)
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _check_range(self) -> "JuteSummaryReportParams":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be <= to_date")
        return self


class JuteSummaryReportRow(BaseModel):
    """One row of the date-wise jute summary report."""
    report_date: str
    opening: float
    purchase: float
    issue: float
    closing: float


class JuteSummaryReportResponse(BaseModel):
    """Response wrapper for GET /api/juteReports/summary."""
    data: List[JuteSummaryReportRow]


class JuteDetailsReportRow(BaseModel):
    """One row of the date + quality-wise jute details report."""
    report_date: str
    quality_id: int
    quality_name: str
    opening: float
    purchase: float
    issue: float
    closing: float


class JuteDetailsReportResponse(BaseModel):
    """Response wrapper for GET /api/juteReports/details."""
    data: List[JuteDetailsReportRow]
