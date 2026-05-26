"""
Modelo Event - Evento general de la institución.

Cubre ensayos, workshops, masterclasses, eventos externos y cualquier
actividad que ocupe una sala e involucre profesores y/o alumnos.

Diseño de asociaciones:
  - event_teachers (M2M): los profesores titulares del evento
  - event_students (M2M): los alumnos participantes

Invitado externo:
  - guest_name + guest_email en el propio Event (máximo 1 por evento)
  - Para Google Calendar: unir emails de teachers + students + guest_email

Sala:
  - room_id nullable — si hay sala, la sucursal se deriva de room.branch_id
  - Si no hay sala asignada, el evento es sin ubicación específica

Tipos de evento (event_type):
  - 'rehearsal'   → Ensayo grupal de alumnos
  - 'workshop'    → Taller con invitado o temática especial
  - 'masterclass' → Clase magistral con artista/docente externo
  - 'external'    → Evento externo que ocupa sala (recital, grabación, etc.)
  - 'other'       → Cualquier otro evento
"""

from datetime import date, time
from sqlalchemy import String, Text, Integer, Date, Time, ForeignKey, Table, Column, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .organization import Organization
    from .room import Room
    from .teacher import Teacher
    from .student import Student


# ── Tablas de asociación M2M ──────────────────────────────────────────────────

event_teachers = Table(
    "event_teachers",
    Base.metadata,
    Column(
        "event_id",
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
        comment="FK al evento"
    ),
    Column(
        "teacher_id",
        Integer,
        ForeignKey("teachers.id", ondelete="CASCADE"),
        primary_key=True,
        comment="FK al profesor titular"
    ),
)

event_students = Table(
    "event_students",
    Base.metadata,
    Column(
        "event_id",
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
        comment="FK al evento"
    ),
    Column(
        "student_id",
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        primary_key=True,
        comment="FK al alumno participante"
    ),
)


# ── Tipos válidos de evento ───────────────────────────────────────────────────

EVENT_TYPES = ["rehearsal", "workshop", "masterclass", "external", "other"]


# ── Modelo principal ──────────────────────────────────────────────────────────

class Event(Base, TimestampMixin):
    """
    Evento institucional.

    Atributos:
        id:             Identificador único
        organization_id: FK a la organización (tenant)
        room_id:        FK a la sala (nullable — sin sala si es externo o virtual)
        title:          Título del evento
        description:    Descripción opcional
        event_type:     Tipo: rehearsal | workshop | masterclass | external | other
        date:           Fecha específica del evento
        time_start:     Hora de inicio
        duration:       Duración en minutos
        guest_name:     Nombre del invitado externo (nullable)
        guest_email:    Email del invitado externo para Google Calendar (nullable)
        notes:          Notas internas del organizador (nullable)
        created_by_id:  FK al teacher que creó el evento (nullable on delete)

    Relaciones:
        organization:   Organización dueña del evento
        room:           Sala asignada (opcional)
        created_by:     Teacher que creó el evento
        teachers:       Profesores titulares (M2M via event_teachers)
        students:       Alumnos participantes (M2M via event_students)

    Ejemplo de uso:
        event = Event(
            organization_id=1,
            room_id=3,
            title="Ensayo de fin de año",
            event_type="rehearsal",
            date=date(2026, 11, 28),
            time_start=time(17, 0),
            duration=90,
            created_by_id=1,
        )
    """
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_organization_date", "organization_id", "date"),
        Index("ix_events_room_date", "room_id", "date"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="Identificador único del evento"
    )

    organization_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Organización a la que pertenece el evento"
    )

    room_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("rooms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Sala asignada al evento (nullable — puede no tener sala)"
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Título descriptivo del evento"
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Descripción detallada del evento"
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="other",
        server_default="other",
        comment="Tipo de evento: rehearsal | workshop | masterclass | external | other"
    )

    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Fecha específica del evento"
    )

    time_start: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        comment="Hora de inicio del evento"
    )

    duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Duración del evento en minutos"
    )

    guest_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Nombre del invitado externo (no es teacher de la institución)"
    )

    guest_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Email del invitado externo para Google Calendar"
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notas internas del organizador"
    )

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Teacher que creó el evento (SET NULL si se elimina el teacher)"
    )

    # ── Relaciones ────────────────────────────────────────────────────────────

    organization: Mapped["Organization"] = relationship(
        back_populates="events",
        lazy="noload"
    )

    room: Mapped["Room | None"] = relationship(
        back_populates="events",
        lazy="selectin"
    )

    created_by: Mapped["Teacher | None"] = relationship(
        foreign_keys=[created_by_id],
        back_populates="created_events",
        lazy="selectin"
    )

    teachers: Mapped[List["Teacher"]] = relationship(
        secondary=event_teachers,
        back_populates="events",
        lazy="selectin"
    )

    students: Mapped[List["Student"]] = relationship(
        secondary=event_students,
        back_populates="events",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Event(id={self.id}, title='{self.title}', "
            f"type='{self.event_type}', date={self.date})>"
        )
