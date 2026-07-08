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
# MULTI-TENANT (debe ir ANTES de Teacher)
# ========================================
from .organization import Organization
from .invitation import Invitation

# ========================================
# MODELOS INDEPENDIENTES
# ========================================
from .teacher import Teacher
from .instrument import Instrument
from .teacher_availability import TeacherAvailability

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

from .enrollment_note import (
    EnrollmentNote,
    NoteType,
)

# ========================================
# MODELOS DE HORARIOS Y CLASES
# ========================================
from .schedule import (
    Schedule,
    DayOfWeek
)

from .branch import Branch
from .branch_hours import BranchHours
from .room import Room
from .room_assignment import RoomAssignment
from .room_override import RoomOverride
from .event import Event, EVENT_TYPES

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

from .suspension_history import SuspensionHistory
from .security_log import SecurityLog
from .job_run_log import JobRunLog

# ========================================
# MODELOS FINANCIEROS
# ========================================
from .fee_discount import (
    FeeDiscount,
    DiscountType
)

from .billing_period import (
    BillingPeriod,
    BillingPeriodStatus
)

from .invoice import (
    Invoice,
    InvoiceStatus
)

from .payment import (
    Payment,
    PaymentConcept,
    PaymentMethod
)

from .credit_transaction import (
    CreditTransaction,
    CreditTransactionSource,
    CreditTransactionReferenceType
)

from .personnel_payment import (
    PersonnelPayment,
    PersonnelPaymentStatus
)

from .expense import (
    Expense,
    ExpenseCategory
)

# ========================================
# EXPORTS
# ========================================
__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    
    # Multi-tenant
    "Organization",
    "Invitation",

    # Modelos
    "Teacher",
    "Instrument",
    "TeacherAvailability",
    "Student",
    "Enrollment",
    "Schedule",
    "Class",
    "Attendance",
    "SuspensionHistory",
    "SecurityLog",
    "JobRunLog",
    
    # Modelos Financieros
    "FeeDiscount",
    "DiscountType",
    "BillingPeriod",
    "BillingPeriodStatus",
    "Invoice",
    "InvoiceStatus",
    "Payment",
    "PaymentConcept",
    "PaymentMethod",
    "CreditTransaction",
    "CreditTransactionSource",
    "CreditTransactionReferenceType",
    "PersonnelPayment",
    "PersonnelPaymentStatus",
    "Expense",
    "ExpenseCategory",
    
    # Enums de Enrollment
    "EnrollmentStatus",
    "EnrollmentLevel",
    
    # Enrollment Notes
    "EnrollmentNote",
    "NoteType",
    
    # Enums de Schedule
    "DayOfWeek",
    "Branch",
    "BranchHours",
    "Room",
    "RoomAssignment",
    "RoomOverride",
    "Event",
    "EVENT_TYPES",
    
    # Enums de Class
    "ClassStatus",
    "ClassType",
    "ClassFormat",
    
    # Enums de Attendance
    "AttendanceStatus",
]