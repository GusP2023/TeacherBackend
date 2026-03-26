"""
Schemas Pydantic para Invitation
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict  # noqa: F401


class InvitationCreate(BaseModel):
    """Body del request para crear una invitación"""
    email: EmailStr
    role: str = Field(default="teacher", pattern="^(teacher|coordinator|administrative)$")


class InvitationResponse(BaseModel):
    id: int
    organization_id: int
    email: str
    role: str
    token: str          # Necesario para que el admin pueda copiarlo y enviarlo
    expires_at: datetime
    used_at: datetime | None
    invited_by_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AcceptInviteRequest(BaseModel):
    """
    Body del request para aceptar una invitación y registrarse.
    El profesor ingresa sus datos personales y sus propias tarifas.
    El resto (teléfono, bio, instrumentos) se completa desde el perfil.
    """
    token: str = Field(..., min_length=10)
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=100)
    tariff_individual: float = Field(default=50.0, gt=0)
    tariff_group: float = Field(default=30.0, gt=0)
