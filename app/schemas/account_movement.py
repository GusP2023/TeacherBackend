"""Schemas Pydantic para AccountMovement y transferencias"""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AccountMovementCreate(BaseModel):
    account_id: int = Field(..., description="ID de la cuenta financiera afectada")
    movement_type: str = Field(
        ...,
        pattern="^(aporte_capital|retiro_capital|ajuste|transferencia_salida|transferencia_entrada)$",
        description="Tipo de movimiento ('aporte_capital', 'retiro_capital', 'ajuste')"
    )
    amount: Decimal = Field(..., description="Monto del movimiento (puede ser negativo solo para ajuste)")
    description: str | None = Field(None, max_length=500, description="Detalle explicativo del movimiento")
    movement_date: date = Field(..., description="Fecha del movimiento")

    @model_validator(mode="after")
    def validate_movement_type(self) -> "AccountMovementCreate":
        if self.movement_type in ("transferencia_salida", "transferencia_entrada"):
            raise ValueError(
                "Los movimientos de tipo transferencia no se pueden registrar directamente; "
                "debe utilizarse el endpoint de transferencias (/admin/account-movements/transfer)."
            )
        if self.movement_type == "ajuste":
            if self.amount == Decimal("0.00") or self.amount == 0:
                raise ValueError("El monto para un movimiento de tipo 'ajuste' debe ser distinto de 0.")
        else:
            if self.amount <= Decimal("0.00"):
                raise ValueError("El monto debe ser mayor a 0.")
        return self


class AccountTransferCreate(BaseModel):
    from_account_id: int = Field(..., description="ID de la cuenta de origen")
    to_account_id: int = Field(..., description="ID de la cuenta de destino")
    amount: Decimal = Field(..., gt=0, description="Monto a transferir (debe ser mayor a 0)")
    description: str | None = Field(None, max_length=500, description="Detalle opcional de la transferencia")
    movement_date: date = Field(..., description="Fecha de la transferencia")

    @model_validator(mode="after")
    def validate_accounts(self) -> "AccountTransferCreate":
        if self.from_account_id == self.to_account_id:
            raise ValueError("from_account_id y to_account_id deben ser cuentas distintas.")
        return self


class AccountMovementResponse(BaseModel):
    id: int
    organization_id: int
    account_id: int
    related_account_id: int | None = None
    movement_type: str
    amount: Decimal
    description: str | None = None
    movement_date: date
    created_by_teacher_id: int
    related_account_name: str | None = None
    created_by_teacher_name: str = ""
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
