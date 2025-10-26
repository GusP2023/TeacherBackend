"""
Students endpoints - CRUD completo para alumnos
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import student
from app.models.teacher import Teacher
from app.schemas.student import StudentCreate, StudentUpdate, StudentResponse

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
    
    # Verificar que el alumno pertenece al profesor logueado
    if student_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este alumno"
        )
    
    return student_obj


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
    
    # Verificar que pertenece al profesor
    if student_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar este alumno"
        )
    
    # Actualizar
    updated_student = await student.update(db, student_id, student_data)
    
    return updated_student


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Eliminar un alumno (soft-delete)
    
    NO elimina físicamente, solo marca active=False
    Mantiene histórico de clases y asistencias
    
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
    
    # Verificar que pertenece al profesor
    if student_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar este alumno"
        )
    
    # Soft-delete
    success = await student.delete(db, student_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar el alumno"
        )
    
    return None  # 204 No Content