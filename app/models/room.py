"""
Modelo Room - Sala física dentro de una sucursal.
"""

from sqlalchemy import String, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .branch import Branch
    from .room_assignment import RoomAssignment
    from .room_override import RoomOverride


class Room(Base, TimestampMixin):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Identificador único de la sala"
    )

    branch_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Sucursal a la que pertenece esta sala"
    )

    organization_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Organización a la que pertenece la sala"
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Nombre de la sala"
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Descripción opcional de la sala"
    )

    capacity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default='1',
        comment="Capacidad de la sala en número de personas"
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default='true',
        comment="Indica si la sala está activa"
    )

    branch: Mapped["Branch"] = relationship(
        back_populates="rooms",
        lazy="selectin"
    )

    assignments: Mapped[List["RoomAssignment"]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="noload"
    )

    overrides: Mapped[List["RoomOverride"]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Room(id={self.id}, name='{self.name}', branch_id={self.branch_id})>"
