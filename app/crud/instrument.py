"""
CRUD operations for Instrument model
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.instrument import Instrument
from app.schemas.instrument import InstrumentCreate, InstrumentUpdate


async def get(db: AsyncSession, instrument_id: int) -> Instrument | None:
    """
    Obtener un instrumento por ID
    
    Args:
        db: Sesión de base de datos
        instrument_id: ID del instrumento
    
    Returns:
        Instrument si existe, None si no
    """
    result = await db.execute(
        select(Instrument).where(Instrument.id == instrument_id)
    )
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100
) -> list[Instrument]:
    """
    Obtener múltiples instrumentos (activos e inactivos)
    
    Args:
        db: Sesión de base de datos
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
    
    Returns:
        Lista de todos los Instruments
    """
    result = await db.execute(
        select(Instrument)
        .offset(skip)
        .limit(limit)
        .order_by(Instrument.name)
    )
    return list(result.scalars().all())


async def get_active(db: AsyncSession) -> list[Instrument]:
    """
    Obtener solo instrumentos activos
    
    Útil para mostrar en selects/dropdowns del frontend
    
    Args:
        db: Sesión de base de datos
    
    Returns:
        Lista de Instruments activos, ordenados alfabéticamente
    """
    result = await db.execute(
        select(Instrument)
        .where(Instrument.active == True)
        .order_by(Instrument.name)
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, instrument_data: InstrumentCreate) -> Instrument:
    """
    Crear un instrumento nuevo
    
    Args:
        db: Sesión de base de datos
        instrument_data: Datos del instrumento a crear
    
    Returns:
        Instrument creado con id asignado
    """
    instrument = Instrument(**instrument_data.model_dump())
    
    db.add(instrument)
    await db.commit()
    await db.refresh(instrument)
    
    return instrument


async def update(
    db: AsyncSession,
    instrument_id: int,
    instrument_data: InstrumentUpdate
) -> Instrument | None:
    """
    Actualizar un instrumento existente
    
    Permite activar/desactivar instrumentos con el campo 'active'
    
    Args:
        db: Sesión de base de datos
        instrument_id: ID del instrumento a actualizar
        instrument_data: Datos a actualizar (solo campos no None)
    
    Returns:
        Instrument actualizado si existe, None si no
    """
    # Obtener el instrumento
    result = await db.execute(
        select(Instrument).where(Instrument.id == instrument_id)
    )
    instrument = result.scalar_one_or_none()
    
    if not instrument:
        return None
    
    # Actualizar solo campos que no sean None
    update_data = instrument_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(instrument, field, value)
    
    await db.commit()
    await db.refresh(instrument)
    
    return instrument