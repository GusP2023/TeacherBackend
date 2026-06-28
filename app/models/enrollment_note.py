"""
Modelo EnrollmentNote — Notas del planificador de clases.

Vinculado a Enrollment (no solo a Student) para aislar notas por instrumento.
El teacher_id es el autor de la nota. Al cambiar de profesor, el nuevo
profesor (que ahora es teacher_id del enrollment) puede leer TODAS las notas
del enrollment, pero solo puede editar/borrar las propias.

Tipos:
  - progress:    Registro histórico del avance del alumno (inmutable por diseño de UI)
  - reminder:    Tarea con due_date, se marca como completada
  - evaluation:  Como reminder pero con campo score opcional (0-100)
"""

from datetime import date
from decimal import Decimal
from sqlalchemy import (
    String, Text, Date, Boolean, Enum as SQLEnum,
    ForeignKey, CheckConstraint, Numeric
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
import enum

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .enrollment import Enrollment
    from .teacher import Teacher


class NoteType(str, enum.Enum):
    PROGRESS   = "progress"
    REMINDER   = "reminder"
    EVALUATION = "evaluation"


class EnrollmentNote(Base, TimestampMixin):
    __tablename__ = "enrollment_notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    enrollment_id: Mapped[int] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type: Mapped[NoteType] = mapped_column(
        SQLEnum(NoteType, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Solo para reminder y evaluation
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Solo para evaluation (0.00 – 100.00)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Solo aplica a reminder y evaluation
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relaciones ──────────────────────────────────────────────────────────────
    enrollment: Mapped["Enrollment"] = relationship(lazy="selectin")
    teacher:    Mapped["Teacher"]    = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="check_note_score_range",
        ),
    )

    def __repr__(self) -> str:
        return f"<EnrollmentNote(id={self.id}, enrollment_id={self.enrollment_id}, type='{self.type}')>"
