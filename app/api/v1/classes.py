"""
Classes endpoints - CRUD de clases específicas + recuperaciones
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import class_crud, enrollment
from app.models.teacher import Teacher
from app.schemas.class_schema import ClassCreate, ClassUpdate, ClassResponse

router = APIRouter()


@router.get("/", response_model=list[ClassResponse])
async def list_classes(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(100, ge=1, le=100, description="Máximo de registros"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Listar todas las clases del profesor logueado
    
    Ordenadas por fecha más reciente primero
    
    Args:
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Lista de clases del profesor
    """
    classes = await class_crud.get_multi(
        db,
        teacher_id=current_teacher.id,
        skip=skip,
        limit=limit
    )
    
    return classes


@router.get("/calendar", response_model=list[ClassResponse])
async def get_classes_by_date_range(
    start_date: date = Query(..., description="Fecha inicio (YYYY-MM-DD)"),
    end_date: date = Query(..., description="Fecha fin (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener clases en un rango de fechas (para vista de calendario)
    
    Útil para mostrar calendario mensual/semanal
    Ordenadas por fecha y hora
    
    Args:
        start_date: Fecha inicio (inclusiva)
        end_date: Fecha fin (inclusiva)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Lista de clases en el rango de fechas
    
    Example:
        GET /api/v1/classes/calendar?start_date=2025-02-01&end_date=2025-02-28
    """
    classes = await class_crud.get_by_date_range(
        db,
        teacher_id=current_teacher.id,
        start_date=start_date,
        end_date=end_date
    )
    
    return classes


@router.post("/", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
async def create_class(
    class_data: ClassCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Crear una clase nueva (genérica - NO usar para recuperaciones)
    
    Para crear recuperaciones usar POST /classes/recovery
    
    Valida que el enrollment exista y pertenezca al profesor
    
    Args:
        class_data: Datos de la clase a crear
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Clase creada con id asignado
    
    Raises:
        400: Si el enrollment no existe o no pertenece al profesor
    """
    # Validar que el enrollment existe y pertenece al profesor
    enrollment_obj = await enrollment.get(db, class_data.enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Inscripción {class_data.enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para crear clases en esta inscripción"
        )
    
    # Asignar el teacher_id del profesor logueado
    class_data.teacher_id = current_teacher.id
    
    # Crear la clase
    new_class = await class_crud.create(db, class_data)
    
    return new_class


@router.post("/recovery", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
async def create_recovery_class(
    class_data: ClassCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Crear una clase de recuperación
    
    Valida que haya créditos disponibles (>= 1)
    Descuenta -1 crédito automáticamente
    Fuerza type='recovery' aunque no se especifique
    
    Args:
        class_data: Datos de la clase a crear
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Clase de recuperación creada
    
    Raises:
        400: Si no hay créditos disponibles
        400: Si el enrollment no existe o no pertenece al profesor
    """
    # Validar que el enrollment existe y pertenece al profesor
    enrollment_obj = await enrollment.get(db, class_data.enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Inscripción {class_data.enrollment_id} no encontrada"
        )
    
    if enrollment_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para crear clases en esta inscripción"
        )
    
    # Asignar el teacher_id del profesor logueado
    class_data.teacher_id = current_teacher.id
    
    # Crear la recuperación (el CRUD valida créditos y descuenta automáticamente)
    try:
        new_recovery = await class_crud.create_recovery(db, class_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return new_recovery


@router.get("/{class_id}", response_model=ClassResponse)
async def get_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener una clase específica por ID
    
    Args:
        class_id: ID de la clase
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Datos de la clase
    
    Raises:
        404: Si la clase no existe
        403: Si la clase no pertenece al profesor
    """
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
    
    return class_obj


@router.patch("/{class_id}", response_model=ClassResponse)
async def update_class(
    class_id: int,
    class_data: ClassUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Actualizar una clase existente
    
    Solo actualiza los campos enviados (parcial)
    
    IMPORTANTE: NO permite cambiar el campo 'type'
    Para crear recuperaciones usar POST /classes/recovery
    
    Args:
        class_id: ID de la clase a actualizar
        class_data: Datos a actualizar (solo campos no None)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Clase actualizada
    
    Raises:
        404: Si la clase no existe
        403: Si la clase no pertenece al profesor
        400: Si se intenta cambiar el campo 'type'
    """
    # Verificar que existe y pertenece al profesor
    class_obj = await class_crud.get(db, class_id)
    
    if not class_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clase {class_id} no encontrada"
        )
    
    if class_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para actualizar esta clase"
        )
    
    # Actualizar (el CRUD bloquea cambio de 'type')
    try:
        updated_class = await class_crud.update(db, class_id, class_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return updated_class


@router.post("/{class_id}/cancel", response_model=ClassResponse)
async def cancel_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Cancelar una clase
    
    Cambia status a 'cancelled'
    Las clases canceladas NO se cobran
    Mantiene el registro (no elimina)
    
    Args:
        class_id: ID de la clase a cancelar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Clase cancelada
    
    Raises:
        404: Si la clase no existe
        403: Si la clase no pertenece al profesor
    """
    # Verificar que existe y pertenece al profesor
    class_obj = await class_crud.get(db, class_id)
    
    if not class_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clase {class_id} no encontrada"
        )
    
    if class_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para cancelar esta clase"
        )
    
    # Cancelar
    cancelled_class = await class_crud.cancel(db, class_id)
    
    return cancelled_class


@router.delete("/recovery/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recovery_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Eliminar una clase de recuperación (físicamente)
    
    Solo para recuperaciones creadas por error
    Valida que sea type='recovery' y NO tenga attendance
    Elimina la clase y devuelve +1 crédito al enrollment
    
    Args:
        class_id: ID de la clase de recuperación a eliminar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        204 No Content (sin body)
    
    Raises:
        404: Si la clase no existe
        403: Si la clase no pertenece al profesor
        400: Si no es recovery o tiene attendance marcado
    """
    # Verificar que existe y pertenece al profesor
    class_obj = await class_crud.get(db, class_id)
    
    if not class_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clase {class_id} no encontrada"
        )
    
    if class_obj.teacher_id != current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar esta clase"
        )
    
    # Eliminar (el CRUD valida que sea recovery y no tenga attendance)
    try:
        success = await class_crud.delete_recovery(db, class_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    return None  # 204 No Content