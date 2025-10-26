"""
Teachers endpoints - Perfil del profesor (solo su propia información)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import teacher
from app.models.teacher import Teacher
from app.schemas.teacher import TeacherUpdate, TeacherResponse

router = APIRouter()


@router.get("/me", response_model=TeacherResponse)
async def get_my_profile(
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Obtener el perfil del profesor logueado
    
    No necesita db query, ya viene del token JWT
    
    Args:
        current_teacher: Profesor autenticado (desde JWT)
    
    Returns:
        Datos del profesor logueado (sin password)
    """
    return current_teacher


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
    
    return updated_teacher