"""
API v1 package - Routers

Exporta todos los routers de la API v1 para su uso en main.py

Uso en main.py:
    from app.api.v1 import (
        auth_router,
        teachers_router,
        students_router,
        ...
    )
    
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
    app.include_router(students_router, prefix="/api/v1/students", tags=["Students"])
"""

from app.api.v1.auth import router as auth_router
from app.api.v1.teachers import router as teachers_router
from app.api.v1.students import router as students_router
from app.api.v1.instruments import router as instruments_router
from app.api.v1.enrollments import router as enrollments_router
from app.api.v1.schedules import router as schedules_router
from app.api.v1.classes import router as classes_router
from app.api.v1.attendances import router as attendances_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.sync import router as sync_router

__all__ = [
    "auth_router",
    "teachers_router",
    "students_router",
    "instruments_router",
    "enrollments_router",
    "schedules_router",
    "classes_router",
    "attendances_router",
    "jobs_router",
    "sync_router"
]