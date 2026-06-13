"""Schemas Pydantic para PersonnelPayment"""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


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
    teacher_id:  int
    period_from: date
    period_to:   date
    adjustment:  Decimal = Field(default=Decimal("0.00"))
    notes:       str | None = None


class PersonnelPaymentUpdate(BaseModel):
    """Solo editable mientras status='pending'"""
    adjustment:  Decimal | None = None
    notes:       str | None = None
    period_from: date | None = None   # Si cambia el período, recalcula automáticamente
    period_to:   date | None = None


class PersonnelPaymentPayRequest(BaseModel):
    invoice_number: str = Field(..., max_length=100)
    invoice_date:   date
    invoice_notes:  str | None = None


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
    created_at:                  datetime
    updated_at:                  datetime

    model_config = ConfigDict(from_attributes=True)


class PendingAlertTeacher(BaseModel):
    id:           int
    name:         str
    payment_mode: str
    model_config = ConfigDict(from_attributes=True)
