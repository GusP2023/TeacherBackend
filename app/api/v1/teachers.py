"""
Teachers endpoints - Perfil del profesor (solo su propia información)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.core.permissions import resolve_permissions
from app.crud import teacher
from app.models.teacher import Teacher
from app.models.instrument import Instrument
from app.schemas.teacher import TeacherUpdate, TeacherResponse

router = APIRouter()


@router.get("/me", response_model=TeacherResponse)
async def get_my_profile(
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener el perfil del profesor logueado, incluyendo sus permisos efectivos.

    Los permisos se resuelven en el servidor combinando:
    - Los defaults del sistema para su rol
    - Los overrides configurados por su organización (si los hay)

    El cliente (Mobile o Admin web) solo necesita leer el campo `permissions`
    sin conocer la lógica de resolución.
    """
    # Resolver permisos efectivos
    org_overrides = None
    if current_teacher.organization:
        org_overrides = current_teacher.organization.role_permissions

    permissions = resolve_permissions(
        role=current_teacher.role,
        organization_id=current_teacher.organization_id,
        org_overrides=org_overrides,
    )

    # Construir respuesta manualmente para incluir el campo calculado
    response = TeacherResponse.model_validate(current_teacher)
    response.permissions = permissions
    return response


@router.patch("/me", response_model=TeacherResponse)
async def update_my_profile(
    teacher_data: TeacherUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Actualizar el perfil del profesor logueado
    
    Solo actualiza los campos enviados (parcial)
    Si se actualiza el password, se hashea automáticamente
    
    Args:
        teacher_data: Datos a actualizar (solo campos no None)
        db: Sesión de base de datos
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Profesor actualizado (sin password)
    
    Raises:
        500: Si ocurre un error al actualizar
    """
    # Actualizar usando el CRUD
    updated_teacher = await teacher.update(
        db,
        teacher_id=current_teacher.id,
        teacher_data=teacher_data
    )
    
    if not updated_teacher:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar el perfil"
        )

    # Incluir permisos resueltos en la respuesta
    org_overrides = None
    if updated_teacher.organization:
        org_overrides = updated_teacher.organization.role_permissions
    permissions = resolve_permissions(
        role=updated_teacher.role,
        organization_id=updated_teacher.organization_id,
        org_overrides=org_overrides,
    )
    response = TeacherResponse.model_validate(updated_teacher)
    response.permissions = permissions
    return response


# ── Instrumentos ─────────────────────────────────────────────────────────────

class InstrumentsUpdate(BaseModel):
    instrument_ids: list[int]


@router.put(
    "/me/instruments",
    response_model=TeacherResponse,
    summary="Reemplazar los instrumentos del profesor logueado",
)
async def update_my_instruments(
    data: InstrumentsUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    Reemplaza la lista completa de instrumentos del profesor.
    Enviar lista vacía [] quita todos los instrumentos.
    """
    result = await db.execute(
        select(Instrument).where(Instrument.id.in_(data.instrument_ids))
    )
    instruments = result.scalars().all()

    # Validar que todos los ids existan
    if len(instruments) != len(data.instrument_ids):
        found_ids = {i.id for i in instruments}
        missing = [i for i in data.instrument_ids if i not in found_ids]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Instrumentos no encontrados: {missing}",
        )

    current_teacher.instruments = list(instruments)
    await db.commit()
    await db.refresh(current_teacher)

    org_overrides = None
    if current_teacher.organization:
        org_overrides = current_teacher.organization.role_permissions
    permissions = resolve_permissions(
        role=current_teacher.role,
        organization_id=current_teacher.organization_id,
        org_overrides=org_overrides,
    )
    response = TeacherResponse.model_validate(current_teacher)
    response.permissions = permissions
    return response