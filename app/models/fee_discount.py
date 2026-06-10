"""
Modelo FeeDiscount - Descuentos temporales sobre la cuota mensual de un enrollment.
Permite definir descuentos porcentuales o fijos con vigencia por mes/año.
Ejemplo: 20% de descuento los primeros 3 meses, descuento por hermano, promoción.
"""

from decimal import Decimal
from sqlalchemy import String, Integer, Enum as SQLEnum, ForeignKey, CheckConstraint, Numeric, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .enrollment import Enrollment


class DiscountType(str, enum.Enum):
    """
    Tipo de descuento aplicado a la cuota mensual.
    
    - PERCENTAGE: Porcentaje sobre base_monthly_fee (ej: 20.00 = 20%)
    - FIXED: Monto fijo a descontar en Bs
    """
    PERCENTAGE = "percentage"
    FIXED = "fixed"


class FeeDiscount(Base, TimestampMixin):
    """
    Modelo de Descuento de Cuota.
    
    Permite definir descuentos temporales sobre la cuota mensual de un enrollment.
    Los descuentos pueden ser porcentuales o fijos, con vigencia por mes/año.
    
    Atributos principales:
        id: Identificador único del descuento
        enrollment_id: FK al enrollment al que aplica el descuento
        discount_type: Tipo de descuento (percentage o fixed)
        discount_value: Valor del descuento (porcentaje o monto fijo)
        
    Vigencia:
        valid_from_year: Año desde el que aplica el descuento
        valid_from_month: Mes desde el que aplica (1-12)
        valid_until_year: Año hasta el que aplica (NULL = indefinido)
        valid_until_month: Mes hasta el que aplica (NULL = indefinido)
        
    Metadatos:
        reason: Motivo del descuento (ej: 'Promo primer trimestre', 'Hermano de alumno')
        active: Si el descuento está activo
        
    Relaciones:
        enrollment: Enrollment al que pertenece el descuento
        
    Ejemplo de uso:
        # 20% de descuento los primeros 3 meses de 2025
        discount = FeeDiscount(
            enrollment_id=1,
            discount_type=DiscountType.PERCENTAGE,
            discount_value=20.00,
            valid_from_year=2025,
            valid_from_month=1,
            valid_until_year=2025,
            valid_until_month=3,
            reason="Promo primer trimestre"
        )
    """
    __tablename__ = "fee_discounts"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único del descuento"
    )
    
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID del enrollment al que aplica el descuento"
    )
    
    discount_type: Mapped[DiscountType] = mapped_column(
        SQLEnum(DiscountType, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        comment="Tipo de descuento: porcentaje o monto fijo"
    )
    
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Porcentaje (ej: 20.00 = 20%) o monto fijo en Bs según discount_type"
    )
    
    # ========================================
    # VIGENCIA
    # ========================================
    
    valid_from_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Año desde el que aplica el descuento (ej: 2025)"
    )
    
    valid_from_month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Mes desde el que aplica el descuento (1-12)"
    )
    
    valid_until_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Año hasta el que aplica (inclusive). NULL = indefinido"
    )
    
    valid_until_month: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Mes hasta el que aplica (inclusive, 1-12). NULL = indefinido"
    )
    
    # ========================================
    # METADATOS
    # ========================================
    
    reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Motivo del descuento (ej: 'Promo primer trimestre', 'Hermano de alumno')"
    )
    
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Si el descuento está activo"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    enrollment: Mapped["Enrollment"] = relationship(
        back_populates="fee_discounts",
        lazy="selectin"
    )

    # ========================================
    # CONSTRAINTS
    # ========================================
    
    __table_args__ = (
        CheckConstraint(
            'discount_value > 0',
            name='check_fee_discount_value_positive'
        ),
        CheckConstraint(
            'valid_from_month >= 1 AND valid_from_month <= 12',
            name='check_fee_discount_from_month_valid'
        ),
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<FeeDiscount(id={self.id}, enrollment_id={self.enrollment_id}, discount_type='{self.discount_type}', discount_value={self.discount_value})>"
