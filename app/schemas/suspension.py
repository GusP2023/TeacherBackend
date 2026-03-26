from pydantic import BaseModel, Field, field_validator
from datetime import date
from typing import Optional, List


class SuspendEnrollmentRequest(BaseModel):
    """Request para suspender enrollment"""
    suspended_at: date = Field(
        ..., 
        description="Fecha desde la que se suspende (inclusive)"
    )
    suspended_until: Optional[date] = Field(
        None, 
        description="Fecha hasta la que se suspende (inclusive). NULL = indefinido"
    )
    reason: Optional[str] = Field(
        None, 
        max_length=255,
        description="Motivo de la suspensión"
    )


class ReactivateScheduleData(BaseModel):
    """Datos de un horario para reactivación"""
    day: str = Field(..., description="Día de la semana (monday-sunday)")
    time: str = Field(..., description="Hora en formato HH:MM o HH:MM:SS")
    duration: int = Field(45, description="Duración en minutos")
    end_date: Optional[date] = Field(None, description="Fecha final de vigencia (YYYY-MM-DD)")
    
    @field_validator('end_date', mode='before')
    @classmethod
    def parse_end_date(cls, v):
        """Convertir string a date si es necesario"""
        if v is None:
            return None
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            from datetime import datetime
            # Intentar parsear como YYYY-MM-DD
            try:
                return datetime.strptime(v, '%Y-%m-%d').date()
            except ValueError:
                # Intentar ISO format
                return date.fromisoformat(v)
        return v


class ReactivateEnrollmentRequest(BaseModel):
    """Request para reactivar enrollment"""
    reactivate_from: date = Field(
        ...,
        description="Fecha desde la que vuelve a clases"
    )
    schedules: List[ReactivateScheduleData] = Field(
        ...,
        description="Nuevos horarios del alumno"
    )
    confirm_delete_classes: bool = Field(
        False,
        description="Confirmar eliminación de clases regulares propias en conflicto"
    )


class ScheduleConflict(BaseModel):
    """Conflicto de horario"""
    date: date
    type: str  # 'regular' | 'recovery'
    student_id: int
    student_name: str


class ClassToDelete(BaseModel):
    """Clase que necesita ser eliminada para continuar"""
    class_id: int
    date: date
    day: str
    time: str


class ScheduleAvailabilityResponse(BaseModel):
    """Respuesta de disponibilidad de horario"""
    available: bool
    conflicts: List[ScheduleConflict] = []


class SuspensionHistoryResponse(BaseModel):
    """Respuesta de historial de suspensión"""
    id: int
    enrollment_id: int
    suspended_at: date
    suspended_until: Optional[date]
    reactivated_at: Optional[date]
    reason: Optional[str]
    created_at: str
    
    class Config:
        from_attributes = True
