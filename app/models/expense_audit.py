"""
Modelo ExpenseAudit - Historial de auditoría para gastos operativos.
Registra acciones de pago ('paid') y reversión ('reverted') con snapshot de cuenta y fecha de pago.
"""
from datetime import datetime, date
from sqlalchemy import String, Integer, Date, ForeignKey, CheckConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import TYPE_CHECKING
import enum

from .base import Base

if TYPE_CHECKING:
    from .expense import Expense
    from .teacher import Teacher
    from .cash_account import CashAccount


class ExpenseAuditAction(str, enum.Enum):
    PAID = "paid"
    REVERTED = "reverted"


class ExpenseAudit(Base):
    __tablename__ = "expense_audit"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    expense_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("expenses.id", ondelete="CASCADE"),
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

    reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("cash_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    paid_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    expense: Mapped["Expense"] = relationship(
        "Expense",
        back_populates="audit_entries",
        lazy="selectin",
    )

    performed_by: Mapped["Teacher"] = relationship(
        "Teacher",
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
            name="check_expense_audit_action",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ExpenseAudit(id={self.id}, expense_id={self.expense_id}, "
            f"action='{self.action}', performed_by_teacher_id={self.performed_by_teacher_id})>"
        )
