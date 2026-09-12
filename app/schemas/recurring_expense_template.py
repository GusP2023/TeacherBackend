"""Schemas Pydantic para RecurringExpenseTemplate"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class RecurringExpenseTemplateCreate(BaseModel):
    category: str = Field(
        ...,
        pattern="^(alquiler|servicios|materiales|marketing|mantenimiento|otro)$",
        description="Categoría del gasto operativo"
    )
    description: str = Field(..., min_length=1, max_length=500, description="Descripción del gasto")
    default_amount: Decimal = Field(..., gt=0, description="Monto por defecto del gasto a generar")
    active: bool = Field(default=True, description="Indica si la plantilla está activa")


class RecurringExpenseTemplateUpdate(BaseModel):
    category: str | None = Field(
        None,
        pattern="^(alquiler|servicios|materiales|marketing|mantenimiento|otro)$",
        description="Nueva categoría del gasto operativo"
    )
    description: str | None = Field(None, min_length=1, max_length=500, description="Nueva descripción")
    default_amount: Decimal | None = Field(None, gt=0, description="Nuevo monto por defecto")
    active: bool | None = Field(None, description="Nuevo estado activo/inactivo")


class RecurringExpenseTemplateResponse(BaseModel):
    id: int
    organization_id: int
    category: str
    description: str
    default_amount: Decimal
    active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
