"""
Modelo Expense - Gasto operativo de la organización.
Cubre costos sin persona asignada: alquiler, servicios, materiales, etc.
Los sueldos del personal con acceso al sistema van en PersonnelPayment.
El campo 'recurring' es informativo (recordatorio visual), NO auto-genera registros.
"""

from datetime import date
from sqlalchemy import String, Integer, Date, Enum as SQLEnum, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .organization import Organization


class ExpenseCategory(str, enum.Enum):
    """
    Categoría del gasto operativo.
    
    - ALQUILER: Pago de alquiler del local
    - SERVICIOS: Luz, agua, internet, teléfono
    - MATERIALES: Insumos, útiles, instrumentos
    - MARKETING: Publicidad y marketing
    - MANTENIMIENTO: Mantenimiento de instalaciones
    - OTRO: Otros gastos no categorizados
    """
    ALQUILER = "alquiler"
    SERVICIOS = "servicios"
    MATERIALES = "materiales"
    MARKETING = "marketing"
    MANTENIMIENTO = "mantenimiento"
    OTRO = "otro"


class Expense(Base, TimestampMixin):
    """
    Modelo de Gasto Operativo.
    
    Representa un gasto operativo de la organización.
    Cubre costos sin persona asignada: alquiler, servicios, materiales, etc.
    Los sueldos del personal con acceso al sistema van en PersonnelPayment.
    
    El campo 'recurring' es informativo (recordatorio visual), NO auto-genera registros.
    
    Atributos principales:
        id: Identificador único del gasto
        organization_id: FK a la organización que registra el gasto
        amount: Monto del gasto
        category: Categoría del gasto
        description: Descripción del gasto
        expense_date: Fecha del gasto
        
    Metadatos:
        recurring: Indica si es un gasto habitual (solo informativo, no auto-genera registros)
        receipt_note: Referencia del comprobante (número de factura, recibo, etc.)
        
    Relaciones:
        organization: Organización que registra el gasto
        
    Ejemplo de uso:
        # Gasto de alquiler mensual
        expense = Expense(
            organization_id=1,
            amount=1500.00,
            category=ExpenseCategory.ALQUILER,
            description="Alquiler mes de marzo 2025",
            expense_date=date(2025, 3, 1),
            recurring=True,
            receipt_note="Factura #12345"
        )
    """
    __tablename__ = "expenses"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único del gasto"
    )
    
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID de la organización que registra el gasto"
    )
    
    # ========================================
    # MONTOS
    # ========================================
    
    amount: Mapped["Decimal"] = mapped_column(
        "amount",
        None,
        nullable=False,
        comment="Monto del gasto"
    )
    
    # ========================================
    # CATEGORÍA Y DESCRIPCIÓN
    # ========================================
    
    category: Mapped[ExpenseCategory] = mapped_column(
        SQLEnum(ExpenseCategory, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
        comment="Categoría del gasto: alquiler, servicios, materiales, etc."
    )
    
    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Descripción del gasto (ej: 'Alquiler mes de marzo', 'Factura ENDE')"
    )
    
    expense_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Fecha del gasto"
    )
    
    # ========================================
    # METADATOS
    # ========================================
    
    recurring: Mapped[bool] = mapped_column(
        None,
        default=False,
        nullable=False,
        comment="Indica si es un gasto habitual (solo informativo, no auto-genera registros)"
    )
    
    receipt_note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Referencia del comprobante (número de factura, recibo, etc.)"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    organization: Mapped["Organization"] = relationship(
        back_populates="expenses",
        lazy="selectin"
    )

    # ========================================
    # CONSTRAINTS
    # ========================================
    
    __table_args__ = (
        CheckConstraint(
            'amount > 0',
            name='check_expense_amount_positive'
        ),
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Expense(id={self.id}, organization_id={self.organization_id}, amount={self.amount}, category='{self.category}')>"
