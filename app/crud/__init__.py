"""
CRUD operations package

Importa todas las operaciones CRUD para facilitar su uso en los endpoints.

Uso en routers:
    from app.crud import teacher, student, enrollment
    
    teacher_obj = await teacher.get(db, teacher_id)
    students = await student.get_multi(db, teacher_id)
"""

# Imports relativos (con punto) para evitar circular imports
from . import teacher
from . import student
from . import instrument
from . import enrollment
from . import schedule
from . import class_crud
from . import attendance

__all__ = [
    "teacher",
    "student",
    "instrument",
    "enrollment",
    "schedule",
    "class_crud",
    "attendance"
]