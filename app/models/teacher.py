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

from datetime import date
from decimal import Decimal
from sqlalchemy import String, Boolean, Numeric, Integer, ForeignKey, Date, Text, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING

from .base import Base, TimestampMixin

# Evita imports circulares en tiempo de ejecución
if TYPE_CHECKING:
    from .student import Student
    from .enrollment import Enrollment
    from .schedule import Schedule
    from .class_model import Class
    from .organization import Organization
    from .instrument import Instrument

# Tabla de asociación Teacher <-> Instrument (many-to-many)
teacher_instruments = Table(
    'teacher_instruments',
    Base.metadata,
    Column('teacher_id', Integer, ForeignKey('teachers.id', ondelete='CASCADE'), primary_key=True),
    Column('instrument_id', Integer, ForeignKey('instruments.id', ondelete='CASCADE'), primary_key=True),
)


# Roles válidos — definidos como constantes para reutilizar en todo el backend
ROLE_ORG_ADMIN     = "org_admin"      # Directora/dueño: acceso total
ROLE_TEACHER       = "teacher"        # Profesor: solo sus alumnos
ROLE_COORDINATOR   = "coordinator"    # Asistente académico: lectura general
ROLE_ADMINISTRATIVE = "administrative" # Secretaria/admin: finanzas/agenda

VALID_ROLES = [ROLE_ORG_ADMIN, ROLE_TEACHER, ROLE_COORDINATOR, ROLE_ADMINISTRATIVE]


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

    birthdate: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Fecha de nacimiento del profesor"
    )

    bio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Descripción o presentación breve del profesor"
    )

    avatar_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="URL de la foto de perfil"
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
    # MULTI-TENANT: organización y rol
    # ========================================

    organization_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,  # nullable en el modelo para compatibilidad con datos previos
        index=True,
        comment="FK a la escuela/organización a la que pertenece"
    )

    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ROLE_ORG_ADMIN,  # default org_admin: datos existentes son dueños
        server_default=ROLE_ORG_ADMIN,
        comment="Rol del teacher: org_admin|teacher|coordinator|administrative"
    )

    # ========================================
    # RELACIONES
    # ========================================

    organization: Mapped["Organization | None"] = relationship(
        back_populates="teachers",
        lazy="selectin"
    )

    instruments: Mapped[List["Instrument"]] = relationship(
        secondary=teacher_instruments,
        lazy="selectin",
    )

    students: Mapped[List["Student"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
        lazy="noload"
    )
    
    enrollments: Mapped[List["Enrollment"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
        lazy="noload"
    )
    
    schedules: Mapped[List["Schedule"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
        lazy="noload"
    )
    
    classes: Mapped[List["Class"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
        lazy="noload"
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Teacher(id={self.id}, name='{self.name}', email='{self.email}')>"