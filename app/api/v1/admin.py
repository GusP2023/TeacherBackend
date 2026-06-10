"""
Admin endpoints — Gestión de la organización y sus teachers.

Solo accesibles por teachers con permisos administrativos reales de la organización.

Endpoints:
    POST  /admin/invite                          → Crear invitación para un nuevo teacher
    GET   /admin/invitations                     → Listar invitaciones de la organización
    GET   /admin/teachers                        → Listar teachers de la organización
    PATCH /admin/teachers/{id}                   → Cambiar rol o desactivar un teacher
    GET   /admin/teachers/{id}/permissions       → Ver permisos efectivos de un teacher
    PATCH /admin/teachers/{id}/permissions       → Configurar permisos individuales de un teacher
    GET   /admin/permissions/schema              → Ver qué permisos son configurables (con labels)
"""

from datetime import date, date as datetime_date, time as time_module, datetime as datetime_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, update
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field, ConfigDict

from app.core.database import get_db
from app.core.security import require_permission
from app.core.permissions import (
    PERMISSION_DEFAULTS,
    resolve_permissions,
)
from app.models.attendance import Attendance, AttendanceStatus
from app.models.branch import Branch
from app.models.class_model import Class, ClassFormat, ClassType, ClassStatus
from app.models.event import Event, EVENT_TYPES
from app.models.room import Room
from app.models.schedule import DayOfWeek, Schedule
from app.models.student import Student
from app.models.teacher import Teacher, VALID_ROLES
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.schemas.invitation import InvitationCreate, InvitationResponse
from app.schemas.student import StudentResponse
from app.schemas.teacher import TeacherResponse
from app.schemas.teacher import TeacherUpdate
from app.api.v1.websocket import notify_data_change
import logging

from app.crud import invitation as invitation_crud
from app.crud import teacher as teacher_crud
from app.models.instrument import Instrument

logger = logging.getLogger(__name__)

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
    current_teacher: Teacher = Depends(require_permission("org.invite_teacher")),
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
    current_teacher: Teacher = Depends(require_permission("org.invite_teacher")),
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
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
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


class AdminStudentResponse(StudentResponse):
    enrollments_count: int
    total_credits: int


