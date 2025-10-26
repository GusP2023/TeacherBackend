"""
Módulo base para todos los modelos de la aplicación.

Este módulo define:
- Base: Clase base declarativa de SQLAlchemy para herencia de modelos
- TimestampMixin: Mixin para agregar timestamps automáticos (created_at, updated_at)
"""

from datetime import datetime
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """
    Clase base para todos los modelos de SQLAlchemy.
    
    Todos los modelos heredan de esta clase para obtener:
    - Metadata automática
    - Configuración de tablas
    - Soporte para type hints modernos (Mapped)
    
    Ejemplo:
        class MiModelo(Base):
            __tablename__ = "mi_tabla"
            id: Mapped[int] = mapped_column(primary_key=True)
    """
    pass


class TimestampMixin:
    """
    Mixin que agrega campos de auditoría temporal a cualquier modelo.
    
    Agrega automáticamente:
    - created_at: Fecha/hora de creación del registro (automático)
    - updated_at: Fecha/hora de última modificación (se actualiza automáticamente)
    
    Uso:
        class MiModelo(Base, TimestampMixin):
            __tablename__ = "mi_tabla"
            ...
    
    Características:
    - server_default: El valor se genera en la BD (no en Python)
    - func.now(): Usa CURRENT_TIMESTAMP de PostgreSQL
    - onupdate: Se actualiza automáticamente en cada UPDATE
    - timezone=True: Almacena con zona horaria (TIMESTAMPTZ)
    """
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # Se ejecuta en PostgreSQL
        nullable=False,
        comment="Fecha y hora de creación del registro"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # Valor inicial
        onupdate=func.now(),        # Se actualiza automáticamente en cada UPDATE
        nullable=False,
        comment="Fecha y hora de última modificación"
    )