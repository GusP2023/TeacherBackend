"""
Schemas Pydantic para Teacher (Profesor)
"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class TeacherBase(BaseModel):
    """
    Campos comunes para Teacher
    """
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=20)
    tariff_individual: Decimal = Field(..., gt=0, decimal_places=2)
    tariff_group: Decimal = Field(..., gt=0, decimal_places=2)


class TeacherCreate(TeacherBase):
    """
    Schema para crear un Teacher (POST /register o /teachers)
    Incluye password
    """
    password: str = Field(..., min_length=8, max_length=100)


class TeacherUpdate(BaseModel):
    """
    Schema para actualizar un Teacher (PUT/PATCH)
    Todos los campos son opcionales
    """
    email: EmailStr | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=20)
    password: str | None = Field(None, min_length=8, max_length=100)
    tariff_individual: Decimal | None = Field(None, gt=0, decimal_places=2)
    tariff_group: Decimal | None = Field(None, gt=0, decimal_places=2)


class TeacherResponse(TeacherBase):
    """
    Schema para respuestas (GET)
    Incluye campos de BD, NO incluye password
    """
    id: int
    active: bool
    created_at: datetime
    updated_at: datetime
    
    # Pydantic v2: usar model_config en lugar de class Config
    model_config = ConfigDict(from_attributes=True)