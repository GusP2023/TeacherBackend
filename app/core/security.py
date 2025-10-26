"""
Módulo de seguridad - Autenticación y autorización

Funcionalidades:
- Hash y verificación de passwords con bcrypt
- Generación y validación de tokens JWT
- Dependency para proteger rutas (get_current_teacher)

Uso:
    from app.core.security import get_password_hash, verify_password, create_access_token
    
    # Hash password
    hashed = get_password_hash("mi_password")
    
    # Verificar password
    is_valid = verify_password("mi_password", hashed)
    
    # Crear JWT
    token = create_access_token({"sub": user_email})
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db

# Security scheme para Swagger UI
security = HTTPBearer()


# ========================================
# PASSWORD HASHING (con bcrypt directo)
# ========================================

def get_password_hash(password: str) -> str:
    """
    Hashea un password usando bcrypt.
    
    Args:
        password: Password en texto plano
        
    Returns:
        Password hasheado (string)
        
    Example:
        hashed = get_password_hash("mypassword123")
    """
    # bcrypt necesita bytes
    password_bytes = password.encode('utf-8')
    # gensalt() genera el salt automáticamente
    salt = bcrypt.gensalt()
    # hashpw retorna bytes, lo convertimos a string
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si un password coincide con su hash.
    
    Args:
        plain_password: Password en texto plano
        hashed_password: Password hasheado
        
    Returns:
        True si coinciden, False si no
        
    Example:
        is_valid = verify_password("mypassword123", hashed)
    """
    # Convertir a bytes
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    # Verificar
    return bcrypt.checkpw(password_bytes, hashed_bytes)


# ========================================
# JWT TOKEN
# ========================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un token JWT.
    
    Args:
        data: Datos a incluir en el token (ej: {"sub": "user@email.com"})
        expires_delta: Tiempo de expiración (opcional)
        
    Returns:
        Token JWT (string)
        
    Example:
        token = create_access_token({"sub": "user@example.com"})
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> dict:
    """
    Decodifica y valida un token JWT.
    
    Args:
        token: Token JWT a decodificar
        
    Returns:
        Payload del token (dict)
        
    Raises:
        HTTPException: Si el token es inválido o expirado
        
    Example:
        payload = decode_token(token)
        email = payload.get("sub")
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ========================================
# DEPENDENCY PARA FASTAPI
# ========================================

async def get_current_teacher(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """
    Dependency para proteger rutas - obtiene el teacher autenticado.
    
    Verifica el token JWT y retorna el objeto Teacher.
    
    Usage:
        @app.get("/protected")
        async def protected_route(
            current_teacher: Teacher = Depends(get_current_teacher)
        ):
            return {"teacher": current_teacher.name}
    
    Raises:
        HTTPException 401: Si el token es inválido o el teacher no existe
    """
    # Extraer token
    token = credentials.credentials
    
    # Decodificar token
    payload = decode_token(token)
    email: str = payload.get("sub")
    
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Buscar teacher en BD
    from app.crud import teacher as teacher_crud
    teacher_obj = await teacher_crud.get_by_email(db, email)
    
    if teacher_obj is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Teacher no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not teacher_obj.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher inactivo"
        )
    
    return teacher_obj