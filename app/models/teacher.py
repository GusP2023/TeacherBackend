"""
Modelo Teacher - Representa a los profesores del sistema.

Este modelo almacena:
- Datos de autenticación (email, password)
- Información personal (nombre, teléfono)
- Configuración de negocio (tarifa por clase)
- Estado (activo/inactivo)

Relaciones:
- 1:N con Students (un profesor tiene muchos alumnos)
- 1:N con Enrollments (un profesor gestiona muchas inscripciones)
- 1:N con Schedules (un profesor gestiona muchos horarios)
- 1:N con Classes (un profesor imparte muchas clases)
"""

from decimal import Decimal
from sqlalchemy import String, Boolean, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING

from .base import Base, TimestampMixin

# Evita imports circulares en tiempo de ejecución
if TYPE_CHECKING:
    from .student import Student
    from .enrollment import Enrollment
    from .schedule import Schedule
    from .class_model import Class


class Teacher(Base, TimestampMixin):
    """
    Modelo de Profesor.
    
    Atributos:
        id: Identificador único del profesor
        email: Email único para login (indexado)
        password_hash: Contraseña hasheada (nunca almacenar en texto plano)
        name: Nombre completo del profesor
        phone: Teléfono de contacto (opcional)
        tariff_individual: Precio que cobra por clase individual
        tariff_group: Precio que cobra por alumno en clase grupal
        active: Indica si el profesor está activo en el sistema
        
    Relaciones:
        students: Lista de alumnos de este profesor
        enrollments: Lista de inscripciones gestionadas
        schedules: Lista de horarios gestionados
        classes: Lista de clases impartidas
        
    Ejemplo de uso:
        teacher = Teacher(
            email="juan@example.com",
            password_hash=hash_password("mi_password"),
            name="Juan Pérez",
            tariff_individual=Decimal("50.00"),
            tariff_group=Decimal("35.00"),
            active=True
        )
    """
    __tablename__ = "teachers"

    # Campos principales
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único del profesor"
    )
    
    email: Mapped[str] = mapped_column(
        String(255), 
        unique=True,      # No puede haber emails duplicados
        nullable=False, 
        index=True,       # Indexado para búsquedas rápidas en login
        comment="Email único para autenticación"
    )
    
    password_hash: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        comment="Contraseña hasheada (bcrypt o similar)"
    )
    
    name: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        comment="Nombre completo del profesor"
    )
    
    phone: Mapped[str | None] = mapped_column(
        String(50), 
        nullable=True,
        comment="Teléfono de contacto (opcional)"
    )
    
    tariff_individual: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0.00,
        comment="Precio por clase individual"
    )

    tariff_group: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=True,   #profesor puede no impartir clases grupales.
        default=0.00,
        comment="Precio por alumno en clase grupal"
    )
    
    active: Mapped[bool] = mapped_column(
        Boolean, 
        default=True, 
        nullable=False,
        comment="Indica si el profesor está activo"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    students: Mapped[List["Student"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",  # Si se elimina teacher, se eliminan sus students
        lazy="selectin"                # Optimizado para FastAPI async
    )
    
    enrollments: Mapped[List["Enrollment"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",  # Si se elimina teacher, se eliminan sus enrollments
        lazy="selectin"
    )
    
    schedules: Mapped[List["Schedule"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    
    classes: Mapped[List["Class"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Teacher(id={self.id}, name='{self.name}', email='{self.email}')>"