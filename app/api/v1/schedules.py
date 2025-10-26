"""
Schedules endpoints - CRUD de horarios recurrentes (templates)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import schedule, enrollment
from app.models.teacher import Teacher
from app.models.class_model import ClassFormat
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate, ScheduleResponse

router = APIRouter()


# Schema para la respuesta de validación de slot
class SlotValidationResponse(BaseModel):
    available: bool
    message: str
    current_students: int
    max_students: int
    existing_format: str | None
    conflict: bool


@router.get("/", response_model=list[ScheduleResponse])
async def list_schedules(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(100, ge=1, le=100, description="Máximo de registros"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Listar todos los horarios del profesor logueado
    
    Ordenados por día de semana y hora de inicio
    
    Args:
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Lista de horarios (templates recurrentes) del profesor
    """
    schedules = await schedule.get_multi(
        db,
        teacher_id=current_teacher.id,
        skip=skip,
        limit=limit
    )
    
    return schedules


@router.get("/validate-slot", response_model=SlotValidationResponse)
async def validate_slot(
    day: str = Query(..., description="Día de la semana (monday, tuesday, etc)"),
    time: str = Query(..., description="Hora (ej: 15:00)"),
    format: str = Query(..., description="Formato (individual o group)"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Validar disponibilidad de un slot (día + hora) para inscribir un alumno

    Reglas de validación:
    - Un horario puede ser SOLO individual O SOLO grupal (no mezclar)
    - Horarios grupales tienen límite de 4 alumnos
    - Horarios individuales tienen límite de 1 alumno

    Args:
        day: Día de la semana (monday, tuesday, wednesday, etc)
        time: Hora de inicio (formato: "15:00" o "15:00:00")
        format: Formato deseado ("individual" o "group")
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)

    Returns:
        Información sobre disponibilidad del slot

    Example:
        GET /api/v1/schedules/validate-slot?day=monday&time=15:00&format=group

        Response:
        {
            "available": true,
            "message": "Horario Grupal con 2/4 alumnos",
            "current_students": 2,
            "max_students": 4,
            "existing_format": "group",
            "conflict": false
        }
    """
    # Validar formato
    try:
        class_format = ClassFormat.INDIVIDUAL if format == "individual" else ClassFormat.GROUP
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato inválido. Debe ser 'individual' o 'group'"
        )

    # Validar disponibilidad
    result = await schedule.validate_slot_availability(
        db,
        teacher_id=current_teacher.id,
        day=day,
        time=time,
        format=class_format
    )

    return result


@router.post("/", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    schedule_data: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Crear un horario nuevo (template recurrente)
    
    Este horario se usará para generar clases automáticamente
    Ejemplo: "Martes 16:00" → genera clases todos los martes
    
    Valida que el enrollment exista y pertenezca al profesor
    
    Args:
        schedule_data: Datos del horario a crear
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Horario creado con id asignado
    
    Raises:
        400: Si el enrollment no existe o no pertenece al profesor
    """
    # Validar que el enrollment existe y pertenece al profesor
    enrollment_obj = await enrollment.get(db, schedule_data.enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Inscripción {schedule_data.enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para crear horarios en esta inscripción"
        )
    
    # Asignar el teacher_id del profesor logueado
    schedule_data.teacher_id = current_teacher.id

    # Crear el horario (con validación de conflictos)
    try:
        new_schedule = await schedule.create(db, schedule_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

    return new_schedule


@router.get("/enrollment/{enrollment_id}", response_model=list[ScheduleResponse])
async def get_enrollment_schedules(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener todos los horarios de una inscripción
    
    Un alumno puede tener múltiples horarios para el mismo instrumento
    Ejemplo: Piano los Lunes 16:00 y Jueves 18:00
    
    Args:
        enrollment_id: ID de la inscripción
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Lista de horarios de la inscripción, ordenados por día y hora
    
    Raises:
        404: Si la inscripción no existe
        403: Si la inscripción no pertenece al profesor
    """
    # Validar que el enrollment existe y pertenece al profesor
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
    
    schedules = await schedule.get_by_enrollment(db, enrollment_id)
    
    return schedules


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener un horario específico por ID
    
    Args:
        schedule_id: ID del horario
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Datos del horario
    
    Raises:
        404: Si el horario no existe
        403: Si el horario no pertenece al profesor
    """
    schedule_obj = await schedule.get(db, schedule_id)
    
    if not schedule_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {schedule_id} no encontrado"
        )
    
    if schedule_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este horario"
        )
    
    return schedule_obj


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    schedule_data: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Actualizar un horario existente
    
    Solo actualiza los campos enviados (parcial)
    
    IMPORTANTE: Cambiar el horario NO afecta clases ya generadas
    Solo afecta las clases futuras que se generen
    
    Args:
        schedule_id: ID del horario a actualizar
        schedule_data: Datos a actualizar (solo campos no None)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Horario actualizado
    
    Raises:
        404: Si el horario no existe
        403: Si el horario no pertenece al profesor
    """
    # Verificar que existe y pertenece al profesor
    schedule_obj = await schedule.get(db, schedule_id)
    
    if not schedule_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {schedule_id} no encontrado"
        )
    
    if schedule_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar este horario"
        )
    
    # Actualizar (con validación de conflictos si cambia día/hora/duración)
    try:
        updated_schedule = await schedule.update(db, schedule_id, schedule_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )

    return updated_schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Eliminar un horario (eliminación física)
    
    IMPORTANTE: Esto NO elimina las clases ya generadas
    Solo evita que se generen nuevas clases en el futuro
    
    Args:
        schedule_id: ID del horario a eliminar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        204 No Content (sin body)
    
    Raises:
        404: Si el horario no existe
        403: Si el horario no pertenece al profesor
    """
    # Verificar que existe y pertenece al profesor
    schedule_obj = await schedule.get(db, schedule_id)
    
    if not schedule_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {schedule_id} no encontrado"
        )
    
    if schedule_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar este horario"
        )
    
    # Eliminar
    success = await schedule.delete(db, schedule_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar el horario"
        )
    
    return None  # 204 No Content