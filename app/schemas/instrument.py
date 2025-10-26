"""
Schemas Pydantic para Instrument (Instrumento: Piano, Guitarra, Canto, etc)

Este modelo es SIMPLE: solo tiene name y active.
Se usa como catálogo de instrumentos disponibles.
"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class InstrumentBase(BaseModel):
    """
    Campo común: nombre del instrumento
    - Único en la BD (no puede haber dos "Piano")
    - Obligatorio, mínimo 1 caracter
    """
    name: str = Field(..., min_length=1, max_length=50)


class InstrumentCreate(InstrumentBase):
    """
    Para CREAR un instrumento (POST /instruments)
    
    Solo necesita el nombre.
    El campo 'active' se crea automáticamente en True.
    """
    pass  # No hay campos adicionales, hereda todo de Base


class InstrumentUpdate(BaseModel):
    """
    Para ACTUALIZAR un instrumento (PATCH /instruments/{id})
    
    Puede cambiar:
    - name: renombrar el instrumento
    - active: desactivar (soft-delete) sin eliminarlo físicamente
    
    Ambos opcionales para poder actualizar solo uno.
    """
    name: str | None = Field(None, min_length=1, max_length=50)
    active: bool | None = None


class InstrumentResponse(InstrumentBase):
    """
    Para RESPUESTAS (GET)
    
    Incluye:
    - id: identificador único
    - active: si está activo o desactivado (soft-delete)
    - timestamps: cuándo se creó y actualizó
    """
    id: int
    active: bool
    created_at: datetime
    updated_at: datetime
    
    # Permite leer desde objetos SQLAlchemy
    model_config = ConfigDict(from_attributes=True)