@router.get(
    "/students",
    response_model=list[AdminStudentResponse],
    summary="Listar alumnos de la organización",
)
async def list_org_students(
    search: str | None = Query(None, description="Buscar por nombre"),
    teacher_id: int | None = Query(None, description="Filtrar por teacher_id"),
    active: bool | None = Query(None, description="Filtrar por estado activo"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("students.view_enrollment")),
):
    """Lista todos los alumnos de la organización."""
    if not current_teacher.organization_id:
        return []

    query = select(Student).join(Teacher).where(
        Teacher.organization_id == current_teacher.organization_id
    )

    if search:
        query = query.where(Student.name.ilike(f"%{search}%"))

    if teacher_id is not None:
        query = query.where(Student.teacher_id == teacher_id)

    if active is not None:
        query = query.where(Student.active == active)

    query = query.order_by(Student.name)
    result = await db.execute(query)
    students = result.scalars().all()

    if not students:
        return []

    student_ids = [student.id for student in students]
    enrollments_result = await db.execute(
        select(
            Enrollment.student_id,
            func.count(Enrollment.id),
            func.sum(Enrollment.credits),
        )
        .where(
            Enrollment.student_id.in_(student_ids),
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
        .group_by(Enrollment.student_id)
    )

    enrollment_stats = {
        row[0]: {
            "count": row[1],
            "sum": row[2] or 0,
        }
        for row in enrollments_result.all()
    }

    return [
        AdminStudentResponse(
            id=student.id,
            teacher_id=student.teacher_id,
            name=student.name,
            phone=student.phone,
            email=student.email,
            birthdate=student.birthdate,
            notes=student.notes,
            sync_id=student.sync_id,
            active=enrollment_stats.get(student.id, {"count": 0})["count"] > 0,
            created_at=student.created_at,
            updated_at=student.updated_at,
            enrollments_count=enrollment_stats.get(student.id, {"count": 0})["count"],
            total_credits=enrollment_stats.get(student.id, {"sum": 0})["sum"],
        )
        for student in students
    ]


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
    current_teacher: Teacher = Depends(require_permission("org.change_teacher_role")),
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


# Admin: actualizar perfil de otro teacher (campos personales)
@router.patch(
    "/teachers/{teacher_id}/profile",
    response_model=TeacherResponse,
    summary="Actualizar datos personales de un teacher (admin)",
)
async def admin_update_teacher_profile(
    teacher_id: int,
    data: TeacherUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Permite a un admin con permiso `org.manage_users` actualizar campos personales
    de otro teacher (name, email, phone, birthdate, bio, tarifas, etc.).
    No permite modificar la propia cuenta por este endpoint.
    """
    try:
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

        # Reutilizar CRUD update para aplicar cambios parciales (incluye hashing de password si viene)
        updated = await teacher_crud.update(db=db, teacher_id=teacher_id, teacher_data=data)
        if not updated:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error al actualizar teacher")

        permissions = resolve_permissions(
            role=updated.role,
            organization_id=updated.organization_id,
            custom_permissions=updated.custom_permissions,
        )
        response = TeacherResponse.model_validate(updated)
        response.permissions = permissions
        return response
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("Error updating teacher profile (admin) %s by %s: %s", teacher_id, getattr(current_teacher, 'id', None), e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


class InstrumentsUpdate(BaseModel):
    instrument_ids: list[int]


@router.put(
    "/teachers/{teacher_id}/instruments",
    response_model=TeacherResponse,
    summary="Reemplazar instrumentos de un teacher (admin)",
)
async def admin_update_teacher_instruments(
    teacher_id: int,
    data: InstrumentsUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Reemplaza la lista completa de instrumentos asignados a otro teacher.
    """
    try:
        result = await db.execute(
            select(Teacher).where(
                Teacher.id == teacher_id,
                Teacher.organization_id == current_teacher.organization_id,
            )
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher no encontrado en tu organización.")

        instr_res = await db.execute(select(Instrument).where(Instrument.id.in_(data.instrument_ids)))
        instruments = instr_res.scalars().all()
        if len(instruments) != len(data.instrument_ids):
            found_ids = {i.id for i in instruments}
            missing = [i for i in data.instrument_ids if i not in found_ids]
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Instrumentos no encontrados: {missing}")

        target.instruments = list(instruments)
        await db.commit()
        await db.refresh(target)

        permissions = resolve_permissions(
            role=target.role,
            organization_id=target.organization_id,
            custom_permissions=target.custom_permissions,
        )
        response = TeacherResponse.model_validate(target)
        response.permissions = permissions
        return response
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("Error updating teacher instruments (admin) %s by %s: %s", teacher_id, getattr(current_teacher, 'id', None), e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ── DASHBOARD ──

class DashboardKpis(BaseModel):
    active_students: int
    active_teachers: int
    classes_today: int
    classes_today_unmarked: int
    monthly_income: float
    monthly_income_pct_marked: int


class DashboardAlert(BaseModel):
    type: str
    severity: str
    count: int
    label: str


class DashboardTeacher(BaseModel):
    id: int
    name: str
    active_students: int
    instruments: list[str]
    unmarked_today: int
    has_alerts: bool


class DashboardResponse(BaseModel):
    kpis: DashboardKpis
    alerts: list[DashboardAlert]
    teachers: list[DashboardTeacher]


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Datos del dashboard administrativo",
)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("finances.view_all")),
):
    if not current_teacher.organization_id:
        return DashboardResponse(
            kpis=DashboardKpis(
                active_students=0,
                active_teachers=0,
                classes_today=0,
                classes_today_unmarked=0,
                monthly_income=0.0,
                monthly_income_pct_marked=0,
            ),
            alerts=[],
            teachers=[],
        )

    org_id = current_teacher.organization_id
    today = date.today()
    month_start = today.replace(day=1)

    active_students_result = await db.execute(
        select(func.count(func.distinct(Enrollment.student_id)))
        .join(Teacher, Enrollment.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Enrollment.status == EnrollmentStatus.ACTIVE,
        )
    )
    active_students = active_students_result.scalar_one() or 0

    active_teachers_result = await db.execute(
        select(func.count())
        .select_from(Teacher)
        .where(
            Teacher.organization_id == org_id,
            Teacher.active == True,
        )
    )
    active_teachers = active_teachers_result.scalar_one() or 0

    classes_today_result = await db.execute(
        select(func.count())
        .select_from(Class)
        .join(Teacher, Class.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Class.date == today,
            Class.status != ClassStatus.CANCELLED,
        )
    )
    classes_today = classes_today_result.scalar_one() or 0

    classes_today_unmarked_result = await db.execute(
        select(func.count())
        .select_from(Class)
        .join(Teacher, Class.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Class.date == today,
            Class.status == ClassStatus.SCHEDULED,
        )
    )
    classes_today_unmarked = classes_today_unmarked_result.scalar_one() or 0

    income_rows = await db.execute(
        select(
            Class.format,
            Teacher.tariff_individual,
            Teacher.tariff_group,
        )
        .select_from(Class)
        .join(Teacher, Class.teacher_id == Teacher.id)
        .join(Attendance, Attendance.class_id == Class.id)
        .where(
            Teacher.organization_id == org_id,
            Class.date >= month_start,
            Class.date <= today,
            Class.status == ClassStatus.COMPLETED,
            Attendance.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.ABSENT]),
        )
    )

    monthly_income = 0.0
    for class_format, tariff_individual, tariff_group in income_rows.all():
        if class_format == ClassFormat.INDIVIDUAL:
            monthly_income += float(tariff_individual or 0)
        else:
            monthly_income += float(tariff_group or 0)

    total_month_classes_result = await db.execute(
        select(func.count())
        .select_from(Class)
        .join(Teacher, Class.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Class.date >= month_start,
            Class.date <= today,
            Class.status != ClassStatus.CANCELLED,
        )
    )
    total_month_classes = total_month_classes_result.scalar_one() or 0

    marked_month_classes_result = await db.execute(
        select(func.count())
        .select_from(Class)
        .join(Teacher, Class.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Class.date >= month_start,
            Class.date <= today,
            Class.status == ClassStatus.COMPLETED,
        )
    )
    marked_month_classes = marked_month_classes_result.scalar_one() or 0

    monthly_income_pct_marked = (
        int(marked_month_classes / total_month_classes * 100)
        if total_month_classes > 0
        else 0
    )

    overdue_classes_result = await db.execute(
        select(func.count())
        .select_from(Class)
        .join(Teacher, Class.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Class.date < today,
            Class.status == ClassStatus.SCHEDULED,
        )
    )
    overdue_classes = overdue_classes_result.scalar_one() or 0

    pending_credits_result = await db.execute(
        select(func.count())
        .select_from(Enrollment)
        .join(Teacher, Enrollment.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Enrollment.credits > 0,
        )
    )
    pending_credits = pending_credits_result.scalar_one() or 0

    overdue_suspensions_result = await db.execute(
        select(func.count())
        .select_from(Enrollment)
        .join(Teacher, Enrollment.teacher_id == Teacher.id)
        .where(
            Teacher.organization_id == org_id,
            Enrollment.status == EnrollmentStatus.SUSPENDED,
            Enrollment.suspended_until < today,
        )
    )
    overdue_suspensions = overdue_suspensions_result.scalar_one() or 0

    alerts: list[DashboardAlert] = []
    if overdue_classes > 0:
        alerts.append(DashboardAlert(
            type="overdue_classes",
            severity="error",
            count=overdue_classes,
            label=f"{overdue_classes} clase{'s' if overdue_classes != 1 else ''} sin marcar de días anteriores",
        ))
    if classes_today_unmarked > 0:
        alerts.append(DashboardAlert(
            type="unmarked_today",
            severity="warning",
            count=classes_today_unmarked,
            label=f"{classes_today_unmarked} clase{'s' if classes_today_unmarked != 1 else ''} sin marcar hoy",
        ))
    if pending_credits > 0:
        alerts.append(DashboardAlert(
            type="pending_credits",
            severity="warning",
            count=pending_credits,
            label=f"{pending_credits} alumno{'s' if pending_credits != 1 else ''} con créditos de recuperación sin usar",
        ))
    if overdue_suspensions > 0:
        alerts.append(DashboardAlert(
            type="overdue_suspensions",
            severity="warning",
            count=overdue_suspensions,
            label=f"{overdue_suspensions} suspensión{'es' if overdue_suspensions != 1 else ''} vencida{'s' if overdue_suspensions != 1 else ''} sin reactivar",
        ))

    teachers_result = await db.execute(
        select(Teacher)
        .options(selectinload(Teacher.instruments))
        .where(
            Teacher.organization_id == org_id,
            Teacher.active == True,
        )
        .order_by(Teacher.name)
    )
    teachers = teachers_result.scalars().all()

    teacher_ids = [teacher.id for teacher in teachers]
    active_students_by_teacher = {}
    unmarked_today_by_teacher = {}

    if teacher_ids:
        active_students_rows = await db.execute(
            select(
                Enrollment.teacher_id,
                func.count(func.distinct(Enrollment.student_id)),
            )
            .where(
                Enrollment.teacher_id.in_(teacher_ids),
                Enrollment.status == EnrollmentStatus.ACTIVE,
            )
            .group_by(Enrollment.teacher_id)
        )
        active_students_by_teacher = {
            row[0]: row[1] or 0
            for row in active_students_rows.all()
        }

        unmarked_today_rows = await db.execute(
            select(
                Class.teacher_id,
                func.count(),
            )
            .where(
                Class.teacher_id.in_(teacher_ids),
                Class.date == today,
                Class.status == ClassStatus.SCHEDULED,
            )
            .group_by(Class.teacher_id)
        )
        unmarked_today_by_teacher = {
            row[0]: row[1] or 0
            for row in unmarked_today_rows.all()
        }

    teacher_summaries = [
        DashboardTeacher(
            id=teacher.id,
            name=teacher.name,
            active_students=active_students_by_teacher.get(teacher.id, 0),
            instruments=[instrument.name for instrument in teacher.instruments],
            unmarked_today=unmarked_today_by_teacher.get(teacher.id, 0),
            has_alerts=(unmarked_today_by_teacher.get(teacher.id, 0) > 0),
        )
        for teacher in teachers
    ]

    return DashboardResponse(
        kpis=DashboardKpis(
            active_students=active_students,
            active_teachers=active_teachers,
            classes_today=classes_today,
            classes_today_unmarked=classes_today_unmarked,
            monthly_income=monthly_income,
            monthly_income_pct_marked=monthly_income_pct_marked,
        ),
        alerts=alerts,
        teachers=teacher_summaries,
    )


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
    current_teacher: Teacher = Depends(require_permission("org.configure_permissions")),
) -> dict[str, list[PermissionKeyLabel]]:
    """
    Retorna la lista de permisos configurables para cada rol, con sus
    valores default y etiquetas para mostrar en la UI de la App Admin.

    No incluye 'org_admin' ya que sus permisos nunca se configuran.
    Los permisos marcados como `protected: true` no pueden ser desactivados.
    """
    # Todos los roles son configurables — el admin decide
    result = {}
    for role, defaults in PERMISSION_DEFAULTS.items():
        keys = []
        for key, default_value in defaults.items():
            label, description = _PERMISSION_LABELS.get(key, (key, ""))
            keys.append(PermissionKeyLabel(
                key=key,
                default=default_value,
                protected=False,
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
    current_teacher: Teacher = Depends(require_permission("org.configure_permissions")),
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
    created_at: datetime_type
    updated_at: datetime_type

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
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
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
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
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
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
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
    instrument_ids: list[int] = Field(default_factory=list)


class RoomResponse(BaseModel):
    id: int
    branch_id: int
    organization_id: int
    name: str
    description: str | None = None
    capacity: int
    active: bool
    instrument_ids: list[int] = Field(default_factory=list)
    created_at: datetime_type
    updated_at: datetime_type

    model_config = ConfigDict(from_attributes=True)


class RoomUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=255)
    capacity: int | None = Field(None, ge=1)
    active: bool | None = None
    instrument_ids: list[int] | None = None


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
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
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
    if data.instrument_ids:
        unique_instrument_ids = list(dict.fromkeys(data.instrument_ids))
        instr_res = await db.execute(select(Instrument).where(Instrument.id.in_(unique_instrument_ids)))
        instruments = instr_res.scalars().all()
        if len(instruments) != len(unique_instrument_ids):
            found_ids = {i.id for i in instruments}
            missing = [i for i in unique_instrument_ids if i not in found_ids]
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Instrumentos no encontrados: {missing}")
        room.instruments = instruments

    await db.commit()
    await db.refresh(room)
    return _build_room_response(room)


def _build_room_response(room: Room) -> dict:
    return {
        "id": room.id,
        "branch_id": room.branch_id,
        "organization_id": room.organization_id,
        "name": room.name,
        "description": room.description,
        "capacity": room.capacity,
        "active": room.active,
        "instrument_ids": [instrument.id for instrument in getattr(room, "instruments", [])],
        "created_at": room.created_at,
        "updated_at": room.updated_at,
    }


async def _load_instruments_by_ids(db: AsyncSession, instrument_ids: list[int]) -> list[Instrument]:
    if not instrument_ids:
        return []
    unique_instrument_ids = list(dict.fromkeys(instrument_ids))
    result = await db.execute(select(Instrument).where(Instrument.id.in_(unique_instrument_ids)))
    instruments = result.scalars().all()
    if len(instruments) != len(unique_instrument_ids):
        found_ids = {i.id for i in instruments}
        missing = [i for i in unique_instrument_ids if i not in found_ids]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Instrumentos no encontrados: {missing}")
    return instruments


@router.get(
    "/branches/{branch_id}/rooms",
    response_model=list[RoomResponse],
    summary="Listar salas de una sucursal",
)
async def list_branch_rooms(
    branch_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        return []

    result = await db.execute(
        select(Room).options(selectinload(Room.instruments)).where(
            Room.branch_id == branch_id,
            Room.organization_id == current_teacher.organization_id,
            Room.active.is_(True),
        ).order_by(Room.name)
    )
    rooms = result.scalars().all()
    return [_build_room_response(room) for room in rooms]


@router.get(
    "/rooms",
    response_model=list[RoomResponse],
    summary="Listar todas las salas de la organización",
)
async def list_org_rooms(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        return []

    result = await db.execute(
        select(Room).options(selectinload(Room.instruments)).where(
            Room.organization_id == current_teacher.organization_id,
            Room.active.is_(True),
        ).order_by(Room.name)
    )
    rooms = result.scalars().all()
    return [_build_room_response(room) for room in rooms]


@router.patch(
    "/rooms/{room_id}",
    response_model=RoomResponse,
    summary="Editar sala",
)
async def update_room(
    room_id: int,
    data: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Room).options(selectinload(Room.instruments)).where(
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

    if data.instrument_ids is not None:
        room.instruments = await _load_instruments_by_ids(db, data.instrument_ids)

    if data.active is not None and data.active is False:
        today = datetime_date.today()
        active_schedules_count = await db.scalar(
            select(func.count()).select_from(Schedule).where(
                Schedule.room_id == room.id,
                Schedule.active.is_(True),
            )
        )
        future_classes_count = await db.scalar(
            select(func.count()).select_from(Class).where(
                Class.room_id == room.id,
                Class.date >= today,
                Class.status == ClassStatus.SCHEDULED,
            )
        )

        if active_schedules_count or future_classes_count:
            await db.execute(
                update(Schedule)
                .where(Schedule.room_id == room.id, Schedule.active.is_(True))
                .values(room_id=None)
            )
            await db.execute(
                update(Class)
                .where(
                    Class.room_id == room.id,
                    Class.date >= today,
                    Class.status == ClassStatus.SCHEDULED,
                )
                .values(room_id=None)
            )
        room.active = False
    elif data.active is not None:
        room.active = data.active

    await db.commit()
    await db.refresh(room)
    return _build_room_response(room)


@router.delete(
    "/rooms/{room_id}",
    response_model=dict,
    summary="Eliminar sala",
)
async def delete_room(
    room_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
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

    active_schedules_count = await db.scalar(
        select(func.count()).select_from(Schedule).where(
            Schedule.room_id == room.id,
            Schedule.active.is_(True),
        )
    )
    if active_schedules_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Esta sala tiene {active_schedules_count} horario(s) asignado(s). Reasigná los horarios antes de eliminar la sala.",
        )

    today = datetime_date.today()
    future_classes_count = await db.scalar(
        select(func.count()).select_from(Class).where(
            Class.room_id == room.id,
            Class.date >= today,
            Class.status == ClassStatus.SCHEDULED,
        )
    )
    if future_classes_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Esta sala tiene {future_classes_count} clase(s) futura(s) asignada(s).",
        )

    await db.delete(room)
    await db.commit()
    return {"deleted": True, "room_id": room_id}


@router.delete(
    "/branches/{branch_id}",
    response_model=dict,
    summary="Eliminar sucursal",
)
async def delete_branch(
    branch_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    branch_result = await db.execute(
        select(Branch).options(selectinload(Branch.rooms)).where(
            Branch.id == branch_id,
            Branch.organization_id == current_teacher.organization_id,
        )
    )
    branch = branch_result.scalar_one_or_none()
    if not branch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sucursal no encontrada en tu organización.",
        )

    today = datetime_date.today()
    for room in branch.rooms or []:
        active_schedules_count = await db.scalar(
            select(func.count()).select_from(Schedule).where(
                Schedule.room_id == room.id,
                Schedule.active.is_(True),
            )
        )
        future_classes_count = await db.scalar(
            select(func.count()).select_from(Class).where(
                Class.room_id == room.id,
                Class.date >= today,
                Class.status == ClassStatus.SCHEDULED,
            )
        )
        if active_schedules_count or future_classes_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La sucursal tiene salas con horarios asignados. Reasigná los horarios antes de eliminar la sucursal.",
            )

    await db.delete(branch)
    await db.commit()
    return {"deleted": True, "branch_id": branch_id}


class AdminScheduleRoomItem(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str
    day: str
    time: time_module
    duration: int
    room_id: int | None = None
    room_name: str | None = None
    student_name: str | None = None
    instrument_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ScheduleRoomAssign(BaseModel):
    room_id: int | None


@router.get(
    "/schedules",
    response_model=list[AdminScheduleRoomItem],
    summary="Listar horarios activos de la organización",
)
async def list_org_schedules(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        return []

    query = select(Schedule).options(
        selectinload(Schedule.teacher),
        selectinload(Schedule.enrollment).selectinload(Enrollment.student),
        selectinload(Schedule.enrollment).selectinload(Enrollment.instrument),
        selectinload(Schedule.room),
    ).join(Teacher).where(
        Teacher.organization_id == current_teacher.organization_id,
        Schedule.active.is_(True),
    ).order_by(Teacher.name, Schedule.day, Schedule.time)

    result = await db.execute(query)
    schedules = result.scalars().all()

    return [
        AdminScheduleRoomItem(
            id=schedule.id,
            teacher_id=schedule.teacher_id,
            teacher_name=schedule.teacher.name if schedule.teacher else "",
            day=schedule.day.value if schedule.day else "",
            time=schedule.time,
            duration=schedule.duration,
            room_id=schedule.room_id,
            room_name=schedule.room.name if schedule.room else None,
            student_name=(schedule.enrollment.student.name if schedule.enrollment and schedule.enrollment.student else None),
            instrument_name=(schedule.enrollment.instrument.name if schedule.enrollment and schedule.enrollment.instrument else None),
        )
        for schedule in schedules
    ]


@router.patch(
    "/schedules/{schedule_id}/room",
    response_model=AdminScheduleRoomItem,
    summary="Asignar o desasignar una sala a un horario recurrente",
)
async def update_schedule_room(
    schedule_id: int,
    data: ScheduleRoomAssign,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    query = select(Schedule).options(
        selectinload(Schedule.teacher),
        selectinload(Schedule.enrollment).selectinload(Enrollment.student),
        selectinload(Schedule.enrollment).selectinload(Enrollment.instrument),
        selectinload(Schedule.room),
    ).join(Teacher).where(
        Schedule.id == schedule_id,
        Teacher.organization_id == current_teacher.organization_id,
    )

    result = await db.execute(query)
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Horario no encontrado en tu organización.",
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

        existing_start = func.extract("hour", Schedule.time) * 60 + func.extract("minute", Schedule.time)
        existing_end = existing_start + Schedule.duration
        new_start = schedule.time.hour * 60 + schedule.time.minute
        new_end = new_start + schedule.duration

        conflict_query = (
            select(Schedule)
            .options(
                selectinload(Schedule.teacher),
                selectinload(Schedule.enrollment).selectinload(Enrollment.student),
            )
            .join(Teacher)
            .where(
                Schedule.id != schedule_id,
                Schedule.active.is_(True),
                Schedule.room_id == data.room_id,
                Schedule.day == schedule.day,
                Teacher.organization_id == current_teacher.organization_id,
                existing_start < new_end,
                existing_end > new_start,
            )
        )
        conflict_result = await db.execute(conflict_query)
        conflicting_schedule = conflict_result.scalar_one_or_none()

        if conflicting_schedule:
            def fmt_time(value: time_module) -> str:
                return f"{value.hour:02d}:{value.minute:02d}"

            conflict_start = fmt_time(conflicting_schedule.time)
            conflict_end_total = conflicting_schedule.time.hour * 60 + conflicting_schedule.time.minute + conflicting_schedule.duration
            conflict_end_hour = conflict_end_total // 60
            conflict_end_minute = conflict_end_total % 60
            conflict_end = f"{conflict_end_hour:02d}:{conflict_end_minute:02d}"
            student_name = (
                conflicting_schedule.enrollment.student.name
                if conflicting_schedule.enrollment and conflicting_schedule.enrollment.student
                else None
            )
            teacher_name = conflicting_schedule.teacher.name if conflicting_schedule.teacher else None
            detail = (
                f"La {room.name} ya está ocupada el {schedule.day.value} de {conflict_start} a {conflict_end}"
            )
            if student_name and teacher_name:
                detail += f" ({student_name} con {teacher_name})."
            else:
                detail += "."
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    schedule.room_id = data.room_id
    await db.commit()
    await db.refresh(schedule)

    return AdminScheduleRoomItem(
        id=schedule.id,
        teacher_id=schedule.teacher_id,
        teacher_name=schedule.teacher.name if schedule.teacher else "",
        day=schedule.day.value if schedule.day else "",
        time=schedule.time,
        duration=schedule.duration,
        room_id=schedule.room_id,
        room_name=schedule.room.name if schedule.room else None,
        student_name=(schedule.enrollment.student.name if schedule.enrollment and schedule.enrollment.student else None),
        instrument_name=(schedule.enrollment.instrument.name if schedule.enrollment and schedule.enrollment.instrument else None),
    )


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
    current_teacher: Teacher = Depends(require_permission("org.configure_permissions")),
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

    if data.custom_permissions is None:
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
            clean[key] = bool(value)
        # Asignar con flag_modified para forzar que SQLAlchemy detecte el cambio en JSONB
        from sqlalchemy.orm.attributes import flag_modified
        target.custom_permissions = clean if clean else None
        flag_modified(target, "custom_permissions")

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


# ────────────────────────────────────────────────────
# EVENTOS
# ────────────────────────────────────────────────────


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None)
    event_type: str = Field(default="other")
    date: datetime_date
    time_start: time_module
    duration: int = Field(..., gt=0)
    room_id: int | None = None
    guest_name: str | None = Field(None, max_length=200)
    guest_email: str | None = Field(None, max_length=255)
    notes: str | None = None
    teacher_ids: list[int] = Field(default_factory=list)
    student_ids: list[int] = Field(default_factory=list)


class EventUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    event_type: str | None = None
    date: datetime_date | None = None
    time_start: time_module | None = None
    duration: int | None = Field(None, gt=0)
    room_id: int | None = None
    guest_name: str | None = None
    guest_email: str | None = None
    notes: str | None = None
    teacher_ids: list[int] | None = None
    student_ids: list[int] | None = None


class TeacherBrief(BaseModel):
    id: int
    name: str
    email: str
    model_config = ConfigDict(from_attributes=True)


class StudentBrief(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class RoomBrief(BaseModel):
    id: int
    name: str
    branch_id: int
    model_config = ConfigDict(from_attributes=True)


class EventResponse(BaseModel):
    id: int
    organization_id: int
    room_id: int | None
    room: RoomBrief | None
    title: str
    description: str | None
    event_type: str
    date: datetime_date
    time_start: time_module
    duration: int
    guest_name: str | None
    guest_email: str | None
    notes: str | None
    created_by_id: int | None
    created_by: TeacherBrief | None
    teachers: list[TeacherBrief]
    students: list[StudentBrief]
    calendar_emails: list[str]
    created_at: str
    updated_at: str
    model_config = ConfigDict(from_attributes=True)


def build_event_response(event: Event) -> dict:
    emails: set[str] = set()
    for teacher in event.teachers or []:
        if teacher.email:
            emails.add(teacher.email)
    for student in event.students or []:
        if student.email:
            emails.add(student.email)
    if event.guest_email:
        emails.add(event.guest_email)

    return {
        "id": event.id,
        "organization_id": event.organization_id,
        "room_id": event.room_id,
        "room": event.room,
        "title": event.title,
        "description": event.description,
        "event_type": event.event_type,
        "date": event.date,
        "time_start": event.time_start,
        "duration": event.duration,
        "guest_name": event.guest_name,
        "guest_email": event.guest_email,
        "notes": event.notes,
        "created_by_id": event.created_by_id,
        "created_by": event.created_by,
        "teachers": event.teachers,
        "students": event.students,
        "calendar_emails": sorted(emails),
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


def _validate_email_format(email: str) -> None:
    if "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email inválido. Debe contener '@'.",
        )


async def _load_teachers_for_organization(db: AsyncSession, teacher_ids: list[int], org_id: int) -> list[Teacher]:
    if not teacher_ids:
        return []

    unique_teacher_ids = list(dict.fromkeys(teacher_ids))
    result = await db.execute(
        select(Teacher).where(
            Teacher.id.in_(unique_teacher_ids),
            Teacher.organization_id == org_id,
        )
    )
    teachers = result.scalars().all()
    missing = [teacher_id for teacher_id in unique_teacher_ids if teacher_id not in {t.id for t in teachers}]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teacher no encontrado en tu organización: {missing[0]}.",
        )
    return teachers


async def _load_students_for_organization(db: AsyncSession, student_ids: list[int], org_id: int) -> list[Student]:
    if not student_ids:
        return []

    unique_student_ids = list(dict.fromkeys(student_ids))
    result = await db.execute(
        select(Student).join(Teacher).where(
            Student.id.in_(unique_student_ids),
            Teacher.organization_id == org_id,
        )
    )
    students = result.scalars().all()
    missing = [student_id for student_id in unique_student_ids if student_id not in {s.id for s in students}]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student no encontrado en tu organización: {missing[0]}.",
        )
    return students


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear evento",
)
async def create_event(
    data: EventCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    if data.event_type not in EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de evento inválido. Opciones válidas: {', '.join(EVENT_TYPES)}.",
        )

    if data.duration <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La duración debe ser mayor a 0.",
        )

    if data.guest_email is not None:
        _validate_email_format(data.guest_email)

    room = None
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
        if not room.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sala inactiva. No se puede asignar a un evento.",
            )

    validated_teachers = await _load_teachers_for_organization(
        db, data.teacher_ids, current_teacher.organization_id
    )
    validated_students = await _load_students_for_organization(
        db, data.student_ids, current_teacher.organization_id
    )

    event = Event(
        organization_id=current_teacher.organization_id,
        room_id=data.room_id,
        title=data.title,
        description=data.description,
        event_type=data.event_type,
        date=data.date,
        time_start=data.time_start,
        duration=data.duration,
        guest_name=data.guest_name,
        guest_email=data.guest_email,
        notes=data.notes,
        created_by_id=current_teacher.id,
    )
    event.teachers = validated_teachers
    event.students = validated_students
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return build_event_response(event)


