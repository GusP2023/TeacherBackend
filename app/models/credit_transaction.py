"""
Modelo CreditTransaction - Ledger de transacciones de créditos de recuperación.

Este modelo almacena el historial completo de todas las operaciones que afectan
el balance de créditos de un enrollment. Permite trazabilidad completa del origen
y consumo de créditos.

Relaciones:
- N:1 con Enrollment (muchas transacciones pertenecen a una inscripción)
- N:1 con Teacher (quién hizo el ajuste manual, opcional)

Tipos de transacción (source_type):
- license: Otorgado por marcar asistencia como licencia (+1)
- license_reversal: Revocado por desmarcar licencia (-1)
- recovery_class: Consumido por crear clase de recuperación (-1)
- recovery_class_deleted: Devuelto por eliminar clase de recuperación (+1)
- manual_adjustment: Ajuste manual directo (puede ser + o -)

Tipos de referencia (reference_type):
- attendance: La transacción se originó desde un registro de asistencia
- class: La transacción se originó desde una clase
- null: Ajuste manual sin referencia específica
"""

from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Optional
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .enrollment import Enrollment
    from .teacher import Teacher


class CreditTransactionSource(str, enum.Enum):
    """
    Tipo de origen de la transacción de crédito.
    
    - LICENSE: Otorgado por marcar licencia en asistencia
    - LICENSE_REVERSAL: Revocado por desmarcar licencia
    - RECOVERY_CLASS: Consumido por crear clase de recuperación
    - RECOVERY_CLASS_DELETED: Devuelto por eliminar clase de recuperación
    - MANUAL_ADJUSTMENT: Ajuste manual directo por admin/profesor
    """
    LICENSE = "license"
    LICENSE_REVERSAL = "license_reversal"
    RECOVERY_CLASS = "recovery_class"
    RECOVERY_CLASS_DELETED = "recovery_class_deleted"
    MANUAL_ADJUSTMENT = "manual_adjustment"


class CreditTransactionReferenceType(str, enum.Enum):
    """
    Tipo de referencia a la entidad que originó la transacción.
    
    - ATTENDANCE: Referencia a un registro de attendance
    - CLASS: Referencia a una clase
    """
    ATTENDANCE = "attendance"
    CLASS = "class"


class CreditTransaction(Base, TimestampMixin):
    """
    Modelo de Transacción de Crédito.
    
    Representa una operación que afecta el balance de créditos de un enrollment.
    Cada vez que enrollment.credits cambia, se debe crear un registro aquí.
    
    Atributos principales:
        id: Identificador único de la transacción
        enrollment_id: FK a la inscripción afectada
        amount: Cantidad de créditos (+ para otorgar, - para consumir)
        source_type: Tipo de origen de la transacción
        reference_type: Tipo de entidad de referencia (opcional)
        reference_id: ID de la entidad de referencia (opcional)
        note: Nota explicativa (útil para ajustes manuales)
        created_by: ID del teacher que hizo el ajuste (opcional)
        
    Balance:
        El balance actual (enrollment.credits) se mantiene denormalizado
        para performance. Esta tabla es solo para trazabilidad histórica.
        
    Ejemplo de uso:
        # Licencia otorgada
        tx1 = CreditTransaction(
            enrollment_id=1,
            amount=1,
            source_type=CreditTransactionSource.LICENSE,
            reference_type=CreditTransactionReferenceType.ATTENDANCE,
            reference_id=42
        )
        
        # Clase de recuperación creada
        tx2 = CreditTransaction(
            enrollment_id=1,
            amount=-1,
            source_type=CreditTransactionSource.RECOVERY_CLASS,
            reference_type=CreditTransactionReferenceType.CLASS,
            reference_id=100
        )
        
        # Ajuste manual
        tx3 = CreditTransaction(
            enrollment_id=1,
            amount=2,
            source_type=CreditTransactionSource.MANUAL_ADJUSTMENT,
            note="Créditos extra por reclamo",
            created_by=5
        )
    """
    __tablename__ = "credit_transactions"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único de la transacción"
    )
    
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID de la inscripción afectada"
    )
    
    # ========================================
    # MONTO Y ORIGEN
    # ========================================

    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Cantidad de créditos (+ para otorgar, - para consumir)"
    )

    source_type: Mapped[CreditTransactionSource] = mapped_column(
        SQLEnum(CreditTransactionSource, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        comment="Tipo de origen de la transacción"
    )

    # ========================================
    # VÍNCULO DE CONSUMO (para RECOVERY_CLASS)
    # ========================================

    consumed_credit_tx_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("credit_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="ID de la transacción de crédito (LICENSE o MANUAL_ADJUSTMENT) que consumió esta transacción RECOVERY_CLASS. Solo aplica a débitos."
    )
    
    # ========================================
    # REFERENCIA (opcional)
    # ========================================
    
    reference_type: Mapped[Optional[CreditTransactionReferenceType]] = mapped_column(
        SQLEnum(CreditTransactionReferenceType, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        comment="Tipo de entidad de referencia (attendance, class)"
    )
    
    reference_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="ID de la entidad de referencia (attendance_id, class_id)"
    )
    
    # ========================================
    # NOTAS Y AUTOR
    # ========================================
    
    note: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Nota explicativa. Obligatoria para MANUAL_ADJUSTMENT."
    )
    
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="ID del teacher que hizo el ajuste manual (null para transacciones automáticas)"
    )
    
    # ========================================
    # RELACIONES
    # ========================================
    
    enrollment: Mapped["Enrollment"] = relationship(
        back_populates="credit_transactions",
        lazy="selectin"
    )
    
    created_by_teacher: Mapped[Optional["Teacher"]] = relationship(
        lazy="selectin"
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return (
            f"<CreditTransaction(id={self.id}, enrollment_id={self.enrollment_id}, "
            f"amount={self.amount}, source_type='{self.source_type}')>"
        )
