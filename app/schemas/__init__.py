"""
__init__.py - Exports de todos los Schemas

PROPÓSITO:
Centralizar las importaciones para facilitar el uso en otros módulos.

USO:
# En lugar de:
from app.schemas.teacher import TeacherCreate, TeacherResponse
from app.schemas.student import StudentCreate, StudentResponse

# Se puede hacer:
from app.schemas import TeacherCreate, TeacherResponse, StudentCreate, StudentResponse
"""

# Teacher schemas
from app.schemas.teacher import (
    TeacherBase,
    TeacherCreate,
    TeacherUpdate,
    TeacherResponse
)

# Student schemas
from app.schemas.student import (
    StudentBase,
    StudentCreate,
    StudentUpdate,
    StudentResponse
)

# Instrument schemas
from app.schemas.instrument import (
    InstrumentBase,
    InstrumentCreate,
    InstrumentUpdate,
    InstrumentResponse
)

# Enrollment schemas
from app.schemas.enrollment import (
    EnrollmentBase,
    EnrollmentCreate,
    EnrollmentUpdate,
    EnrollmentResponse
)

# Schedule schemas
from app.schemas.schedule import (
    ScheduleBase,
    ScheduleCreate,
    ScheduleUpdate,
    ScheduleResponse
)

# Class schemas
from app.schemas.class_schema import (
    ClassBase,
    ClassCreate,
    ClassUpdate,
    ClassResponse
)

# Attendance schemas
from app.schemas.attendance import (
    AttendanceBase,
    AttendanceCreate,
    AttendanceUpdate,
    AttendanceResponse
)

# Auth schemas
from app.schemas.auth import (
    Login,
    Token,
    TokenData
)

# Lista de exports (para que IDEs autocompleten)
__all__ = [
    # Teacher
    "TeacherBase",
    "TeacherCreate",
    "TeacherUpdate",
    "TeacherResponse",
    # Student
    "StudentBase",
    "StudentCreate",
    "StudentUpdate",
    "StudentResponse",
    # Instrument
    "InstrumentBase",
    "InstrumentCreate",
    "InstrumentUpdate",
    "InstrumentResponse",
    # Enrollment
    "EnrollmentBase",
    "EnrollmentCreate",
    "EnrollmentUpdate",
    "EnrollmentResponse",
    # Schedule
    "ScheduleBase",
    "ScheduleCreate",
    "ScheduleUpdate",
    "ScheduleResponse",
    # Class
    "ClassBase",
    "ClassCreate",
    "ClassUpdate",
    "ClassResponse",
    # Attendance
    "AttendanceBase",
    "AttendanceCreate",
    "AttendanceUpdate",
    "AttendanceResponse",
    # Auth
    "Login",
    "Token",
    "TokenData",
]