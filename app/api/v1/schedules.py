"""
Schedules endpoints - CRUD de horarios recurrentes (templates)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import date, time as time_module
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import schedule, enrollment
from app.models.teacher import Teacher
from app.models.class_model import ClassFormat
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate, ScheduleResponse, ChangeScheduleRequest, ChangeScheduleResponse, RemoveScheduleRequest, RemoveScheduleResponse
from app.api.v1.websocket import notify_data_change

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


# ========================================
# VERIFICACIÓN DE DISPONIBILIDAD (ANTES DE /{schedule_id} para evitar conflicto de rutas)
# ========================================

@router.get("/check-availability")
async def check_availability(
    day: str = Query(..., description="Día de la semana (monday-sunday)"),
    time: str = Query(..., description="Hora en formato HH:MM (ej: 16:00)"),
    from_date: date = Query(..., description="Fecha inicial (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="Fecha final (YYYY-MM-DD)"),
    exclude_enrollment_id: Optional[int] = Query(None, description="Excluir clases de este enrollment (para reactivación)"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Verifica disponibilidad de horario en rango de fechas.

    Query params:
    - day: monday, tuesday, wednesday, thursday, friday, saturday, sunday
    - time: HH:MM formato 24h (ej: 16:00)
    - from_date: Fecha inicial (YYYY-MM-DD)
    - to_date: Fecha final opcional (default: fin de año actual)
    - exclude_enrollment_id: Opcional, excluye clases de este enrollment (útil para reactivación)

    Returns:
        {
            "available": bool,
            "conflicts": [
                {
                    "date": "2025-08-05",
                    "type": "regular",
                    "student_id": 5,
                    "student_name": "Pedro García"
                }
            ]
        }
    """
    from app.schemas.suspension import ScheduleAvailabilityResponse, ScheduleConflict
    from app.crud.schedule import check_schedule_availability_dates

    # Validar day
    valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    if day.lower() not in valid_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Día inválido. Debe ser uno de: {', '.join(valid_days)}"
        )

    # Validar time formato
    try:
        time_obj = time_module.fromisoformat(time)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de hora inválido. Use HH:MM (ej: 16:00)"
        )

    # Verificar disponibilidad
    conflicts_data = await check_schedule_availability_dates(
        db=db,
        day=day,
        time_str=time,
        teacher_id=current_teacher.id,
        from_date=from_date,
        to_date=to_date,
        exclude_enrollment_id=exclude_enrollment_id
    )

    # Formatear respuesta
    conflicts = [
        ScheduleConflict(
            date=c['date'],
            type=c['type'],
            student_id=c['student_id'],
            student_name=c['student_name']
        )
        for c in conflicts_data
    ]

    return ScheduleAvailabilityResponse(
        available=len(conflicts) == 0,
        conflicts=conflicts
    )


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

    await notify_data_change(current_teacher.id, "schedule", "create", new_schedule.id)
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

    await notify_data_change(current_teacher.id, "schedule", "update", updated_schedule.id)
    return updated_schedule


@router.put("/{schedule_id}/remove", response_model=dict)
async def remove_schedule_with_date(
    schedule_id: int,
    data: RemoveScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Elimina un horario desde una fecha específica (soft-delete con histórico).
    
    Validaciones:
    - Schedule debe existir y pertenecer al profesor
    - No puede haber clases con asistencia desde remove_from
    - No puede haber recuperaciones futuras en ese día/hora
    
    Acciones:
    - Elimina clases regulares scheduled desde remove_from
    - Marca schedule como inactivo: valid_until=remove_from, active=False
    - Mantiene histórico del schedule (NO elimina físicamente)
    
    Returns:
        200: Schedule eliminado exitosamente
        400: Schedule no existe o no pertenece al profesor
        409: Hay conflictos que impiden la eliminación
    """
    from app.crud.schedule import remove_schedule_with_history
    
    # Verificar que schedule existe y pertenece al profesor
    schedule_obj = await schedule.get(db, schedule_id)
    
    if not schedule_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Horario no encontrado"
        )
    
    if schedule_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar este horario"
        )
    
    # Verificar que está activo
    if not schedule_obj.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El horario ya no está activo"
        )
    
    # Validar que remove_from es presente o futuro
    from datetime import date as date_module
    today = date_module.today()
    
    if data.remove_from < today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de eliminación no puede ser en el pasado"
        )
    
    # Ejecutar eliminación
    try:
        result = await remove_schedule_with_history(
            db=db,
            schedule_id=schedule_id,
            remove_from=data.remove_from
        )
        await notify_data_change(current_teacher.id, "schedule", "remove", result["schedule_id"])
        
        return {
            "schedule_id": result["schedule_id"],
            "classes_deleted": result["classes_deleted"],
            "valid_until": result["valid_until"].isoformat(),
            "message": result["message"]
        }
    
    except ValueError as e:
        # Conflictos de validación → 409
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    
    except Exception as e:
        # Error inesperado → 500
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar horario: {str(e)}"
        )


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    ⚠️ DEPRECADO: No usar este endpoint.
    
    Usar PUT /{schedule_id}/remove con fecha específica para mantener histórico.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Endpoint deprecado. Usar PUT /{schedule_id}/remove con fecha 'remove_from'"
    )


# ========================================
# CAMBIO DE HORARIO
# ========================================

@router.put("/{schedule_id}/change", response_model=ChangeScheduleResponse)
async def change_schedule_endpoint(
    schedule_id: int,
    data: ChangeScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Cambia el horario de un alumno de forma atómica.

    Flujo:
    1. Valida que el schedule existe y pertenece al profesor
    2. Valida que está activo
    3. Llama a change_schedule() (transacción atómica)

    Errores:
    - 404: Schedule no encontrado o no pertenece al profesor
    - 400: Schedule inactivo, horario igual al actual, o clases con asistencia
    - 409: Recuperaciones en conflicto con el nuevo horario
    - 500: Error interno
    """
    from app.crud.schedule import change_schedule

    # Verificar que existe y pertenece al profesor
    schedule_obj = await schedule.get(db, schedule_id)

    if not schedule_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Horario no encontrado"
        )

    if schedule_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar este horario"
        )

    # Verificar que está activo
    if not schedule_obj.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El horario ya no está activo"
        )

    # Ejecutar cambio atómico
    try:
        result = await change_schedule(
            db=db,
            schedule_id=schedule_id,
            new_day=data.new_day,
            new_time=data.new_time,
            change_from=data.change_from
        )

        # Notify teacher about schedule change (new schedule created)
        await notify_data_change(current_teacher.id, "schedule", "change", result["new_schedule_id"])

        return ChangeScheduleResponse(
            old_schedule_id=result["old_schedule_id"],
            new_schedule_id=result["new_schedule_id"],
            classes_deleted=result["classes_deleted"],
            classes_generated=result["classes_generated"],
            message="Horario cambiado exitosamente"
        )

    except ValueError as e:
        error_msg = str(e)

        # Recuperaciones en conflicto → 409
        if "recuperaciones" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg
            )

        # Resto de errores de validación → 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al cambiar horario: {str(e)}"
        )
