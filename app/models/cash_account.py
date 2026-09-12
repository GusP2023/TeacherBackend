"""
Modelo CashAccount - Cuenta de caja o banco de la organización.

Permite registrar y conciliar saldos iniciales, ingresos, egresos y movimientos de capital.
"""

from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .organization import Organization


class CashAccount(Base, TimestampMixin):
    """
    Modelo de Cuenta Financiera (Caja / Banco).

    Representa una cuenta de origen/destino de fondos para la institución.
    El saldo actual se calcula dinámicamente a partir del opening_balance
    y los movimientos/gastos/pagos asociados.

    Atributos:
        id: Identificador único de la cuenta
        organization_id: FK a la organización
        name: Nombre identificatorio (ej: 'Caja Chica', 'Banco BCP', 'Efectivo Recepción')
        opening_balance: Saldo inicial con el que parte la cuenta (no editable)
        active: Si la cuenta está activa para operar
    """
    __tablename__ = "cash_accounts"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único de la cuenta"
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID de la organización a la que pertenece la cuenta"
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Nombre de la cuenta (ej: 'Banco Central', 'Caja Chica')"
    )

    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="Saldo inicial histórico de la cuenta"
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Indica si la cuenta está activa"
    )

    # ── Relaciones ──────────────────────────────────────────────────────
    organization: Mapped["Organization"] = relationship(
        back_populates="cash_accounts",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<CashAccount(id={self.id}, name='{self.name}', active={self.active})>"
