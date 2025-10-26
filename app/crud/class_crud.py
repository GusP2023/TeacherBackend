"""
CRUD operations for Class model
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, date
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.enrollment import Enrollment
from app.schemas.class_schema import ClassCreate, ClassUpdate


async def get(db: AsyncSession, class_id: int) -> Class | None:
    """
    Obtener una clase por ID
    
    Args:
        db: Sesión de base de datos
        class_id: ID de la clase
    
    Returns:
        Class si existe, None si no
    """
    result = await db.execute(
        select(Class).where(Class.id == class_id)
    )
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    teacher_id: int,
    skip: int = 0,
    limit: int = 100
) -> list[Class]:
    """
    Obtener múltiples clases de un profesor
    
    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
    
    Returns:
        Lista de Classes del profesor, ordenadas por fecha/hora más reciente
    """
    result = await db.execute(
        select(Class)
        .where(Class.teacher_id == teacher_id)
        .offset(skip)
        .limit(limit)
        .order_by(Class.date.desc(), Class.time.desc())
    )
    return list(result.scalars().all())


async def get_by_date_range(
    db: AsyncSession,
    teacher_id: int,
    start_date: date,
    end_date: date
) -> list[Class]:
    """
    Obtener clases de un profesor en un rango de fechas
    
    Útil para vista de calendario mensual/semanal
    
    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
        start_date: Fecha inicio (inclusiva)
        end_date: Fecha fin (inclusiva)
    
    Returns:
        Lista de Classes en el rango, ordenadas por fecha/hora
    """
    result = await db.execute(
        select(Class)
        .where(
            Class.teacher_id == teacher_id,
            Class.date >= start_date,
            Class.date <= end_date
        )
        .order_by(Class.date, Class.time)
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, class_data: ClassCreate) -> Class:
    """
    Crear una clase nueva (genérica - para generación automática)
    
    Usada principalmente por el job que genera clases desde schedules.
    NO valida créditos ni descuenta nada.
    
    Args:
        db: Sesión de base de datos
        class_data: Datos de la clase a crear
    
    Returns:
        Class creada con id asignado
    """
    class_obj = Class(**class_data.model_dump())
    
    db.add(class_obj)
    await db.commit()
    await db.refresh(class_obj)
    
    return class_obj


async def create_recovery(
    db: AsyncSession,
    class_data: ClassCreate
) -> Class | None:
    """
    Crear una clase de recuperación (con validación de créditos)
    
    Valida que el enrollment tenga créditos disponibles (>= 1)
    Descuenta -1 crédito automáticamente
    
    Args:
        db: Sesión de base de datos
        class_data: Datos de la clase a crear (debe tener type='recovery')
    
    Returns:
        Class creada si hay créditos, None si no hay créditos suficientes
    
    Raises:
        ValueError: Si no hay créditos suficientes
    """
    # Obtener el enrollment
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == class_data.enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        raise ValueError(f"Enrollment {class_data.enrollment_id} no existe")
    
    # Validar créditos
    if enrollment.credits < 1:
        raise ValueError(f"No hay créditos disponibles. Créditos actuales: {enrollment.credits}")
    
    # Crear la clase de recuperación
    class_dict = class_data.model_dump()
    class_dict['type'] = ClassType.RECOVERY  # Forzar type='recovery'
    class_obj = Class(**class_dict)
    
    # Descontar crédito
    enrollment.credits -= 1
    
    # Guardar ambos cambios en una transacción
    db.add(class_obj)
    await db.commit()
    await db.refresh(class_obj)
    await db.refresh(enrollment)
    
    return class_obj


async def update(
    db: AsyncSession,
    class_id: int,
    class_data: ClassUpdate
) -> Class | None:
    """
    Actualizar una clase existente
    
    IMPORTANTE: NO permite cambiar el 'type' de la clase
    Para crear recuperaciones usar create_recovery()
    
    Args:
        db: Sesión de base de datos
        class_id: ID de la clase a actualizar
        class_data: Datos a actualizar (solo campos no None)
    
    Returns:
        Class actualizada si existe, None si no
    
    Raises:
        ValueError: Si se intenta cambiar el campo 'type'
    """
    # Obtener la clase
    result = await db.execute(
        select(Class).where(Class.id == class_id)
    )
    class_obj = result.scalar_one_or_none()
    
    if not class_obj:
        return None
    
    # Actualizar solo campos que no sean None
    update_data = class_data.model_dump(exclude_unset=True)
    
    # Bloquear cambio de type
    if 'type' in update_data:
        raise ValueError("No se puede cambiar el tipo de clase. Para crear recuperaciones usar create_recovery()")
    
    for field, value in update_data.items():
        setattr(class_obj, field, value)
    
    await db.commit()
    await db.refresh(class_obj)
    
    return class_obj


async def cancel(db: AsyncSession, class_id: int) -> Class | None:
    """
    Cancelar una clase
    
    Cambia status a 'cancelled'
    Las clases canceladas NO se cobran
    
    Args:
        db: Sesión de base de datos
        class_id: ID de la clase a cancelar
    
    Returns:
        Class cancelada si existe, None si no
    """
    # Obtener la clase
    result = await db.execute(
        select(Class).where(Class.id == class_id)
    )
    class_obj = result.scalar_one_or_none()
    
    if not class_obj:
        return None
    
    # Cancelar
    class_obj.status = ClassStatus.CANCELLED
    
    await db.commit()
    await db.refresh(class_obj)
    
    return class_obj


async def delete_recovery(db: AsyncSession, class_id: int) -> bool:
    """
    Eliminar una clase de recuperación (físicamente)
    
    Valida que sea type='recovery' y NO tenga attendance
    Elimina la clase y devuelve +1 crédito al enrollment
    
    Args:
        db: Sesión de base de datos
        class_id: ID de la clase de recuperación a eliminar
    
    Returns:
        True si se eliminó correctamente
    
    Raises:
        ValueError: Si no es recovery, tiene attendance, o no existe
    """
    # Obtener la clase
    result = await db.execute(
        select(Class).where(Class.id == class_id)
    )
    class_obj = result.scalar_one_or_none()
    
    if not class_obj:
        raise ValueError(f"Clase {class_id} no existe")
    
    # Validar que sea recovery
    if class_obj.type != ClassType.RECOVERY:
        raise ValueError(f"Solo se pueden eliminar clases de recuperación. Esta clase es tipo '{class_obj.type}'")
    
    # Validar que NO tenga attendance
    if class_obj.attendance:
        raise ValueError("No se puede eliminar una clase con asistencia marcada")
    
    # Obtener el enrollment
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        raise ValueError(f"Enrollment {class_obj.enrollment_id} no existe")
    
    # Devolver el crédito
    enrollment.credits += 1
    
    # Eliminar la clase físicamente
    await db.delete(class_obj)
    await db.commit()
    await db.refresh(enrollment)
    
    return True