@router.get(
    "/events",
    response_model=list[EventResponse],
    summary="Listar eventos de la organización",
)
async def list_events(
    date_from: datetime_date | None = None,
    date_to: datetime_date | None = None,
    event_type: str | None = None,
    room_id: int | None = None,
    teacher_id: int | None = None,
    upcoming_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        return []

    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El filtro date_from no puede ser mayor que date_to.",
        )

    if event_type is not None and event_type not in EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de evento inválido. Opciones válidas: {', '.join(EVENT_TYPES)}.",
        )

    query = select(Event).where(Event.organization_id == current_teacher.organization_id)

    if date_from is not None:
        query = query.where(Event.date >= date_from)
    if date_to is not None:
        query = query.where(Event.date <= date_to)
    if event_type is not None:
        query = query.where(Event.event_type == event_type)
    if room_id is not None:
        query = query.where(Event.room_id == room_id)
    if upcoming_only:
        query = query.where(Event.date >= datetime_date.today())
    if teacher_id is not None:
        query = query.join(Event.teachers).where(Teacher.id == teacher_id).distinct()

    query = query.order_by(Event.date, Event.time_start)
    result = await db.execute(query)
    events = result.scalars().unique().all()
    return [build_event_response(event) for event in events]


@router.get(
    "/events/{event_id}",
    response_model=EventResponse,
    summary="Obtener un evento",
)
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Event).where(
            Event.id == event_id,
            Event.organization_id == current_teacher.organization_id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado en tu organización.",
        )
    return build_event_response(event)


