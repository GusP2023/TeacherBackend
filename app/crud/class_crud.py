"""
CRUD operations for Class model
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, not_, exists
from sqlalchemy.orm import aliased
from datetime import datetime, date
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.enrollment import Enrollment
from app.services import credit_service
from app.models.credit_transaction import CreditTransactionSource, CreditTransactionReferenceType
from app.schemas.class_schema import ClassCreate, ClassUpdate

logger = logging.getLogger(__name__)


async def get(db: AsyncSession, class_id: int) -> Class | None:
    """
    Obtener una clase por ID
    
    Args:
        db: Sesión de base de datos
        class_id: ID de la clase
    
    Returns:
        Class si existe, None si no
    """
    # Guardar contra IDs no positivos (IDs temporales negativos desde cliente)
    # Evita pasar valores fuera de rango a asyncpg (int32) y lanzar excepciones 500
    if class_id is None or class_id <= 0:
        return None

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
    Crear una clase nueva (genérica - para generación automática o eventos extra)
    
    VALIDACIÓN:
    - type='regular' o 'recovery' → enrollment_id es OBLIGATORIO
    - type='extra' → enrollment_id puede ser None (evento sin alumno)
    - Validación de duplicados: No puede existir otra clase con mismo enrollment_id, date, time, type
    
    Args:
        db: Sesión de base de datos
        class_data: Datos de la clase a crear
    
    Returns:
        Class creada con id asignado
    
    Raises:
        ValueError: Si falta enrollment_id para type regular/recovery, o si ya existe una clase duplicada
    """
    # Validar enrollment_id según el tipo
    if class_data.type in [ClassType.REGULAR, ClassType.RECOVERY]:
        if not class_data.enrollment_id:
            raise ValueError(f"enrollment_id es obligatorio para clases de tipo '{class_data.type.value}'")
    
    # Validar duplicados: No puede existir clase con mismo enrollment_id + date + time + type
    # (excepto si es CANCELLED, que permite recrear)
    if class_data.enrollment_id:
        duplicate_result = await db.execute(
            select(Class).where(
                and_(
                    Class.enrollment_id == class_data.enrollment_id,
                    Class.date == class_data.date,
                    Class.time == class_data.time,
                    Class.type == class_data.type,
                    Class.status != ClassStatus.CANCELLED,
                )
            )
        )
        existing_class = duplicate_result.scalar_one_or_none()
        if existing_class:
            logger.warning(
                f"create: duplicada enrollment {class_data.enrollment_id} "
                f"{class_data.date} {class_data.time} type={class_data.type.value} "
                f"(ID existente {existing_class.id})"
            )
            raise ValueError(
                f"Ya existe una clase {class_data.type.value} para este enrollment "
                f"en {class_data.date} {class_data.time}"
            )
    
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
    Descuenta -1 crédito automáticamente y vincula la transacción RECOVERY_CLASS
    al crédito específico que consume (LICENSE o MANUAL_ADJUSTMENT) usando FIFO.

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

    # Validar que no exista ya una recuperación para el mismo enrollment+fecha+hora.
    # Esto previene duplicados por doble-tap o reintento de sync concurrente.
    duplicate_result = await db.execute(
        select(Class).where(
            and_(
                Class.enrollment_id == class_data.enrollment_id,
                Class.date == class_data.date,
                Class.time == class_data.time,
                Class.type == ClassType.RECOVERY,
                Class.status != ClassStatus.CANCELLED,
            )
        )
    )
    existing_recovery = duplicate_result.scalar_one_or_none()
    if existing_recovery:
        logger.warning(
            f"create_recovery: duplicada enrollment {class_data.enrollment_id} "
            f"{class_data.date} {class_data.time} (ID existente {existing_recovery.id})"
        )
        raise ValueError(
            f"Ya existe una recuperación para esta inscripción el "
            f"{class_data.date} a las {str(class_data.time)[:5]} (ID: {existing_recovery.id})"
        )

    # Buscar créditos disponibles (LICENSE o MANUAL_ADJUSTMENT) que no hayan sido consumidos
    # Un crédito está disponible si no existe ninguna RECOVERY_CLASS con consumed_credit_tx_id apuntando a él
    from app.models.credit_transaction import CreditTransaction

    # Alias para la tabla de recovery transactions
    RecoveryTx = aliased(CreditTransaction, name='recovery_tx')

    # Subquery: verificar si existe alguna RECOVERY_CLASS que consuma este crédito
    consumed_subq = exists(
        select(1)
        .where(
            RecoveryTx.consumed_credit_tx_id == CreditTransaction.id,
            RecoveryTx.source_type == CreditTransactionSource.RECOVERY_CLASS
        )
    )

    available_credits_result = await db.execute(
        select(CreditTransaction)
        .where(
            CreditTransaction.enrollment_id == class_data.enrollment_id,
            CreditTransaction.source_type.in_([
                CreditTransactionSource.LICENSE,
                CreditTransactionSource.MANUAL_ADJUSTMENT
            ]),
            CreditTransaction.amount > 0,  # Solo créditos positivos
            # No está consumido por ninguna RECOVERY_CLASS
            not_(consumed_subq)
        )
        .order_by(CreditTransaction.created_at.asc())
    )
    available_credits = available_credits_result.scalars().all()

    if not available_credits:
        raise ValueError(f"No hay créditos disponibles para consumir. Créditos actuales: {enrollment.credits}")

    # FIFO: tomar el crédito más antiguo disponible
    credit_to_consume = available_credits[0]

    # Crear la clase de recuperación
    class_dict = class_data.model_dump()
    class_dict['type'] = ClassType.RECOVERY  # Forzar type='recovery'

    # Si el enrollment todavía tiene partial_sessions activas, moverlas a la clase de recuperación.
    partial_sessions = class_dict.get('partial_sessions') or []
    if not partial_sessions and enrollment.partial_sessions:
        partial_sessions = enrollment.partial_sessions
    class_dict['partial_sessions'] = partial_sessions
    enrollment.partial_sessions = []

    class_obj = Class(**class_dict)

    # Flush para obtener el ID de la clase antes de crear la transacción
    db.add(class_obj)
    await db.flush()

    await credit_service.apply(
        db=db,
        enrollment=enrollment,
        amount=-1,
        source_type=CreditTransactionSource.RECOVERY_CLASS,
        reference_id=class_obj.id,
        reference_type=CreditTransactionReferenceType.CLASS,
        consumed_credit_tx_id=credit_to_consume.id,
    )

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
    Libera el consumed_credit_tx_id para que el crédito pueda ser consumido nuevamente

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

    # Obtener el enrollment
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
    )
    enrollment = result.scalar_one_or_none()

    if not enrollment:
        raise ValueError(f"Enrollment {class_obj.enrollment_id} no existe")

    # Buscar la transacción RECOVERY_CLASS original para liberar el consumed_credit_tx_id
    from app.models.credit_transaction import CreditTransaction
    recovery_tx_result = await db.execute(
        select(CreditTransaction).where(
            CreditTransaction.enrollment_id == class_obj.enrollment_id,
            CreditTransaction.source_type == CreditTransactionSource.RECOVERY_CLASS,
            CreditTransaction.reference_id == class_obj.id
        )
    )
    recovery_tx = recovery_tx_result.scalar_one_or_none()

    # Liberar el consumed_credit_tx_id si existe
    if recovery_tx and recovery_tx.consumed_credit_tx_id is not None:
        recovery_tx.consumed_credit_tx_id = None

    await credit_service.apply(
        db=db,
        enrollment=enrollment,
        amount=1,
        source_type=CreditTransactionSource.RECOVERY_CLASS_DELETED,
        reference_id=class_obj.id,
        reference_type=CreditTransactionReferenceType.CLASS,
    )

    # Eliminar la clase físicamente
    await db.delete(class_obj)
    await db.commit()
    await db.refresh(enrollment)

    return True