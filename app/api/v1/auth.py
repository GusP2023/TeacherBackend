"""
Authentication endpoints - Login & Register
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import create_access_token
from app.crud import teacher
from app.schemas.auth import Login, Token
from app.schemas.teacher import TeacherCreate

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(
    credentials: Login,
    db: AsyncSession = Depends(get_db)
):
    """
    Login endpoint - Autenticar profesor y obtener JWT token
    
    El token expira en 30 días (configurable en .env)
    Guardar en localStorage del móvil para login persistente
    
    Args:
        credentials: Email y password del profesor
        db: Sesión de base de datos
    
    Returns:
        Token JWT para usar en header Authorization: Bearer {token}
    
    Raises:
        401: Si credenciales incorrectas
    """
    # Autenticar usando CRUD
    teacher_obj = await teacher.authenticate(
        db,
        email=credentials.email,
        password=credentials.password
    )
    
    if not teacher_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Crear JWT token con "sub" (estándar JWT)
    access_token = create_access_token(
        data={"sub": teacher_obj.email}
    )
    
    return Token(access_token=access_token, token_type="bearer")


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    teacher_data: TeacherCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Register endpoint - Crear cuenta nueva de profesor
    
    Después de registrarse, el usuario recibe automáticamente un token JWT
    para que quede logueado sin necesidad de hacer login manual.
    
    Args:
        teacher_data: Datos del profesor a registrar
        db: Sesión de base de datos
    
    Returns:
        Token JWT para usar inmediatamente (auto-login)
    
    Raises:
        400: Si el email ya está registrado
    """
    # Verificar que el email no exista
    existing_teacher = await teacher.get_by_email(db, email=teacher_data.email)
    
    if existing_teacher:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El email {teacher_data.email} ya está registrado"
        )
    
    # Crear el profesor (el CRUD hashea el password automáticamente)
    new_teacher = await teacher.create(db, teacher_data)
    
    # Crear JWT token automáticamente (auto-login después de registro)
    access_token = create_access_token(
        data={"sub": new_teacher.email}
    )
    
    return Token(access_token=access_token, token_type="bearer")