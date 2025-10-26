"""
Schemas Pydantic para Schedule (Horario Recurrente)

CONCEPTO:
Un Schedule es un TEMPLATE de horario recurrente.
Ejemplo: "Todos los martes a las 16:00, 45 minutos"

Desde este template se GENERAN las clases (Class) automáticamente mes a mes.
- Si el alumno tiene "Martes 16:00", se crean clases cada martes del mes.
- Si se suspende el enrollment, las clases futuras se cancelan.
- Si se reactiva, se vuelven a generar.

IMPORTANTE:
- day: día de la semana (monday-sunday) NO una fecha específica
- time: hora (ej: 16:00) sin fecha
- valid_from/valid_until: período de vigencia del horario
"""
from typing import Optional
from datetime import date, datetime, time
from pydantic import BaseModel, Field, ConfigDict

# Importar enum desde los modelos
from app.models.schedule import DayOfWeek
from app.models.class_model import ClassFormat


class ScheduleBase(BaseModel):
    """
    Campos comunes del horario recurrente.
    
    - enrollment_id: a qué inscripción pertenece (alumno + instrumento)
    - day: día de la semana (lunes, martes, etc)
    - time: hora de inicio (ej: 16:00, 18:30)
    - duration: duración en minutos (por defecto 45)
    - valid_from: desde qué fecha es válido este horario
    - valid_until: hasta qué fecha (None = indefinido)
    """
    enrollment_id: int = Field(..., gt=0)
    day: DayOfWeek
    time: time  # Hora sin fecha (ej: 16:00:00)
    duration: int = Field(default=45, gt=0, le=240)  # le=240 → max 4 horas
    valid_from: date
    valid_until: date | None = None  # None = indefinido


class ScheduleCreate(ScheduleBase):
    """
    Para CREAR un horario (POST /schedules)
    
    - teacher_id: se puede obtener del JWT, pero lo incluimos por flexibilidad
    - active: por defecto True al crear
    
    Ejemplo de uso:
    {
        "enrollment_id": 5,
        "teacher_id": 1,
        "day": "tuesday",
        "time": "16:00:00",
        "duration": 45,
        "valid_from": "2025-01-15",
        "valid_until": null
    }
    """
    teacher_id: int = Field(..., gt=0)
    active: bool = True


class ScheduleUpdate(BaseModel):
    """
    Para ACTUALIZAR un horario (PATCH /schedules/{id})
    
    Casos de uso:
    - Cambiar día u hora (el alumno pidió cambio de horario)
    - Modificar duración (pasar de 45 a 60 minutos)
    - Establecer valid_until (el horario termina en cierta fecha)
    - Desactivar (active=False) sin eliminar
    
    NOTA: Si se cambia day/time, las clases futuras ya generadas
    NO se actualizan automáticamente. Se deben cancelar y regenerar.
    """
    day: DayOfWeek | None = None
    time: Optional[time] = None
    duration: int | None = Field(None, gt=0, le=240)
    valid_from: date | None = None
    valid_until: date | None = None
    active: bool | None = None


# Schema anidado para Enrollment (solo campos necesarios)
class EnrollmentNested(BaseModel):
    """Schema simplificado de Enrollment para relaciones anidadas"""
    id: int
    format: ClassFormat

    model_config = ConfigDict(from_attributes=True)


class ScheduleResponse(ScheduleBase):
    """
    Para RESPUESTAS (GET)

    Incluye todos los campos de la BD:
    - id: identificador único
    - teacher_id: a qué profesor pertenece
    - active: si está activo o desactivado
    - sync_id: para sincronización móvil
    - timestamps: created_at y updated_at
    - enrollment: relación con el enrollment (para validaciones de formato)
    """
    id: int
    teacher_id: int
    active: bool
    sync_id: str | None = None
    created_at: datetime
    updated_at: datetime

    # Relación anidada
    enrollment: EnrollmentNested | None = None

    # Permite leer desde objetos SQLAlchemy
    model_config = ConfigDict(from_attributes=True)