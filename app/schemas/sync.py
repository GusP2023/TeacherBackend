"""
Schemas Pydantic para Sincronización Offline-First

CONCEPTO:
Endpoints optimizados para apps móviles (Capacitor) que necesitan:
1. Carga inicial completa (todos los datos del año)
2. Sincronización incremental (solo cambios)
3. Soporte offline (datos en localStorage)

FLUJO:
1. Login → /sync/initial (carga pesada, una vez)
2. Guardar en localStorage del móvil
3. Mostrar datos inmediatamente (offline-first)
4. Background sync cada 5 min → /sync/delta (solo cambios)
5. Merge incremental en localStorage

BENEFICIOS:
- UX instantáneo (0ms de carga)
- Funciona sin internet
- Tráfico de red mínimo después de inicial
- Baja batería (pocos requests)
"""

from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel, Field

# Importar schemas de cada modelo (para reutilizar validaciones)
from app.schemas.student import StudentRead
from app.schemas.enrollment import EnrollmentRead
from app.schemas.schedule import ScheduleRead
from app.schemas.class_schema import ClassRead
from app.schemas.attendance import AttendanceRead
from app.schemas.instrument import InstrumentRead


# ========================================
# SCHEMAS DE REQUEST
# ========================================


class InitialSyncRequest(BaseModel):
    """
    Request para sincronización inicial.

    El frontend especifica el año a sincronizar (ej: 2025).
    El backend devuelve TODOS los datos de ese año.

    Ejemplo:
    {
        "year": 2025
    }
    """

    year: int = Field(
        ...,
        ge=2020,
        le=2050,
        description="Año a sincronizar (ej: 2025)",
        example=2025,
    )


# ========================================
# SCHEMAS DE RESPONSE
# ========================================


class SyncMetadata(BaseModel):
    """
    Metadata de la sincronización.

    Incluye:
    - sync_timestamp: Momento exacto de la sincronización (guardar para próximo delta)
    - total_records: Número total de registros sincronizados
    """

    sync_timestamp: datetime = Field(
        ...,
        description="Timestamp de la sincronización (ISO 8601 con timezone)",
        example="2025-01-27T12:00:00Z",
    )

    total_records: int = Field(
        ..., ge=0, description="Número total de registros en esta sync", example=1234
    )


class InitialSyncResponse(BaseModel):
    """
    Response de sincronización inicial.

    Contiene TODOS los datos del año especificado:
    - students: Todos los alumnos del profesor
    - enrollments: Todas las inscripciones
    - schedules: Todos los horarios
    - classes: Todas las clases del año
    - attendances: Todas las asistencias del año
    - instruments: Todos los instrumentos disponibles
    - metadata: Timestamp y conteo total

    El frontend guarda todo esto en localStorage para uso offline.

    Ejemplo:
    {
        "students": [{ id: 1, name: "Juan", ... }, ...],
        "enrollments": [...],
        "schedules": [...],
        "classes": [...],
        "attendances": [...],
        "instruments": [...],
        "metadata": {
            "sync_timestamp": "2025-01-27T12:00:00Z",
            "total_records": 1234
        }
    }
    """

    students: List[StudentRead]
    enrollments: List[EnrollmentRead]
    schedules: List[ScheduleRead]
    classes: List[ClassRead]
    attendances: List[AttendanceRead]
    instruments: List[InstrumentRead]
    metadata: SyncMetadata


class DeltaSyncCreated(BaseModel):
    """
    Registros CREADOS desde la última sincronización.

    Separados por tipo de entidad.
    """

    students: List[StudentRead] = []
    enrollments: List[EnrollmentRead] = []
    schedules: List[ScheduleRead] = []
    classes: List[ClassRead] = []
    attendances: List[AttendanceRead] = []
    instruments: List[InstrumentRead] = []


class DeltaSyncUpdated(BaseModel):
    """
    Registros ACTUALIZADOS desde la última sincronización.

    Separados por tipo de entidad.
    Solo incluye registros donde updated_at >= since (pero created_at < since).
    """

    students: List[StudentRead] = []
    enrollments: List[EnrollmentRead] = []
    schedules: List[ScheduleRead] = []
    classes: List[ClassRead] = []
    attendances: List[AttendanceRead] = []
    instruments: List[InstrumentRead] = []


class DeltaSyncDeleted(BaseModel):
    """
    IDs de registros ELIMINADOS desde la última sincronización.

    Separados por tipo de entidad.
    Solo IDs, no objetos completos (para eficiencia).

    NOTA: Requiere implementar soft delete (deleted_at en modelos).
    Si no tienes soft delete, estas listas estarán vacías.
    """

    student_ids: List[int] = []
    enrollment_ids: List[int] = []
    schedule_ids: List[int] = []
    class_ids: List[int] = []
    attendance_ids: List[int] = []
    instrument_ids: List[int] = []


class DeltaSyncResponse(BaseModel):
    """
    Response de sincronización incremental (delta).

    Contiene solo los CAMBIOS desde la última sincronización:
    - created: Registros nuevos
    - updated: Registros modificados
    - deleted: IDs de registros eliminados
    - metadata: Timestamp y conteo de cambios

    Es MUY rápido porque solo envía lo que cambió (no todo).

    Ejemplo:
    {
        "created": {
            "students": [],
            "classes": [{ id: 456, ... }]
        },
        "updated": {
            "students": [{ id: 123, name: "Juan Updated", ... }],
            "enrollments": []
        },
        "deleted": {
            "student_ids": [],
            "class_ids": [789]
        },
        "metadata": {
            "sync_timestamp": "2025-01-27T12:05:00Z",
            "total_records": 3
        }
    }
    """

    created: DeltaSyncCreated
    updated: DeltaSyncUpdated
    deleted: DeltaSyncDeleted
    metadata: SyncMetadata
