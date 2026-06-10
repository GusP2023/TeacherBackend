"""
Modelo Payment - Pago recibido de una familia.
Puede estar vinculado a un BillingPeriod (cuota mensual) o ser independiente
(matrícula, cobro extra, recuperación).
La relación con el alumno/institución se obtiene a través de enrollment_id.
Opcionalmente puede tener un Invoice asociado (comprobante emitido).
"""

from datetime import date
from decimal import Decimal
from sqlalchemy import String, Integer, Date, Enum as SQLEnum, ForeignKey, Text, CheckConstraint, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .enrollment import Enrollment
    from .billing_period import BillingPeriod
    from .invoice import Invoice


class PaymentConcept(str, enum.Enum):
    """
    Concepto del pago.
    
    - CUOTA: Pago de cuota mensual
    - MATRICULA: Pago de matrícula de inscripción
    - EXTRA: Cobro extra (evento, material, examen, etc.)
    - RECUPERACION: Pago de clase de recuperación fuera del plan
    """
    CUOTA = "cuota"
    MATRICULA = "matricula"
    EXTRA = "extra"
    RECUPERACION = "recuperacion"


class PaymentMethod(str, enum.Enum):
    """
    Método de pago utilizado.
    
    - EFECTIVO: Pago en efectivo
    - TRANSFERENCIA: Transferencia bancaria
    - TARJETA: Pago con tarjeta de crédito/débito
    - OTRO: Otro método de pago
    """
    EFECTIVO = "efectivo"
    TRANSFERENCIA = "transferencia"
    TARJETA = "tarjeta"
    OTRO = "otro"


class Payment(Base, TimestampMixin):
    """
    Modelo de Pago.
    
    Representa un pago recibido de una familia.
    Puede estar vinculado a un BillingPeriod (cuota mensual) o ser independiente
    (matrícula, cobro extra, recuperación).
    La relación con el alumno/institución se obtiene a través de enrollment_id.
    Opcionalmente puede tener un Invoice asociado (comprobante emitido).
    
    Atributos principales:
        id: Identificador único del pago
        enrollment_id: FK al enrollment al que corresponde el pago
        billing_period_id: FK al período de cobro asociado (NULL si es matrícula, extra, etc.)
        invoice_id: FK al comprobante emitido (NULL si no se generó factura/recibo)
        
    Montos:
        amount: Monto del pago
        
    Detalles:
        concept: Concepto del pago (cuota, matrícula, extra, recuperación)
        payment_date: Fecha en que se realizó el pago
        payment_method: Método de pago utilizado
        notes: Notas adicionales sobre el pago
        
    Relaciones:
        enrollment: Enrollment al que corresponde el pago
        billing_period: Período de cobro asociado (opcional)
        invoice: Comprobante emitido (opcional)
        
    Ejemplo de uso:
        # Pago de cuota mensual
        payment = Payment(
            enrollment_id=1,
            billing_period_id=5,
            invoice_id=10,
            amount=160.00,
            concept=PaymentConcept.CUOTA,
            payment_date=date.today(),
            payment_method=PaymentMethod.EFECTIVO
        )
        
        # Pago de matrícula (sin billing_period)
        payment_matricula = Payment(
            enrollment_id=1,
            amount=100.00,
            concept=PaymentConcept.MATRICULA,
            payment_date=date.today(),
            payment_method=PaymentMethod.TRANSFERENCIA
        )
    """
    __tablename__ = "payments"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único del pago"
    )
    
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Enrollment al que corresponde el pago"
    )
    
    billing_period_id: Mapped[int | None] = mapped_column(
        ForeignKey("billing_periods.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Período de cobro asociado (NULL si es matrícula, extra, etc.)"
    )
    
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Comprobante emitido (NULL si no se generó factura/recibo)"
    )
    
    # ========================================
    # MONTOS
    # ========================================
    
    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Monto del pago"
    )
    
    # ========================================
    # DETALLES
    # ========================================
    
    concept: Mapped[PaymentConcept] = mapped_column(
        SQLEnum(PaymentConcept, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        comment="Concepto del pago: cuota, matrícula, extra o recuperación"
    )
    
    payment_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Fecha en que se realizó el pago"
    )
    
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PaymentMethod.EFECTIVO,
        comment="Método de pago utilizado"
    )
    
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notas adicionales sobre el pago"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    enrollment: Mapped["Enrollment"] = relationship(
        back_populates="payments",
        lazy="selectin"
    )
    
    billing_period: Mapped["BillingPeriod | None"] = relationship(
        back_populates="payments",
        lazy="selectin"
    )
    
    invoice: Mapped["Invoice | None"] = relationship(
        back_populates="payments",
        lazy="selectin"
    )

    # ========================================
    # CONSTRAINTS
    # ========================================
    
    __table_args__ = (
        CheckConstraint(
            'amount > 0',
            name='check_payment_amount_positive'
        ),
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Payment(id={self.id}, enrollment_id={self.enrollment_id}, amount={self.amount}, concept='{self.concept}')>"
