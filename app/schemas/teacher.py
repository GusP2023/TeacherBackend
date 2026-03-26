"""
Schemas Pydantic para Teacher (Profesor)
"""
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class InstrumentSimple(BaseModel):
    """Representación mínima de instrumento para incluir en TeacherResponse"""
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class TeacherBase(BaseModel):
    """
    Campos comunes para Teacher.
    Tarifas tienen defaults sensatos para que el registro sea simple.
    """
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=20)
    birthdate: date | None = None
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=500)
    tariff_individual: Decimal = Field(default=Decimal('50.00'), gt=0, decimal_places=2)
    tariff_group: Decimal = Field(default=Decimal('30.00'), gt=0, decimal_places=2)


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
    birthdate: date | None = None
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=500)
    password: str | None = Field(None, min_length=8, max_length=100)
    tariff_individual: Decimal | None = Field(None, gt=0, decimal_places=2)
    tariff_group: Decimal | None = Field(None, gt=0, decimal_places=2)


class TeacherResponse(TeacherBase):
    """
    Schema para respuestas (GET)
    Incluye campos de BD, NO incluye password.
    El campo `permissions` contiene los permisos efectivos ya resueltos
    (defaults del rol + overrides de la organización). El cliente no necesita
    conocer la lógica de resolución — solo lee este dict.
    """
    id: int
    active: bool
    created_at: datetime
    updated_at: datetime
    role: str = "org_admin"
    organization_id: int | None = None
    instruments: list[InstrumentSimple] = []
    permissions: dict[str, bool] = {}

    model_config = ConfigDict(from_attributes=True)