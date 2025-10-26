"""
Modelo Attendance - Representa la asistencia de un alumno a una clase.

Este modelo almacena:
- Estado de asistencia (presente, ausente, licencia)
- Notas opcionales sobre la asistencia
- Relación 1:1 con Class

Lógica de negocio:
- Cuando se marca "license" → se suma +1 crédito al enrollment
- Cuando se usa crédito en recovery → se resta -1 crédito al enrollment
- Solo se cobran clases con status "present" o "absent"
- NO se cobran clases con status "license" ni clases canceladas

Relaciones:
- 1:1 con Class (cada clase tiene máximo un registro de asistencia)

Estados de asistencia:
- present: Alumno asistió a la clase
- absent: Alumno faltó a la clase (sin justificación)
- license: Alumno pidió licencia (justificada, genera crédito)
"""

from sqlalchemy import String, Integer, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .class_model import Class


class AttendanceStatus(str, enum.Enum):
    """
    Estado de asistencia de un alumno a una clase.
    
    - PRESENT: Asistió a la clase → SE COBRA
    - ABSENT: Faltó sin justificación → SE COBRA
    - LICENSE: Licencia justificada → NO SE COBRA, +1 CRÉDITO
    """
    PRESENT = "present"
    ABSENT = "absent"
    LICENSE = "license"


class Attendance(Base, TimestampMixin):
    """
    Modelo de Asistencia.
    
    Registra si un alumno asistió, faltó o pidió licencia en una clase.
    Relación 1:1 con Class (cada clase tiene máximo un registro de asistencia).
    
    Atributos principales:
        id: Identificador único del registro de asistencia
        class_id: FK a la clase (UNIQUE, relación 1:1)
        status: Estado de asistencia (present, absent, license)
        notes: Notas opcionales sobre la asistencia
        
    Lógica de créditos:
        - status=LICENSE → +1 crédito al enrollment (clase justificada)
        - status=PRESENT/ABSENT en recovery → -1 crédito (usó recuperación)
        
    Lógica de cobro:
        Se cobran clases con:
        ✅ attendance.status = PRESENT
        ✅ attendance.status = ABSENT
        
        NO se cobran clases con:
        ❌ attendance.status = LICENSE
        ❌ class.status = CANCELLED
        ❌ Sin attendance marcado
        
    Futuro:
        sync_id: ID del sistema principal (NULL si fue creado localmente)
        
    Ejemplo de uso:
        # Alumno asistió
        attendance1 = Attendance(
            class_id=1,
            status=AttendanceStatus.PRESENT,
            notes="Excelente progreso en escalas"
        )
        
        # Alumno faltó sin aviso
        attendance2 = Attendance(
            class_id=2,
            status=AttendanceStatus.ABSENT,
            notes=None
        )
        
        # Alumno pidió licencia (genera +1 crédito)
        attendance3 = Attendance(
            class_id=3,
            status=AttendanceStatus.LICENSE,
            notes="Viaje familiar"
        )
    """
    __tablename__ = "attendances"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único del registro de asistencia"
    )
    
    class_id: Mapped[int] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"),
        unique=True,  # Relación 1:1 con Class
        nullable=False,
        index=True,
        comment="ID de la clase (relación 1:1)"
    )
    
    status: Mapped[AttendanceStatus] = mapped_column(
        SQLEnum(AttendanceStatus, native_enum=False),
        nullable=False,
        index=True,
        comment="Estado: present (asistió), absent (faltó), license (licencia)"
    )
    
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notas opcionales sobre la asistencia o progreso del alumno"
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
    
    class_: Mapped["Class"] = relationship(
        back_populates="attendance",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Attendance(id={self.id}, class_id={self.class_id}, status='{self.status}')>"