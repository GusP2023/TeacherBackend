"""
Utilidades para el procesamiento de créditos.

Contiene funciones puras para calcular resúmenes e historial de créditos
sin depender de conexiones a la base de datos ni operaciones asíncronas.
"""

from app.models.credit_transaction import (
    CreditTransaction,
    CreditTransactionSource,
)


def calculate_credit_summary(
    transactions: list[CreditTransaction],
    year: int,
    month: int,
) -> dict:
    """
    Calcula el resumen de créditos (licencias y recuperaciones) de un mes específico
    a partir del historial completo de transacciones.
    
    Esta función es pura y no tiene acceso a base de datos. El algoritmo empareja
    cronológicamente las licencias otorgadas con las clases de recuperación consumidas,
    teniendo en cuenta las cancelaciones/reversiones y ajustes manuales.
    
    Args:
        transactions: Lista completa del historial de CreditTransaction del enrollment.
        year: Año a filtrar para las licencias.
        month: Mes a filtrar para las licencias.
        
    Returns:
        Un diccionario con el resumen de licencias, recuperaciones pendientes y ajustes manuales.
    """
    # PASO 1 - Identificar transacciones canceladas
    reversed_att_ids = {
        tx.reference_id 
        for tx in transactions 
        if tx.source_type == CreditTransactionSource.LICENSE_REVERSAL and tx.reference_id is not None
    }
    deleted_cls_ids = {
        tx.reference_id 
        for tx in transactions 
        if tx.source_type == CreditTransactionSource.RECOVERY_CLASS_DELETED and tx.reference_id is not None
    }

    # PASO 2 - Filtrar transacciones activas por tipo
    active_licenses = []
    active_recoveries = []
    manual_adjustments = []

    for tx in transactions:
        if tx.source_type == CreditTransactionSource.LICENSE:
            if tx.reference_id not in reversed_att_ids:
                if tx.created_at.year == year and tx.created_at.month == month:
                    active_licenses.append(tx)
        elif tx.source_type == CreditTransactionSource.RECOVERY_CLASS:
            if tx.reference_id not in deleted_cls_ids:
                active_recoveries.append(tx)
        elif tx.source_type == CreditTransactionSource.MANUAL_ADJUSTMENT:
            manual_adjustments.append(tx)

    # PASO 3 - Armar lista de eventos cronológicos
    events = []
    for tx in active_licenses:
        events.append((tx.created_at, 0, 'license', tx))
    for tx in manual_adjustments:
        events.append((tx.created_at, 1, 'manual', tx))
    for tx in active_recoveries:
        events.append((tx.created_at, 2, 'recovery', tx))

    events.sort(key=lambda e: (e[0], e[1]))

    # PASO 4 - Procesar eventos con colas
    license_queue = []
    manual_pool = 0
    paired = []
    
    for _, _, tag, tx in events:
        if tag == 'license':
            license_queue.append(tx)
        elif tag == 'manual':
            manual_pool += tx.amount
        elif tag == 'recovery':
            if license_queue:
                paired.append((license_queue.pop(0), tx))
            elif manual_pool > 0:
                manual_pool -= 1

    pending = list(license_queue)

    # PASO 5 - Construir respuesta
    detail = [
        {
            "attendance_id": lic.reference_id,
            "license_date": lic.created_at.date().isoformat(),
            "recovered_by_class_id": rec.reference_id,
            "recovery_date": rec.created_at.date().isoformat(),
        }
        for lic, rec in paired
    ] + [
        {
            "attendance_id": lic.reference_id,
            "license_date": lic.created_at.date().isoformat(),
            "recovered_by_class_id": None,
            "recovery_date": None,
        }
        for lic in pending
    ]

    manual_adjustments_sorted = [
        {
            "amount": tx.amount,
            "note": tx.note,
            "created_at": tx.created_at.isoformat(),
            "created_by": tx.created_by,
        }
        for tx in sorted(manual_adjustments, key=lambda t: t.created_at)
    ]

    return {
        "year": year,
        "month": month,
        "licenses_total": len(active_licenses),
        "licenses_recovered": len(paired),
        "licenses_pending": len(pending),
        "manual_adjustments_count": len(manual_adjustments),
        "detail": detail,
        "manual_adjustments": manual_adjustments_sorted,
    }
