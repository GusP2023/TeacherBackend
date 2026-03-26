"""
CRUD operations for Attendance model
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.attendance import Attendance, AttendanceStatus
from app.models.enrollment import Enrollment
from app.models.class_model import Class
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate


async def get(db: AsyncSession, attendance_id: int) -> Attendance | None:
    """
    Obtener una asistencia por ID
    
    Args:
        db: Sesión de base de datos
        attendance_id: ID de la asistencia
    
    Returns:
        Attendance si existe, None si no
    """
    result = await db.execute(
        select(Attendance).where(Attendance.id == attendance_id)
    )
    return result.scalar_one_or_none()


async def get_by_class(db: AsyncSession, class_id: int) -> Attendance | None:
    """
    Obtener la asistencia de una clase específica
    
    Relación 1:1 - Una clase tiene máximo 1 attendance
    
    Args:
        db: Sesión de base de datos
        class_id: ID de la clase
    
    Returns:
        Attendance si existe, None si no está marcada
    """
    result = await db.execute(
        select(Attendance).where(Attendance.class_id == class_id)
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, attendance_data: AttendanceCreate) -> Attendance:
    """
    Crear/marcar asistencia para una clase
    
    Si el status es 'license' o 'excused', otorga +1 crédito al enrollment automáticamente
    
    Args:
        db: Sesión de base de datos
        attendance_data: Datos de la asistencia a crear
    
    Returns:
        Attendance creada con id asignado
    
    Raises:
        ValueError: Si ya existe attendance para esa clase
        ValueError: Si la clase no existe
    """
    # Verificar que no exista attendance para esta clase
    existing = await get_by_class(db, attendance_data.class_id)
    if existing:
        raise ValueError(f"Ya existe asistencia marcada para la clase {attendance_data.class_id}")
    
    # Obtener la clase para conseguir el enrollment_id
    result = await db.execute(
        select(Class).where(Class.id == attendance_data.class_id)
    )
    class_obj = result.scalar_one_or_none()
    
    if not class_obj:
        raise ValueError(f"Clase {attendance_data.class_id} no encontrada")
    
    # Crear la asistencia
    attendance = Attendance(**attendance_data.model_dump())
    db.add(attendance)
    
    # Si es license o excused, otorgar crédito
    if attendance_data.status in (AttendanceStatus.LICENSE, AttendanceStatus.EXCUSED):
        result = await db.execute(
            select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
        )
        enrollment = result.scalar_one_or_none()
        
        if enrollment:
            enrollment.credits += 1
    
    await db.commit()
    await db.refresh(attendance)
    
    return attendance


async def delete(db: AsyncSession, attendance_id: int) -> bool:
    """
    Eliminar una asistencia
    
    IMPORTANTE: Si la asistencia era 'license' o 'excused', quita -1 crédito del enrollment
    
    Args:
        db: Sesión de base de datos
        attendance_id: ID de la asistencia a eliminar
    
    Returns:
        True si se eliminó, False si no existía
    
    Raises:
        ValueError: Si era license/excused y el alumno ya usó los créditos
    """
    # Obtener la asistencia con su clase
    result = await db.execute(
        select(Attendance).where(Attendance.id == attendance_id)
    )
    attendance = result.scalar_one_or_none()
    
    if not attendance:
        return False
    
    # Si era license o excused, quitar el crédito otorgado
    if attendance.status in (AttendanceStatus.LICENSE, AttendanceStatus.EXCUSED):
        # Obtener el enrollment_id desde la clase
        result = await db.execute(
            select(Class).where(Class.id == attendance.class_id)
        )
        class_obj = result.scalar_one_or_none()
        
        if class_obj:
            result = await db.execute(
                select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
            )
            enrollment = result.scalar_one_or_none()
            
            if enrollment:
                if enrollment.credits > 0:
                    enrollment.credits -= 1
                else:
                    raise ValueError("No se puede eliminar asistencia 'license' porque el alumno ya usó los créditos")
    
    await db.delete(attendance)
    await db.commit()
    
    return True


async def update(
    db: AsyncSession,
    attendance_id: int,
    attendance_data: AttendanceUpdate
) -> Attendance | None:
    """
    Actualizar una asistencia existente
    
    IMPORTANTE: Si cambia de/a 'license'/'excused', ajusta créditos automáticamente:
    - present/absent → license/excused: +1 crédito
    - license/excused → present/absent: -1 crédito
    
    Args:
        db: Sesión de base de datos
        attendance_id: ID de la asistencia a actualizar
        attendance_data: Datos a actualizar (solo campos no None)
    
    Returns:
        Attendance actualizada si existe, None si no
    """
    # Obtener la asistencia
    result = await db.execute(
        select(Attendance).where(Attendance.id == attendance_id)
    )
    attendance = result.scalar_one_or_none()
    
    if not attendance:
        return None
    
    # Actualizar solo campos que no sean None
    update_data = attendance_data.model_dump(exclude_unset=True)
    
    # Status que otorgan créditos
    credit_statuses = (AttendanceStatus.LICENSE, AttendanceStatus.EXCUSED)
    
    # Manejar cambios de status que afectan créditos
    if 'status' in update_data:
        old_status = attendance.status
        new_status = update_data['status']
        
        # Si cambia el status relacionado con license/excused
        if old_status != new_status:
            # Obtener el enrollment_id desde la clase
            result = await db.execute(
                select(Class).where(Class.id == attendance.class_id)
            )
            class_obj = result.scalar_one_or_none()
            
            if class_obj:
                result = await db.execute(
                    select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
                )
                enrollment = result.scalar_one_or_none()
                
                if enrollment:
                    # Caso 1: Cambia A license/excused (otorgar crédito)
                    if old_status not in credit_statuses and new_status in credit_statuses:
                        enrollment.credits += 1
                    
                    # Caso 2: Cambia DESDE license/excused (quitar crédito)
                    elif old_status in credit_statuses and new_status not in credit_statuses:
                        if enrollment.credits > 0:
                            enrollment.credits -= 1
                        else:
                            raise ValueError("No se puede cambiar de 'license' porque el alumno ya usó los créditos")
    
    # Aplicar cambios
    for field, value in update_data.items():
        setattr(attendance, field, value)
    
    await db.commit()
    await db.refresh(attendance)
    
    return attendance