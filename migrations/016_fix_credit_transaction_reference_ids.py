"""
Migración para reparar reference_id en credit_transactions

Las transacciones viejas tienen reference_id=None, lo que impide que el FIFO
funcione correctamente para determinar qué licencias están recuperadas.

Este script asigna los reference_id correctos basándose en:
- LICENSE → attendance.id
- LICENSE_REVERSAL → attendance.id  
- RECOVERY_CLASS → class.id
- RECOVERY_CLASS_DELETED → class.id
"""

import asyncio
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from app.models.credit_transaction import CreditTransaction, CreditTransactionSource
from app.models.attendance import Attendance, AttendanceStatus
from app.models.class_model import Class
from app.core.database import get_db


async def fix_reference_ids():
    """Repara los reference_id de las transacciones de crédito"""
    
    async for db in get_db():
        print("Iniciando reparación de reference_id en credit_transactions...")
        
        # 1. Reparar transacciones LICENSE (deben apuntar a attendance.id)
        print("\n1. Reparando transacciones LICENSE...")
        license_txs_result = await db.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.source_type == CreditTransactionSource.LICENSE,
                CreditTransaction.reference_id.is_(None)
            )
        )
        license_txs = license_txs_result.scalars().all()
        print(f"   Encontradas {len(license_txs)} transacciones LICENSE con reference_id=None")
        
        for tx in license_txs:
            # Buscar la attendance correspondiente a esta licencia
            # Buscamos attendance con status='license' para el enrollment y fecha cercana a created_at
            attendance_result = await db.execute(
                select(Attendance)
                .join(Class, Attendance.class_id == Class.id)
                .where(
                    Class.enrollment_id == tx.enrollment_id,
                    Attendance.status == AttendanceStatus.LICENSE
                )
                .order_by(Attendance.created_at)
            )
            attendances = attendance_result.scalars().all()
            
            if attendances:
                # Tomar la primera attendance que coincida (debería ser única)
                attendance = attendances[0]
                await db.execute(
                    update(CreditTransaction)
                    .where(CreditTransaction.id == tx.id)
                    .values(reference_id=attendance.id)
                )
                print(f"   ✓ TX {tx.id}: reference_id → {attendance.id}")
            else:
                print(f"   ✗ TX {tx.id}: No se encontró attendance correspondiente")
        
        # 2. Reparar transacciones LICENSE_REVERSAL (deben apuntar a attendance.id)
        print("\n2. Reparando transacciones LICENSE_REVERSAL...")
        reversal_txs_result = await db.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.source_type == CreditTransactionSource.LICENSE_REVERSAL,
                CreditTransaction.reference_id.is_(None)
            )
        )
        reversal_txs = reversal_txs_result.scalars().all()
        print(f"   Encontradas {len(reversal_txs)} transacciones LICENSE_REVERSAL con reference_id=None")
        
        for tx in reversal_txs:
            # Buscar attendance que fue revertida (status cambió de license a otro)
            # Esto es más complejo, por ahora intentamos buscar por enrollment y fecha
            attendance_result = await db.execute(
                select(Attendance)
                .join(Class, Attendance.class_id == Class.id)
                .where(
                    Class.enrollment_id == tx.enrollment_id,
                    Attendance.created_at <= tx.created_at
                )
                .order_by(Attendance.created_at.desc())
            )
            attendances = attendance_result.scalars().all()
            
            if attendances:
                attendance = attendances[0]
                await db.execute(
                    update(CreditTransaction)
                    .where(CreditTransaction.id == tx.id)
                    .values(reference_id=attendance.id)
                )
                print(f"   ✓ TX {tx.id}: reference_id → {attendance.id}")
            else:
                print(f"   ✗ TX {tx.id}: No se encontró attendance correspondiente")
        
        # 3. Reparar transacciones RECOVERY_CLASS (deben apuntar a class.id)
        print("\n3. Reparando transacciones RECOVERY_CLASS...")
        recovery_txs_result = await db.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.source_type == CreditTransactionSource.RECOVERY_CLASS,
                CreditTransaction.reference_id.is_(None)
            )
        )
        recovery_txs = recovery_txs_result.scalars().all()
        print(f"   Encontradas {len(recovery_txs)} transacciones RECOVERY_CLASS con reference_id=None")
        
        for tx in recovery_txs:
            # Buscar la clase de recuperación correspondiente
            class_result = await db.execute(
                select(Class)
                .where(
                    Class.enrollment_id == tx.enrollment_id,
                    Class.type == 'recovery'
                )
                .order_by(Class.created_at)
            )
            classes = class_result.scalars().all()
            
            if classes:
                # Tomar la primera recovery class que coincida
                recovery_class = classes[0]
                await db.execute(
                    update(CreditTransaction)
                    .where(CreditTransaction.id == tx.id)
                    .values(reference_id=recovery_class.id)
                )
                print(f"   ✓ TX {tx.id}: reference_id → {recovery_class.id}")
            else:
                print(f"   ✗ TX {tx.id}: No se encontró recovery class correspondiente")
        
        # 4. Reparar transacciones RECOVERY_CLASS_DELETED (deben apuntar a class.id)
        print("\n4. Reparando transacciones RECOVERY_CLASS_DELETED...")
        deleted_txs_result = await db.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.source_type == CreditTransactionSource.RECOVERY_CLASS_DELETED,
                CreditTransaction.reference_id.is_(None)
            )
        )
        deleted_txs = deleted_txs_result.scalars().all()
        print(f"   Encontradas {len(deleted_txs)} transacciones RECOVERY_CLASS_DELETED con reference_id=None")
        
        for tx in deleted_txs:
            # Estas son más difíciles porque la clase ya fue borrada
            # Intentamos buscar por enrollment y fecha cercana
            class_result = await db.execute(
                select(Class)
                .where(
                    Class.enrollment_id == tx.enrollment_id,
                    Class.type == 'recovery'
                )
                .order_by(Class.created_at.desc())
            )
            classes = class_result.scalars().all()
            
            if classes:
                # Tomar la última recovery class (probablemente la que se borró)
                recovery_class = classes[0]
                await db.execute(
                    update(CreditTransaction)
                    .where(CreditTransaction.id == tx.id)
                    .values(reference_id=recovery_class.id)
                )
                print(f"   ✓ TX {tx.id}: reference_id → {recovery_class.id}")
            else:
                print(f"   ✗ TX {tx.id}: No se encontró recovery class correspondiente")
        
        await db.commit()
        print("\n✓ Migración completada. Commit realizado.")
        break


if __name__ == "__main__":
    asyncio.run(fix_reference_ids())
