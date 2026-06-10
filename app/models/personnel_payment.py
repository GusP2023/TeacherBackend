"""
Modelo PersonnelPayment - Liquidación mensual de cualquier miembro del personal.
Cubre todos los roles del sistema: teacher, org_admin, coordinator, administrative.
Para payment_mode='per_class': amount_calculated = clases cobrables × tariff.
Para payment_mode='monthly_fixed': amount_calculated = fixed_amount_snapshot.
Para payment_mode='mixed': amount_calculated = ambos sumados.
Se almacenan snapshots de tarifas para preservar histórico aunque cambien en el futuro.

Clases cobrables = clases con status='completed' Y attendance.status IN ('present','absent').
Las clases con attendance.status='license' NO cuentan (pero sí cuentan cuando
se recuperan y la recovery tiene present/absent).
"""

from datetime import date
from decimal import Decimal
from sqlalchemy import String, Integer, Date, Enum as SQLEnum, ForeignKey, CheckConstraint, UniqueConstraint, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .teacher import Teacher


class PersonnelPaymentStatus(str, enum.Enum):
    """
    Estado de la liquidación de personal.
    
    - PENDING: Generado, pendiente de pago
    - PAID: Pagado al empleado
    """
    PENDING = "pending"
    PAID = "paid"


class PersonnelPayment(Base, TimestampMixin):
    """
    Modelo de Liquidación de Personal.
    
    Representa la liquidación mensual de cualquier miembro del personal.
    Cubre todos los roles del sistema: teacher, org_admin, coordinator, administrative.
    
    Cálculo del monto según payment_mode:
    - per_class: amount_calculated = clases cobrables × tariff
    - monthly_fixed: amount_calculated = fixed_amount_snapshot
    - mixed: amount_calculated = ambos sumados
    
    Clases cobrables = clases con status='completed' Y attendance.status IN ('present','absent').
    Las clases con attendance.status='license' NO cuentan (pero sí cuentan cuando
    se recuperan y la recovery tiene present/absent).
    
    Se almacenan snapshots de tarifas para preservar histórico aunque cambien en el futuro.
    
    Atributos principales:
        id: Identificador único de la liquidación
        teacher_id: FK al teacher/personal a liquidar
        period_year: Año del período de liquidación
        period_month: Mes del período de liquidación (1-12)
        
    Snapshots del estado al momento de generar:
        payment_mode_snapshot: Copia de teacher.payment_mode
        tariff_individual_snapshot: Copia de teacher.tariff_individual
        tariff_group_snapshot: Copia de teacher.tariff_group
        fixed_amount_snapshot: Copia de teacher.monthly_salary
        
    Conteo de clases cobrables:
        classes_individual_count: Clases individuales cobrables en el período
        classes_group_count: Clases grupales cobrables en el período
        
    Montos:
        amount_calculated: Monto calculado automáticamente por el sistema
        adjustment: Ajuste manual del mes (bonus positivo o descuento negativo)
        total_amount: Monto final a pagar (amount_calculated + adjustment)
        
    Estado:
        status: Estado de la liquidación (pending, paid)
        paid_date: Fecha en que se efectuó el pago (NULL si aún pending)
        notes: Notas adicionales
        
    Relaciones:
        teacher: Teacher/personal a liquidar
        
    Ejemplo de uso:
        # Liquidación para profesor con payment_mode='per_class'
        payment = PersonnelPayment(
            teacher_id=1,
            period_year=2025,
            period_month=1,
            payment_mode_snapshot="per_class",
            tariff_individual_snapshot=50.00,
            tariff_group_snapshot=35.00,
            classes_individual_count=20,
            classes_group_count=10,
            amount_calculated=1350.00,  # 20×50 + 10×35
            adjustment=0,
            total_amount=1350.00,
            status=PersonnelPaymentStatus.PENDING
        )
    """
    __tablename__ = "personnel_payments"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único de la liquidación"
    )
    
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID del teacher/personal a liquidar"
    )
    
    period_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Año del período de liquidación"
    )
    
    period_month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Mes del período de liquidación (1-12)"
    )
    
    # ========================================
    # SNAPSHOTS DEL ESTADO
    # ========================================
    
    payment_mode_snapshot: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Copia de teacher.payment_mode al momento de generar"
    )
    
    tariff_individual_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Copia de teacher.tariff_individual al momento de generar"
    )
    
    tariff_group_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Copia de teacher.tariff_group al momento de generar"
    )
    
    fixed_amount_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Copia de teacher.monthly_salary al momento de generar"
    )
    
    # ========================================
    # CONTEO DE CLASES COBRABLES
    # ========================================
    
    classes_individual_count: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        comment="Clases individuales cobrables (present o absent) en el período"
    )
    
    classes_group_count: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        comment="Clases grupales cobrables (present o absent) en el período"
    )
    
    # ========================================
    # MONTOS
    # ========================================
    
    amount_calculated: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Monto calculado automáticamente por el sistema"
    )
    
    adjustment: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="Ajuste manual del mes (bonus positivo o descuento negativo)"
    )
    
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Monto final a pagar (amount_calculated + adjustment)"
    )
    
    # ========================================
    # ESTADO
    # ========================================
    
    status: Mapped[PersonnelPaymentStatus] = mapped_column(
        SQLEnum(PersonnelPaymentStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=PersonnelPaymentStatus.PENDING,
        nullable=False,
        index=True,
        comment="Estado de la liquidación: pendiente o pagado"
    )
    
    paid_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Fecha en que se efectuó el pago (NULL si aún pending)"
    )
    
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notas adicionales sobre la liquidación"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    teacher: Mapped["Teacher"] = relationship(
        back_populates="personnel_payments",
        lazy="selectin"
    )

    # ========================================
    # CONSTRAINTS
    # ========================================
    
    __table_args__ = (
        UniqueConstraint(
            'teacher_id',
            'period_year',
            'period_month',
            name='uq_personnel_payment_teacher_month'
        ),
        CheckConstraint(
            'period_month >= 1 AND period_month <= 12',
            name='check_personnel_payment_month_valid'
        ),
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<PersonnelPayment(id={self.id}, teacher_id={self.teacher_id}, period_year={self.period_year}, period_month={self.period_month}, status='{self.status}')>"
