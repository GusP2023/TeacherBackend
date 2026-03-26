"""
Attendances endpoints - CRUD de asistencias (marca presente/ausente/licencia)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import attendance, class_crud
from app.models.teacher import Teacher
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate, AttendanceResponse
from app.api.v1.websocket import notify_data_change

router = APIRouter()


@router.get("/class/{class_id}", response_model=AttendanceResponse)
async def get_class_attendance(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener la asistencia de una clase específica
    
    Relación 1:1 - Una clase tiene máximo 1 attendance
    
    Args:
        class_id: ID de la clase
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Attendance si está marcada, 404 si no
    
    Raises:
        404: Si la clase no existe o no tiene attendance marcada
        403: Si la clase no pertenece al profesor
    """
    # Rechazar IDs no positivos temprano (IDs temporales negativos vienen del cliente)
    if class_id is None or class_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clase {class_id} no encontrada"
        )

    # Verificar que la clase existe y pertenece al profesor
    class_obj = await class_crud.get(db, class_id)
    
    if not class_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clase {class_id} no encontrada"
        )
    
    if class_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver esta clase"
        )
    
    # Obtener la asistencia
    attendance_obj = await attendance.get_by_class(db, class_id)
    
    if not attendance_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La clase {class_id} no tiene asistencia marcada"
        )
    
    return attendance_obj


@router.post("/", response_model=AttendanceResponse, status_code=status.HTTP_201_CREATED)
async def mark_attendance(
    attendance_data: AttendanceCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Marcar asistencia para una clase
    
    Si status es 'license', otorga +1 crédito automáticamente
    
    Args:
        attendance_data: Datos de la asistencia a crear
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Attendance creada
    
    Raises:
        404: Si la clase no existe
        403: Si la clase no pertenece al profesor
        400: Si ya existe attendance para esa clase
    """
    # Verificar que la clase existe y pertenece al profesor
    class_obj = await class_crud.get(db, attendance_data.class_id)
    
    if not class_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clase {attendance_data.class_id} no encontrada"
        )
    
    if class_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para marcar asistencia en esta clase"
        )
    
    # Crear la asistencia (el CRUD obtiene enrollment_id de la clase y maneja créditos)
    try:
        new_attendance = await attendance.create(db, attendance_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    await notify_data_change(current_teacher.id, "attendance", "create", new_attendance.id)
    
    return new_attendance


@router.get("/{attendance_id}", response_model=AttendanceResponse)
async def get_attendance(
    attendance_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener una asistencia específica por ID
    
    Args:
        attendance_id: ID de la asistencia
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Datos de la asistencia
    
    Raises:
        404: Si la asistencia no existe
        403: Si la asistencia no pertenece al profesor
    """
    attendance_obj = await attendance.get(db, attendance_id)
    
    if not attendance_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asistencia {attendance_id} no encontrada"
        )
    
    # Verificar que pertenece al profesor (a través de la clase relacionada)
    if not getattr(attendance_obj, "class_", None) or attendance_obj.class_.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver esta asistencia"
        )
    
    return attendance_obj


@router.delete("/{attendance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attendance(
    attendance_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Eliminar una asistencia
    
    IMPORTANTE: Si la asistencia era 'license', quita -1 crédito del enrollment
    
    Args:
        attendance_id: ID de la asistencia a eliminar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        204 No Content (sin body)
    
    Raises:
        404: Si la asistencia no existe
        403: Si la asistencia no pertenece al profesor
        400: Si era 'license' y el alumno ya usó los créditos
    """
    # Verificar que existe
    attendance_obj = await attendance.get(db, attendance_id)
    
    if not attendance_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asistencia {attendance_id} no encontrada"
        )
    
    # Verificar que pertenece al profesor (a través de la clase relacionada)
    if not getattr(attendance_obj, "class_", None) or attendance_obj.class_.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar esta asistencia"
        )
    
    # Eliminar
    try:
        await attendance.delete(db, attendance_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    await notify_data_change(current_teacher.id, "attendance", "delete", attendance_id)
    
    return None  # 204 No Content


@router.patch("/{attendance_id}", response_model=AttendanceResponse)
async def update_attendance(
    attendance_id: int,
    attendance_data: AttendanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Actualizar una asistencia existente
    
    Solo actualiza los campos enviados (parcial)
    
    IMPORTANTE: Si cambia el status de/a 'license', ajusta créditos automáticamente:
    - present/absent → license: +1 crédito
    - license → present/absent: -1 crédito (si tiene disponibles)
    
    Args:
        attendance_id: ID de la asistencia a actualizar
        attendance_data: Datos a actualizar (solo campos no None)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Asistencia actualizada
    
    Raises:
        404: Si la asistencia no existe
        403: Si la asistencia no pertenece al profesor
        400: Si intenta cambiar de 'license' pero ya usó los créditos
    """
    # Verificar que existe
    attendance_obj = await attendance.get(db, attendance_id)
    
    if not attendance_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asistencia {attendance_id} no encontrada"
        )
    
    # Verificar que pertenece al profesor (a través de la clase relacionada)
    if not getattr(attendance_obj, "class_", None) or attendance_obj.class_.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar esta asistencia"
        )
    
    # Actualizar (el CRUD maneja lógica de créditos automáticamente)
    try:
        updated_attendance = await attendance.update(db, attendance_id, attendance_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    await notify_data_change(current_teacher.id, "attendance", "update", updated_attendance.id)
    
    return updated_attendance