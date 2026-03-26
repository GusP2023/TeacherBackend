from datetime import date
from sqlalchemy import Integer, Date, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Optional

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .enrollment import Enrollment


class SuspensionHistory(Base, TimestampMixin):
    """
    Historial de suspensiones de enrollments.
    
    Registra todas las suspensiones (temporales/indefinidas) y reactivaciones.
    Permite auditoría y análisis de patrones de asistencia.
    """
    __tablename__ = "suspension_history"

    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único del registro"
    )
    
    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID de la inscripción suspendida"
    )
    
    suspended_at: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Fecha desde la que se suspendió"
    )
    
    suspended_until: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Fecha hasta la que está suspendido (NULL = indefinido)"
    )
    
    reactivated_at: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Fecha en que fue reactivado (NULL = aún suspendido)"
    )
    
    reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Motivo de la suspensión"
    )
    
    # Relación
    enrollment: Mapped["Enrollment"] = relationship(
        back_populates="suspension_history",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<SuspensionHistory(id={self.id}, enrollment_id={self.enrollment_id}, suspended_at={self.suspended_at})>"