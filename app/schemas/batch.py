from typing import Literal, Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.student import StudentCreate, StudentUpdate
from app.schemas.enrollment import EnrollmentCreate, EnrollmentUpdate
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.schemas.class_schema import ClassCreate, ClassUpdate
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate
from app.models.class_model import ClassType

# Definir tipos de operaciones soportadas
OperationType = Literal[
    "CREATE_STUDENT", "UPDATE_STUDENT", "DELETE_STUDENT",
    "CREATE_ENROLLMENT", "UPDATE_ENROLLMENT", "DELETE_ENROLLMENT",
    "CREATE_SCHEDULE", "UPDATE_SCHEDULE", "DELETE_SCHEDULE",
    "CREATE_CLASS", "UPDATE_CLASS", "DELETE_CLASS",
    "CREATE_RECOVERY_CLASS", "DELETE_RECOVERY_CLASS", "CANCEL_CLASS",
    "CREATE_ATTENDANCE", "UPDATE_ATTENDANCE", "DELETE_ATTENDANCE",
    "ADD_PARTIAL_RECOVERY", "REMOVE_PARTIAL_RECOVERY", "CLEAR_PARTIAL_RECOVERIES"
]

class ClassRecoveryCreate(ClassCreate):
    """
    Schema específico para crear clases de recuperación.
    Hereda de ClassCreate pero fuerza el tipo a RECOVERY si no se especifica.
    """
    type: ClassType = ClassType.RECOVERY

class BatchOperation(BaseModel):
    """
    Representa una única operación dentro del lote.
    """
    temp_id: int | None = Field(None, description="ID temporal (negativo) usado para referencias dentro del batch")
    type: OperationType
    payload: Dict[str, Any] = Field(default_factory=dict, description="Datos para la operación (Create/Update schemas)")
    
    # Para updates/deletes que referencian un ID real o temporal
    id: int | None = Field(None, description="ID del objeto a modificar/eliminar (puede ser real o temp_id)")

class BatchRequest(BaseModel):
    """
    Request con lista de operaciones a procesar en orden.
    """
    operations: List[BatchOperation] = Field(..., min_length=1, max_length=50)

class BatchOperationResult(BaseModel):
    """
    Resultado de una operación individual.
    """
    temp_id: int | None = None
    real_id: int | None = None
    type: OperationType
    status: Literal["success", "error"]
    error: str | None = None

class BatchResponse(BaseModel):
    """
    Respuesta final del endpoint batch.
    """
    results: List[BatchOperationResult]
    processed_count: int
    success: bool
    message: str
