"""
Modelo JobRunLog - Registro de ejecución de jobs

Este modelo mantiene un registro persistente de cuándo se ejecutaron
los jobs automáticos por última vez, para evitar ejecuciones duplicadas
en entornos donde el scheduler puede perder triggers (como Render free tier).

Uso principal:
- monthly_class_generation: Job mensual de generación de clases
"""

from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class JobRunLog(Base, TimestampMixin):
    """
    Registro de ejecución de jobs automáticos.

    Mantiene un marcador persistente para evitar ejecuciones duplicadas
    cuando el servidor se reinicia y pierde triggers de APScheduler.

    Campos:
    - job_name: Nombre único del job (PK)
    - last_run_year_month: Último mes ejecutado (formato YYYY-MM)
    - last_run_at: Fecha/hora exacta de la última ejecución
    """

    __tablename__ = "job_run_logs"

    job_name: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        comment="Nombre único del job (ej: 'monthly_class_generation')"
    )

    last_run_year_month: Mapped[str] = mapped_column(
        String(7),  # YYYY-MM
        nullable=False,
        comment="Último mes ejecutado (formato YYYY-MM)"
    )

    last_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Fecha y hora de la última ejecución"
    )