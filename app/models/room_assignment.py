"""
Modelo RoomAssignment - Asignación recurrente de sala a profesor.
"""

from datetime import date as dt_date, time as dt_time
# pyrefly: ignore [missing-import]
from sqlalchemy import Integer, Date, Time, ForeignKey, Enum as SQLEnum, Index
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from .base import Base, TimestampMixin
from .schedule import DayOfWeek

if TYPE_CHECKING:
    from .teacher import Teacher
    from .room import Room


class RoomAssignment(Base, TimestampMixin):
    __tablename__ = "room_assignments"
    __table_args__ = (
        Index("ix_room_assignments_teacher_day", "teacher_id", "day", "valid_until"),
        Index("ix_room_assignments_room_day", "room_id", "day"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Identificador único de la asignación de sala"
    )

    teacher_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID del profesor asignado"
    )

    room_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID de la sala asignada"
    )

    day: Mapped[DayOfWeek] = mapped_column(
        SQLEnum(DayOfWeek, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        comment="Día de la semana recurrente"
    )

    time: Mapped[dt_time] = mapped_column(
        Time,
        nullable=False,
        comment="Hora de inicio de la asignación"
    )

    duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Duración en minutos"
    )

    valid_from: Mapped[dt_date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Desde cuándo aplica esta asignación"
    )

    valid_until: Mapped[dt_date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
        comment="Hasta cuándo aplica esta asignación (NULL = vigente indefinidamente)"
    )

    teacher: Mapped["Teacher"] = relationship(
        back_populates="room_assignments",
        lazy="noload"
    )

    room: Mapped["Room"] = relationship(
        back_populates="assignments",
        lazy="noload"
    )

    def __repr__(self) -> str:
        return (
            f"<RoomAssignment(id={self.id}, teacher_id={self.teacher_id}, room_id={self.room_id}, "
            f"day={self.day}, time={self.time}, valid_from={self.valid_from}, valid_until={self.valid_until})>"
        )
