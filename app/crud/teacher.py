"""
CRUD operations for Teacher model
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.teacher import Teacher
from app.schemas.teacher import TeacherCreate, TeacherUpdate
from app.core.security import verify_password, get_password_hash


async def get(db: AsyncSession, teacher_id: int) -> Teacher | None:
    """
    Obtener un profesor por ID
    
    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
    
    Returns:
        Teacher si existe, None si no
    """
    result = await db.execute(
        select(Teacher).where(Teacher.id == teacher_id)
    )
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> Teacher | None:
    """
    Obtener un profesor por email
    
    Args:
        db: Sesión de base de datos
        email: Email del profesor
    
    Returns:
        Teacher si existe, None si no
    """
    result = await db.execute(
        select(Teacher).where(Teacher.email == email)
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, teacher_data: TeacherCreate) -> Teacher:
    """
    Crear un profesor nuevo
    
    Args:
        db: Sesión de base de datos
        teacher_data: Datos del profesor a crear
    
    Returns:
        Teacher creado con id asignado
    """
    # Hashear el password antes de guardar
    teacher_dict = teacher_data.model_dump()
    teacher_dict['password_hash'] = get_password_hash(teacher_dict.pop('password'))
    
    # Crear el objeto Teacher
    teacher = Teacher(**teacher_dict)
    
    db.add(teacher)
    await db.commit()
    await db.refresh(teacher)
    
    return teacher


async def update(
    db: AsyncSession,
    teacher_id: int,
    teacher_data: TeacherUpdate
) -> Teacher | None:
    """
    Actualizar un profesor existente
    
    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor a actualizar
        teacher_data: Datos a actualizar (solo campos no None)
    
    Returns:
        Teacher actualizado si existe, None si no
    """
    # Obtener el profesor
    result = await db.execute(
        select(Teacher).where(Teacher.id == teacher_id)
    )
    teacher = result.scalar_one_or_none()
    
    if not teacher:
        return None
    
    # Actualizar solo campos que no sean None
    update_data = teacher_data.model_dump(exclude_unset=True)
    
    # Si se actualiza el password, hashearlo
    if 'password' in update_data:
        update_data['password_hash'] = get_password_hash(update_data.pop('password'))
    
    for field, value in update_data.items():
        setattr(teacher, field, value)
    
    await db.commit()
    await db.refresh(teacher)
    
    return teacher


async def authenticate(
    db: AsyncSession,
    email: str,
    password: str
) -> Teacher | None:
    """
    Autenticar un profesor (para login)
    
    Args:
        db: Sesión de base de datos
        email: Email del profesor
        password: Password en texto plano
    
    Returns:
        Teacher si las credenciales son correctas, None si no
    """
    # Buscar profesor por email
    teacher = await get_by_email(db, email)
    
    if not teacher:
        return None
    
    # Verificar password
    if not verify_password(password, teacher.password_hash):
        return None
    
    return teacher