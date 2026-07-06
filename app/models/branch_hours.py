"""
Modelo BranchHours - Horarios de apertura por día de la semana de una sucursal.
"""

# pyrefly: ignore [missing-import]
from sqlalchemy import Boolean, Integer, ForeignKey, String, Time
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from .base import Base

if TYPE_CHECKING:
    from .branch import Branch


class BranchHours(Base):
    __tablename__ = "branch_hours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    branch_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    day_of_week: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="monday | tuesday | wednesday | thursday | friday | saturday | sunday",
    )

    morning_open: Mapped[object | None] = mapped_column(Time, nullable=True)
    morning_close: Mapped[object | None] = mapped_column(Time, nullable=True)
    afternoon_open: Mapped[object | None] = mapped_column(Time, nullable=True)
    afternoon_close: Mapped[object | None] = mapped_column(Time, nullable=True)

    is_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    branch: Mapped["Branch"] = relationship(back_populates="hours", lazy="noload")

    def __repr__(self) -> str:
        return f"<BranchHours(branch_id={self.branch_id}, day={self.day_of_week})>"
