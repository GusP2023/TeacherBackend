"""
Instruments endpoints - Solo GET (catálogo de instrumentos)

Los instrumentos se crean con script seed, no hay POST desde la app
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import instrument
from app.models.teacher import Teacher
from app.schemas.instrument import InstrumentResponse

router = APIRouter()


@router.get("/", response_model=list[InstrumentResponse])
async def list_instruments(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Listar todos los instrumentos activos
    
    Útil para mostrar en selects/dropdowns al crear enrollments
    Solo retorna instrumentos activos (active=True)
    Ordenados alfabéticamente
    
    Args:
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (validación de token)
    
    Returns:
        Lista de instrumentos activos
    
    Example response:
        [
            {"id": 1, "name": "Piano", "active": true, ...},
            {"id": 2, "name": "Guitarra", "active": true, ...},
            {"id": 3, "name": "Canto", "active": true, ...}
        ]
    """
    instruments = await instrument.get_active(db)
    
    return instruments


@router.get("/{instrument_id}", response_model=InstrumentResponse)
async def get_instrument(
    instrument_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener un instrumento específico por ID
    
    Retorna el instrumento aunque esté inactivo (para ver datos históricos)
    
    Args:
        instrument_id: ID del instrumento
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (validación de token)
    
    Returns:
        Datos del instrumento
    
    Raises:
        404: Si el instrumento no existe
    """
    instrument_obj = await instrument.get(db, instrument_id)
    
    if not instrument_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrumento {instrument_id} no encontrado"
        )
    
    return instrument_obj