"""
Modelo Organization - Representa una escuela/institución en el sistema multi-tenant.

Cada organización agrupa a sus teachers y todos sus datos.
El aislamiento de datos entre escuelas se garantiza filtrando por
organization_id en cada query de los endpoints.
"""

from sqlalchemy import String, Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .teacher import Teacher
    from .invitation import Invitation


class Organization(Base, TimestampMixin):
    """
    Modelo de Organización (Escuela).

    Una organización es el tenant raíz.
    Todos los datos (alumnos, clases, etc.) pertenecen a teachers que
    pertenecen a una organización.

    Atributos:
        id: Identificador único
        name: Nombre de la escuela (ej: "Escuela de Música Armonía")
        slug: Identificador URL-friendly único (ej: "escuela-armonia")
        active: Si la organización está activa (soft-disable)
        notes: Notas internas del admin del SaaS

    Relaciones:
        teachers: Todos los teachers de esta organización
        invitations: Invitaciones pendientes

    Ejemplo:
        org = Organization(
            name="Escuela de Música Armonía",
            slug="escuela-armonia",
        )
    """
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único de la organización"
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Nombre de la escuela"
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Identificador único URL-friendly"
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Si la organización está activa"
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notas internas (uso del SaaS admin)"
    )

    role_permissions: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment=(
            "Overrides de permisos por rol. NULL = sin restricciones (usa defaults del sistema). "
            'Formato: {"teacher": {"students.create": false, ...}}'
        )
    )

    # ── Relaciones ──────────────────────────────────────────────────────
    teachers: Mapped[List["Teacher"]] = relationship(
        back_populates="organization",
        lazy="noload"
    )

    invitations: Mapped[List["Invitation"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name='{self.name}', slug='{self.slug}')>"
