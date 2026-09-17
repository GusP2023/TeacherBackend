"""
Modelo PersonnelPaymentAudit - Historial de auditoría para pagos de personal.
Registra acciones de pago ('paid') y reversión ('reverted') con snapshot de datos de factura.
"""
from datetime import datetime, date
from sqlalchemy import String, Integer, Date, ForeignKey, CheckConstraint, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import TYPE_CHECKING

from .base import Base

if TYPE_CHECKING:
    from .personnel_payment import PersonnelPayment
    from .teacher import Teacher
    from .cash_account import CashAccount


class PersonnelPaymentAudit(Base):
    __tablename__ = "personnel_payment_audit"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    payment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("personnel_payments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    performed_by_teacher_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("cash_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_date:   Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_notes:  Mapped[str | None]  = mapped_column(Text, nullable=True)
    reason:         Mapped[str | None]  = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    payment: Mapped["PersonnelPayment"] = relationship(
        "PersonnelPayment",
        back_populates="audit_entries",
        lazy="selectin",
    )

    performed_by: Mapped["Teacher"] = relationship(
        "Teacher",
        back_populates="personnel_payment_audits",
        lazy="selectin",
    )

    account: Mapped["CashAccount | None"] = relationship(
        "CashAccount",
        lazy="selectin",
    )

    @property
    def performed_by_teacher_name(self) -> str:
        return self.performed_by.name if self.performed_by else ""

    @property
    def account_name(self) -> str | None:
        return self.account.name if self.account else None

    __table_args__ = (
        CheckConstraint(
            "action IN ('paid', 'reverted')",
            name="check_personnel_payment_audit_action",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PersonnelPaymentAudit(id={self.id}, payment_id={self.payment_id}, "
            f"action='{self.action}', performed_by_teacher_id={self.performed_by_teacher_id})>"
        )
