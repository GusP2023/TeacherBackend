"""
Sync endpoints - Sincronización Offline-First

Endpoints optimizados para apps móviles con Capacitor:
- /sync/initial: Carga inicial pesada (todos los datos del año)
- /sync/delta: Sincronización incremental (solo cambios)

Estrategia:
1. Al login → /sync/initial (una sola vez, guardar en localStorage)
2. Cada 5 min → /sync/delta (solo si hay cambios, muy rápido)
3. Offline → usar datos de localStorage (UX instantáneo)
"""

from datetime import datetime, timezone, date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.models import (
    Teacher,
    Student,
    Enrollment,
    Schedule,
    Class,
    Attendance,
    Instrument,
)
from app.schemas.sync import (
    InitialSyncRequest,
    InitialSyncResponse,
    DeltaSyncResponse,
    SyncMetadata,
)

router = APIRouter()


@router.post("/initial", response_model=InitialSyncResponse)
async def sync_initial(
    request: InitialSyncRequest,
    current_teacher: Teacher = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Sincronización inicial - Carga TODOS los datos del año especificado.

    Esta es una carga pesada que se ejecuta UNA SOLA VEZ al login:
    - Todos los alumnos del profesor
    - Todas las inscripciones activas
    - Todos los horarios
    - Todas las clases del año (ej: 2025)
    - Todos los instrumentos disponibles

    El frontend guarda todo en localStorage y lo usa offline.

    Args:
        request: Año a sincronizar (ej: 2025)
        current_teacher: Profesor autenticado (automático)
        db: Sesión de base de datos

    Returns:
        Objeto con TODOS los datos del año + metadata de sync

    Example:
        POST /api/v1/sync/initial
        Body: { "year": 2025 }

        Response: {
          "students": [...],
          "enrollments": [...],
          "schedules": [...],
          "classes": [...],
          "instruments": [...],
          "metadata": {
            "sync_timestamp": "2025-01-27T12:00:00Z",
            "total_records": 1234
          }
        }
    """
    # Timestamp de sincronización
    sync_time = datetime.now(timezone.utc)

    # Rango de fechas del año solicitado (OBJETOS DATE para PostgreSQL)
    year_start = date(request.year, 1, 1)   # E.g., 2025-01-01
    year_end = date(request.year, 12, 31)   # E.g., 2025-12-31

    # ========================================
    # 1. CARGAR ALUMNOS DEL PROFESOR
    # ========================================
    students_query = select(Student).where(Student.teacher_id == current_teacher.id)
    students_result = await db.execute(students_query)
    students = students_result.scalars().all()

    # ========================================
    # 2. CARGAR INSCRIPCIONES
    # ========================================
    enrollments_query = select(Enrollment).where(
        Enrollment.teacher_id == current_teacher.id
    )
    enrollments_result = await db.execute(enrollments_query)
    enrollments = enrollments_result.scalars().all()

    # ========================================
    # 3. CARGAR HORARIOS
    # ========================================
    schedules_query = select(Schedule).where(
        Schedule.teacher_id == current_teacher.id
    )
    schedules_result = await db.execute(schedules_query)
    schedules = schedules_result.scalars().all()

    # ========================================
    # 4. CARGAR CLASES DEL AÑO
    # ========================================
    classes_query = select(Class).where(
        and_(
            Class.teacher_id == current_teacher.id,
            Class.date >= year_start,
            Class.date <= year_end,
        )
    )
    classes_result = await db.execute(classes_query)
    classes = classes_result.scalars().all()

    # ========================================
    # 5. CARGAR ASISTENCIAS DEL AÑO
    # ========================================
    # Attendance no tiene teacher_id ni date - hay que hacer JOIN con Class
    attendances_query = (
        select(Attendance)
        .join(Class, Attendance.class_id == Class.id)
        .where(
            and_(
                Class.teacher_id == current_teacher.id,
                Class.date >= year_start,
                Class.date <= year_end,
            )
        )
    )
    attendances_result = await db.execute(attendances_query)
    attendances = attendances_result.scalars().all()

    # ========================================
    # 6. CARGAR INSTRUMENTOS (todos, son pocos)
    # ========================================
    instruments_query = select(Instrument)
    instruments_result = await db.execute(instruments_query)
    instruments = instruments_result.scalars().all()

    # ========================================
    # 7. METADATA
    # ========================================
    total_records = (
        len(students)
        + len(enrollments)
        + len(schedules)
        + len(classes)
        + len(attendances)
        + len(instruments)
    )

    metadata = SyncMetadata(
        sync_timestamp=sync_time,
        total_records=total_records,
    )

    # ========================================
    # 8. RESPUESTA
    # ========================================
    return InitialSyncResponse(
        students=students,
        enrollments=enrollments,
        schedules=schedules,
        classes=classes,
        attendances=attendances,
        instruments=instruments,
        metadata=metadata,
    )


@router.get("/delta", response_model=DeltaSyncResponse)
async def sync_delta(
    since: datetime = Query(
        ...,
        description="Timestamp de última sincronización (ISO 8601 con timezone)",
        example="2025-01-27T12:00:00Z",
    ),
    current_teacher: Teacher = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Sincronización incremental - Solo cambios desde última sync.

    Este endpoint es MUY rápido porque solo retorna lo que cambió:
    - Registros creados desde `since`
    - Registros actualizados desde `since`
    - IDs de registros eliminados (soft delete)

    Se ejecuta en background cada 5 minutos automáticamente.

    Args:
        since: Timestamp de última sincronización
        current_teacher: Profesor autenticado (automático)
        db: Sesión de base de datos

    Returns:
        Objeto con creaciones, actualizaciones y eliminaciones + metadata

    Example:
        GET /api/v1/sync/delta?since=2025-01-27T12:00:00Z

        Response: {
          "created": {
            "students": [],
            "classes": [{ ... }]
          },
          "updated": {
            "students": [{ ... }],
            "enrollments": []
          },
          "deleted": {
            "student_ids": [],
            "class_ids": [123, 456]
          },
          "metadata": {
            "sync_timestamp": "2025-01-27T12:05:00Z",
            "total_changes": 3
          }
        }
    """
    # Timestamp de sincronización actual
    sync_time = datetime.now(timezone.utc)

    # ========================================
    # HELPER: Separar creados vs actualizados
    # ========================================
    def split_created_updated(records, since_time):
        """Separa registros en creados (created_at >= since) y actualizados (updated_at >= since pero created_at < since)"""
        created = [r for r in records if r.created_at >= since_time]
        updated = [
            r
            for r in records
            if r.updated_at >= since_time and r.created_at < since_time
        ]
        return created, updated

    # ========================================
    # 1. ESTUDIANTES CAMBIADOS
    # ========================================
    students_query = select(Student).where(
        and_(
            Student.teacher_id == current_teacher.id,
            or_(Student.created_at >= since, Student.updated_at >= since),
        )
    )
    students_result = await db.execute(students_query)
    students_changed = students_result.scalars().all()
    students_created, students_updated = split_created_updated(students_changed, since)

    # ========================================
    # 2. INSCRIPCIONES CAMBIADAS
    # ========================================
    enrollments_query = select(Enrollment).where(
        and_(
            Enrollment.teacher_id == current_teacher.id,
            or_(Enrollment.created_at >= since, Enrollment.updated_at >= since),
        )
    )
    enrollments_result = await db.execute(enrollments_query)
    enrollments_changed = enrollments_result.scalars().all()
    enrollments_created, enrollments_updated = split_created_updated(
        enrollments_changed, since
    )

    # ========================================
    # 3. HORARIOS CAMBIADOS
    # ========================================
    schedules_query = select(Schedule).where(
        and_(
            Schedule.teacher_id == current_teacher.id,
            or_(Schedule.created_at >= since, Schedule.updated_at >= since),
        )
    )
    schedules_result = await db.execute(schedules_query)
    schedules_changed = schedules_result.scalars().all()
    schedules_created, schedules_updated = split_created_updated(
        schedules_changed, since
    )

    # ========================================
    # 4. CLASES CAMBIADAS
    # ========================================
    classes_query = select(Class).where(
        and_(
            Class.teacher_id == current_teacher.id,
            or_(Class.created_at >= since, Class.updated_at >= since),
        )
    )
    classes_result = await db.execute(classes_query)
    classes_changed = classes_result.scalars().all()
    classes_created, classes_updated = split_created_updated(classes_changed, since)

    # ========================================
    # 5. ASISTENCIAS CAMBIADAS
    # ========================================
    # Attendance no tiene teacher_id - hay que hacer JOIN con Class
    attendances_query = (
        select(Attendance)
        .join(Class, Attendance.class_id == Class.id)
        .where(
            and_(
                Class.teacher_id == current_teacher.id,
                or_(Attendance.created_at >= since, Attendance.updated_at >= since),
            )
        )
    )
    attendances_result = await db.execute(attendances_query)
    attendances_changed = attendances_result.scalars().all()
    attendances_created, attendances_updated = split_created_updated(
        attendances_changed, since
    )

    # ========================================
    # 6. INSTRUMENTOS CAMBIADOS (raro, pero incluir)
    # ========================================
    instruments_query = select(Instrument).where(
        or_(Instrument.created_at >= since, Instrument.updated_at >= since)
    )
    instruments_result = await db.execute(instruments_query)
    instruments_changed = instruments_result.scalars().all()
    instruments_created, instruments_updated = split_created_updated(
        instruments_changed, since
    )

    # ========================================
    # 7. ELIMINACIONES (soft delete)
    # ========================================
    # TODO: Si implementas soft delete, detectar registros con deleted_at >= since
    # Por ahora, listas vacías
    deleted = {
        "student_ids": [],
        "enrollment_ids": [],
        "schedule_ids": [],
        "class_ids": [],
        "attendance_ids": [],
        "instrument_ids": [],
    }

    # ========================================
    # 8. METADATA
    # ========================================
    total_changes = (
        len(students_created)
        + len(students_updated)
        + len(enrollments_created)
        + len(enrollments_updated)
        + len(schedules_created)
        + len(schedules_updated)
        + len(classes_created)
        + len(classes_updated)
        + len(attendances_created)
        + len(attendances_updated)
        + len(instruments_created)
        + len(instruments_updated)
    )

    metadata = SyncMetadata(
        sync_timestamp=sync_time,
        total_records=total_changes,
    )

    # ========================================
    # 9. RESPUESTA
    # ========================================
    return DeltaSyncResponse(
        created={
            "students": students_created,
            "enrollments": enrollments_created,
            "schedules": schedules_created,
            "classes": classes_created,
            "attendances": attendances_created,
            "instruments": instruments_created,
        },
        updated={
            "students": students_updated,
            "enrollments": enrollments_updated,
            "schedules": schedules_updated,
            "classes": classes_updated,
            "attendances": attendances_updated,
            "instruments": instruments_updated,
        },
        deleted=deleted,
        metadata=metadata,
    )
