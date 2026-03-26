"""
Authentication endpoints - Login & Register
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.logging import log_event, Actions
from app.core.security import create_access_token, security, should_refresh_token, refresh_access_token, decode_token
from app.crud import teacher
from app.crud import organization as org_crud
from app.crud import invitation as invitation_crud
from app.schemas.auth import Login, Token
from app.schemas.teacher import TeacherCreate, TeacherResponse
from app.schemas.organization import OrganizationCreate
from app.schemas.invitation import AcceptInviteRequest
from app.models.teacher import Teacher

router = APIRouter()


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")  # Máx 10 intentos por minuto por IP
async def login(
    request: Request,          # requerido por slowapi
    credentials: Login,
    db: AsyncSession = Depends(get_db)
):
    """
    Login endpoint con rate limiting (10 intentos/min por IP).
    Registra en security_logs tanto éxitos como fallos.
    """
    teacher_obj = await teacher.authenticate(
        db,
        email=credentials.email,
        password=credentials.password
    )

    if not teacher_obj:
        # Loguear intento fallido (sin teacher_id porque no sabemos quién es)
        await log_event(
            db, request,
            action=Actions.LOGIN_FAILED,
            success=False,
            detail=f"email: {credentials.email}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": teacher_obj.email})

    # Loguear login exitoso
    await log_event(
        db, request,
        action=Actions.LOGIN_SUCCESS,
        teacher_id=teacher_obj.id,
        detail=teacher_obj.email,
    )

    return Token(access_token=access_token, token_type="bearer")


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    teacher_data: TeacherCreate,
    org_name: str = "Mi Escuela",
    db: AsyncSession = Depends(get_db)
):
    """
    Registro de nueva escuela.

    Crea:
    1. Una Organization nueva con el nombre indicado (default: "Mi Escuela")
    2. El teacher con rol org_admin, asociado a esa organización

    Uso: POST /auth/register?org_name=Escuela+Armonía

    El teacher queda como administrador de su propia escuela y puede
    invitar a otros teachers desde /admin/invite.

    Raises:
        400: Si el email ya está registrado
    """
    # Verificar email único
    existing_teacher = await teacher.get_by_email(db, email=teacher_data.email)
    if existing_teacher:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El email {teacher_data.email} ya está registrado",
        )

    # 1. Crear la organización
    org = await org_crud.create(db, OrganizationCreate(name=org_name))

    # 2. Crear el teacher como org_admin de esa organización
    new_teacher = await teacher.create(db, teacher_data)

    # 3. Asociar teacher → organización con rol org_admin
    new_teacher.organization_id = org.id
    new_teacher.role = "org_admin"
    await db.commit()
    await db.refresh(new_teacher)

    await log_event(
        db, request,
        action=Actions.REGISTER,
        teacher_id=new_teacher.id,
        detail=f"org: {org.name} ({org.slug})",
    )

    access_token = create_access_token(data={"sub": new_teacher.email})
    return Token(access_token=access_token, token_type="bearer")


@router.post("/accept-invite", response_model=Token, status_code=status.HTTP_201_CREATED)
async def accept_invite(
    data: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Aceptar una invitación y crear cuenta.

    El token de invitación es generado por el org_admin desde POST /admin/invite.
    El invitado recibe el token (por email o WhatsApp) y lo usa aquí para
    crear su cuenta con el rol pre-asignado.

    Raises:
        400: Token inválido, expirado o ya usado
        409: El email del invitado ya tiene cuenta
    """
    # Buscar la invitación
    invitation = await invitation_crud.get_by_token(db, data.token)

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de invitación inválido.",
        )

    if not invitation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta invitación ya fue usada o expiró. Solicita una nueva al administrador.",
        )

    # Verificar que el email elegido por el profesor no tenga cuenta
    existing = await teacher.get_by_email(db, email=data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El email {data.email} ya está registrado. Usa otro email.",
        )

    from decimal import Decimal
    from app.schemas.teacher import TeacherCreate as TC
    teacher_data = TC(
        email=data.email,
        name=data.name,
        password=data.password,
        tariff_individual=Decimal(str(data.tariff_individual)),
        tariff_group=Decimal(str(data.tariff_group)),
    )
    new_teacher = await teacher.create(db, teacher_data)

    # Asociar a la organización con el rol de la invitación
    new_teacher.organization_id = invitation.organization_id
    new_teacher.role = invitation.role
    await db.commit()
    await db.refresh(new_teacher)

    # Marcar la invitación como usada
    await invitation_crud.mark_used(db, invitation)

    access_token = create_access_token(data={"sub": new_teacher.email})
    return Token(access_token=access_token, token_type="bearer")


# ========================================
# FIX 2: ENDPOINT DE REFRESH DE TOKEN
# ========================================
@router.post("/refresh", response_model=Token)
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Refresh endpoint - Refrescar token JWT expirado o próximo a expirar
    
    CRÍTICO: Este endpoint debe aceptar tokens expirados para poder refrescarlos.
    Por eso NO usa decode_token() que valida expiración, sino jwt.decode()
    con options={"verify_exp": False}.
    
    Esta es la base del auto-refresh en el frontend (Fix 2).
    El interceptor de client.ts llama a este endpoint cuando recibe 401,
    permitiendo que el usuario continúe sin desconectarse.
    
    Args:
        credentials: Bearer token del usuario (puede estar expirado)
    
    Returns:
        Token JWT nuevo con 30 días de validez
    
    Raises:
        401: Si el token es inválido sintácticamente o está corrupto
        
    Example:
        POST /auth/refresh
        Authorization: Bearer {expired_token}
        
        Response:
        {
            "access_token": "{new_token}",
            "token_type": "bearer"
        }
    """
    from jose import jwt, JWTError
    from app.core.config import settings
    
    token = credentials.credentials
    
    # Decodificar token SIN validar expiración (aceptar tokens expirados)
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False}  # ← CRÍTICO: Permitir tokens expirados
        )
        
        email = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido - sin email",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Crear nuevo token con 30 días de validez (siempre refrescar)
        new_token = create_access_token({"sub": email})
        return Token(access_token=new_token, token_type="bearer")
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido o corrupto: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )
