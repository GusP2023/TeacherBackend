"""
Modelo Schedule - Representa el horario recurrente de un alumno.

Este modelo es un TEMPLATE (patrón) que define:
- Qué día de la semana tiene clase el alumno (ej: Martes)
- A qué hora (ej: 16:00)
- Duración de la clase (ej: 45 minutos)
- Vigencia del horario (desde cuándo hasta cuándo aplica)

NO es una clase específica en una fecha concreta.
Las clases concretas (Class) se generan automáticamente desde este template.

Ejemplo:
    Schedule: "Martes a las 16:00, desde 15-enero-2025"
    Genera →  Class: 21-enero-2025 16:00
             Class: 28-enero-2025 16:00
             Class: 4-febrero-2025 16:00
             ... (automáticamente mes a mes)

Relaciones:
- N:1 con Enrollment (muchos horarios pertenecen a una inscripción)
- N:1 con Teacher (muchos horarios pertenecen a un profesor)
- 1:N con Class (un horario genera múltiples clases concretas)

Cambio de horario:
    Si un alumno cambia de horario (ej: de Martes 16:00 a Jueves 18:00):
    - Schedule anterior: valid_until = fecha_cambio
    - Schedule nuevo: valid_from = fecha_cambio
    Así se mantiene el histórico completo.
"""

from datetime import date, time
from sqlalchemy import Integer, Date, Time, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .enrollment import Enrollment
    from .teacher import Teacher
    from .class_model import Class


class DayOfWeek(str, enum.Enum):
    """
    Días de la semana.
    
    Usados para definir en qué día(s) tiene clase el alumno.
    """
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class Schedule(Base, TimestampMixin):
    """
    Modelo de Horario Recurrente (Template).
    
    Define el patrón de recurrencia para generar clases automáticamente.
    NO es una clase específica, sino una regla de cuándo tiene clase el alumno.
    
    Atributos principales:
        id: Identificador único del horario
        enrollment_id: FK a la inscripción (alumno + instrumento)
        teacher_id: FK al profesor (redundante pero útil para queries)
        day: Día de la semana (MONDAY, TUESDAY, etc)
        time: Hora de inicio (ej: 16:00)
        duration: Duración en minutos (por defecto 45)
        
    Vigencia del horario:
        valid_from: Desde cuándo aplica este horario
        valid_until: Hasta cuándo aplica (NULL = indefinido)
        
        Ejemplo de cambio de horario:
            Horario 1: valid_from=15-ene, valid_until=28-feb (cerrado)
            Horario 2: valid_from=1-mar, valid_until=NULL (nuevo vigente)
            
    Estado:
        active: Permite desactivar horario sin eliminarlo (soft-delete)
        
    Generación de clases:
        - Job automático revisa schedules activos y vigentes
        - Genera Classes para el próximo mes si no existen
        - Solo genera si enrollment.status == ACTIVE
        
    Futuro:
        sync_id: ID del sistema principal (NULL si fue creado localmente)
        
    Ejemplo de uso:
        # María estudia Canto - Martes y Jueves 16:00
        schedule1 = Schedule(
            enrollment_id=1,  # María - Canto
            teacher_id=1,
            day=DayOfWeek.TUESDAY,
            time=time(16, 0),
            duration=45,
            valid_from=date(2025, 1, 15),
            valid_until=None,  # Vigente indefinidamente
            active=True
        )
        
        schedule2 = Schedule(
            enrollment_id=1,  # María - Canto
            teacher_id=1,
            day=DayOfWeek.THURSDAY,
            time=time(16, 0),
            duration=45,
            valid_from=date(2025, 1, 15),
            valid_until=None,
            active=True
        )
    """
    __tablename__ = "schedules"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único del horario"
    )
    
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="ID de la inscripción (alumno + instrumento)"
    )
    
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="ID del profesor (redundante pero útil para queries)"
    )
    
    # ========================================
    # DEFINICIÓN DEL HORARIO
    # ========================================
    
    day: Mapped[DayOfWeek] = mapped_column(
        SQLEnum(DayOfWeek, native_enum=False),
        nullable=False,
        index=True,
        comment="Día de la semana (monday, tuesday, etc)"
    )
    
    time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        comment="Hora de inicio de la clase (ej: 16:00)"
    )
    
    duration: Mapped[int] = mapped_column(
        Integer,
        default=45,
        nullable=False,
        comment="Duración de la clase en minutos (por defecto 45)"
    )
    
    # ========================================
    # VIGENCIA DEL HORARIO
    # ========================================
    
    valid_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Desde cuándo aplica este horario"
    )
    
    valid_until: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
        comment="Hasta cuándo aplica este horario (NULL = indefinido)"
    )
    
    # ========================================
    # ESTADO
    # ========================================
    
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Indica si el horario está activo (soft-delete)"
    )
    
    # ========================================
    # SINCRONIZACIÓN FUTURA
    # ========================================
    
    sync_id: Mapped[int | None] = mapped_column(
        Integer,
        unique=True,
        nullable=True,
        comment="ID del sistema principal (futuro). NULL si creado localmente"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    enrollment: Mapped["Enrollment"] = relationship(
        back_populates="schedules",
        lazy="selectin"
    )
    
    teacher: Mapped["Teacher"] = relationship(
        back_populates="schedules",
        lazy="selectin"
    )
    
    classes: Mapped[List["Class"]] = relationship(
        back_populates="schedule",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Schedule(id={self.id}, day='{self.day}', time={self.time}, enrollment_id={self.enrollment_id})>"