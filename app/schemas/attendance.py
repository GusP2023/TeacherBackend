"""
Schemas Pydantic para Attendance (Asistencia)

CONCEPTO:
La Attendance registra si el alumno asistió a una clase específica.
- Relación 1:1 con Class (una clase = una asistencia)
- Se crea DESPUÉS de que la clase ocurre (o se marca ausente)

ESTADOS:
- present: alumno asistió → SE COBRA
- absent: alumno NO asistió → SE COBRA (ausencia injustificada)
- license: alumno justificó ausencia → NO SE COBRA + GANA 1 CRÉDITO

LÓGICA DE NEGOCIO:
- license → enrollment.credits += 1
- Usar clase recovery → enrollment.credits -= 1
- Constraint: enrollment.credits >= 0

IMPORTANTE:
- Solo se crea Attendance cuando la clase YA ocurrió
- Sin Attendance = clase no marcada = NO se cobra
"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# Importar enum desde los modelos
from app.models.attendance import AttendanceStatus


class AttendanceBase(BaseModel):
    """
    Campos comunes de la asistencia.
    
    - class_id: a qué clase específica pertenece (relación 1:1)
    - status: present, absent, license
    - notes: notas opcionales del profesor (ej: "llegó 10 min tarde")
    """
    class_id: int = Field(..., gt=0)
    status: AttendanceStatus
    notes: str | None = None


class AttendanceCreate(AttendanceBase):
    """
    Para CREAR una asistencia (POST /attendances)
    
    Se crea cuando:
    - La clase ya ocurrió y el profesor marca asistencia
    - El alumno avisó con anticipación (license)
    
    IMPORTANTE:
    - Una vez creada, el class_id NO puede cambiar (relación 1:1)
    - Si necesitas cambiar, DELETE y CREATE nuevo
    
    Ejemplo presente:
    {
        "class_id": 42,
        "status": "present",
        "notes": null
    }
    
    Ejemplo ausente con justificación:
    {
        "class_id": 43,
        "status": "license",
        "notes": "Avisó con 2 días de anticipación - enfermedad"
    }
    """
    pass  # No hay campos adicionales, hereda todo de Base


class AttendanceUpdate(BaseModel):
    """
    Para ACTUALIZAR una asistencia (PATCH /attendances/{id})
    
    Casos de uso:
    - Cambiar status (absent → license si justificó después)
    - Cambiar status (present → absent si se detectó error)
    - Agregar/modificar notes
    
    IMPORTANTE AL CAMBIAR STATUS:
    - absent → license: sumar 1 crédito al enrollment
    - license → absent: restar 1 crédito al enrollment
    - Validar que credits >= 0 siempre
    
    NO se puede cambiar class_id (es relación 1:1 única).
    """
    status: AttendanceStatus | None = None
    notes: str | None = None


class AttendanceResponse(AttendanceBase):
    """
    Para RESPUESTAS (GET)
    
    Incluye todos los campos de la BD:
    - id: identificador único
    - sync_id: para sincronización móvil
    - timestamps: created_at y updated_at
    
    NOTA: Para obtener info de la clase, hacer join con Class.
    """
    id: int
    sync_id: str | None = None
    created_at: datetime
    updated_at: datetime
    
    # Permite leer desde objetos SQLAlchemy
    model_config = ConfigDict(from_attributes=True)