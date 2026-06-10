"""
Modelo Invoice - Comprobante o factura emitida a un cliente.
Numeración correlativa por organización (1, 2, 3...).
Un Invoice puede tener múltiples Payments asociados.
La relación con el alumno se obtiene a través de Payment → Enrollment.
"""

from datetime import date
from sqlalchemy import String, Integer, Date, Enum as SQLEnum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .organization import Organization
    from .payment import Payment


class InvoiceStatus(str, enum.Enum):
    """
    Estado del comprobante/factura.
    
    - DRAFT: Borrador, aún no emitido
    - ISSUED: Emitido y entregado al cliente
    - CANCELLED: Anulado
    """
    DRAFT = "draft"
    ISSUED = "issued"
    CANCELLED = "cancelled"


class Invoice(Base, TimestampMixin):
    """
    Modelo de Comprobante/Factura.
    
    Representa un comprobante o factura emitida a un cliente.
    La numeración es correlativa por organización (1, 2, 3...).
    Un Invoice puede tener múltiples Payments asociados.
    La relación con el alumno se obtiene a través de Payment → Enrollment.
    
    Atributos principales:
        id: Identificador único del comprobante
        organization_id: FK a la organización que emite el comprobante
        invoice_number: Número correlativo por organización
        issued_date: Fecha de emisión del comprobante
        
    Montos:
        total_amount: Monto total del comprobante
        
    Detalles:
        concept_detail: Detalle del concepto (texto libre para imprimir en el recibo)
        status: Estado del comprobante (draft, issued, cancelled)
        
    Relaciones:
        organization: Organización que emite el comprobante
        payments: Pagos asociados a este comprobante
        
    Ejemplo de uso:
        # Emitir factura #5 para la organización 1
        invoice = Invoice(
            organization_id=1,
            invoice_number=5,
            issued_date=date.today(),
            total_amount=200.00,
            concept_detail="Cuota mensual enero 2025 - María González",
            status=InvoiceStatus.ISSUED
        )
    """
    __tablename__ = "invoices"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="Identificador único del comprobante"
    )
    
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="ID de la organización que emite el comprobante"
    )
    
    invoice_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Número correlativo por organización (se incrementa por org)"
    )
    
    issued_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Fecha de emisión del comprobante"
    )
    
    # ========================================
    # MONTOS
    # ========================================
    
    total_amount: Mapped["Decimal"] = mapped_column(
        "total_amount",
        None,
        nullable=False,
        comment="Monto total del comprobante"
    )
    
    # ========================================
    # DETALLES
    # ========================================
    
    concept_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Detalle del concepto (texto libre para imprimir en el recibo)"
    )
    
    status: Mapped[InvoiceStatus] = mapped_column(
        SQLEnum(InvoiceStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=InvoiceStatus.DRAFT,
        nullable=False,
        index=True,
        comment="Estado del comprobante: borrador, emitido o anulado"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    organization: Mapped["Organization"] = relationship(
        back_populates="invoices",
        lazy="selectin"
    )
    
    payments: Mapped[List["Payment"]] = relationship(
        back_populates="invoice",
        lazy="noload"
    )

    # ========================================
    # CONSTRAINTS
    # ========================================
    
    __table_args__ = (
        UniqueConstraint(
            'organization_id',
            'invoice_number',
            name='uq_invoice_number_per_org'
        ),
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Invoice(id={self.id}, organization_id={self.organization_id}, invoice_number={self.invoice_number}, status='{self.status}')>"
