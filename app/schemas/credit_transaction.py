"""
Schemas Pydantic para CreditTransaction (Transacción de Crédito)
"""

from datetime import datetime, date
from decimal import Decimal
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from typing import Optional, Literal

# Importar enums desde los modelos
from app.models.credit_transaction import CreditTransactionSource, CreditTransactionReferenceType


class CreditTransactionResponse(BaseModel):
    """
    Para RESPUESTAS (GET)

    Incluye todos los campos de la transacción:
    - id: identificador único
    - enrollment_id: a qué inscripción pertenece
    - amount: cantidad de créditos (+ para otorgar, - para consumir)
    - source_type: tipo de origen de la transacción
    - reference_type: tipo de entidad de referencia (opcional)
    - reference_id: ID de la entidad de referencia (opcional)
    - note: nota explicativa (opcional)
    - created_by: ID del teacher que hizo el ajuste (opcional)
    - created_at: fecha de creación
    - updated_at: fecha de última actualización
    """
    id: int
    enrollment_id: int
    amount: int
    source_type: CreditTransactionSource
    reference_type: Optional[CreditTransactionReferenceType] = None
    reference_id: Optional[int] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Permite leer desde objetos SQLAlchemy
    model_config = {"from_attributes": True}


class LicenseRecoveryStatus(BaseModel):
    """
    Estado de una licencia específica

    - attendance_id: ID de la asistencia tipo 'license'
    - class_date: Fecha de la clase donde se marcó la licencia
    - status: 'recovered' o 'pending'
    - recovery_class_id: ID de la clase de recuperación que la consumió (si está recuperada)
    - recovery_time: Hora de la clase de recuperación (formato "HH:MM", si está recuperada)
    """
    attendance_id: int
    class_date: date
    status: Literal["recovered", "pending"]
    recovery_class_id: Optional[int] = None
    recovery_time: Optional[str] = None