@router.patch(
    "/events/{event_id}",
    response_model=EventResponse,
    summary="Actualizar un evento",
)
async def update_event(
    event_id: int,
    data: EventUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Event).where(
            Event.id == event_id,
            Event.organization_id == current_teacher.organization_id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado en tu organización.",
        )

    data_dict = data.model_dump(exclude_unset=True)

    if "event_type" in data_dict and data.event_type is not None:
        if data.event_type not in EVENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tipo de evento inválido. Opciones válidas: {', '.join(EVENT_TYPES)}.",
            )

    if "duration" in data_dict and data.duration is not None and data.duration <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La duración debe ser mayor a 0.",
        )

    if "guest_email" in data_dict and data.guest_email is not None:
        _validate_email_format(data.guest_email)

    if "room_id" in data_dict:
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
            if not room.active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Sala inactiva. No se puede asignar a un evento.",
                )
            event.room_id = data.room_id
        else:
            event.room_id = None

    if "title" in data_dict:
        event.title = data.title
    if "description" in data_dict:
        event.description = data.description
    if "event_type" in data_dict:
        event.event_type = data.event_type
    if "date" in data_dict:
        event.date = data.date
    if "time_start" in data_dict:
        event.time_start = data.time_start
    if "duration" in data_dict:
        event.duration = data.duration
    if "guest_name" in data_dict:
        event.guest_name = data.guest_name
    if "guest_email" in data_dict:
        event.guest_email = data.guest_email
    if "notes" in data_dict:
        event.notes = data.notes

    if "teacher_ids" in data_dict:
        event.teachers = await _load_teachers_for_organization(
            db, data.teacher_ids or [], current_teacher.organization_id
        )

    if "student_ids" in data_dict:
        event.students = await _load_students_for_organization(
            db, data.student_ids or [], current_teacher.organization_id
        )

    await db.commit()
    await db.refresh(event)
    return build_event_response(event)


