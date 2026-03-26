"""
Jobs Package

Contiene los trabajos automatizados del sistema:
- Generación mensual de clases
- Tareas de mantenimiento
- Sincronizaciones
"""

from .class_generator import (
    generate_classes_for_enrollment,
    generate_monthly_classes,
    delete_future_classes_for_schedule,
    regenerate_classes_manual
)

__all__ = [
    "generate_classes_for_enrollment",
    "generate_monthly_classes",
    "delete_future_classes_for_schedule",
    "regenerate_classes_manual",
]
