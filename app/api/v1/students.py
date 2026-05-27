"""
Students endpoints - CRUD completo para alumnos
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import student
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.enrollment import Enrollment
from app.models.teacher import Teacher
from app.schemas.student import (
    StudentCreate,
    StudentHistoryItem,
    StudentResponse,
    StudentUpdate,
)
from app.api.v1.websocket import notify_data_change
import logging

# Prefer the server-managed loggers so messages appear under gunicorn/uvicorn
# Use the server logger but do NOT raise its level here; keep our logs at DEBUG
logger = logging.getLogger("uvicorn.error")
if not logger.handlers:
    logger = logging.getLogger("gunicorn.error")

router = APIRouter()


@router.get("/", response_model=list[StudentResponse])
async def list_students(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(100, ge=1, le=100, description="Máximo de registros"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Listar todos los alumnos del profesor logueado
    
    Solo retorna alumnos activos (soft-delete respetado)
    Ordenados alfabéticamente por nombre
    
    Args:
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Lista de alumnos activos del profesor
    """
    students = await student.get_multi(
        db,
        teacher_id=current_teacher.id,
        skip=skip,
        limit=limit
    )
    
    return students


@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    student_data: StudentCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Crear un alumno nuevo
    
    El alumno se asocia automáticamente al profesor logueado
    
    Args:
        student_data: Datos del alumno a crear
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Alumno creado con id asignado
    """
    # Asignar el teacher_id del profesor logueado
    student_data.teacher_id = current_teacher.id
    
    new_student = await student.create(db, student_data)
    await notify_data_change(current_teacher.id, "student", "create", new_student.id)
    
    return new_student


@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener un alumno específico por ID
    
    Args:
        student_id: ID del alumno
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Datos del alumno
    
    Raises:
        404: Si el alumno no existe o no pertenece al profesor
    """
    student_obj = await student.get(db, student_id)
    
    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {student_id} no encontrado"
        )
    # Verificar pertenencia: si el teacher actual pertenece a una organización,
    # permitir ver alumnos cuyo teacher pertenezca a la misma organización.
    # Si el teacher es independiente (sin organization_id), solo permitir sus propios alumnos.
    result = await db.execute(select(Teacher).where(Teacher.id == student_obj.teacher_id))
    student_teacher = result.scalar_one_or_none()

    if current_teacher.organization_id:
        if not student_teacher or student_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver este alumno"
            )
    else:
        if student_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver este alumno"
            )
    
    return student_obj


@router.get("/{student_id}/history", response_model=list[StudentHistoryItem])
async def get_student_history(
    student_id: int,
    limit: int = Query(30, ge=1, le=100, description="Cantidad máxima de clases a retornar"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener el historial de clases recientes de un alumno.

    Retorna las últimas clases del alumno ordenadas por fecha descendente,
    con el instrumento, el estado de asistencia y notas si existen.
    """
    student_obj = await student.get(db, student_id)

    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {student_id} no encontrado"
        )
    # Verificación por organización similar a get_student
    result = await db.execute(select(Teacher).where(Teacher.id == student_obj.teacher_id))
    student_teacher = result.scalar_one_or_none()

    if current_teacher.organization_id:
        if not student_teacher or student_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver el historial de este alumno"
            )
    else:
        if student_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver el historial de este alumno"
            )

    result = await db.execute(
        select(Class)
        .join(Class.enrollment)
        .options(
            selectinload(Class.enrollment).selectinload(Enrollment.instrument),
            selectinload(Class.attendance)
        )
        .where(Enrollment.student_id == student_id)
        .order_by(Class.date.desc(), Class.time.desc())
        .limit(limit)
    )

    classes = result.scalars().all()
    history = []

    for class_obj in classes:
        attendance_obj = getattr(class_obj, "attendance", None)
        status_value = None

        if attendance_obj is not None:
            status_value = attendance_obj.status.value
        else:
            # Use the class status when there's no attendance record.
            # Avoid using class_type as the status value (it hides present/absent).
            status_value = class_obj.status.value

        notes_value = None
        if attendance_obj is not None and attendance_obj.notes:
            notes_value = attendance_obj.notes
        elif class_obj.notes:
            notes_value = class_obj.notes

        logger.debug('history class_obj.time=%s class_id=%s class_type=%s attendance=%s', repr(class_obj.time), class_obj.id, getattr(class_obj, 'type', None), bool(attendance_obj))

        history.append(
            StudentHistoryItem(
                class_id=class_obj.id,
                date=class_obj.date,
                time=class_obj.time.strftime('%H:%M:%S') if class_obj.time else None,
                class_type=class_obj.type.value,
                enrollment_id=class_obj.enrollment_id,
                instrument=(
                    class_obj.enrollment.instrument.name
                    if class_obj.enrollment is not None and class_obj.enrollment.instrument is not None
                    else ""
                ),
                status=status_value,
                notes=notes_value,
            )
        )

    # Log the serialized payload so it appears in gunicorn/uvicorn logs
    try:
        payload = [h.model_dump() for h in history]
    except Exception:
        # Fallback: best-effort repr
        payload = [repr(h) for h in history]

    logger.debug('returning history payload count=%s payload=%s', len(payload), payload)

    return history


@router.patch("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: int,
    student_data: StudentUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Actualizar un alumno existente
    
    Solo actualiza los campos enviados (parcial)
    
    Args:
        student_id: ID del alumno a actualizar
        student_data: Datos a actualizar (solo campos no None)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Alumno actualizado
    
    Raises:
        404: Si el alumno no existe
        403: Si el alumno no pertenece al profesor
    """
    # Verificar que existe
    student_obj = await student.get(db, student_id)
    
    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {student_id} no encontrado"
        )
    
    # Verificación por organización: permitir si el teacher del alumno pertenece
    # a la misma organización que el teacher autenticado; si el teacher autenticado
    # es independiente, solo permitir sus propios alumnos.
    result = await db.execute(select(Teacher).where(Teacher.id == student_obj.teacher_id))
    student_teacher = result.scalar_one_or_none()

    if current_teacher.organization_id:
        if not student_teacher or student_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para actualizar este alumno"
            )
    else:
        if student_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para actualizar este alumno"
            )
    
    # Actualizar
    updated_student = await student.update(db, student_id, student_data)
    await notify_data_change(current_teacher.id, "student", "update", updated_student.id)
    
    return updated_student


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Eliminar un alumno FÍSICAMENTE (hard-delete)
    
    Esto dispara la eliminación en cascada en la base de datos
    para inscripciones y horarios asociados.
    
    Args:
        student_id: ID del alumno a eliminar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        204 No Content (sin body)
    
    Raises:
        404: Si el alumno no existe
        403: Si el alumno no pertenece al profesor
    """
    # Verificar que existe
    student_obj = await student.get(db, student_id)
    
    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {student_id} no encontrado"
        )
    
    # Verificación por organización para eliminación (mismo patrón que arriba)
    result = await db.execute(select(Teacher).where(Teacher.id == student_obj.teacher_id))
    student_teacher = result.scalar_one_or_none()

    if current_teacher.organization_id:
        if not student_teacher or student_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para eliminar este alumno"
            )
    else:
        if student_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para eliminar este alumno"
            )
    
    # Hard-delete
    success = await student.remove(db, student_id)
    
    if not success:
        # Esto no debería ocurrir si la validación anterior pasó
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar el alumno"
        )
    
    await notify_data_change(current_teacher.id, "student", "delete", student_id)
    return None  # 204 No Content