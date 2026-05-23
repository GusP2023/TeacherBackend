"""
Admin endpoints — Gestión de la organización y sus teachers.

Solo accesibles por teachers con rol org_admin.

Endpoints:
    POST  /admin/invite                          → Crear invitación para un nuevo teacher
    GET   /admin/invitations                     → Listar invitaciones de la organización
    GET   /admin/teachers                        → Listar teachers de la organización
    PATCH /admin/teachers/{id}                   → Cambiar rol o desactivar un teacher
    GET   /admin/teachers/{id}/permissions       → Ver permisos efectivos de un teacher
    PATCH /admin/teachers/{id}/permissions       → Configurar permisos individuales de un teacher
    GET   /admin/permissions/schema              → Ver qué permisos son configurables (con labels)
"""

from datetime import date, time as time_module
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel, Field, ConfigDict

from app.core.database import get_db
from app.core.security import require_role
from app.core.permissions import (
    PERMISSION_DEFAULTS,
    UNRESTRICTED_ROLES,
    ALWAYS_ALLOWED_KEYS,
    resolve_permissions,
)
from app.models.branch import Branch
from app.models.room import Room
from app.models.room_assignment import RoomAssignment
from app.models.room_override import RoomOverride
from app.models.schedule import DayOfWeek
from app.models.teacher import Teacher, VALID_ROLES
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
# PERMISOS POR TEACHER
# ────────────────────────────────────────────────────

class PermissionKeyLabel(BaseModel):
    """Descripción de una clave de permiso para mostrar en la UI."""
    key: str
    default: bool
    protected: bool
    label: str
    description: str


# Labels legibles para la App Admin web
_PERMISSION_LABELS: dict[str, tuple[str, str]] = {
    "students.create":            ("Crear alumnos",            "Puede registrar nuevos alumnos en el sistema"),
    "students.view_enrollment":   ("Ver inscripción",           "Puede ver instrumento, nivel, créditos y estado de la inscripción (sin modificar)"),
    "students.edit_personal":     ("Editar datos personales",  "Puede editar nombre, teléfono, email, cumpleaños y notas del alumno"),
    "students.edit_enrollment":   ("Editar inscripción",       "Puede cambiar el instrumento, nivel y estado de la inscripción"),
    "students.edit_schedule":     ("Editar horarios",          "Puede modificar los horarios de clase del alumno"),
    "students.suspend":           ("Suspender/reactivar",      "Puede suspender o reactivar a un alumno"),
    "students.delete":            ("Eliminar alumnos",         "Puede eliminar alumnos del sistema (acción irreversible)"),
    "classes.mark_attendance":    ("Marcar asistencia",        "Puede registrar asistencia, ausencias y licencias en las clases"),
    "classes.create_recovery":    ("Crear recuperaciones",     "Puede programar clases de recuperación"),
    "classes.delete":             ("Eliminar clases",          "Puede eliminar clases del calendario"),
    "finances.view_own":          ("Ver sus finanzas",         "Puede ver sus propias tarifas y resumen financiero"),
    "finances.view_all":          ("Ver finanzas globales",    "Puede ver las finanzas de todos los profesores"),
    "org.manage_users":           ("Gestionar usuarios",       "Puede ver y modificar las cuentas de otros miembros"),
    "org.invite_teacher":         ("Invitar miembros",         "Puede enviar invitaciones para unirse a la organización"),
    "org.change_teacher_role":    ("Cambiar roles",            "Puede cambiar el rol de otros miembros"),
    "org.configure_permissions":  ("Configurar permisos",      "Puede modificar los permisos de los roles"),
    "org.reset_total":            ("Reset total",              "Puede ejecutar un reset completo de datos (acción extrema)"),
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
    "/teachers/{teacher_id}/permissions",
    summary="Ver permisos efectivos de un teacher",
)
async def get_teacher_permissions(
    teacher_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
) -> dict:
    """
    Retorna los permisos efectivos del teacher indicado.

    La respuesta incluye:
    - `custom_permissions`: overrides individuales guardados en BD (o null)
    - `resolved`: permisos efectivos completos (defaults del rol + custom_permissions)
    """
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

    resolved = resolve_permissions(target.role, target.organization_id, target.custom_permissions)

    return {
        "teacher_id": target.id,
        "name": target.name,
        "role": target.role,
        "custom_permissions": target.custom_permissions,
        "resolved": resolved,
    }


# ────────────────────────────────────────────────────
# SUCURSALES, SALAS Y ASIGNACIONES DE SALA
# ────────────────────────────────────────────────────


class BranchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    address: str | None = Field(None, max_length=255)


class BranchResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    address: str | None = None
    active: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class BranchUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    address: str | None = Field(None, max_length=255)
    active: bool | None = None


@router.post(
    "/branches",
    response_model=BranchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear sucursal",
)
async def create_branch(
    data: BranchCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    branch = Branch(
        organization_id=current_teacher.organization_id,
        name=data.name,
        address=data.address,
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get(
    "/branches",
    response_model=list[BranchResponse],
    summary="Listar sucursales de la organización",
)
async def list_branches(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        return []

    query = select(Branch).where(
        Branch.organization_id == current_teacher.organization_id
    )
    if not include_inactive:
        query = query.where(Branch.active.is_(True))
    query = query.order_by(Branch.name)

    result = await db.execute(query)
    return result.scalars().all()


@router.patch(
    "/branches/{branch_id}",
    response_model=BranchResponse,
    summary="Editar sucursal",
)
async def update_branch(
    branch_id: int,
    data: BranchUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == current_teacher.organization_id,
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sucursal no encontrada en tu organización.",
        )

    if data.name is not None:
        branch.name = data.name
    if data.address is not None:
        branch.address = data.address
    if data.active is not None:
        branch.active = data.active

    await db.commit()
    await db.refresh(branch)
    return branch


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=255)
    capacity: int = Field(default=1, ge=1)


class RoomResponse(BaseModel):
    id: int
    branch_id: int
    organization_id: int
    name: str
    description: str | None = None
    capacity: int
    active: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class RoomUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=255)
    capacity: int | None = Field(None, ge=1)
    active: bool | None = None


@router.post(
    "/branches/{branch_id}/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear sala en una sucursal",
)
async def create_room(
    branch_id: int,
    data: RoomCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == current_teacher.organization_id,
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sucursal no encontrada en tu organización.",
        )

    room = Room(
        branch_id=branch_id,
        organization_id=current_teacher.organization_id,
        name=data.name,
        description=data.description,
        capacity=data.capacity,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


@router.get(
    "/branches/{branch_id}/rooms",
    response_model=list[RoomResponse],
    summary="Listar salas de una sucursal",
)
async def list_branch_rooms(
    branch_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        return []

    result = await db.execute(
        select(Room).where(
            Room.branch_id == branch_id,
            Room.organization_id == current_teacher.organization_id,
            Room.active.is_(True),
        ).order_by(Room.name)
    )
    return result.scalars().all()


@router.get(
    "/rooms",
    response_model=list[RoomResponse],
    summary="Listar todas las salas de la organización",
)
async def list_org_rooms(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        return []

    result = await db.execute(
        select(Room).where(
            Room.organization_id == current_teacher.organization_id,
            Room.active.is_(True),
        ).order_by(Room.name)
    )
    return result.scalars().all()


@router.patch(
    "/rooms/{room_id}",
    response_model=RoomResponse,
    summary="Editar sala",
)
async def update_room(
    room_id: int,
    data: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Room).where(
            Room.id == room_id,
            Room.organization_id == current_teacher.organization_id,
        )
    )
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sala no encontrada en tu organización.",
        )

    if data.name is not None:
        room.name = data.name
    if data.description is not None:
        room.description = data.description
    if data.capacity is not None:
        room.capacity = data.capacity
    if data.active is not None:
        room.active = data.active

    await db.commit()
    await db.refresh(room)
    return room


class RoomAssignmentCreate(BaseModel):
    teacher_id: int
    room_id: int
    day: DayOfWeek
    time: time_module
    duration: int = Field(..., gt=0)
    valid_from: date


class RoomAssignmentResponse(BaseModel):
    id: int
    teacher_id: int
    room_id: int
    day: DayOfWeek
    time: time_module
    duration: int
    valid_from: date
    valid_until: date | None = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/room-assignments",
    response_model=RoomAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar sala recurrente a un profesor",
)
async def create_room_assignment(
    data: RoomAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    teacher_result = await db.execute(
        select(Teacher).where(
            Teacher.id == data.teacher_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    teacher = teacher_result.scalar_one_or_none()
    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Teacher no encontrado en tu organización.",
        )

    room_result = await db.execute(
        select(Room).where(
            Room.id == data.room_id,
            Room.organization_id == current_teacher.organization_id,
        )
    )
    room = room_result.scalar_one_or_none()
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sala no encontrada en tu organización.",
        )

    active_assignments = await db.execute(
        select(RoomAssignment).where(
            RoomAssignment.teacher_id == data.teacher_id,
            RoomAssignment.day == data.day,
            or_(
                RoomAssignment.valid_until.is_(None),
                RoomAssignment.valid_until > data.valid_from,
            ),
        )
    )
    for existing in active_assignments.scalars().all():
        existing.valid_until = data.valid_from

    assignment = RoomAssignment(
        teacher_id=data.teacher_id,
        room_id=data.room_id,
        day=data.day,
        time=data.time,
        duration=data.duration,
        valid_from=data.valid_from,
        valid_until=None,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


@router.get(
    "/room-assignments",
    response_model=list[RoomAssignmentResponse],
    summary="Listar asignaciones de sala activas",
)
async def list_room_assignments(
    teacher_id: int | None = None,
    room_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        return []

    today = date.today()
    query = select(RoomAssignment).join(Room).where(
        Room.organization_id == current_teacher.organization_id,
        or_(
            RoomAssignment.valid_until.is_(None),
            RoomAssignment.valid_until > today,
        ),
    )

    if teacher_id is not None:
        query = query.where(RoomAssignment.teacher_id == teacher_id)
    if room_id is not None:
        query = query.where(RoomAssignment.room_id == room_id)

    query = query.order_by(RoomAssignment.teacher_id, RoomAssignment.day, RoomAssignment.time)
    result = await db.execute(query)
    return result.scalars().all()


@router.delete(
    "/room-assignments/{assignment_id}",
    response_model=RoomAssignmentResponse,
    summary="Cerrar una asignación recurrente de sala",
)
async def close_room_assignment(
    assignment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(RoomAssignment).join(Room).where(
            RoomAssignment.id == assignment_id,
            Room.organization_id == current_teacher.organization_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asignación de sala no encontrada en tu organización.",
        )

    assignment.valid_until = date.today()
    await db.commit()
    await db.refresh(assignment)
    return assignment


class RoomOverrideCreate(BaseModel):
    teacher_id: int
    room_id: int | None = None
    date: date
    time: time_module
    duration: int = Field(..., gt=0)
    reason: str | None = Field(None, max_length=255)


class RoomOverrideResponse(BaseModel):
    id: int
    teacher_id: int
    room_id: int | None = None
    date: date
    time: time_module
    duration: int
    reason: str | None = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/room-overrides",
    response_model=RoomOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear override puntual de sala",
)
async def create_room_override(
    data: RoomOverrideCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    teacher_result = await db.execute(
        select(Teacher).where(
            Teacher.id == data.teacher_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    teacher = teacher_result.scalar_one_or_none()
    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Teacher no encontrado en tu organización.",
        )

    if data.room_id is not None:
        room_result = await db.execute(
            select(Room).where(
                Room.id == data.room_id,
                Room.organization_id == current_teacher.organization_id,
            )
        )
        room = room_result.scalar_one_or_none()
        if not room:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sala no encontrada en tu organización.",
            )

    existing_result = await db.execute(
        select(RoomOverride).where(
            RoomOverride.teacher_id == data.teacher_id,
            RoomOverride.date == data.date,
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un override para ese teacher y esa fecha.",
        )

    override = RoomOverride(
        teacher_id=data.teacher_id,
        room_id=data.room_id,
        date=data.date,
        time=data.time,
        duration=data.duration,
        reason=data.reason,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return override


@router.get(
    "/room-overrides",
    response_model=list[RoomOverrideResponse],
    summary="Listar overrides puntuales futuros",
)
async def list_room_overrides(
    teacher_id: int | None = None,
    room_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        return []

    if room_id is not None:
        room_result = await db.execute(
            select(Room).where(
                Room.id == room_id,
                Room.organization_id == current_teacher.organization_id,
            )
        )
        if not room_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sala no encontrada en tu organización.",
            )

    today = date.today()
    query = select(RoomOverride).join(Teacher).where(
        Teacher.organization_id == current_teacher.organization_id,
        RoomOverride.date >= today,
    )
    if teacher_id is not None:
        query = query.where(RoomOverride.teacher_id == teacher_id)
    if room_id is not None:
        query = query.where(RoomOverride.room_id == room_id)

    result = await db.execute(query.order_by(RoomOverride.date, RoomOverride.time))
    return result.scalars().all()


@router.delete(
    "/room-overrides/{override_id}",
    summary="Eliminar override puntual de sala",
)
async def delete_room_override(
    override_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(RoomOverride).join(Teacher).where(
            RoomOverride.id == override_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    override = result.scalar_one_or_none()
    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Override no encontrado en tu organización.",
        )

    await db.delete(override)
    await db.commit()
    return {"deleted": True}


class OccupiedBy(BaseModel):
    teacher_id: int
    teacher_name: str


class RoomAvailabilityResponse(BaseModel):
    id: int
    branch_id: int
    name: str
    active: bool
    available: bool
    occupied_by: OccupiedBy | None = None

    model_config = ConfigDict(from_attributes=True)


@router.get(
    "/rooms/availability",
    response_model=list[RoomAvailabilityResponse],
    summary="Ver disponibilidad de salas para un slot",
)
async def get_room_availability(
    day: DayOfWeek,
    time: str,
    duration: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
):
    if not current_teacher.organization_id:
        return []

    try:
        requested_time = time_module.fromisoformat(time)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de hora inválido. Use HH:MM o HH:MM:SS.",
        )

    end_minutes = (requested_time.hour * 60 + requested_time.minute) + duration

    rooms_result = await db.execute(
        select(Room).where(
            Room.organization_id == current_teacher.organization_id,
            Room.active.is_(True),
        ).order_by(Room.name)
    )
    rooms = rooms_result.scalars().all()

    assignment_result = await db.execute(
        select(RoomAssignment, Teacher).join(Teacher, Teacher.id == RoomAssignment.teacher_id).join(Room, Room.id == RoomAssignment.room_id).where(
            Room.organization_id == current_teacher.organization_id,
            RoomAssignment.day == day,
            or_(
                RoomAssignment.valid_until.is_(None),
                RoomAssignment.valid_until > date.today(),
            ),
        )
    )

    occupied_by_room: dict[int, OccupiedBy] = {}
    for assignment, teacher in assignment_result.all():
        start_minutes = assignment.time.hour * 60 + assignment.time.minute
        assignment_end = start_minutes + assignment.duration
        if start_minutes < end_minutes and assignment_end > (requested_time.hour * 60 + requested_time.minute):
            if assignment.room_id not in occupied_by_room:
                occupied_by_room[assignment.room_id] = OccupiedBy(
                    teacher_id=teacher.id,
                    teacher_name=teacher.name,
                )

    availability = []
    for room in rooms:
        occupied = occupied_by_room.get(room.id)
        availability.append(
            RoomAvailabilityResponse(
                id=room.id,
                branch_id=room.branch_id,
                name=room.name,
                active=room.active,
                available=occupied is None,
                occupied_by=occupied,
            )
        )

    return availability


class TeacherPermissionsUpdate(BaseModel):
    """
    Body para actualizar permisos individuales de un teacher.

    - Enviar null en custom_permissions resetea al default del rol.
    - Solo se aceptan claves conocidas para el rol del teacher.
    - Las claves protegidas (ALWAYS_ALLOWED_KEYS) se ignoran silenciosamente.

    Ejemplo:
    {
        "custom_permissions": {
            "students.create": true,
            "classes.delete": false
        }
    }
    """
    custom_permissions: dict[str, bool] | None


@router.patch(
    "/teachers/{teacher_id}/permissions",
    summary="Configurar permisos individuales de un teacher",
)
async def update_teacher_permissions(
    teacher_id: int,
    data: TeacherPermissionsUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_role("org_admin")),
) -> dict:
    """
    Actualiza los custom_permissions de un teacher específico.

    Reglas:
    - No puedes modificar tus propios permisos.
    - No se pueden configurar permisos de un org_admin.
    - Claves desconocidas para el rol devuelven error 400.
    - Claves protegidas (ALWAYS_ALLOWED_KEYS) se ignoran silenciosamente.
    - Enviar null resetea al default del rol (elimina todos los overrides).
    """
    if teacher_id == current_teacher.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes modificar tus propios permisos.",
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

    if target.role in UNRESTRICTED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se pueden configurar permisos de un teacher con rol '{target.role}'.",
        )

    if data.custom_permissions is None:
        # Reset: vuelve a usar los defaults del rol sin overrides
        target.custom_permissions = None
    else:
        known_keys = set(PERMISSION_DEFAULTS.get(target.role, {}).keys())
        clean: dict[str, bool] = {}

        for key, value in data.custom_permissions.items():
            if key not in known_keys:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Clave de permiso desconocida: '{key}' para rol '{target.role}'.",
                )
            if key in ALWAYS_ALLOWED_KEYS:
                continue  # Silenciosamente ignorada — nunca se puede restringir
            clean[key] = bool(value)

        target.custom_permissions = clean if clean else None

    await db.commit()
    await db.refresh(target)

    resolved = resolve_permissions(target.role, target.organization_id, target.custom_permissions)
    return {
        "teacher_id": target.id,
        "name": target.name,
        "role": target.role,
        "custom_permissions": target.custom_permissions,
        "resolved": resolved,
    }
