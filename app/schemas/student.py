"""
Schemas Pydantic para Student (Alumno)

CONCEPTOS CLAVE:
- BaseModel: Clase base de Pydantic para validación automática
- Field: Permite agregar validaciones (min_length, max_length, etc)
- EmailStr: Valida que sea un email válido automáticamente
- date: Tipo de dato para fechas (sin hora)
- | None: Significa "opcional" (puede ser None/null)
"""
from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class StudentBase(BaseModel):
    """
    Campos comunes del alumno.
    Estos campos se reutilizarán en Create y Response.

    VALIDACIONES:
    - name: obligatorio, mínimo 1 caracter (no vacío)
    - phone: opcional, máximo 20 caracteres
    - email: opcional, pero si se envía debe ser válido
    - birthdate: opcional, tipo date (sin hora)
    - notes: opcional, para que el profesor guarde observaciones
    """
    name: str = Field(..., min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    birthdate: date | None = None
    notes: str | None = None


class StudentCreate(StudentBase):
    """
    Schema para CREAR un alumno (POST /students)

    ¿Por qué teacher_id aquí y no en Base?
    - Porque al crear, NECESITAMOS saber a qué profesor pertenece
    - Pero en Base no lo ponemos porque no es un campo "común"
      que queramos en Update o que venga del usuario siempre

    El teacher_id se obtiene del token JWT del profesor logueado,
    por lo que es opcional en el schema (será asignado automáticamente
    por el endpoint desde current_teacher).
    """
    teacher_id: int | None = Field(None, gt=0)  # Opcional, se asigna desde el JWT


class StudentUpdate(BaseModel):
    """
    Schema para ACTUALIZAR un alumno (PUT/PATCH /students/{id})

    ¿Por qué todos son opcionales?
    - Porque con PATCH puedes actualizar solo 1 campo sin tocar los demás
    - Ejemplo: solo cambiar el teléfono sin modificar nombre ni email

    NO incluimos teacher_id porque un alumno no puede cambiar de profesor
    (si necesitas eso en el futuro, sería otra operación)
    """
    name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    birthdate: date | None = None
    notes: str | None = None


class StudentResponse(StudentBase):
    """
    Schema para RESPUESTAS (GET /students, GET /students/{id})
    
    Incluye campos que vienen de la base de datos:
    - id: identificador único del alumno
    - teacher_id: a qué profesor pertenece
    - sync_id: para sincronización móvil (puede ser None)
    - created_at/updated_at: timestamps automáticos
    
    ConfigDict(from_attributes=True):
    - Le dice a Pydantic que puede leer desde objetos SQLAlchemy
    - Sin esto, solo podría leer desde diccionarios
    """
    id: int
    teacher_id: int
    sync_id: str | None = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)