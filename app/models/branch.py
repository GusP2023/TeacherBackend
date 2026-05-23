"""
Modelo Branch - Sucursal/Sede de la institución.
"""

from sqlalchemy import String, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .organization import Organization
    from .room import Room


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Identificador único de la sucursal"
    )

    organization_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID de la organización a la que pertenece la sucursal"
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Nombre de la sucursal"
    )

    address: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Dirección física de la sucursal"
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default='true',
        comment="Indica si la sucursal está activa"
    )

    organization: Mapped["Organization"] = relationship(
        back_populates="branches",
        lazy="noload"
    )

    rooms: Mapped[List["Room"]] = relationship(
        back_populates="branch",
        cascade="all, delete-orphan",
        lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Branch(id={self.id}, name='{self.name}', organization_id={self.organization_id})>"
