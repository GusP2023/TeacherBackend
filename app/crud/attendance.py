"""
CRUD operations for Attendance model
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.attendance import Attendance, AttendanceStatus
from app.models.enrollment import Enrollment
from app.models.class_model import Class, ClassStatus
from app.services import credit_service
from app.models.credit_transaction import CreditTransactionSource, CreditTransactionReferenceType
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
    
    Si el status es 'license', otorga +1 crédito al enrollment automáticamente
    
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

    # Flush para obtener el ID de la asistencia antes de crear la transacción
    await db.flush()

    # Marcar la clase como completada
    class_obj.status = ClassStatus.COMPLETED

    # Si es license, otorgar crédito y registrar transacción
    if attendance_data.status == AttendanceStatus.LICENSE:
        result = await db.execute(
            select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
        )
        enrollment = result.scalar_one_or_none()

        if enrollment:
            await credit_service.apply(
                db=db,
                enrollment=enrollment,
                amount=1,
                source_type=CreditTransactionSource.LICENSE,
                reference_id=attendance.id,
                reference_type=CreditTransactionReferenceType.ATTENDANCE,
            )

    await db.commit()
    await db.refresh(attendance)

    return attendance


async def delete(db: AsyncSession, attendance_id: int) -> bool:
    """
    Eliminar una asistencia
    
    IMPORTANTE: Si la asistencia era 'license', quita -1 crédito del enrollment
    
    Args:
        db: Sesión de base de datos
        attendance_id: ID de la asistencia a eliminar
    
    Returns:
        True si se eliminó, False si no existía
    
    Raises:
        ValueError: Si era license y el alumno ya usó los créditos
    """
    # Obtener la asistencia con su clase
    result = await db.execute(
        select(Attendance).where(Attendance.id == attendance_id)
    )
    attendance = result.scalar_one_or_none()
    
    if not attendance:
        return False

    # Obtener la clase para revertir su estado
    result = await db.execute(
        select(Class).where(Class.id == attendance.class_id)
    )
    class_obj = result.scalar_one_or_none()

    # Si era license, quitar el crédito otorgado y registrar transacción
    if attendance.status == AttendanceStatus.LICENSE:

        if class_obj:
            result = await db.execute(
                select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
            )
            enrollment = result.scalar_one_or_none()

            if enrollment:
                # Buscar la transacción LICENSE original para liberar el consumed_credit_tx_id
                from app.models.credit_transaction import CreditTransaction
                license_tx_result = await db.execute(
                    select(CreditTransaction).where(
                        CreditTransaction.enrollment_id == class_obj.enrollment_id,
                        CreditTransaction.source_type == CreditTransactionSource.LICENSE,
                        CreditTransaction.reference_id == attendance.id
                    )
                )
                license_tx = license_tx_result.scalar_one_or_none()

                # Liberar el consumed_credit_tx_id si existe (algun RECOVERY_CLASS consumió esta licencia)
                if license_tx:
                    # Buscar RECOVERY_CLASS que consumió esta licencia y liberarla
                    recovery_tx_result = await db.execute(
                        select(CreditTransaction).where(
                            CreditTransaction.consumed_credit_tx_id == license_tx.id,
                            CreditTransaction.source_type == CreditTransactionSource.RECOVERY_CLASS
                        )
                    )
                    recovery_tx = recovery_tx_result.scalar_one_or_none()
                    if recovery_tx:
                        recovery_tx.consumed_credit_tx_id = None

                try:
                    await credit_service.apply(
                        db=db,
                        enrollment=enrollment,
                        amount=-1,
                        source_type=CreditTransactionSource.LICENSE_REVERSAL,
                        reference_id=attendance.id,
                        reference_type=CreditTransactionReferenceType.ATTENDANCE,
                    )
                except ValueError:
                    raise ValueError("No se puede eliminar asistencia 'license' porque el alumno ya usó los créditos")

    await db.delete(attendance)
    if class_obj:
        class_obj.status = ClassStatus.SCHEDULED
    await db.commit()

    return True


async def update(
    db: AsyncSession,
    attendance_id: int,
    attendance_data: AttendanceUpdate
) -> Attendance | None:
    """
    Actualizar una asistencia existente
    
    IMPORTANTE: Si cambia de/a 'license', ajusta créditos automáticamente:
    - present/absent → license: +1 crédito
    - license → present/absent: -1 crédito
    
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
    
    # Manejar cambios de status que afectan créditos
    if 'status' in update_data:
        old_status = attendance.status
        new_status = update_data['status']
        
        # Si cambia el status relacionado con license
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
                    # Caso 1: Cambia A license (otorgar crédito)
                    if old_status != AttendanceStatus.LICENSE and new_status == AttendanceStatus.LICENSE:
                        license_tx = await credit_service.apply(
                            db=db,
                            enrollment=enrollment,
                            amount=1,
                            source_type=CreditTransactionSource.LICENSE,
                            reference_id=attendance.id,
                            reference_type=CreditTransactionReferenceType.ATTENDANCE,
                        )
                        if license_tx is None:
                            raise ValueError("La licencia ya estaba activa para esta asistencia")

                    # Caso 2: Cambia DESDE license (quitar crédito)
                    elif old_status == AttendanceStatus.LICENSE and new_status != AttendanceStatus.LICENSE:
                        # Buscar la transacción LICENSE original para liberar el consumed_credit_tx_id
                        from app.models.credit_transaction import CreditTransaction
                        license_tx_result = await db.execute(
                            select(CreditTransaction).where(
                                CreditTransaction.enrollment_id == class_obj.enrollment_id,
                                CreditTransaction.source_type == CreditTransactionSource.LICENSE,
                                CreditTransaction.reference_id == attendance.id
                            )
                        )
                        license_tx = license_tx_result.scalar_one_or_none()

                        # Liberar el consumed_credit_tx_id si existe (algun RECOVERY_CLASS consumió esta licencia)
                        if license_tx:
                            # Buscar RECOVERY_CLASS que consumió esta licencia y liberarla
                            recovery_tx_result = await db.execute(
                                select(CreditTransaction).where(
                                    CreditTransaction.consumed_credit_tx_id == license_tx.id,
                                    CreditTransaction.source_type == CreditTransactionSource.RECOVERY_CLASS
                                )
                            )
                            recovery_tx = recovery_tx_result.scalar_one_or_none()
                            if recovery_tx:
                                recovery_tx.consumed_credit_tx_id = None

                        try:
                            reversal_tx = await credit_service.apply(
                                db=db,
                                enrollment=enrollment,
                                amount=-1,
                                source_type=CreditTransactionSource.LICENSE_REVERSAL,
                                reference_id=attendance.id,
                                reference_type=CreditTransactionReferenceType.ATTENDANCE,
                            )
                            if reversal_tx is None:
                                raise ValueError("La reversión de licencia ya estaba aplicada")
                        except ValueError as exc:
                            raise ValueError(str(exc)) from exc
    
    # Aplicar cambios
    for field, value in update_data.items():
        setattr(attendance, field, value)
    
    await db.commit()
    await db.refresh(attendance)
    
    return attendance