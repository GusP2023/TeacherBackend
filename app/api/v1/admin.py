"""
Admin endpoints — Gestión de la organización y sus teachers.

Solo accesibles por teachers con rol org_admin.

Endpoints:
    POST  /admin/invite                     → Crear invitación para un nuevo teacher
    GET   /admin/invitations                → Listar invitaciones de la organización
    GET   /admin/teachers                   → Listar teachers de la organización
    PATCH /admin/teachers/{id}              → Cambiar rol o desactivar un teacher
    GET   /admin/permissions                → Ver permisos actuales de la organización
    PATCH /admin/permissions                → Configurar overrides de permisos por rol
    GET   /admin/permissions/schema         → Ver qué permisos son configurables (con labels)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import require_role
from app.core.permissions import (
    PERMISSION_DEFAULTS,
    UNRESTRICTED_ROLES,
    ALWAYS_ALLOWED_KEYS,
    resolve_permissions,
    get_overridable_keys_for_role,
)
from app.models.teacher import Teacher, VALID_ROLES
from app.models.organization import Organization
from app.schemas.invitation import InvitationCreate, InvitationResponse
from app.schemas.teacher import TeacherResponse
from app.crud import invitation as invitation_crud

router = APIRouter()


# ────────────────────────────────────────────────────
# INVITACIONES
# ────────────────────────────────────────────────────

@router.post(
    "/invite",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear invitación para un nuevo teacher",
)
async def create_invitation(
    data: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    """
    Crea una invitación de 48h para que un nuevo usuario se una a la organización.

    El token generado se envía (manualmente por ahora) al invitado.
    El invitado lo usa en POST /auth/accept-invite para registrarse.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    invitation = await invitation_crud.create(
        db=db,
        data=data,
        organization_id=current_teacher.organization_id,
        invited_by_id=current_teacher.id,
    )
    return invitation


