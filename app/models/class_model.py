"""
Modelo Class - Representa una clase específica en una fecha concreta.

Este modelo almacena instancias CONCRETAS de clases:
- Una clase específica el día 21-enero-2025 a las 16:00
- NO es un template recurrente (eso es Schedule)

Las clases se generan automáticamente desde los Schedule mediante un job:
    Schedule "Martes 16:00" → genera Classes todos los martes del mes

Este modelo almacena:
- Fecha y hora específica de la clase
- Estado (agendada, completada, cancelada, reprogramada)
- Tipo (regular o recuperación)
- Formato (individual o grupal, para cálculo de tarifa)
- Asistencia (relación 1:1 con Attendance)

Relaciones:
- N:1 con Schedule (muchas clases vienen del mismo horario template)
- N:1 con Enrollment (muchas clases pertenecen a una inscripción)
- N:1 con Teacher (muchas clases pertenecen a un profesor)
- 1:1 con Attendance (cada clase tiene un registro de asistencia)

Estados del ciclo de vida:
    scheduled → completed (cuando se marca asistencia)
    scheduled → cancelled (si se cancela antes)
    scheduled → rescheduled (si se reprograma)
    
Tipos de clase:
    regular: Clase normal del horario
    recovery: Clase de recuperación (usa crédito)
    
Formatos:
    individual: 1 alumno → cobra tariff_individual
    group: N alumnos → cobra tariff_group × N
"""

from datetime import date, time
from sqlalchemy import Integer, Date, Time, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .schedule import Schedule
    from .enrollment import Enrollment
    from .teacher import Teacher
    from .attendance import Attendance


class ClassStatus(str, enum.Enum):
    """
    Estado de la clase.
    
    - SCHEDULED: Agendada, aún no ocurre
    - COMPLETED: Completada (tiene asistencia marcada)
    - CANCELLED: Cancelada (por suspensión, retiro, etc)
    - RESCHEDULED: Reprogramada a otra fecha/hora
    """
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class ClassType(str, enum.Enum):
    """
    Tipo de clase.
    
    - REGULAR: Clase normal del horario recurrente
    - RECOVERY: Clase de recuperación (usa crédito del alumno)
    """
    REGULAR = "regular"
    RECOVERY = "recovery"


class ClassFormat(str, enum.Enum):
    """
    Formato de la clase (para cálculo de tarifa).
    
    - INDIVIDUAL: 1 alumno → cobra tariff_individual
    - GROUP: N alumnos → cobra tariff_group × cantidad_alumnos
    """
    INDIVIDUAL = "individual"
    GROUP = "group"


class Class(Base, TimestampMixin):
    """
    Modelo de Clase (instancia concreta).
    
    Representa una clase específica en una fecha y hora determinada.
    Se genera automáticamente desde Schedule mediante un job mensual.
    
    Atributos principales:
        id: Identificador único de la clase
        schedule_id: FK al horario template que generó esta clase
        enrollment_id: FK a la inscripción (redundante pero rápido)
        teacher_id: FK al profesor (redundante pero rápido)
        date: Fecha específica de la clase (ej: 2025-01-21)
        time: Hora de inicio (heredado de Schedule)
        duration: Duración en minutos (heredado de Schedule)
        
    Estado y tipo:
        status: Estado actual (scheduled, completed, cancelled, rescheduled)
        type: Tipo de clase (regular o recovery)
        format: Formato (individual o group, para calcular tarifa)
        
    Generación automática:
        - Job revisa schedules activos y vigentes
        - Genera classes para el próximo mes si no existen
        - Copia time y duration desde Schedule
        - Marca como status=SCHEDULED por defecto
        
    Cancelación por suspensión/retiro:
        - Cuando enrollment.status cambia a SUSPENDED o WITHDRAWN
        - Todas las classes futuras se marcan como status=CANCELLED
        - No aparecen en calendario (filtro WHERE status != 'cancelled')
        
    Cálculo de ingresos:
        - Solo se cobran classes con status != CANCELLED
        - Solo se cobran classes con attendance marcado
        - Formato INDIVIDUAL: tariff_individual
        - Formato GROUP: tariff_group × cantidad_alumnos
        
    Futuro:
        sync_id: ID del sistema principal (NULL si fue creado localmente)
        
    Ejemplo de uso:
        # Clase regular generada automáticamente
        class1 = Class(
            schedule_id=1,  # Template "Martes 16:00"
            enrollment_id=1,  # María - Canto
            teacher_id=1,
            date=date(2025, 1, 21),  # Martes 21 de enero
            time=time(16, 0),
            duration=45,
            status=ClassStatus.SCHEDULED,
            type=ClassType.REGULAR,
            format=ClassFormat.INDIVIDUAL
        )
        
        # Clase de recuperación creada manualmente
        class2 = Class(
            schedule_id=None,  # No viene de template
            enrollment_id=1,
            teacher_id=1,
            date=date(2025, 1, 25),  # Viernes (día libre)
            time=time(17, 0),
            duration=45,
            status=ClassStatus.SCHEDULED,
            type=ClassType.RECOVERY,  # Es recuperación
            format=ClassFormat.INDIVIDUAL
        )
    """
    __tablename__ = "classes"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único de la clase"
    )
    
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedules.id", ondelete="SET NULL"),
        nullable=True,  # NULL si es recuperación manual
        index=True,
        comment="ID del horario template que generó esta clase (NULL si es recuperación)"
    )
    
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="ID de la inscripción (redundante pero rápido para queries)"
    )
    
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="ID del profesor (redundante pero rápido para queries)"
    )
    
    # ========================================
    # FECHA Y HORA ESPECÍFICA
    # ========================================
    
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Fecha específica de la clase (ej: 2025-01-21)"
    )
    
    time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
        comment="Hora de inicio (heredado de Schedule o manual)"
    )
    
    duration: Mapped[int] = mapped_column(
        Integer,
        default=45,
        nullable=False,
        comment="Duración en minutos (heredado de Schedule o manual)"
    )
    
    # ========================================
    # ESTADO Y TIPO
    # ========================================
    
    status: Mapped[ClassStatus] = mapped_column(
        SQLEnum(ClassStatus, native_enum=False),
        default=ClassStatus.SCHEDULED,
        nullable=False,
        index=True,
        comment="Estado: scheduled, completed, cancelled, rescheduled"
    )
    
    type: Mapped[ClassType] = mapped_column(
        SQLEnum(ClassType, native_enum=False),
        default=ClassType.REGULAR,
        nullable=False,
        index=True,
        comment="Tipo: regular (normal) o recovery (recuperación)"
    )
    
    format: Mapped[ClassFormat] = mapped_column(
        SQLEnum(ClassFormat, native_enum=False),
        default=ClassFormat.INDIVIDUAL,
        nullable=False,
        comment="Formato: individual (1 alumno) o group (N alumnos)"
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
    
    schedule: Mapped["Schedule"] = relationship(
        back_populates="classes",
        lazy="selectin"
    )
    
    enrollment: Mapped["Enrollment"] = relationship(
        back_populates="classes",
        lazy="selectin"
    )
    
    teacher: Mapped["Teacher"] = relationship(
        back_populates="classes",
        lazy="selectin"
    )
    
    attendance: Mapped["Attendance"] = relationship(
        back_populates="class_",
        uselist=False,  # Relación 1:1
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Class(id={self.id}, date={self.date}, time={self.time}, status='{self.status}', type='{self.type}')>"