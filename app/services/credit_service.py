"""
Servicio centralizado para la gestión de créditos.

Este servicio es el único punto de entrada para modificar los créditos de las
inscripciones (enrollments). Centraliza la lógica de actualización, evitando
modificaciones directas dispersas en el código, insertando las transacciones
históricas correspondientes y manejando la concurrencia/idempotencia.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.enrollment import Enrollment
from app.models.credit_transaction import (
    CreditTransaction,
    CreditTransactionSource,
    CreditTransactionReferenceType,
)


async def apply(
    db: AsyncSession,
    enrollment: Enrollment,
    amount: int,
    source_type: CreditTransactionSource,
    reference_id: int | None = None,
    reference_type: CreditTransactionReferenceType | None = None,
    note: str | None = None,
    created_by: int | None = None,
    consumed_credit_tx_id: int | None = None,
) -> CreditTransaction | None:
    """
    Aplica un cambio al balance de créditos de una inscripción.

    Valida que los créditos resultantes no sean negativos. Actualiza el balance en
    memoria y registra la transacción en el historial. Maneja silenciosamente
    los casos de duplicados mediante la captura de IntegrityError al hacer db.flush().

    Args:
        db: Sesión asíncrona de base de datos.
        enrollment: Inscripción a afectar (debe estar cargada en la sesión).
        amount: Cantidad de créditos a sumar (positivo) o restar (negativo).
        source_type: Tipo de origen de la transacción.
        reference_id: ID de la entidad relacionada a la transacción (opcional).
        reference_type: Tipo de la entidad relacionada (opcional).
        note: Nota explicativa (opcional, requerida para ajustes manuales).
        created_by: ID del usuario/profesor que realiza la acción (opcional).
        consumed_credit_tx_id: ID de la transacción de crédito que consume esta RECOVERY_CLASS (opcional).

    Returns:
        CreditTransaction: La transacción creada si fue exitosa.
        None: Si la transacción se ignoró por idempotencia (ya existía).

    Raises:
        ValueError: Si los créditos resultantes son menores a cero.
    """
    if enrollment.credits + amount < 0:
        raise ValueError(f"Créditos insuficientes. Balance actual: {enrollment.credits}, cambio solicitado: {amount}")

    enrollment.credits += amount

    transaction = CreditTransaction(
        enrollment_id=enrollment.id,
        amount=amount,
        source_type=source_type,
        reference_id=reference_id,
        reference_type=reference_type,
        note=note,
        created_by=created_by,
        consumed_credit_tx_id=consumed_credit_tx_id,
    )
    db.add(transaction)

    try:
        await db.flush()
    except IntegrityError:
        # Revert changes if transaction already exists (idempotency check via unique index)
        enrollment.credits -= amount
        return None

    return transaction


async def apply_manual(
    db: AsyncSession,
    enrollment: Enrollment,
    new_credits: int,
    note: str,
    created_by: int,
) -> CreditTransaction | None:
    """
    Aplica un ajuste manual al balance de créditos estableciendo un nuevo valor fijo.

    Calcula la diferencia necesaria (delta) y delega la ejecución a apply().

    Args:
        db: Sesión asíncrona de base de datos.
        enrollment: Inscripción a afectar (debe estar cargada en la sesión).
        new_credits: Nuevo valor total de créditos a establecer.
        note: Nota obligatoria explicando el motivo del ajuste.
        created_by: ID del usuario/profesor que autoriza el ajuste.

    Returns:
        CreditTransaction: La transacción creada si el delta es distinto de 0.
        None: Si no hay cambio en el balance (delta == 0).

    Raises:
        ValueError: Si new_credits es menor a cero.
    """
    delta = new_credits - enrollment.credits
    if delta == 0:
        return None

    if new_credits < 0:
        raise ValueError("El valor de créditos no puede ser negativo.")

    return await apply(
        db=db,
        enrollment=enrollment,
        amount=delta,
        source_type=CreditTransactionSource.MANUAL_ADJUSTMENT,
        reference_id=None,
        reference_type=None,
        note=note,
        created_by=created_by,
    )
