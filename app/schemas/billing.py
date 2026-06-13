"""Schemas Pydantic para BillingPeriod y Payment"""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class StudentBrief(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class EnrollmentBrief(BaseModel):
    id: int
    instrument_name: str
    format: str
    model_config = ConfigDict(from_attributes=True)


# ── BillingPeriod ─────────────────────────────────────────────────────────────

class BillingPeriodResponse(BaseModel):
    id: int
    enrollment_id: int
    student: StudentBrief
    enrollment: EnrollmentBrief
    period_year: int
    period_month: int
    base_amount: Decimal
    discount_applied: Decimal
    final_amount: Decimal
    amount_paid: Decimal
    status: str
    due_date: date
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BillingPeriodUpdate(BaseModel):
    due_date: date | None = None
    notes: str | None = None


class GenerateBillingPeriodsResponse(BaseModel):
    created: int
    skipped: int
    enrollments_processed: int
    errors: list[str]


# ── Payment ───────────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    enrollment_id: int
    billing_period_id: int | None = None
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    concept: str = Field(..., pattern="^(cuota|matricula|extra|recuperacion)$")
    payment_date: date
    payment_method: str = Field(default="efectivo",
                                 pattern="^(efectivo|transferencia|tarjeta|otro)$")
    notes: str | None = None


class PaymentResponse(BaseModel):
    id: int
    enrollment_id: int
    billing_period_id: int | None
    amount: Decimal
    concept: str
    payment_date: date
    payment_method: str
    notes: str | None
    student_name: str
    instrument_name: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
