"""
Schemas Pydantic para Enrollment (Inscripción)

CONCEPTO:
Un Enrollment es la INSCRIPCIÓN de un alumno a un instrumento específico.
- Un alumno puede tener MÚLTIPLES enrollments (ej: Piano + Canto)
- Pero solo UNO por instrumento (constraint: UNIQUE(student_id, instrument_id))

IMPORTANTE:
- status: active, suspended, withdrawn (activo, suspendido, retirado)
- level: Elemental, Nivel1-8 (progresión del alumno)
- credits: créditos de recuperación (license da +1, usar recuperación -1)
"""
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List

# Importar enums desde los modelos
from app.models.enrollment import EnrollmentStatus, EnrollmentLevel
from app.models.class_model import ClassFormat


class EnrollmentBase(BaseModel):
    """
    Campos comunes de la inscripción.

    - student_id: a qué alumno pertenece
    - instrument_id: qué instrumento está estudiando
    - level: nivel actual del alumno (Elemental hasta Nivel8)
    - credits: créditos de recuperación disponibles (default 0)
    - format: formato de las clases (individual o group)
    """
    student_id: int = Field(..., gt=0)
    instrument_id: int = Field(..., gt=0)
    level: EnrollmentLevel = EnrollmentLevel.ELEMENTAL
    credits: int = Field(default=0, ge=0)  # ge=0 → greater or equal (>=0)
    format: ClassFormat = ClassFormat.INDIVIDUAL  # Formato de clases por defecto
    manual_credit_dates: List[str] = Field(
        default_factory=list,
        description="Array de fechas (YYYY-MM-DD) de créditos agregados manualmente"
    )


class EnrollmentCreate(EnrollmentBase):
    """
    Para CREAR una inscripción (POST /enrollments)

    - teacher_id: opcional, se asigna automáticamente desde el JWT en el endpoint
    - status: por defecto será ACTIVE al crear
    - enrolled_date: fecha de inscripción (se puede pasar o usar fecha actual)
    """
    teacher_id: int | None = Field(None, gt=0)  # Opcional, se asigna desde el JWT
    status: EnrollmentStatus = EnrollmentStatus.ACTIVE
    enrolled_date: date | None = None  # Si no se envía, se usa fecha actual


class EnrollmentUpdate(BaseModel):
    """
    Para ACTUALIZAR una inscripción (PATCH /enrollments/{id})

    Casos de uso:
    - Cambiar status (active → suspended, suspended → active, active → withdrawn)
    - Actualizar level cuando el alumno progresa
    - Modificar credits cuando usa/gana recuperaciones
    - Establecer suspended_until cuando se suspende temporalmente
    - Marcar withdrawn_date cuando se retira definitivamente
    - Cambiar format (individual → group o viceversa)
    - Cambiar enrolled_date (fecha de inicio de clases)

    Todos opcionales para actualizar solo lo necesario.
    """
    status: EnrollmentStatus | None = None
    level: EnrollmentLevel | None = None
    credits: int | None = Field(None, ge=0)
    suspended_until: date | None = None  # Hasta qué fecha está suspendido
    withdrawn_date: date | None = None    # Fecha de retiro definitivo
    format: ClassFormat | None = None     # Cambiar formato de clases
    enrolled_date: date | None = None     # Cambiar fecha de inicio de clases
    manual_credit_dates: List[str] | None = Field(
        None,
        description="Array de fechas (YYYY-MM-DD) de créditos agregados manualmente"
    )


# ========================================
# SCHEMAS PARA SUSPENSIÓN/REACTIVACIÓN
# ========================================

class EnrollmentSuspendRequest(BaseModel):
    """
    Para SUSPENDER una inscripción (POST /enrollments/{id}/suspend)
    
    Acciones automáticas:
    - Cambia status → 'suspended'
    - Guarda suspended_at con la fecha actual
    - ELIMINA todas las clases futuras (scheduled)
    """
    reason: Optional[str] = Field(
        None, 
        max_length=255,
        description="Motivo de la suspensión (opcional)"
    )
    suspended_until: Optional[date] = Field(
        None,
        description="Fecha hasta cuándo está suspendido (opcional)"
    )


class EnrollmentReactivateRequest(BaseModel):
    """
    Para REACTIVAR una inscripción (POST /enrollments/{id}/reactivate)
    
    Flujo:
    1. Si use_previous_schedule=True → Valida disponibilidad del horario anterior
    2. Si use_previous_schedule=False → Se espera que se cree un nuevo schedule después
    3. Cambia status → 'active'
    4. Limpia campos de suspensión
    5. Genera clases desde HOY hasta fin del mes + 2 meses (si tiene schedules activos)
    """
    use_previous_schedule: bool = Field(
        True,
        description="Si True, intenta reactivar con el horario anterior"
    )


class EnrollmentSuspendResponse(BaseModel):
    """Respuesta después de suspender"""
    enrollment_id: int
    status: EnrollmentStatus
    suspended_at: date
    suspended_reason: Optional[str]
    classes_deleted: int = Field(
        ...,
        description="Cantidad de clases futuras eliminadas"
    )
    message: str


class EnrollmentReactivateResponse(BaseModel):
    """Respuesta después de reactivar"""
    enrollment_id: int
    status: EnrollmentStatus
    previous_schedule_available: bool
    classes_generated: int = Field(
        ...,
        description="Cantidad de clases generadas"
    )
    schedule_conflicts: list[dict] = Field(
        default_factory=list,
        description="Lista de conflictos si el horario anterior está ocupado"
    )
    message: str


class ScheduleAvailabilityCheck(BaseModel):
    """Para verificar disponibilidad de un horario"""
    day: str
    time: str
    is_available: bool
    conflict_with: Optional[str] = Field(
        None,
        description="Nombre del alumno que ocupa ese horario (si hay conflicto)"
    )


# ========================================
# RESPONSE PRINCIPAL
# ========================================

class EnrollmentResponse(EnrollmentBase):
    """
    Para RESPUESTAS (GET)

    Incluye todos los campos de la BD:
    - id: identificador único
    - teacher_id: a qué profesor pertenece
    - status: estado actual (active/suspended/withdrawn)
    - enrolled_date: cuándo se inscribió
    - suspended_at: cuándo se suspendió
    - suspended_until: si está suspendido, hasta cuándo
    - suspended_reason: motivo de la suspensión
    - withdrawn_date: si se retiró, cuándo fue
    - format: formato de las clases (individual o group)
    - sync_id: para sincronización móvil (opcional)
    - timestamps: created_at y updated_at
    """
    id: int
    teacher_id: int
    status: EnrollmentStatus
    enrolled_date: date
    suspended_at: Optional[date] = None
    suspended_until: Optional[date] = None
    suspended_reason: Optional[str] = None
    withdrawn_date: Optional[date] = None
    sync_id: str | None = None
    created_at: datetime
    updated_at: datetime

    # Permite leer desde objetos SQLAlchemy
    model_config = ConfigDict(from_attributes=True)
