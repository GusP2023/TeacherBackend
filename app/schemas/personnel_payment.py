"""Schemas Pydantic para PersonnelPayment"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PersonnelPaymentPreviewRequest(BaseModel):
    teacher_id: int
    period_from: date
    period_to:   date


class PersonnelPaymentPreviewResponse(BaseModel):
    teacher_id:                  int
    teacher_name:                str
    payment_mode_snapshot:       str
    tariff_individual_snapshot:  Decimal | None
    tariff_group_snapshot:       Decimal | None
    fixed_amount_snapshot:       Decimal | None
    classes_individual_count:    int | None
    classes_group_count:         int | None
    amount_calculated:           Decimal

    model_config = ConfigDict(from_attributes=True)


class PersonnelPaymentCreate(BaseModel):
    teacher_id:     int
    period_from:    date
    period_to:      date
    adjustment:     Decimal = Field(default=Decimal("0.00"))
    notes:          str | None = None
    mark_as_paid:   bool = False
    account_id:     int | None = None
    invoice_number: str | None = Field(None, max_length=100)
    invoice_date:   date | None = None
    invoice_notes:  str | None = None

    @model_validator(mode='after')
    def validate_mark_as_paid(self) -> 'PersonnelPaymentCreate':
        if self.mark_as_paid:
            if not self.invoice_number or not self.invoice_number.strip():
                raise ValueError("invoice_number es requerido y no puede estar vacío cuando mark_as_paid=True")
            if not self.invoice_date:
                raise ValueError("invoice_date es requerido cuando mark_as_paid=True")
            if not self.account_id:
                raise ValueError("account_id es requerido cuando mark_as_paid=True")
        return self


class PersonnelPaymentUpdate(BaseModel):
    """Solo editable mientras status='pending'"""
    adjustment:  Decimal | None = None
    notes:       str | None = None
    period_from: date | None = None   # Si cambia el período, recalcula automáticamente
    period_to:   date | None = None


class PersonnelPaymentPayRequest(BaseModel):
    account_id:     int
    invoice_number: str = Field(..., max_length=100)
    invoice_date:   date
    invoice_notes:  str | None = None


class PersonnelPaymentRevertRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class TeacherSimple(BaseModel):
    id:   int
    name: str
    model_config = ConfigDict(from_attributes=True)


class PersonnelPaymentResponse(BaseModel):
    id:                          int
    teacher_id:                  int
    teacher:                     TeacherSimple
    period_from:                 date
    period_to:                   date
    payment_mode_snapshot:       str
    tariff_individual_snapshot:  Decimal | None
    tariff_group_snapshot:       Decimal | None
    fixed_amount_snapshot:       Decimal | None
    classes_individual_count:    int | None
    classes_group_count:         int | None
    amount_calculated:           Decimal
    adjustment:                  Decimal
    total_amount:                Decimal
    status:                      str
    notes:                       str | None
    invoice_number:              str | None
    invoice_date:                date | None
    invoice_notes:               str | None
    revision_count:              int = 0
    account_id:                  int | None = None
    account_name:                str | None = None
    created_at:                  datetime
    updated_at:                  datetime

    model_config = ConfigDict(from_attributes=True)


class PersonnelPaymentAuditResponse(BaseModel):
    id:                        int
    action:                    Literal['paid', 'reverted']
    performed_by_teacher_id:   int
    performed_by_teacher_name: str
    invoice_number:            str | None
    invoice_date:              date | None
    invoice_notes:             str | None
    reason:                    str | None = None
    account_id:                int | None = None
    account_name:              str | None = None
    created_at:                datetime

    model_config = ConfigDict(from_attributes=True)


class PendingMonth(BaseModel):
    year:   int
    month:  int
    reason: Literal['unpaid', 'no_classes']


class PendingAlertTeacher(BaseModel):
    id:             int
    name:           str
    payment_mode:   str
    pending_months: list[PendingMonth] = []

    model_config = ConfigDict(from_attributes=True)
