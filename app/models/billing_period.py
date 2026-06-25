"""
Modelo BillingPeriod - Deuda mensual generada automáticamente por enrollment activo.
Se genera un registro por mes por cada enrollment con status='active'.
Enrollments suspended o withdrawn NO generan BillingPeriod.
Almacena snapshot de montos al momento de generación para preservar histórico.
"""

from datetime import date
from decimal import Decimal
from sqlalchemy import String, Integer, Date, Enum as SQLEnum, ForeignKey, CheckConstraint, UniqueConstraint, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .enrollment import Enrollment
    from .payment import Payment


class BillingPeriodStatus(str, enum.Enum):
    """
    Estado del período de cobro.
    
    - PENDING: Generado, sin pagos aún
    - PARTIAL: Con pagos parciales (sum(payments) < final_amount)
    - PAID: Pagado completamente
    - WAIVED: Anulado/condonado manualmente por el admin
    """
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    WAIVED = "waived"


class BillingPeriod(Base, TimestampMixin):
    """
    Modelo de Período de Cobro.
    
    Representa la deuda mensual generada automáticamente por un enrollment activo.
    Se genera un registro por mes para cada enrollment con status='active'.
    Enrollments suspended o withdrawn NO generan BillingPeriod.
    
    Almacena snapshot de montos al momento de generación para preservar histórico:
    - base_amount: Copia de enrollment.base_monthly_fee al momento de generar
    - discount_applied: Monto total de descuento activo para este período
    - final_amount: Monto real a cobrar este mes (base_amount - discount_applied)
    
    Atributos principales:
        id: Identificador único del período
        enrollment_id: FK al enrollment que genera este período
        period_year: Año del período de cobro
        period_month: Mes del período de cobro (1-12)
        
    Montos (snapshot):
        base_amount: Cuota base al momento de generación
        discount_applied: Descuento aplicado este período
        final_amount: Monto final a cobrar
        
    Estado:
        status: Estado del período (pending, partial, paid, waived)
        due_date: Fecha límite de pago
        
    Relaciones:
        enrollment: Enrollment que genera este período
        payments: Pagos asociados a este período
        
    Ejemplo de uso:
        # Generar período de cobro para enero 2025
        billing_period = BillingPeriod(
            enrollment_id=1,
            period_year=2025,
            period_month=1,
            base_amount=200.00,
            discount_applied=40.00,
            final_amount=160.00,
            status=BillingPeriodStatus.PENDING,
            due_date=date(2025, 1, 5)
        )
    """
    __tablename__ = "billing_periods"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único del período de cobro"
    )
    
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID del enrollment que genera este período"
    )
    
    period_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Año del período. NULL para matricula/extra/clase_suelta"
    )
    
    period_month: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Mes del período (1-12). NULL para matricula/extra/clase_suelta"
    )
    
    # ========================================
    # MONTOS (SNAPSHOT)
    # ========================================
    
    base_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Copia de enrollment.base_monthly_fee al momento de generar"
    )
    
    discount_applied: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="Monto total de descuento activo para este período"
    )
    
    final_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Monto real a cobrar este mes (base_amount - discount_applied)"
    )
    
    # ========================================
    # ESTADO
    # ========================================
    
    status: Mapped[BillingPeriodStatus] = mapped_column(
        SQLEnum(BillingPeriodStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=BillingPeriodStatus.PENDING,
        nullable=False,
        index=True,
        comment="Estado del período: pendiente, parcial, pagado o anulado"
    )
    
    due_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Fecha límite de pago (ej: día 5 del mes correspondiente)"
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notas del administrador sobre este período"
    )

    charge_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="cuota",
        server_default="cuota",
        comment="Tipo de cobro: cuota | matricula | extra | clase_suelta"
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Descripción libre para cobros extra y clases sueltas"
    )

    quantity: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Para clase_suelta: cantidad de créditos a otorgar al pagar"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    enrollment: Mapped["Enrollment"] = relationship(
        back_populates="billing_periods",
        lazy="selectin"
    )
    
    payments: Mapped[List["Payment"]] = relationship(
        back_populates="billing_period",
        cascade="all, delete-orphan",
        lazy="noload"
    )

    # ========================================
    # CONSTRAINTS
    # ========================================
    
    __table_args__ = (
        CheckConstraint(
            'final_amount >= 0',
            name='check_billing_period_final_amount'
        ),
        # UniqueConstraint eliminado — reemplazado por índice parcial en DB
        # que solo aplica cuando period_year/month no son NULL (cuotas)
        # CheckConstraint de period_month también gestionado en DB (permite NULL)
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<BillingPeriod(id={self.id}, enrollment_id={self.enrollment_id}, period_year={self.period_year}, period_month={self.period_month}, status='{self.status}')>"
