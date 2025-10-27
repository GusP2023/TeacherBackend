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
    Crea un token JWT con sliding window (renovación automática).

    Args:
        data: Datos a incluir en el token (ej: {"sub": "user@email.com"})
        expires_delta: Tiempo de expiración (opcional, default: 30 días)

    Returns:
        Token JWT (string)

    Example:
        token = create_access_token({"sub": "user@example.com"})

    Note:
        Con sliding window, el token se renueva automáticamente si tiene
        menos de 25 días de vida restante cuando se usa (ver middleware).
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Default: 30 días (43200 minutos) para sliding window
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


def should_refresh_token(token: str, refresh_threshold_days: int = 25) -> bool:
    """
    Determina si un token debe ser refrescado basándose en su tiempo de vida restante.

    Args:
        token: Token JWT a verificar
        refresh_threshold_days: Días mínimos de vida restante para NO refrescar (default: 25)
                               Si le quedan menos de 25 días, se debe refrescar.

    Returns:
        True si el token debe ser refrescado, False si aún es válido por suficiente tiempo

    Example:
        if should_refresh_token(token):
            new_token = refresh_access_token(token)

    Note:
        Configurado para tokens de 30 días:
        - Si tiene 26-30 días restantes: NO refrescar
        - Si tiene 0-25 días restantes: SÍ refrescar (se emitirá nuevo token de 30 días)
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False}  # No validar expiración aquí
        )

        exp_timestamp = payload.get("exp")
        if not exp_timestamp:
            return True  # Si no tiene exp, refrescar

        expire_datetime = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        now = datetime.now(timezone.utc)

        time_remaining = expire_datetime - now

        # Si le quedan menos de X días, refrescar
        return time_remaining < timedelta(days=refresh_threshold_days)

    except JWTError:
        return False  # Si el token es inválido, no intentar refrescar


def refresh_access_token(token: str) -> str:
    """
    Refresca un token JWT válido, emitiendo uno nuevo con 30 días adicionales.

    Args:
        token: Token JWT actual (debe ser válido)

    Returns:
        Nuevo token JWT con 30 días de expiración

    Raises:
        HTTPException: Si el token actual es inválido o expirado

    Example:
        new_token = refresh_access_token(old_token)

    Note:
        Esta función valida que el token sea legítimo antes de emitir uno nuevo.
        Solo refresca el timestamp de expiración, mantiene el mismo payload (sub, etc).
    """
    # Validar y extraer payload del token actual
    payload = decode_token(token)  # Esto valida que sea legítimo

    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido - sin email"
        )

    # Crear nuevo token con el mismo email pero nueva expiración
    new_token = create_access_token({"sub": email})
    return new_token


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