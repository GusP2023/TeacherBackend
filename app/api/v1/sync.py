"""
Sync endpoints - Sincronización Offline-First

Endpoints optimizados para apps móviles con Capacitor:
- /sync/initial: Carga inicial pesada (todos los datos del año + horizonte)
- /sync/delta: Sincronización incremental (solo cambios)

Estrategia:
1. Al login → /sync/initial (una sola vez, guardar en localStorage)
2. Cada 5 min → /sync/delta (solo si hay cambios, muy rápido)
3. Offline → usar datos de localStorage (UX instantáneo)
"""

from datetime import datetime, timezone, date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
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
    VerifyOperationRequest,
    VerifyOperationsRequest,
    VerifyOperationsResponse,
)

router = APIRouter()


@router.post("/initial", response_model=InitialSyncResponse)
async def sync_initial(
    request: InitialSyncRequest,
    current_teacher: Teacher = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Sincronización inicial - Carga TODOS los datos del año especificado + horizonte.

    Esta es una carga pesada que se ejecuta UNA SOLA VEZ al login:
    - Todos los alumnos del profesor
    - Todas las inscripciones activas
    - Todos los horarios
    - Todas las clases del año + 3 meses del siguiente (horizonte de planificación)
    - Todos los instrumentos disponibles

    El frontend guarda todo en localStorage y lo usa offline.

    Args:
        request: Año a sincronizar (ej: 2025)
        current_teacher: Profesor autenticado (automático)
        db: Sesión de base de datos

    Returns:
        Objeto con TODOS los datos del año + metadata de sync
    """
    # Timestamp de sincronización
    sync_time = datetime.now(timezone.utc)

    # ========================================
    # RANGO DE FECHAS EXTENDIDO
    # ========================================
    # Desde: 1 de enero del año solicitado
    # Hasta: 31 de marzo del año siguiente (para cubrir horizonte de clases)
    # Esto asegura que las clases generadas 2-3 meses adelante se sincronicen
    year_start = date(request.year, 1, 1)
    year_end = date(request.year + 1, 3, 31)  # ⬅️ EXTENDIDO: hasta marzo del siguiente año

    # ========================================
    # 1. CARGAR ALUMNOS DEL PROFESOR (todos, activos e inactivos)
    # ========================================
    # Se envían todos para evitar problemas de referencia en histórico
    students_query = select(Student).where(
        Student.teacher_id == current_teacher.id
    )
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
    # 3. CARGAR HORARIOS (todos, activos e inactivos)
    # ========================================
    # Se envían todos para evitar que el frontend borre clases asociadas
    # a horarios inactivos pero que tienen historial o clases futuras manuales.
    schedules_query = select(Schedule).where(
        Schedule.teacher_id == current_teacher.id
    )
    schedules_result = await db.execute(schedules_query)
    schedules = schedules_result.scalars().all()

    # ========================================
    # 4. CARGAR CLASES (año + horizonte)
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
    # 5. CARGAR ASISTENCIAS (año + horizonte)
    # ========================================
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
    # 6. CARGAR INSTRUMENTOS
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
    last_sync: str = Query(..., description="ISO datetime del último sync"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Delta sync mejorado que incluye:
    - Registros nuevos/actualizados
    - Schedules desactivados recientemente
    - Enrollments suspendidos/reactivados
    """
    from datetime import datetime
    
    # Parsear fecha, manejando posible espacio en lugar de + para timezone
    try:
        last_sync_date = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
    except ValueError:
        # Fallback si el formato no es exacto
        last_sync_date = datetime.now()

    # 1. Schedules activos actualizados
    active_schedules_result = await db.execute(
        select(Schedule).where(
            and_(
                Schedule.teacher_id == current_teacher.id,
                Schedule.updated_at > last_sync_date,
                Schedule.active == True
            )
        )
    )
    active_schedules = active_schedules_result.scalars().all()
    
    # 2. ✅ NUEVO: Schedules desactivados recientemente
    deactivated_schedules_result = await db.execute(
        select(Schedule).where(
            and_(
                Schedule.teacher_id == current_teacher.id,
                Schedule.active == False,
                or_(
                    Schedule.updated_at > last_sync_date,
                    Schedule.valid_until >= (last_sync_date.date() if last_sync_date else date.today())
                )
            )
        )
    )
    deactivated_schedules = deactivated_schedules_result.scalars().all()
    
    # 3. Enrollments actualizados (incluye suspendidos/reactivados)
    enrollments_result = await db.execute(
        select(Enrollment).where(
            and_(
                Enrollment.teacher_id == current_teacher.id,
                Enrollment.updated_at > last_sync_date
            )
        )
    )
    enrollments = enrollments_result.scalars().all()
    
    # 4. Clases actualizadas
    classes_result = await db.execute(
        select(Class).where(
            and_(
                Class.teacher_id == current_teacher.id,
                Class.updated_at > last_sync_date
            )
        )
    )
    classes = classes_result.scalars().all()
    
    # 5. Estudiantes actualizados
    students_result = await db.execute(
        select(Student).where(
            and_(
                Student.teacher_id == current_teacher.id,
                Student.updated_at > last_sync_date
            )
        )
    )
    students = students_result.scalars().all()

    # 6. Asistencias actualizadas (join con clases del profesor)
    attendances_result = await db.execute(
        select(Attendance)
        .join(Class, Attendance.class_id == Class.id)
        .where(
            and_(
                Class.teacher_id == current_teacher.id,
                Attendance.updated_at > last_sync_date
            )
        )
    )
    attendances = attendances_result.scalars().all()

    return {
        "schedules": {
            "active": active_schedules,
            "deactivated": deactivated_schedules
        },
        "enrollments": enrollments,
        "classes": classes,
        "students": students,
        "attendances": attendances,
        "sync_timestamp": datetime.now().isoformat()
    }


@router.post("/verify-operations", response_model=VerifyOperationsResponse)
async def verify_operations(
    request: VerifyOperationsRequest,
    current_teacher: Teacher = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Verifica si las operaciones UPDATE/DELETE fueron aplicadas en el backend.
    """
    operations = request.operations
    results = []

    # Agrupar IDs por entidad para hacer queries en bloque
    ids_by_entity: dict[str, set[int]] = {
        "student": set(),
        "enrollment": set(),
        "schedule": set(),
        "class": set(),
        "attendance": set(),
    }

    for op in operations:
        ids_by_entity[op.entity_type].add(op.entity_id)

    entities: dict[str, dict[int, any]] = {
        "student": {},
        "enrollment": {},
        "schedule": {},
        "class": {},
        "attendance": {},
    }

    if ids_by_entity["student"]:
        students_result = await db.execute(
            select(Student).where(
                and_(
                    Student.teacher_id == current_teacher.id,
                    Student.id.in_(ids_by_entity["student"]),
                )
            )
        )
        entities["student"] = {s.id: s for s in students_result.scalars().all()}

    if ids_by_entity["enrollment"]:
        enrollments_result = await db.execute(
            select(Enrollment).where(
                and_(
                    Enrollment.teacher_id == current_teacher.id,
                    Enrollment.id.in_(ids_by_entity["enrollment"]),
                )
            )
        )
        entities["enrollment"] = {e.id: e for e in enrollments_result.scalars().all()}

    if ids_by_entity["schedule"]:
        schedules_result = await db.execute(
            select(Schedule).where(
                and_(
                    Schedule.teacher_id == current_teacher.id,
                    Schedule.id.in_(ids_by_entity["schedule"]),
                )
            )
        )
        entities["schedule"] = {s.id: s for s in schedules_result.scalars().all()}

    if ids_by_entity["class"]:
        classes_result = await db.execute(
            select(Class).where(
                and_(
                    Class.teacher_id == current_teacher.id,
                    Class.id.in_(ids_by_entity["class"]),
                )
            )
        )
        entities["class"] = {c.id: c for c in classes_result.scalars().all()}

    if ids_by_entity["attendance"]:
        attendances_result = await db.execute(
            select(Attendance)
            .join(Class, Attendance.class_id == Class.id)
            .where(
                and_(
                    Class.teacher_id == current_teacher.id,
                    Attendance.id.in_(ids_by_entity["attendance"]),
                )
            )
        )
        entities["attendance"] = {a.id: a for a in attendances_result.scalars().all()}

    for op in operations:
        entity = entities[op.entity_type].get(op.entity_id)
        verdict = "not_found"
        server_updated_at = None

        if entity is not None:
            server_updated_at = entity.updated_at
            if op.type in {
                "DELETE_STUDENT",
                "DELETE_ENROLLMENT",
                "DELETE_SCHEDULE",
                "DELETE_CLASS",
                "DELETE_ATTENDANCE",
            }:
                verdict = "not_applied"
            elif op.type == "CANCEL_CLASS":
                verdict = "applied" if getattr(entity, "status", None) == "cancelled" else "not_applied"
            else:
                verdict = "applied" if entity.updated_at >= op.sent_at else "not_applied"

        else:
            if op.type in {
                "DELETE_STUDENT",
                "DELETE_ENROLLMENT",
                "DELETE_SCHEDULE",
                "DELETE_CLASS",
                "DELETE_ATTENDANCE",
                "CANCEL_CLASS",
            }:
                verdict = "applied"
            else:
                verdict = "not_found"

        results.append(
            {
                "operation_id": op.operation_id,
                "entity_type": op.entity_type,
                "entity_id": op.entity_id,
                "verdict": verdict,
                "server_updated_at": server_updated_at,
            }
        )

    return {"results": results}
