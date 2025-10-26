"""
Enrollments endpoints - CRUD + suspend/reactivate/withdraw
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import enrollment, student, instrument
from app.models.teacher import Teacher
from app.schemas.enrollment import EnrollmentCreate, EnrollmentUpdate, EnrollmentResponse

router = APIRouter()


@router.get("/", response_model=list[EnrollmentResponse])
async def list_enrollments(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(100, ge=1, le=100, description="Máximo de registros"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Listar todas las inscripciones del profesor logueado
    
    Incluye todas (activas, suspendidas, retiradas)
    Ordenadas por más recientes primero
    
    Args:
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Lista de inscripciones del profesor
    """
    enrollments = await enrollment.get_multi(
        db,
        teacher_id=current_teacher.id,
        skip=skip,
        limit=limit
    )
    
    return enrollments


@router.post("/", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    enrollment_data: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    print("🟢 LLEGÓ REQUEST DE CREACIÓN:", enrollment_data.dict(), flush=True)
    """
    Crear una inscripción nueva
    
    Valida que el alumno e instrumento existan y pertenezcan al profesor
    
    Args:
        enrollment_data: Datos de la inscripción a crear
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Inscripción creada con id asignado
    
    Raises:
        400: Si el alumno no existe o no pertenece al profesor
        400: Si el instrumento no existe o no está activo
    """
    # Validar que el alumno existe y pertenece al profesor
    student_obj = await student.get(db, enrollment_data.student_id)
    
    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Alumno {enrollment_data.student_id} no encontrado"
        )
    
    if student_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para inscribir este alumno"
        )
    
    # Validar que el instrumento existe y está activo
    instrument_obj = await instrument.get(db, enrollment_data.instrument_id)
    
    if not instrument_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Instrumento {enrollment_data.instrument_id} no encontrado"
        )
    
    if not instrument_obj.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El instrumento '{instrument_obj.name}' no está disponible"
        )
    
    # Asignar el teacher_id del profesor logueado
    enrollment_data.teacher_id = current_teacher.id
    
    # Crear la inscripción
    new_enrollment = await enrollment.create(db, enrollment_data)
    
    return new_enrollment


@router.get("/student/{student_id}", response_model=list[EnrollmentResponse])
async def get_student_enrollments(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener todas las inscripciones de un alumno
    
    Útil para ver historial: Piano (activo), Guitarra (retirado), etc.
    
    Args:
        student_id: ID del alumno
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Lista de inscripciones del alumno (todos los estados)
    
    Raises:
        404: Si el alumno no existe
        403: Si el alumno no pertenece al profesor
    """
    # Validar que el alumno existe y pertenece al profesor
    student_obj = await student.get(db, student_id)
    
    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {student_id} no encontrado"
        )
    
    if student_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este alumno"
        )
    
    enrollments = await enrollment.get_by_student(db, student_id)
    
    return enrollments


@router.get("/{enrollment_id}", response_model=EnrollmentResponse)
async def get_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener una inscripción específica por ID
    
    Args:
        enrollment_id: ID de la inscripción
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Datos de la inscripción
    
    Raises:
        404: Si la inscripción no existe
        403: Si la inscripción no pertenece al profesor
    """
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver esta inscripción"
        )
    
    return enrollment_obj


@router.patch("/{enrollment_id}", response_model=EnrollmentResponse)
async def update_enrollment(
    enrollment_id: int,
    enrollment_data: EnrollmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Actualizar una inscripción existente
    
    Solo actualiza los campos enviados (parcial)
    
    Args:
        enrollment_id: ID de la inscripción a actualizar
        enrollment_data: Datos a actualizar (solo campos no None)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Inscripción actualizada
    
    Raises:
        404: Si la inscripción no existe
        403: Si la inscripción no pertenece al profesor
    """
    # Verificar que existe y pertenece al profesor
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar esta inscripción"
        )
    
    # Actualizar
    updated_enrollment = await enrollment.update(db, enrollment_id, enrollment_data)
    
    return updated_enrollment


@router.post("/{enrollment_id}/suspend", response_model=EnrollmentResponse)
async def suspend_enrollment(
    enrollment_id: int,
    until_date: date | None = Query(None, description="Fecha hasta cuándo suspender (opcional)"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Suspender una inscripción temporalmente
    
    Cambia status a 'suspended'
    Opcionalmente guarda fecha hasta cuándo
    
    Args:
        enrollment_id: ID de la inscripción a suspender
        until_date: Fecha hasta cuándo está suspendido (opcional)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Inscripción suspendida
    
    Raises:
        404: Si la inscripción no existe
        403: Si la inscripción no pertenece al profesor
    """
    # Verificar que existe y pertenece al profesor
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para suspender esta inscripción"
        )
    
    # Suspender
    suspended_enrollment = await enrollment.suspend(db, enrollment_id, until_date)
    
    return suspended_enrollment


@router.post("/{enrollment_id}/reactivate", response_model=EnrollmentResponse)
async def reactivate_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Reactivar una inscripción suspendida
    
    Cambia status a 'active' y limpia suspended_until
    
    Args:
        enrollment_id: ID de la inscripción a reactivar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Inscripción reactivada
    
    Raises:
        404: Si la inscripción no existe
        403: Si la inscripción no pertenece al profesor
    """
    # Verificar que existe y pertenece al profesor
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para reactivar esta inscripción"
        )
    
    # Reactivar
    reactivated_enrollment = await enrollment.reactivate(db, enrollment_id)
    
    return reactivated_enrollment


@router.post("/{enrollment_id}/withdraw", response_model=EnrollmentResponse)
async def withdraw_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Retirar una inscripción definitivamente
    
    Cambia status a 'withdrawn'
    NO elimina el registro, mantiene histórico
    
    Args:
        enrollment_id: ID de la inscripción a retirar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Inscripción retirada
    
    Raises:
        404: Si la inscripción no existe
        403: Si la inscripción no pertenece al profesor
    """
    # Verificar que existe y pertenece al profesor
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para retirar esta inscripción"
        )
    
    # Retirar
    withdrawn_enrollment = await enrollment.withdraw(db, enrollment_id)
    
    return withdrawn_enrollment