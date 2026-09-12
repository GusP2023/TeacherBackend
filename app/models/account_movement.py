"""
Modelo AccountMovement - Movimientos de caja/banco (aportes, retiros, ajustes y transferencias).
"""

from datetime import date, datetime
from decimal import Decimal
import enum
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Date, Numeric, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base

if TYPE_CHECKING:
    from .organization import Organization
    from .cash_account import CashAccount
    from .teacher import Teacher


class AccountMovementType(str, enum.Enum):
    APORTE_CAPITAL = "aporte_capital"
    RETIRO_CAPITAL = "retiro_capital"
    AJUSTE = "ajuste"
    TRANSFERENCIA_SALIDA = "transferencia_salida"
    TRANSFERENCIA_ENTRADA = "transferencia_entrada"


class AccountMovement(Base):
    """
    Modelo de Movimiento de Cuenta Financiera.

    Registra transferencias entre cuentas de la institución o movimientos de
    aporte/retiro de capital y ajustes manuales.
    """
    __tablename__ = "account_movements"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único del movimiento"
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID de la organización"
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey("cash_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID de la cuenta financiera principal afectada"
    )

    related_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_accounts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="ID de la cuenta contraparte (en transferencias)"
    )

    movement_type: Mapped[AccountMovementType] = mapped_column(
        SQLEnum(
            AccountMovementType,
            native_enum=False,
            values_callable=lambda x: [e.value for e in x]
        ),
        nullable=False,
        index=True,
        comment="Tipo de movimiento (aporte, retiro, ajuste, transferencia)"
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Monto del movimiento (positivo)"
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Descripción o motivo del movimiento"
    )

    movement_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Fecha en que se efectuó el movimiento"
    )

    created_by_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID del usuario/profesor que registró el movimiento"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Fecha y hora de registro del movimiento"
    )

    # ── Relaciones ──────────────────────────────────────────────────────
    organization: Mapped["Organization"] = relationship(
        lazy="selectin"
    )

    account: Mapped["CashAccount"] = relationship(
        "CashAccount",
        foreign_keys=[account_id],
        lazy="selectin"
    )

    related_account: Mapped[Optional["CashAccount"]] = relationship(
        "CashAccount",
        foreign_keys=[related_account_id],
        lazy="selectin"
    )

    created_by: Mapped["Teacher"] = relationship(
        "Teacher",
        foreign_keys=[created_by_teacher_id],
        lazy="selectin"
    )

    @property
    def related_account_name(self) -> str | None:
        return self.related_account.name if self.related_account else None

    @property
    def created_by_teacher_name(self) -> str:
        return self.created_by.name if self.created_by else ""

    def __repr__(self) -> str:
        return (
            f"<AccountMovement(id={self.id}, account_id={self.account_id}, "
            f"type='{self.movement_type}', amount={self.amount})>"
        )
