"""
Modelo RoomOverride - Excepción puntual de sala para una fecha específica.
"""

from datetime import date as dt_date, time as dt_time
# pyrefly: ignore [missing-import]
from sqlalchemy import Integer, Date, Time, ForeignKey, String, Index
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .teacher import Teacher
    from .room import Room


class RoomOverride(Base, TimestampMixin):
    __tablename__ = "room_overrides"
    __table_args__ = (
        Index("ix_room_overrides_teacher_date", "teacher_id", "date", unique=True),
        Index("ix_room_overrides_room_date", "room_id", "date"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Identificador único del override de sala"
    )

    teacher_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID del profesor"
    )

    room_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("rooms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="ID de la sala opcional para este override"
    )

    date: Mapped[dt_date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Fecha exacta del override"
    )

    time: Mapped[dt_time] = mapped_column(
        Time,
        nullable=False,
        comment="Hora de inicio del override"
    )

    duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Duración en minutos del override"
    )

    reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Motivo informativo del cambio"
    )

    teacher: Mapped["Teacher"] = relationship(
        back_populates="room_overrides",
        lazy="noload"
    )

    room: Mapped["Room | None"] = relationship(
        back_populates="overrides",
        lazy="noload"
    )

    def __repr__(self) -> str:
        return (
            f"<RoomOverride(id={self.id}, teacher_id={self.teacher_id}, room_id={self.room_id}, "
            f"date={self.date}, time={self.time})>"
        )
