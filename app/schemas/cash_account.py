"""Schemas Pydantic para CashAccount"""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class CashAccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Nombre de la cuenta de caja o banco")
    opening_balance: Decimal = Field(default=Decimal("0.00"), ge=0, description="Saldo inicial con el que parte la cuenta")


class CashAccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255, description="Nuevo nombre de la cuenta")
    active: bool | None = Field(None, description="Estado de activación de la cuenta")


class CashAccountResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    opening_balance: Decimal
    active: bool
    created_at: datetime
    updated_at: datetime
    current_balance: Decimal

    model_config = ConfigDict(from_attributes=True)


class LedgerItem(BaseModel):
    date: date
    type: str
    description: str | None = None
    counterpart_name: str | None = None
    amount: Decimal
    running_balance: Decimal
    is_voided: bool = False

    model_config = ConfigDict(from_attributes=True)


class AccountLedgerResponse(BaseModel):
    items: list[LedgerItem]
    total_count: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)