@router.delete(
    "/events/{event_id}",
    summary="Eliminar un evento",
)
async def delete_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Event).where(
            Event.id == event_id,
            Event.organization_id == current_teacher.organization_id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado en tu organización.",
        )

    await db.delete(event)
    await db.commit()
    return {"deleted": True, "event_id": event_id}


@router.get(
    "/events/{event_id}/calendar-emails",
    summary="Obtener emails del evento para Google Calendar",
)
async def get_event_calendar_emails(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    result = await db.execute(
        select(Event).where(
            Event.id == event_id,
            Event.organization_id == current_teacher.organization_id,
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento no encontrado en tu organización.",
        )

    emails: list[str] = []
    for teacher in event.teachers or []:
        if teacher.email:
            emails.append(teacher.email)
    for student in event.students or []:
        if student.email:
            emails.append(student.email)
    if event.guest_email:
        emails.append(event.guest_email)

    unique_emails = sorted(set(emails))
    return {
        "event_id": event.id,
        "title": event.title,
        "emails": unique_emails,
        "total": len(unique_emails),
    }


# ────────────────────────────────────────────────────
# GESTIÓN ADMIN DE CLASES
# ────────────────────────────────────────────────────

class AdminClassResponse(BaseModel):
    id: int
    teacher_id: int
    room_id: int | None = None
    enrollment_id: int | None = None
    schedule_id: int | None = None
    date: datetime_date
    time: time_module
    duration: int
    status: str
    type: str
    format: str
    notes: str | None = None
    attendance_status: str | None = None
    attendance_notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminClassUpdate(BaseModel):
    """
    Campos editables de una clase desde el panel admin.
    No permite cambiar el tipo de clase.
    """
    date: datetime_date | None = None
    time: time_module | None = None
    duration: int | None = Field(None, gt=0, le=240)
    notes: str | None = None
    status: ClassStatus | None = None
    room_id: int | None = None


class AdminAttendanceUpdate(BaseModel):
    """
    Body para crear o actualizar la asistencia de una clase desde admin.
    Maneja automáticamente la lógica de créditos por licencia.
    """
    status: AttendanceStatus
    notes: str | None = None


def _build_admin_class_response(class_obj: Class) -> dict:
    return {
        "id": class_obj.id,
        "teacher_id": class_obj.teacher_id,
        "room_id": class_obj.room_id,
        "enrollment_id": class_obj.enrollment_id,
        "schedule_id": class_obj.schedule_id,
        "date": class_obj.date,
        "time": class_obj.time,
        "duration": class_obj.duration,
        "status": class_obj.status,
        "type": class_obj.type,
        "format": class_obj.format,
        "notes": class_obj.notes,
        "attendance_status": class_obj.attendance.status if class_obj.attendance else None,
        "attendance_notes": class_obj.attendance.notes if class_obj.attendance else None,
    }


async def _get_class_for_org(db: AsyncSession, class_id: int, org_id: int) -> Class:
    """
    Obtiene una clase verificando que pertenezca a la organización.
    Lanza 404 si no existe o no corresponde a la org.
    """
    result = await db.execute(
        select(Class).join(Teacher, Teacher.id == Class.teacher_id).where(
            Class.id == class_id,
            Teacher.organization_id == org_id,
        )
    )
    class_obj = result.scalar_one_or_none()
    if not class_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clase no encontrada en tu organización.",
        )
    return class_obj


@router.delete(
    "/classes/{class_id}",
    summary="Eliminar una clase (admin)",
)
async def admin_delete_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("classes.delete")),
):
    """
    Elimina una clase del calendario.

    Lógica de créditos:
    - Si la clase es de tipo 'recovery', devuelve +1 crédito al enrollment,
      independientemente de si tiene asistencia marcada o no.
    - Si es 'regular' o 'extra', se elimina sin ajuste de créditos.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    class_obj = await _get_class_for_org(db, class_id, current_teacher.organization_id)

    # Bloquear eliminación si la clase tiene asistencia registrada
    if class_obj.attendance:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta clase tiene asistencia registrada. Eliminá primero la asistencia antes de borrar la clase.",
        )

    # Devolver crédito si es recuperación
    if class_obj.type == ClassType.RECOVERY and class_obj.enrollment_id:
        enrollment_result = await db.execute(
            select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
        )
        enrollment = enrollment_result.scalar_one_or_none()
        if enrollment:
            enrollment.credits += 1

    teacher_id = class_obj.teacher_id
    await db.delete(class_obj)
    await db.commit()
    await notify_data_change(teacher_id, "class", "delete", class_id)
    return {"deleted": True, "class_id": class_id}


@router.patch(
    "/classes/{class_id}",
    response_model=AdminClassResponse,
    summary="Editar datos de una clase (admin)",
)
async def admin_update_class(
    class_id: int,
    data: AdminClassUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("students.edit_schedule")),
):
    """
    Edita los datos de una clase existente: fecha, hora, duración, notas y/o estado.
    No permite cambiar el tipo de clase.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    class_obj = await _get_class_for_org(db, class_id, current_teacher.organization_id)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(class_obj, field, value)

    await db.commit()
    await db.refresh(class_obj)
    await notify_data_change(class_obj.teacher_id, "class", "update", class_obj.id)
    return _build_admin_class_response(class_obj)


