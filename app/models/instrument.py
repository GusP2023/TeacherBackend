"""
Modelo Instrument - Representa los instrumentos disponibles en el sistema.

Este modelo almacena:
- Catálogo de instrumentos (Piano, Guitarra, Canto, etc.)
- Estado del instrumento (activo/inactivo)

Relaciones:
- 1:N con Enrollment (un instrumento puede tener múltiples inscripciones)

Características:
- Los instrumentos NO se eliminan físicamente, solo se desactivan
- El campo 'name' es único para evitar duplicados
- Permite agregar nuevos instrumentos sin afectar datos históricos
"""

from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .enrollment import Enrollment


class Instrument(Base, TimestampMixin):
    """
    Modelo de Instrumento.
    
    Atributos principales:
        id: Identificador único del instrumento
        name: Nombre del instrumento (ej: "Piano", "Guitarra", "Canto")
        active: Indica si el instrumento está disponible para nuevas inscripciones
        
    Sistema de soft-delete:
        - active=True: Instrumento disponible para nuevas inscripciones
        - active=False: Instrumento desactivado (pero preserva datos históricos)
        
    Relaciones:
        enrollments: Lista de inscripciones vinculadas a este instrumento
        
    Ejemplo de uso:
        # Crear nuevo instrumento
        instrument = Instrument(
            name="Piano",
            active=True
        )
        
        # Desactivar instrumento (soft-delete)
        instrument.active = False
    """
    __tablename__ = "instruments"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único del instrumento"
    )
    
    name: Mapped[str] = mapped_column(
        String(100), 
        unique=True,      # No puede haber instrumentos con el mismo nombre
        nullable=False,
        index=True,       # Indexado para búsquedas rápidas
        comment="Nombre del instrumento (ej: Piano, Guitarra, Violín, Canto)"
    )
    
    active: Mapped[bool] = mapped_column(
        Boolean, 
        default=True, 
        nullable=False,
        index=True,       # Indexado para filtrar instrumentos activos
        comment="Indica si el instrumento está disponible para nuevas inscripciones"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    enrollments: Mapped[List["Enrollment"]] = relationship(
        back_populates="instrument",
        lazy="selectin"  # Optimizado para FastAPI async
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Instrument(id={self.id}, name='{self.name}', active={self.active})>"