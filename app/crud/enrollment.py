"""
CRUD operations for Enrollment model
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.schemas.enrollment import EnrollmentCreate, EnrollmentUpdate


async def get(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """
    Obtener una inscripción por ID
    
    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción
    
    Returns:
        Enrollment si existe, None si no
    """
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    teacher_id: int,
    skip: int = 0,
    limit: int = 100
) -> list[Enrollment]:
    """
    Obtener múltiples inscripciones de un profesor
    
    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
    
    Returns:
        Lista de Enrollments del profesor
    """
    result = await db.execute(
        select(Enrollment)
        .where(Enrollment.teacher_id == teacher_id)
        .offset(skip)
        .limit(limit)
        .order_by(Enrollment.created_at.desc())
    )
    return list(result.scalars().all())


async def get_by_student(
    db: AsyncSession,
    student_id: int
) -> list[Enrollment]:
    """
    Obtener todas las inscripciones de un alumno
    
    Útil para ver historial: Piano (activo), Guitarra (retirado), etc.
    
    Args:
        db: Sesión de base de datos
        student_id: ID del alumno
    
    Returns:
        Lista de Enrollments del alumno (todos los estados)
    """
    result = await db.execute(
        select(Enrollment)
        .where(Enrollment.student_id == student_id)
        .order_by(Enrollment.created_at.desc())
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, enrollment_data: EnrollmentCreate) -> Enrollment:
    """
    Crear una inscripción nueva
    
    Args:
        db: Sesión de base de datos
        enrollment_data: Datos de la inscripción a crear
    
    Returns:
        Enrollment creado con id asignado
    """
    enrollment = Enrollment(**enrollment_data.model_dump())
    
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    
    return enrollment


async def update(
    db: AsyncSession,
    enrollment_id: int,
    enrollment_data: EnrollmentUpdate
) -> Enrollment | None:
    """
    Actualizar una inscripción existente
    
    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción a actualizar
        enrollment_data: Datos a actualizar (solo campos no None)
    
    Returns:
        Enrollment actualizado si existe, None si no
    """
    # Obtener la inscripción
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return None
    
    # Actualizar solo campos que no sean None
    update_data = enrollment_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(enrollment, field, value)
    
    await db.commit()
    await db.refresh(enrollment)
    
    return enrollment


async def suspend(
    db: AsyncSession,
    enrollment_id: int,
    until_date: date | None = None
) -> Enrollment | None:
    """
    Suspender una inscripción temporalmente
    
    Cambia status a 'suspended' y opcionalmente guarda fecha hasta cuándo
    
    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción a suspender
        until_date: Fecha hasta cuándo está suspendido (opcional)
    
    Returns:
        Enrollment suspendido si existe, None si no
    """
    # Obtener la inscripción
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return None
    
    # Suspender
    enrollment.status = EnrollmentStatus.SUSPENDED
    enrollment.suspended_until = until_date
    
    await db.commit()
    await db.refresh(enrollment)
    
    return enrollment


async def reactivate(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """
    Reactivar una inscripción suspendida
    
    Cambia status a 'active' y limpia suspended_until
    
    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción a reactivar
    
    Returns:
        Enrollment reactivado si existe, None si no
    """
    # Obtener la inscripción
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return None
    
    # Reactivar
    enrollment.status = EnrollmentStatus.ACTIVE
    enrollment.suspended_until = None
    
    await db.commit()
    await db.refresh(enrollment)
    
    return enrollment


async def withdraw(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """
    Retirar una inscripción definitivamente
    
    Cambia status a 'withdrawn'. NO elimina el registro.
    Mantiene histórico de clases pasadas.
    
    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción a retirar
    
    Returns:
        Enrollment retirado si existe, None si no
    """
    # Obtener la inscripción
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return None
    
    # Retirar
    enrollment.status = EnrollmentStatus.WITHDRAWN
    
    await db.commit()
    await db.refresh(enrollment)
    
    return enrollment