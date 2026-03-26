"""
Modelo Invitation - Invitaciones para unirse a una organización.

Reemplaza el registro público (/auth/register abierto).
El org_admin genera un token de invitación para cada nuevo teacher.
El teacher usa ese token para registrarse y queda asociado a la organización.

Cada invitación:
- Es de un solo uso (used_at se setea al aceptarla)
- Expira a las 48h de su creación
- Tiene un rol pre-asignado por el org_admin
"""

from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .organization import Organization
    from .teacher import Teacher


class Invitation(Base, TimestampMixin):
    """
    Invitación para unirse a una organización.

    Atributos:
        id: Identificador único
        organization_id: FK a la organización que invita
        email: Email del invitado (para validar al aceptar)
        role: Rol que tendrá el invitado al aceptar
        token: Token único UUID de 32 caracteres
        expires_at: Fecha de expiración (48h desde creación)
        used_at: Cuándo fue usada (NULL = pendiente)
        invited_by_id: FK al teacher que la creó (org_admin)

    Ejemplo:
        inv = Invitation(
            organization_id=1,
            email="profesor@escuela.com",
            role="teacher",
            token="abc123...",
            expires_at=datetime.now() + timedelta(hours=48),
            invited_by_id=1
        )
    """
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Email del invitado"
    )

    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="teacher",
        comment="Rol que tendrá al aceptar: teacher|coordinator|administrative"
    )

    token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Token único para aceptar la invitación"
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Fecha de expiración (48h desde creación)"
    )

    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Cuándo fue aceptada (NULL = pendiente)"
    )

    invited_by_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK al teacher org_admin que la creó"
    )

    # ── Relaciones ──────────────────────────────────────────────────────
    organization: Mapped["Organization"] = relationship(
        back_populates="invitations",
        lazy="selectin"
    )

    invited_by: Mapped["Teacher"] = relationship(
        foreign_keys=[invited_by_id],
        lazy="selectin"
    )

    @property
    def is_valid(self) -> bool:
        """True si la invitación no fue usada y no expiró."""
        from datetime import timezone
        return (
            self.used_at is None and
            self.expires_at > datetime.now(timezone.utc)
        )

    def __repr__(self) -> str:
        return (
            f"<Invitation(id={self.id}, email='{self.email}', "
            f"role='{self.role}', used={self.used_at is not None})>"
        )
