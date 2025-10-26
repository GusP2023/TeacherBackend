"""
Modelo Student - Representa a los alumnos del sistema.

Este modelo almacena SOLO la información básica del alumno.
La información de inscripciones (instrumento, nivel, estado, créditos)
ahora se maneja en el modelo Enrollment.

Este modelo almacena:
- Información personal del alumno (nombre, contacto, cumpleaños)
- Relación con su profesor
- Notas opcionales del profesor
- ID de sincronización (para futuro sistema principal)

Relaciones:
- N:1 con Teacher (muchos alumnos pertenecen a un profesor)
- 1:N con Enrollment (un alumno puede tener múltiples inscripciones a instrumentos)

Arquitectura:
    Teacher (1:N) → Student (1:N) → Enrollment (N:1) → Instrument
    
    Ejemplo:
    - María (Student) estudia con Juan (Teacher)
    - María tiene 2 Enrollments:
      * Piano - Nivel 3 - Activo
      * Guitarra - Elemental - Suspendido
"""

from datetime import date
from sqlalchemy import String, Integer, Date, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import List, TYPE_CHECKING

from .base import Base, TimestampMixin

# Evita imports circulares
if TYPE_CHECKING:
    from .teacher import Teacher
    from .enrollment import Enrollment


class Student(Base, TimestampMixin):
    """
    Modelo de Alumno (simplificado).
    
    Este modelo ahora solo contiene información básica del alumno.
    Los datos de inscripción (instrumento, nivel, estado) están en Enrollment.
    
    Atributos principales:
        id: Identificador único del alumno
        teacher_id: FK al profesor que lo gestiona
        name: Nombre completo del alumno
        phone: Número de contacto (opcional)
        email: Email de contacto (opcional)
        birthdate: Fecha de nacimiento (opcional, para cumpleaños)
        notes: Notas opcionales del profesor sobre el alumno
        
    Futuro:
        sync_id: ID del sistema principal (NULL si fue creado por profesor)
                 Permite sincronizar con sistema centralizado futuro
                 
    Relaciones:
        teacher: Profesor que gestiona al alumno
        enrollments: Lista de inscripciones a instrumentos
        
    Ejemplo de uso:
        student = Student(
            teacher_id=1,
            name="María González",
            phone="+591 7012345678",
            email="maria@example.com",
            birthdate=date(2010, 5, 15),
            notes="Muy dedicada, practica 2 horas diarias"
        )
        
        # María puede tener múltiples inscripciones:
        # - Piano (Nivel 3, activo)
        # - Guitarra (Elemental, suspendido)
    """
    __tablename__ = "students"

    # ========================================
    # CAMPOS PRINCIPALES
    # ========================================
    
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        index=True,
        comment="Identificador único del alumno"
    )
    
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True,
        comment="ID del profesor que gestiona al alumno"
    )
    
    name: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        comment="Nombre completo del alumno"
    )
    
    # ========================================
    # INFORMACIÓN DE CONTACTO
    # ========================================
    
    phone: Mapped[str | None] = mapped_column(
        String(50), 
        nullable=True,
        comment="Número de teléfono de contacto (opcional)"
    )
    
    email: Mapped[str | None] = mapped_column(
        String(255), 
        nullable=True,
        comment="Email de contacto (opcional)"
    )
    
    birthdate: Mapped[date | None] = mapped_column(
        "birthday",  # Nombre de la columna en la base de datos
        Date,
        nullable=True,
        comment="Fecha de nacimiento (para recordar cumpleaños)"
    )
    
    # ========================================
    # NOTAS DEL PROFESOR
    # ========================================
    
    notes: Mapped[str | None] = mapped_column(
        Text, 
        nullable=True,
        comment="Notas opcionales del profesor sobre el alumno"
    )
    
    # ========================================
    # SINCRONIZACIÓN FUTURA
    # ========================================
    
    sync_id: Mapped[int | None] = mapped_column(
        Integer,
        unique=True,
        nullable=True,
        comment="ID del sistema principal (futuro). NULL si creado localmente"
    )

    active: Mapped[bool] = mapped_column(
        Boolean, 
        default=True, 
        nullable=False,
        index=True,
        comment="Indica si el alumno está activo (soft-delete)"
    )

    # ========================================
    # RELACIONES
    # ========================================
    
    teacher: Mapped["Teacher"] = relationship(
        back_populates="students", 
        lazy="selectin"
    )
    
    enrollments: Mapped[List["Enrollment"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        """Representación string del objeto para debugging"""
        return f"<Student(id={self.id}, name='{self.name}', teacher_id={self.teacher_id})>"