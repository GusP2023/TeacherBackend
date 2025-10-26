"""
Modelo Enrollment - Representa la inscripción de un alumno a un instrumento.

Este es el modelo CENTRAL del sistema. Reemplaza la lógica anterior donde
student tenía instrument/level/status directamente.

Este modelo almacena:
- Relación Student ↔ Instrument (muchos a muchos a través de Enrollment)
- Estado de la inscripción (activo, suspendido, retirado)
- Progreso del alumno (nivel)
- Créditos de recuperación
- Fechas importantes (inscripción, suspensión, retiro)

Ventajas de este diseño:
- Un alumno puede estudiar múltiples instrumentos
- Cada inscripción tiene su propio estado/nivel/créditos
- Histórico completo por instrumento
- No se pierde información si un alumno cambia de instrumento

Relaciones:
- N:1 con Student (muchas inscripciones pertenecen a un alumno)
- N:1 con Instrument (muchas inscripciones pertenecen a un instrumento)
- N:1 con Teacher (muchas inscripciones pertenecen a un profesor)
- 1:N con Schedule (una inscripción tiene múltiples horarios)
- 1:N con Class (una inscripción tiene múltiples clases)

Estados posibles:
- active: Inscripción activa, alumno tomando clases normalmente
- suspended: Suspendido temporalmente (ej: vacaciones)
- withdrawn: Retirado definitivamente de este instrumento
"""

from datetime import date
from sqlalchemy import String, Integer, Date, Enum as SQLEnum, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING
import enum

from .base import Base, TimestampMixin
from .class_model import ClassFormat  # Import directo para usar en Enrollment

# Evita imports circulares
if TYPE_CHECKING:
    from .student import Student
    from .teacher import Teacher
    from .instrument import Instrument
    from .schedule import Schedule
    from .class_model import Class


class EnrollmentStatus(str, enum.Enum):
    """
    Estado de la inscripción en el sistema.
    
    - ACTIVE: Inscripción activa, alumno tomando clases
    - SUSPENDED: Suspendido temporalmente (puede volver)
    - WITHDRAWN: Retirado definitivamente de este instrumento
    """
    ACTIVE = "active"
    SUSPENDED = "suspended"
    WITHDRAWN = "withdrawn"


class EnrollmentLevel(str, enum.Enum):
    """
    Nivel del alumno en su instrumento.
    
    Sistema de niveles:
    - Elemental: Nivel inicial/principiante
    - Nivel1 a Nivel8: Progresión de aprendizaje
    - NULL: Sin nivel asignado aún
    """
    ELEMENTAL = "Elemental"
    NIVEL1 = "Nivel1"
    NIVEL2 = "Nivel2"
    NIVEL3 = "Nivel3"
    NIVEL4 = "Nivel4"
    NIVEL5 = "Nivel5"
    NIVEL6 = "Nivel6"
    NIVEL7 = "Nivel7"
    NIVEL8 = "Nivel8"


