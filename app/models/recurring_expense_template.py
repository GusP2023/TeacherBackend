"""
Modelo RecurringExpenseTemplate - Plantilla para generación periódica de gastos operativos.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from sqlalchemy import String, Boolean, Numeric, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base
from .expense import ExpenseCategory

if TYPE_CHECKING:
    from .organization import Organization


class RecurringExpenseTemplate(Base):
    """
    Modelo de Plantilla de Gasto Recurrente.

    Define gastos habituales (ej: alquiler, internet, contabilidad) con monto por defecto
    que pueden generarse masivamente para cada período mensual en estado 'pending'.
    """
    __tablename__ = "recurring_expense_templates"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único de la plantilla"
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID de la organización a la que pertenece la plantilla"
    )

    category: Mapped[ExpenseCategory] = mapped_column(
        SQLEnum(
            ExpenseCategory,
            native_enum=False,
            values_callable=lambda x: [e.value for e in x]
        ),
        nullable=False,
        index=True,
        comment="Categoría del gasto operativo"
    )

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Descripción del gasto (ej: 'Alquiler sede central')"
    )

    default_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Monto por defecto para el gasto a generar"
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Indica si la plantilla está activa para generación mensual"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Fecha y hora de creación de la plantilla"
    )

    # ── Relaciones ──────────────────────────────────────────────────────
    organization: Mapped["Organization"] = relationship(
        back_populates="recurring_expense_templates",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<RecurringExpenseTemplate(id={self.id}, org={self.organization_id}, "
            f"category='{self.category}', amount={self.default_amount}, active={self.active})>"
        )
