"""
Schemas Pydantic para Autenticación (JWT)

CONCEPTO:
Manejo de login, tokens JWT y datos de autenticación.

FLUJO:
1. Usuario envía email + password (Login)
2. Backend valida y devuelve Token (JWT)
3. Frontend guarda token en localStorage (NO pide login cada vez)
4. En cada request, frontend envía token en header
5. Backend decodifica token y obtiene TokenData (id, email del profesor)

TOKEN JWT:
- Se guarda en localStorage del móvil
- Expira en 30 días (configurable en .env)
- Contiene: teacher_id, email, exp (fecha expiración)
"""
from pydantic import BaseModel, EmailStr, Field


class Login(BaseModel):
    """
    Schema para LOGIN (POST /auth/login)
    
    El usuario envía email + password.
    El backend valida y devuelve un Token.
    
    Ejemplo:
    {
        "email": "profesor@example.com",
        "password": "mipassword123"
    }
    """
    email: EmailStr
    password: str = Field(..., min_length=8)


class Token(BaseModel):
    """
    Schema para RESPUESTA del login.
    
    Se devuelve al usuario después de autenticarse exitosamente.
    El frontend guarda access_token en localStorage.
    
    Ejemplo de respuesta:
    {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer"
    }
    
    IMPORTANTE:
    - token_type siempre es "bearer"
    - access_token es el JWT que contiene los datos del profesor
    - Frontend lo envía en headers: Authorization: Bearer {token}
    """
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """
    Schema para DATOS DENTRO del JWT (payload).
    
    Cuando el backend decodifica el token, obtiene estos datos.
    NO se envía al frontend, es solo para uso interno.
    
    Contiene:
    - email: del profesor logueado (para identificarlo)
    - teacher_id: id del profesor (para queries a BD)
    
    NOTA:
    El JWT también incluye "exp" (expiration) automáticamente,
    pero no lo ponemos aquí porque lo maneja PyJWT internamente.
    """
    email: EmailStr
    teacher_id: int = Field(..., gt=0)