class Enrollment(Base, TimestampMixin):
    """
    Modelo de Inscripción (Student + Instrument).
    
    Este modelo representa la inscripción de UN alumno a UN instrumento específico.
    Es la tabla intermedia que permite que un alumno estudie múltiples instrumentos.
    
    Atributos principales:
        id: Identificador único de la inscripción
        student_id: FK al alumno inscrito
        instrument_id: FK al instrumento que estudia
        teacher_id: FK al profesor que gestiona (evita inconsistencias)
        status: Estado actual (active, suspended, withdrawn)
        level: Nivel de aprendizaje (puede ser NULL)
        
    Fechas importantes:
        enrolled_date: Fecha de inscripción a este instrumento
        suspended_until: Fecha hasta cuándo está suspendido (NULL si no aplica)
        withdrawn_date: Fecha en que se retiró (NULL si no aplica)
        
    Sistema de créditos:
        credits: Créditos de recuperación disponibles
                 - Se suma +1 cuando marca "licencia" en una clase
                 - Se resta -1 cuando agenda una recuperación
                 - CONSTRAINT: No puede ser negativo
                 
    Futuro:
        sync_id: ID del sistema principal (NULL si fue creado por profesor)
                 Permite sincronizar con sistema centralizado futuro
                 
    Ejemplo de uso:
        # María estudia Piano
        enrollment1 = Enrollment(
            student_id=1,
            instrument_id=1,  # Piano
            teacher_id=1,
            status=EnrollmentStatus.ACTIVE,
            level=EnrollmentLevel.NIVEL3,
            enrolled_date=date.today(),
            credits=0
        )
        
        # María también estudia Guitarra (misma alumna, otro instrumento)
        enrollment2 = Enrollment(
            student_id=1,
            instrument_id=2,  # Guitarra
            teacher_id=1,
            status=EnrollmentStatus.ACTIVE,
            level=EnrollmentLevel.ELEMENTAL,
            enrolled_date=date.today(),
            credits=0
        )
    """
    __tablename__ = "enrollments"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único de la inscripción"
    )
    
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="ID del alumno inscrito"
    )
    
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), 
        nullable=False, 
        index=True,
        comment="ID del instrumento que estudia"
    )
    
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="ID del profesor que gestiona esta inscripción"
    )
    
    status: Mapped[EnrollmentStatus] = mapped_column(
        SQLEnum(EnrollmentStatus, native_enum=False),
        default=EnrollmentStatus.ACTIVE,
        nullable=False,
        index=True,
        comment="Estado de la inscripción: activo, suspendido o retirado"
    )
    
    level: Mapped[EnrollmentLevel | None] = mapped_column(
        SQLEnum(EnrollmentLevel, native_enum=False),
        nullable=True,
        comment="Nivel de aprendizaje del alumno en este instrumento"
    )
    
    # ========================================
    # FECHAS
    # ========================================
    
    enrolled_date: Mapped[date] = mapped_column(
        Date, 
        nullable=False,
        comment="Fecha en que se inscribió a este instrumento"
    )
    
    suspended_until: Mapped[date | None] = mapped_column(
        Date, 
        nullable=True,
        comment="Fecha hasta cuándo está suspendido (NULL si no aplica)"
    )
    
    withdrawn_date: Mapped[date | None] = mapped_column(
        Date, 
        nullable=True,
        comment="Fecha en que se retiró de este instrumento (NULL si sigue activo)"
    )
    
    # ========================================
    # SISTEMA DE CRÉDITOS
    # ========================================
    
    credits: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Créditos de recuperación disponibles (no puede ser negativo)"
    )

    # ========================================
    # FORMATO DE CLASE
    # ========================================

    format: Mapped[ClassFormat] = mapped_column(
        SQLEnum(ClassFormat, native_enum=False),
        default=ClassFormat.INDIVIDUAL,
        nullable=False,
        comment="Formato de las clases: individual o group"
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
    
    student: Mapped["Student"] = relationship(
        back_populates="enrollments", 
        lazy="selectin"
    )
    
    instrument: Mapped["Instrument"] = relationship(
        back_populates="enrollments", 
        lazy="selectin"
    )
    
    teacher: Mapped["Teacher"] = relationship(
        back_populates="enrollments", 
        lazy="selectin"
    )
    
    schedules: Mapped[List["Schedule"]] = relationship(
        back_populates="enrollment",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    
    classes: Mapped[List["Class"]] = relationship(
        back_populates="enrollment",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # ========================================
    # CONSTRAINTS
    # ========================================
    
    __table_args__ = (
        CheckConstraint(
            'credits >= 0', 
            name='check_enrollment_credits_non_negative'
        ),
        UniqueConstraint(
            'student_id', 
            'instrument_id', 
            name='uq_student_instrument'
        ),
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Enrollment(id={self.id}, student_id={self.student_id}, instrument_id={self.instrument_id}, status='{self.status}')>"