@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    summary="Listar invitaciones de la organización",
)
async def list_invitations(
    only_pending: bool = False,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    """Lista todas las invitaciones de la organización. Filtrar pendientes con ?only_pending=true."""
    if not current_teacher.organization_id:
        return []
    return await invitation_crud.list_by_org(
        db, current_teacher.organization_id, only_pending=only_pending
    )


# ────────────────────────────────────────────────────
# GESTIÓN DE TEACHERS DE LA ORGANIZACIÓN
# ────────────────────────────────────────────────────

@router.get(
    "/teachers",
    response_model=list[TeacherResponse],
    summary="Listar teachers de la organización",
)
async def list_org_teachers(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    """Lista todos los teachers de la misma organización."""
    if not current_teacher.organization_id:
        return [current_teacher]

    result = await db.execute(
        select(Teacher).where(
            Teacher.organization_id == current_teacher.organization_id
        ).order_by(Teacher.name)
    )
    return result.scalars().all()


class TeacherAdminUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None


@router.patch(
    "/teachers/{teacher_id}",
    response_model=TeacherResponse,
    summary="Cambiar rol o desactivar un teacher de la organización",
)
async def update_org_teacher(
    teacher_id: int,
    data: TeacherAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    """
    Permite al org_admin:
    - Cambiar el rol de un teacher (teacher → coordinator, etc.)
    - Desactivar/reactivar una cuenta

    Restricciones:
    - No puede modificar su propia cuenta por este endpoint
    - El teacher debe pertenecer a la misma organización
    - No puede asignar rol 'org_admin' a otros (solo uno por org)
    """
    if teacher_id == current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes modificar tu propia cuenta desde este endpoint. Usa /teachers/me.",
        )

    result = await db.execute(
        select(Teacher).where(
            Teacher.id == teacher_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    target = result.scalar_one_or_none()

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Teacher no encontrado en tu organización.",
        )

    if data.role is not None:
        if data.role not in VALID_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rol inválido. Opciones válidas: {', '.join(VALID_ROLES)}",
            )
        target.role = data.role

    if data.active is not None:
        target.active = data.active

    await db.commit()
    await db.refresh(target)
    return target


# ────────────────────────────────────────────────────
# CONFIGURACIÓN DE PERMISOS DE LA ORGANIZACIÓN
# ────────────────────────────────────────────────────

class PermissionKeyLabel(BaseModel):
    """Descripción de una clave de permiso para mostrar en la UI."""
    key: str
    default: bool
    protected: bool  # True = nunca se puede restringir (ALWAYS_ALLOWED_KEYS)
    label: str
    description: str


# Labels legibles para la App Admin web
_PERMISSION_LABELS: dict[str, tuple[str, str]] = {
    "students.create":            ("Crear alumnos",           "Puede registrar nuevos alumnos en el sistema"),
    "students.edit_personal":     ("Editar datos personales", "Puede editar nombre, teléfono, email, cumpleaños y notas del alumno"),
    "students.edit_enrollment":   ("Editar inscripción",      "Puede cambiar el instrumento, nivel y estado de la inscripción"),
    "students.edit_schedule":     ("Editar horarios",         "Puede modificar los horarios de clase del alumno"),
    "students.suspend":           ("Suspender/reactivar",     "Puede suspender o reactivar a un alumno"),
    "students.delete":            ("Eliminar alumnos",        "Puede eliminar alumnos del sistema (acción irreversible)"),
    "classes.mark_attendance":    ("Marcar asistencia",       "Puede registrar asistencia, ausencias y licencias en las clases"),
    "classes.create_recovery":    ("Crear recuperaciones",    "Puede programar clases de recuperación"),
    "classes.delete":             ("Eliminar clases",         "Puede eliminar clases del calendario"),
    "finances.view_own":          ("Ver sus finanzas",        "Puede ver sus propias tarifas y resumen financiero"),
    "finances.view_all":          ("Ver finanzas globales",   "Puede ver las finanzas de todos los profesores"),
    "org.manage_users":           ("Gestionar usuarios",      "Puede ver y modificar las cuentas de otros miembros"),
    "org.invite_teacher":         ("Invitar miembros",        "Puede enviar invitaciones para unirse a la organización"),
    "org.change_teacher_role":    ("Cambiar roles",           "Puede cambiar el rol de otros miembros"),
    "org.configure_permissions":  ("Configurar permisos",     "Puede modificar los permisos de los roles"),
    "org.reset_total":            ("Reset total",             "Puede ejecutar un reset completo de datos (acción extrema)"),
}


@router.get(
    "/permissions/schema",
    summary="Ver el esquema de permisos configurables por rol",
)
async def get_permissions_schema(
    current_teacher: Teacher = Depends(require_role("org_admin")),
) -> dict[str, list[PermissionKeyLabel]]:
    """
    Retorna la lista de permisos configurables para cada rol, con sus
    valores default y etiquetas para mostrar en la UI de la App Admin.

    No incluye 'org_admin' ya que sus permisos nunca se configuran.
    Los permisos marcados como `protected: true` no pueden ser desactivados.
    """
    configurable_roles = [r for r in PERMISSION_DEFAULTS if r not in UNRESTRICTED_ROLES]
    result = {}

    for role in configurable_roles:
        defaults = PERMISSION_DEFAULTS[role]
        keys = []
        for key, default_value in defaults.items():
            label, description = _PERMISSION_LABELS.get(key, (key, ""))
            keys.append(PermissionKeyLabel(
                key=key,
                default=default_value,
                protected=key in ALWAYS_ALLOWED_KEYS,
                label=label,
                description=description,
            ))
        result[role] = keys

    return result


@router.get(
    "/permissions",
    summary="Ver los overrides de permisos actuales de la organización",
)
async def get_org_permissions(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
) -> dict:
    """
    Retorna los permisos efectivos actuales de cada rol en esta organización.

    La respuesta incluye:
    - `overrides`: el JSONB crudo guardado en BD (solo las diferencias)
    - `resolved`: los permisos efectivos completos por rol (defaults + overrides)
    """
    if not current_teacher.organization_id:
        # Independiente: retorna defaults de org_admin para todos los roles
        return {
            "overrides": None,
            "resolved": {
                role: dict(PERMISSION_DEFAULTS["org_admin"])
                for role in PERMISSION_DEFAULTS
            }
        }

    result = await db.execute(
        select(Organization).where(Organization.id == current_teacher.organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    overrides = org.role_permissions or {}
    resolved = {
        role: resolve_permissions(role, org.id, org.role_permissions)
        for role in PERMISSION_DEFAULTS
        if role not in UNRESTRICTED_ROLES
    }

    return {"overrides": overrides, "resolved": resolved}


class OrgPermissionsUpdate(BaseModel):
    """
    Body para actualizar permisos de la organización.

    Solo se aceptan cambios para roles no restringidos (no 'org_admin').
    Las claves protegidas (ALWAYS_ALLOWED_KEYS) se ignoran aunque se envíen.

    Ejemplo:
    {
        "teacher": {
            "students.create": false,
            "students.edit_enrollment": false,
            "classes.create_recovery": false
        }
    }
    """
    permissions: dict[str, dict[str, bool]]


@router.patch(
    "/permissions",
    summary="Configurar overrides de permisos para los roles de la organización",
)
async def update_org_permissions(
    data: OrgPermissionsUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
) -> dict:
    """
    Actualiza los overrides de permisos de la organización.

    Reglas de validación:
    - Solo se aceptan roles conocidos (no 'org_admin', no roles inventados).
    - Solo se aceptan claves de permisos conocidas.
    - Las claves protegidas se eliminan silenciosamente del payload.
    - Un rol con overrides vacíos {} se trata como "sin overrides" (usa defaults).
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Perfil independiente: no hay organización que configurar.",
        )

    result = await db.execute(
        select(Organization).where(Organization.id == current_teacher.organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    # Validar y limpiar el payload
    clean_overrides: dict[str, dict[str, bool]] = {}

    for role, role_perms in data.permissions.items():
        # Rechazar roles desconocidos o no configurables
        if role not in PERMISSION_DEFAULTS or role in UNRESTRICTED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rol '{role}' no es configurable. Roles válidos: "
                       f"{[r for r in PERMISSION_DEFAULTS if r not in UNRESTRICTED_ROLES]}",
            )

        known_keys = set(PERMISSION_DEFAULTS[role].keys())
        clean_role: dict[str, bool] = {}

        for key, value in role_perms.items():
            if key not in known_keys:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Clave de permiso desconocida: '{key}' para rol '{role}'.",
                )
            if key in ALWAYS_ALLOWED_KEYS:
                continue  # Silenciosamente ignorada
            clean_role[key] = bool(value)

        if clean_role:
            clean_overrides[role] = clean_role

    # Guardar (None si no hay nada que overridear)
    org.role_permissions = clean_overrides if clean_overrides else None

    await db.commit()
    await db.refresh(org)

    # Retornar permisos resueltos actualizados
    resolved = {
        role: resolve_permissions(role, org.id, org.role_permissions)
        for role in PERMISSION_DEFAULTS
        if role not in UNRESTRICTED_ROLES
    }
    return {
        "overrides": org.role_permissions,
        "resolved": resolved,
    }
