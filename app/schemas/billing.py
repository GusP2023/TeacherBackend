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
    teacher_name: str = "—"
    model_config = ConfigDict(from_attributes=True)


# ── BillingPeriod ─────────────────────────────────────────────────────────────

class BillingPeriodResponse(BaseModel):
    id: int
    enrollment_id: int
    student: StudentBrief
    enrollment: EnrollmentBrief
    charge_type: str
    description: str | None = None
    quantity: int | None = None
    period_year: int | None = None
    period_month: int | None = None
    base_amount: Decimal
    discount_applied: Decimal
    final_amount: Decimal
    amount_paid: Decimal
    status: str
    due_date: date | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BillingPeriodUpdate(BaseModel):
    due_date: date | None = None
    notes: str | None = None
    description: str | None = None
    quantity: int | None = None
    base_amount: Decimal | None = Field(None, gt=0, decimal_places=2)
    discount_applied: Decimal | None = Field(None, ge=0, decimal_places=2)


class BillingPeriodCreate(BaseModel):
    enrollment_id: int
    charge_type: str = Field(
        ...,
        pattern="^(cuota|matricula|extra|clase_suelta)$"
    )
    description: str | None = None
    quantity: int | None = Field(None, ge=1)  # solo para clase_suelta
    base_amount: Decimal = Field(..., gt=0, decimal_places=2)
    discount_applied: Decimal = Field(Decimal("0.00"), ge=0, decimal_places=2)
    due_date: date | None = None
    notes: str | None = None
    period_year: int | None = None   # solo para charge_type='cuota'
    period_month: int | None = Field(None, ge=1, le=12)


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
    concept: str = Field(
        ...,
        pattern="^(cuota|matricula|extra|recuperacion|clase_suelta)$"
    )
    payment_date: date
    payment_method: str = Field(
        default="efectivo",
        pattern="^(efectivo|transferencia|tarjeta|otro)$"
    )
    notes: str | None = None
    reference: str | None = None


class PaymentResponse(BaseModel):
    id: int
    enrollment_id: int
    billing_period_id: int | None
    amount: Decimal
    concept: str
    payment_date: date
    payment_method: str
    notes: str | None
    reference: str | None = None
    student_name: str
    instrument_name: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class StudentBillingSummary(BaseModel):
    student_id: int
    student_name: str
    teacher_name: str
    enrollment_count: int
    total_pending: Decimal
    pending_count: int
    has_overdue: bool
    billing_status: str  # 'current' | 'pending' | 'overdue'
