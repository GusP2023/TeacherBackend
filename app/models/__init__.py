"""
Módulo models - Exporta todos los modelos de la aplicación.

Este archivo centraliza todos los imports para facilitar su uso:
    from app.models import Teacher, Student, Enrollment, etc.

También exporta los enums para validaciones:
    from app.models import EnrollmentStatus, ClassStatus, etc.

IMPORTANTE: El orden de imports importa para evitar errores circulares.
Se importa en este orden:
    1. Base y Mixins (sin dependencias)
    2. Modelos independientes (Teacher, Instrument)
    3. Modelos con pocas dependencias (Student)
    4. Modelos intermedios (Enrollment)
    5. Modelos con muchas dependencias (Schedule, Class, Attendance)
"""

# ========================================
# BASE
# ========================================
from .base import Base, TimestampMixin

# ========================================
# MODELOS INDEPENDIENTES
# ========================================
from .teacher import Teacher
from .instrument import Instrument

# ========================================
# MODELOS CON POCAS DEPENDENCIAS
# ========================================
from .student import Student

# ========================================
# MODELOS INTERMEDIOS
# ========================================
from .enrollment import (
    Enrollment,
    EnrollmentStatus,
    EnrollmentLevel
)

# ========================================
# MODELOS DE HORARIOS Y CLASES
# ========================================
from .schedule import (
    Schedule,
    DayOfWeek
)

from .class_model import (
    Class,
    ClassStatus,
    ClassType,
    ClassFormat
)

# ========================================
# MODELO DE ASISTENCIA
# ========================================
from .attendance import (
    Attendance,
    AttendanceStatus
)

# ========================================
# EXPORTS
# ========================================
__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    
    # Modelos
    "Teacher",
    "Instrument",
    "Student",
    "Enrollment",
    "Schedule",
    "Class",
    "Attendance",
    
    # Enums de Enrollment
    "EnrollmentStatus",
    "EnrollmentLevel",
    
    # Enums de Schedule
    "DayOfWeek",
    
    # Enums de Class
    "ClassStatus",
    "ClassType",
    "ClassFormat",
    
    # Enums de Attendance
    "AttendanceStatus",
]