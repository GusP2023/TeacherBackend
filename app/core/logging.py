"""
Security logging helper — ProfesorSYS

Función auxiliar para registrar eventos de seguridad de forma
no-bloqueante. Los errores de logging nunca deben interrumpir
la request principal.

Uso en endpoints:
    from app.core.logging import log_event, Actions

    await log_event(db, request,
        action=Actions.LOGIN_SUCCESS,
        teacher_id=teacher.id,
        detail=teacher.email,
    )

Uso cuando la acción falla (sin teacher_id):
    await log_event(db, request,
        action=Actions.LOGIN_FAILED,
        success=False,
        detail=f"email: {credentials.email}",
    )
"""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security_log import SecurityLog


# ── Constantes de acciones ────────────────────────────────────────────────────

class Actions:
    # Autenticación
    LOGIN_SUCCESS       = "LOGIN_SUCCESS"
    LOGIN_FAILED        = "LOGIN_FAILED"
    REGISTER            = "REGISTER"
    PASSWORD_CHANGED    = "PASSWORD_CHANGED"
    TOKEN_REFRESH       = "TOKEN_REFRESH"

    # Invitaciones
    INVITE_CREATED      = "INVITE_CREATED"
    INVITE_ACCEPTED     = "INVITE_ACCEPTED"

    # Gestión de teachers
    TEACHER_ROLE_CHANGED = "TEACHER_ROLE_CHANGED"
    TEACHER_DEACTIVATED  = "TEACHER_DEACTIVATED"

    # Alumnos
    STUDENT_CREATED     = "STUDENT_CREATED"
    STUDENT_DELETED     = "STUDENT_DELETED"

    # Operaciones críticas
    RESET_TOTAL         = "RESET_TOTAL"
    FULL_SYNC           = "FULL_SYNC"
    EMERGENCY_RESET     = "EMERGENCY_RESET"


# ── Extracción de IP ──────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str | None:
    """
    Extrae la IP real del cliente.
    Considera proxies y load balancers (X-Forwarded-For).
    """
    # Render y otros proxies ponen la IP real aquí
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Puede ser "ip1, ip2, ip3" — la primera es la del cliente
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ── Función principal ─────────────────────────────────────────────────────────

async def log_event(
    db: AsyncSession,
    request: Request,
    action: str,
    teacher_id: int | None = None,
    resource: str | None = None,
    resource_id: int | None = None,
    success: bool = True,
    detail: str | None = None,
) -> None:
    """
    Registra un evento de seguridad.

    Nunca lanza excepciones — si el logging falla, la request
    principal continúa normalmente. Los logs son un "best effort".

    Args:
        db:          Sesión de base de datos
        request:     Request de FastAPI (para extraer IP y User-Agent)
        action:      Constante de Actions (ej: Actions.LOGIN_SUCCESS)
        teacher_id:  ID del teacher que ejecuta (None para acciones anónimas)
        resource:    Tipo de recurso afectado (ej: "student", "teacher")
        resource_id: ID del recurso afectado
        success:     True si la acción fue exitosa
        detail:      Texto libre con contexto adicional
    """
    try:
        log = SecurityLog(
            teacher_id=teacher_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip_address=_get_client_ip(request),
            user_agent=request.headers.get("User-Agent", "")[:300],
            success=success,
            detail=detail,
        )
        db.add(log)
        await db.commit()
    except Exception as e:
        # Log nunca debe romper la request principal
        print(f"[SecurityLog] ⚠️ Error al guardar log '{action}': {e}")
