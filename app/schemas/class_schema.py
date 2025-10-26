"""
Schemas Pydantic para Class (Clase Específica)

CONCEPTO:
Una Class es una CLASE CONCRETA en una fecha y hora específica.
Ejemplo: "Martes 21 de enero 2025 a las 16:00"

DIFERENCIA CON SCHEDULE:
- Schedule: "Todos los martes a las 16:00" (template recurrente)
- Class: "Martes 21-enero-2025 a las 16:00" (fecha específica)

ORIGEN:
- Se GENERAN automáticamente desde Schedule (job mensual)
- O se CREAN manualmente (ej: clase de recuperación en horario especial)

ENUMS:
- status: scheduled, completed, cancelled, rescheduled
- type: regular (generada desde schedule), recovery (recuperación)
- format: individual (1 alumno), group (varios alumnos)
"""
from typing import Optional
from datetime import date, datetime, time
from pydantic import BaseModel, Field, ConfigDict

# Importar enums desde los modelos
from app.models.class_model import ClassStatus, ClassType, ClassFormat
from app.models.attendance import AttendanceStatus


# ========================================
# NESTED SCHEMAS (para relaciones)
# ========================================

class StudentNested(BaseModel):
    """Schema simplificado de Student para relaciones anidadas"""
    id: int
    name: str
    phone: str | None = None
    email: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EnrollmentNested(BaseModel):
    """Schema simplificado de Enrollment para relaciones anidadas"""
    id: int
    student_id: int
    instrument_id: int
    student: StudentNested | None = None

    model_config = ConfigDict(from_attributes=True)


class AttendanceNested(BaseModel):
    """Schema simplificado de Attendance para relaciones anidadas"""
    id: int
    status: AttendanceStatus
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ClassBase(BaseModel):
    """
    Campos comunes de una clase específica.
    
    - enrollment_id: a qué inscripción pertenece
    - date: fecha específica de la clase (ej: 2025-01-21)
    - time: hora específica (ej: 16:00)
    - duration: duración en minutos (por defecto 45)
    - status: estado de la clase (scheduled, completed, cancelled, rescheduled)
    - type: tipo (regular desde schedule, o recovery manual)
    - format: individual (1 alumno) o group (varios alumnos)
    """
    enrollment_id: int = Field(..., gt=0)
    date: date
    time: time
    duration: int = Field(default=45, gt=0, le=240)  # max 4 horas
    status: ClassStatus = ClassStatus.SCHEDULED
    type: ClassType = ClassType.REGULAR
    format: ClassFormat = ClassFormat.INDIVIDUAL
    

class ClassCreate(ClassBase):
    """
    Para CREAR una clase (POST /classes)
    
    - teacher_id: se puede obtener del JWT, pero lo incluimos por flexibilidad
    - schedule_id: OPCIONAL
      · Si viene desde Schedule (auto-generada) → tiene schedule_id
      · Si es manual (recuperación especial) → schedule_id = None
    
    Ejemplo clase regular auto-generada:
    {
        "enrollment_id": 5,
        "teacher_id": 1,
        "schedule_id": 3,
        "date": "2025-01-21",
        "time": "16:00:00",
        "duration": 45,
        "status": "scheduled",
        "type": "regular",
        "format": "individual"
    }
    
    Ejemplo clase de recuperación manual:
    {
        "enrollment_id": 5,
        "teacher_id": 1,
        "schedule_id": null,
        "date": "2025-01-25",
        "time": "18:00:00",
        "duration": 45,
        "type": "recovery",
        "format": "individual"
    }
    """
    teacher_id: int = Field(..., gt=0)
    schedule_id: int | None = Field(None, gt=0)


class ClassUpdate(BaseModel):
    """
    Para ACTUALIZAR una clase (PATCH /classes/{id})
    
    Casos de uso:
    - Cambiar status (scheduled → completed al finalizar la clase)
    - Cambiar status (scheduled → cancelled si se cancela)
    - Reprogramar: cambiar fecha/hora y marcar status=rescheduled
    - Cambiar formato (individual → group si se une otro alumno)
    
    IMPORTANTE:
    - NO se debe cambiar enrollment_id (sería otra clase diferente)
    - schedule_id tampoco se cambia (es referencia histórica)
    """
    date: Optional[date]  = None
    time: Optional[time] = None
    duration: int | None = Field(None, gt=0, le=240)
    status: ClassStatus | None = None
    type: ClassType | None = None
    format: ClassFormat | None = None


class ClassResponse(ClassBase):
    """
    Para RESPUESTAS (GET)

    Incluye todos los campos de la BD:
    - id: identificador único
    - teacher_id: a qué profesor pertenece
    - schedule_id: de qué schedule se generó (None si es manual)
    - sync_id: para sincronización móvil
    - timestamps: created_at y updated_at
    - enrollment: relación anidada con enrollment y student
    - attendance: relación anidada con attendance (si existe)
    """
    id: int
    teacher_id: int
    schedule_id: int | None = None
    sync_id: str | None = None
    created_at: datetime
    updated_at: datetime

    # Relaciones anidadas
    enrollment: EnrollmentNested | None = None
    attendance: AttendanceNested | None = None

    # Permite leer desde objetos SQLAlchemy
    model_config = ConfigDict(from_attributes=True)