@router.patch(
    "/classes/{class_id}/attendance",
    response_model=AdminClassResponse,
    summary="Crear o actualizar asistencia de una clase (admin)",
)
async def admin_update_class_attendance(
    class_id: int,
    data: AdminAttendanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("classes.mark_attendance")),
):
    """
    Crea o actualiza el registro de asistencia de una clase desde el panel admin.

    Lógica de créditos:
    - Marcar como 'license' o 'excused' → +1 crédito al enrollment.
    - Cambiar de 'license'/'excused' a 'present'/'absent' → -1 crédito (se revoca).
    - Siempre marca la clase como 'completed' al registrar asistencia.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    class_obj = await _get_class_for_org(db, class_id, current_teacher.organization_id)

    _LICENSE = {AttendanceStatus.LICENSE, AttendanceStatus.EXCUSED}

    # Obtener enrollment para ajuste de créditos
    enrollment = None
    if class_obj.enrollment_id:
        enr_result = await db.execute(
            select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
        )
        enrollment = enr_result.scalar_one_or_none()

    if class_obj.attendance:
        # Actualizar asistencia existente con ajuste de crédito delta
        prev_is_license = class_obj.attendance.status in _LICENSE
        new_is_license = data.status in _LICENSE

        if enrollment:
            if prev_is_license and not new_is_license:
                # Revocar licencia → quitar crédito
                enrollment.credits = max(0, enrollment.credits - 1)
            elif not prev_is_license and new_is_license:
                # Nueva licencia → dar crédito
                enrollment.credits += 1

        class_obj.attendance.status = data.status
        class_obj.attendance.notes = data.notes
    else:
        # Crear registro de asistencia nuevo
        if enrollment and data.status in _LICENSE:
            enrollment.credits += 1

        db.add(Attendance(
            class_id=class_obj.id,
            status=data.status,
            notes=data.notes,
        ))

    class_obj.status = ClassStatus.COMPLETED

    await db.commit()
    await db.refresh(class_obj)

    if class_obj.attendance:
        await notify_data_change(class_obj.teacher_id, "attendance", "update", class_obj.attendance.id)

    return _build_admin_class_response(class_obj)


@router.delete(
    "/classes/{class_id}/attendance",
    summary="Eliminar asistencia de una clase (admin)",
)
async def admin_delete_class_attendance(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("classes.mark_attendance")),
):
    """
    Elimina el registro de asistencia de una clase y la regresa a estado 'scheduled'.

    Lógica de créditos:
    - Si la asistencia eliminada era 'license' o 'excused', se revoca el crédito
      otorgado originalmente (-1 al enrollment).
    - Para cualquier otro status no se ajustan créditos.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    class_obj = await _get_class_for_org(db, class_id, current_teacher.organization_id)

    if not class_obj.attendance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Esta clase no tiene asistencia registrada.",
        )

    _LICENSE = {AttendanceStatus.LICENSE, AttendanceStatus.EXCUSED}

    # Revertir crédito si corresponde
    if class_obj.attendance.status in _LICENSE and class_obj.enrollment_id:
        enr_result = await db.execute(
            select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
        )
        enrollment = enr_result.scalar_one_or_none()
        if enrollment:
            enrollment.credits = max(0, enrollment.credits - 1)

    # Eliminar asistencia y regresar clase a scheduled
    await db.delete(class_obj.attendance)
    class_obj.status = ClassStatus.SCHEDULED

    await db.commit()
    await notify_data_change(class_obj.teacher_id, "attendance", "delete", class_id)
    return {"deleted": True, "class_id": class_id}
