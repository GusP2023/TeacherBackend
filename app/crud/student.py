"""
CRUD operations for Student model
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.student import Student
from app.schemas.student import StudentCreate, StudentUpdate


async def get(db: AsyncSession, student_id: int) -> Student | None:
    """
    Obtener un alumno por ID
    
    Args:
        db: Sesión de base de datos
        student_id: ID del alumno
    
    Returns:
        Student si existe, None si no
    """
    result = await db.execute(
        select(Student).where(
            Student.id == student_id,
            Student.active == True
        )
    )
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    teacher_id: int,
    skip: int = 0,
    limit: int = 100
) -> list[Student]:
    """
    Obtener múltiples alumnos de un profesor
    
    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
    
    Returns:
        Lista de Students activos del profesor
    """
    result = await db.execute(
        select(Student)
        .where(
            Student.teacher_id == teacher_id,
            Student.active == True
        )
        .offset(skip)
        .limit(limit)
        .order_by(Student.name)
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, student_data: StudentCreate) -> Student:
    """
    Crear un alumno nuevo
    
    Args:
        db: Sesión de base de datos
        student_data: Datos del alumno a crear
    
    Returns:
        Student creado con id asignado
    """
    student = Student(**student_data.model_dump())
    
    db.add(student)
    await db.commit()
    await db.refresh(student)
    
    return student


async def update(
    db: AsyncSession,
    student_id: int,
    student_data: StudentUpdate
) -> Student | None:
    """
    Actualizar un alumno existente
    
    Args:
        db: Sesión de base de datos
        student_id: ID del alumno a actualizar
        student_data: Datos a actualizar (solo campos no None)
    
    Returns:
        Student actualizado si existe, None si no
    """
    # Obtener el alumno
    result = await db.execute(
        select(Student).where(
            Student.id == student_id,
            Student.active == True
        )
    )
    student = result.scalar_one_or_none()
    
    if not student:
        return None
    
    # Actualizar solo campos que no sean None
    update_data = student_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(student, field, value)
    
    await db.commit()
    await db.refresh(student)
    
    return student


async def delete(db: AsyncSession, student_id: int) -> bool:
    """
    Eliminar un alumno (soft-delete)
    
    NO elimina físicamente el registro, solo marca active=False
    Esto permite mantener histórico de clases y asistencias
    
    Args:
        db: Sesión de base de datos
        student_id: ID del alumno a eliminar
    
    Returns:
        True si se eliminó correctamente, False si no existe
    """
    # Obtener el alumno
    result = await db.execute(
        select(Student).where(
            Student.id == student_id,
            Student.active == True
        )
    )
    student = result.scalar_one_or_none()
    
    if not student:
        return False
    
    # Soft-delete: marcar como inactivo
    student.active = False
    
    await db.commit()
    
    return True