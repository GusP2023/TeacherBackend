"""
Modelo TeacherAvailability - Disponibilidad horaria de profesores.

Este modelo almacena los bloques de disponibilidad de cada profesor:
- Día de la semana (monday, tuesday, etc.)
- Hora inicio y fin
- Estado activo/inactivo

Relaciones:
- N:1 con Teacher (muchas disponibilidades pertenecen a un profesor)
"""

from datetime import time
from sqlalchemy import ForeignKey, String, Boolean, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from .base import Base, TimestampMixin

# Evita imports circulares en tiempo de ejecución
if TYPE_CHECKING:
    from .teacher import Teacher


class TeacherAvailability(Base, TimestampMixin):
    """
    Modelo de Disponibilidad de Profesor.
    
    Atributos:
        id: Identificador único
        teacher_id: FK al profesor
        day: Día de la semana (monday, tuesday, etc.)
        time_start: Hora de inicio del bloque
        time_end: Hora de fin del bloque
        active: Indica si el bloque está activo
        
    Relaciones:
        teacher: Profesor al que pertenece esta disponibilidad
    """
    __tablename__ = "teacher_availability"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK al profesor"
    )
    
    day: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Día de la semana: monday, tuesday, etc."
    )
    
    time_start: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        comment="Hora de inicio del bloque de disponibilidad"
    )
    
    time_end: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        comment="Hora de fin del bloque de disponibilidad"
    )
    
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Indica si el bloque está activo"
    )

    teacher: Mapped["Teacher"] = relationship(
        "Teacher",
        back_populates="availability",
        lazy="noload"
    )

    @property
    def teacher_name(self) -> str:
        return self.teacher.name if self.teacher else ""

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<TeacherAvailability(id={self.id}, teacher_id={self.teacher_id}, day='{self.day}', time_start='{self.time_start}', time_end='{self.time_end}')>"
