"""
Modelo PersonnelPayment - Liquidación de personal para un período definido.

El período es flexible: puede ser quincena, mes completo, o cualquier rango.
Se almacenan snapshots de tarifas para preservar histórico.

Clases cobrables = status='completed' AND attendance.status IN ('present','absent').
Las clases con attendance='license' NO cuentan.
"""

from datetime import date
from decimal import Decimal
from sqlalchemy import String, Integer, Date, ForeignKey, CheckConstraint, UniqueConstraint, Numeric, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .teacher import Teacher


class PersonnelPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"


class PersonnelPayment(Base, TimestampMixin):
    __tablename__ = "personnel_payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )

    # Período flexible (quincena, mes, etc.)
    period_from: Mapped[date] = mapped_column(Date, nullable=False, comment="Inicio del período")
    period_to:   Mapped[date] = mapped_column(Date, nullable=False, comment="Fin del período (inclusive)")

    # Snapshots del estado del teacher al momento de generar
    payment_mode_snapshot:       Mapped[str]            = mapped_column(String(20), nullable=False)
    tariff_individual_snapshot:  Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    tariff_group_snapshot:       Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fixed_amount_snapshot:       Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Conteo de clases cobrables (NULL si payment_mode='monthly_fixed')
    classes_individual_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    classes_group_count:      Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    # Montos
    amount_calculated: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    adjustment:        Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"),
                                                        comment="Bono (+) o descuento (-)")
    total_amount:      Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Estado
    status: Mapped[PersonnelPaymentStatus] = mapped_column(
        SQLEnum(PersonnelPaymentStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False, default=PersonnelPaymentStatus.PENDING, index=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Datos de factura (solo cuando status='paid')
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True,
                                                        comment="Ej: 001-001-0000123")
    invoice_date:   Mapped[date | None] = mapped_column(Date, nullable=True,
                                                         comment="Fecha de emisión de la factura")
    invoice_notes:  Mapped[str | None]  = mapped_column(Text, nullable=True)

    teacher: Mapped["Teacher"] = relationship(
        back_populates="personnel_payments", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint('teacher_id', 'period_from', 'period_to',
                         name='uq_personnel_payment_teacher_period'),
        CheckConstraint('period_from <= period_to',
                        name='check_personnel_payment_period_valid'),
    )

    def __repr__(self):
        return (f"<PersonnelPayment(id={self.id}, teacher_id={self.teacher_id}, "
                f"{self.period_from}→{self.period_to}, status='{self.status}')>")
