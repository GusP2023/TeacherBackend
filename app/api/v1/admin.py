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

from datetime import date, date as datetime_date, time as time_module, datetime as datetime_type, timedelta, time as time_type
from decimal import Decimal
from typing import Optional, Literal

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, Query, status
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select, or_, func, update, and_, case, delete
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import selectinload, joinedload
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, ConfigDict, model_validator

# pyrefly: ignore [missing-import]
from app.core.database import get_db
# pyrefly: ignore [missing-import]
from app.core.security import require_permission
from app.core.permissions import (
    PERMISSION_DEFAULTS,
    resolve_permissions,
)
from app.models.attendance import Attendance, AttendanceStatus
from app.models.branch import Branch
from app.models.branch_hours import BranchHours
from app.models.class_model import Class, ClassFormat, ClassType, ClassStatus
from app.models.event import Event, EVENT_TYPES, event_teachers, event_students
from app.models.room import Room
from app.models.schedule import DayOfWeek, Schedule
from app.models.student import Student
from app.models.teacher import Teacher, VALID_ROLES
from app.models.teacher_availability import TeacherAvailability
from app.models.enrollment import Enrollment, EnrollmentStatus, EnrollmentLevel
from app.models.billing_period import BillingPeriod, BillingPeriodStatus
from app.models.payment import Payment, PaymentConcept, PaymentMethod
from app.services import credit_service
from app.models.credit_transaction import CreditTransaction, CreditTransactionSource, CreditTransactionReferenceType
from app.models.personnel_payment import PersonnelPayment, PersonnelPaymentStatus
from app.models.fee_discount import FeeDiscount, DiscountType
from app.models.expense import Expense, ExpenseCategory
from app.models.organization import Organization
from app.schemas.invitation import InvitationCreate, InvitationResponse
from app.schemas.student import StudentResponse
from app.schemas.teacher import TeacherResponse
from app.schemas.teacher import TeacherUpdate
from app.schemas.billing import (
    BillingPeriodResponse, BillingPeriodUpdate, BillingPeriodCreate,
    GenerateBillingPeriodsResponse, StudentBillingSummary,
    StudentBrief as BillingStudentBrief,
    EnrollmentBrief,
    PaymentCreate, PaymentResponse,
)
from app.schemas.personnel_payment import (
    PersonnelPaymentPreviewRequest, PersonnelPaymentPreviewResponse,
    PersonnelPaymentCreate, PersonnelPaymentUpdate,
    PersonnelPaymentPayRequest, PersonnelPaymentResponse,
    PendingAlertTeacher,
)
from app.api.v1.websocket import notify_data_change
import logging

from app.crud import invitation as invitation_crud
from app.crud import teacher as teacher_crud
from app.models.instrument import Instrument
from app.jobs.financial_jobs import generate_billing_periods
from app.services.financial_generator import calculate_teacher_payment

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
        Teacher.organization_id == current_teacher.organization_id,
        Teacher.is_instructor == True,
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
            sync_id=str(student.sync_id) if student.sync_id is not None else None,
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


async def _recalculate_billing_status(db: AsyncSession, billing_period_id: int) -> None:
    """Recalcula el status de un BillingPeriod según la suma de pagos recibidos."""
    bp_result = await db.execute(
        select(BillingPeriod).where(BillingPeriod.id == billing_period_id)
    )
    bp = bp_result.scalar_one_or_none()
    if not bp or bp.status == BillingPeriodStatus.WAIVED:
        return

    sum_result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.billing_period_id == billing_period_id
        )
    )
    amount_paid = Decimal(str(sum_result.scalar_one()))

    if amount_paid <= 0:
        bp.status = BillingPeriodStatus.PENDING
    elif amount_paid < bp.final_amount:
        bp.status = BillingPeriodStatus.PARTIAL
    else:
        bp.status = BillingPeriodStatus.PAID


def _build_bp_response(bp: BillingPeriod, amount_paid: Decimal,
                        teacher_name: str = "—") -> BillingPeriodResponse:
    """Construye BillingPeriodResponse a partir de un BillingPeriod cargado."""
    enrollment = bp.enrollment
    student    = enrollment.student if enrollment else None
    instrument = enrollment.instrument if enrollment else None
    return BillingPeriodResponse(
        id=bp.id,
        enrollment_id=bp.enrollment_id,
        student=BillingStudentBrief(
            id=student.id if student else 0,
            name=student.name if student else "—",
        ),
        enrollment=EnrollmentBrief(
            id=enrollment.id if enrollment else 0,
            instrument_name=instrument.name if instrument else "—",
            format=enrollment.format.value if enrollment else "—",
            teacher_name=teacher_name,
        ),
        charge_type=bp.charge_type,
        description=bp.description,
        quantity=bp.quantity,
        period_year=bp.period_year,
        period_month=bp.period_month,
        base_amount=bp.base_amount,
        discount_applied=bp.discount_applied,
        final_amount=bp.final_amount,
        amount_paid=amount_paid,
        status=bp.status.value if hasattr(bp.status, 'value') else bp.status,
        due_date=bp.due_date,
        notes=bp.notes,
        created_at=bp.created_at,
        updated_at=bp.updated_at,
    )


# ════════════════════════════════════════════════════════════════════
# REVERT PERSONNEL PAYMENT
# ════════════════════════════════════════════════════════════════════

@router.post(
    "/personnel-payments/{payment_id}/revert",
    response_model=PersonnelPaymentResponse,
    summary="Revertir un pago pagado a pendiente",
)
async def revert_personnel_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Revierte un PersonnelPayment de status=paid a status=pending.
    Limpia los datos de factura. Usar cuando se registró un pago por error.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(PersonnelPayment)
        .join(Teacher, Teacher.id == PersonnelPayment.teacher_id)
        .where(
            PersonnelPayment.id == payment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    if payment.status != PersonnelPaymentStatus.PAID:
        raise HTTPException(status_code=409, detail="Solo se pueden revertir liquidaciones pagadas.")

    payment.status         = PersonnelPaymentStatus.PENDING
    payment.invoice_number = None
    payment.invoice_date   = None
    payment.invoice_notes  = None

    await db.commit()
    await db.refresh(payment)
    return payment


# ════════════════════════════════════════════════════════════════════
# BILLING PERIODS
# ════════════════════════════════════════════════════════════════════

@router.get(
    "/billing-summary",
    response_model=list[StudentBillingSummary],
    summary="Resumen de cobros agrupado por alumno",
)
async def get_billing_summary(
    teacher_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Devuelve un resumen por alumno activo: saldo total pendiente,
    si tiene cobros vencidos, y cantidad de cobros pendientes.
    Ordenado: vencidos → pendientes → al día, luego alfabético.
    """
    if not current_teacher.organization_id:
        return []

    # 1. Enrollments activos de la org
    enr_query = (
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            Teacher.organization_id == current_teacher.organization_id,
            Enrollment.status == "active",
        )
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.teacher),
        )
    )
    if teacher_id is not None:
        enr_query = enr_query.where(Enrollment.teacher_id == teacher_id)

    enr_result = await db.execute(enr_query)
    enrollments = enr_result.scalars().all()
    if not enrollments:
        return []

    enr_ids = [e.id for e in enrollments]

    # 2. Mapa estudiante → info
    student_map: dict[int, dict] = {}
    for e in enrollments:
        sid = e.student_id
        if sid not in student_map:
            student_map[sid] = {
                "name": e.student.name if e.student else "—",
                "teacher_name": e.teacher.name if e.teacher else "—",
                "enrollment_ids": [],
            }
        student_map[sid]["enrollment_ids"].append(e.id)

    # 3. BillingPeriods pendientes / parciales
    bp_result = await db.execute(
        select(BillingPeriod)
        .where(
            BillingPeriod.enrollment_id.in_(enr_ids),
            BillingPeriod.status.in_(["pending", "partial"]),
        )
    )
    pending_bps = bp_result.scalars().all()

    # 4. Mapa de pagos
    paid_map: dict[int, Decimal] = {}
    bp_ids = [bp.id for bp in pending_bps]
    if bp_ids:
        paid_rows = await db.execute(
            select(Payment.billing_period_id, func.sum(Payment.amount))
            .where(Payment.billing_period_id.in_(bp_ids))
            .group_by(Payment.billing_period_id)
        )
        paid_map = {row[0]: Decimal(str(row[1])) for row in paid_rows.all()}

    # 5. Agrupar BPs por student_id
    enr_to_student = {e.id: e.student_id for e in enrollments}
    today = date.today()
    student_bps: dict[int, list[dict]] = {sid: [] for sid in student_map}
    for bp in pending_bps:
        sid = enr_to_student.get(bp.enrollment_id)
        if sid:
            amount_paid = paid_map.get(bp.id, Decimal("0"))
            student_bps[sid].append({
                "saldo": bp.final_amount - amount_paid,
                "due_date": bp.due_date,
            })

    # 6. Construir resumen
    summaries = []
    for sid, info in student_map.items():
        bps = student_bps.get(sid, [])
        total_pending = Decimal(str(sum(b["saldo"] for b in bps)))
        has_overdue = any(
            b["due_date"] and b["due_date"] < today for b in bps
        )
        if has_overdue:
            billing_status = "overdue"
        elif total_pending > 0:
            billing_status = "pending"
        else:
            billing_status = "current"

        summaries.append(StudentBillingSummary(
            student_id=sid,
            student_name=info["name"],
            teacher_name=info["teacher_name"],
            enrollment_count=len(info["enrollment_ids"]),
            total_pending=total_pending,
            pending_count=len(bps),
            has_overdue=has_overdue,
            billing_status=billing_status,
        ))

    order = {"overdue": 0, "pending": 1, "current": 2}
    summaries.sort(key=lambda s: (order[s.billing_status], s.student_name.lower()))
    return summaries


@router.post(
    "/billing-periods/generate",
    response_model=GenerateBillingPeriodsResponse,
    summary="Generar cobros mensuales para todos los enrollments activos",
)
async def generate_billing_periods_endpoint(
    year:  int | None = Query(None, description="Año del período. Default: año actual"),
    month: int | None = Query(None, description="Mes del período (1-12). Default: mes actual"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Genera un BillingPeriod por cada Enrollment activo de la organización
    para el mes indicado. Idempotente: no duplica si ya existe.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    today = date.today()
    target_year  = year  if year  is not None else today.year
    target_month = month if month is not None else today.month

    if not (1 <= target_month <= 12):
        raise HTTPException(status_code=400, detail="Mes inválido (1-12).")

    stats = await generate_billing_periods(
        db=db,
        target_date=date(target_year, target_month, 1),
        organization_id=current_teacher.organization_id,
    )
    return stats


@router.get(
    "/billing-periods",
    response_model=list[BillingPeriodResponse],
    summary="Listar períodos de cobro de la organización",
)
async def list_billing_periods(
    year:         int | None = Query(None),
    month:        int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    student_id:   int | None = Query(None),
    teacher_id:   int | None = Query(None),
    charge_type:  str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        return []

    query = (
        select(BillingPeriod)
        .join(Enrollment, Enrollment.id == BillingPeriod.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(Teacher.organization_id == current_teacher.organization_id)
        .order_by(BillingPeriod.period_year.desc(), BillingPeriod.period_month.desc())
        .options(
            selectinload(BillingPeriod.enrollment).selectinload(Enrollment.teacher)
        )
    )

    if year is not None:
        query = query.where(BillingPeriod.period_year == year)
    if month is not None:
        query = query.where(BillingPeriod.period_month == month)
    if status_filter is not None:
        query = query.where(BillingPeriod.status == status_filter)
    if student_id is not None:
        query = query.where(Enrollment.student_id == student_id)
    if teacher_id is not None:
        query = query.where(Enrollment.teacher_id == teacher_id)
    if charge_type is not None:
        query = query.where(BillingPeriod.charge_type == charge_type)

    result = await db.execute(query)
    billing_periods = result.scalars().all()

    bp_ids = [bp.id for bp in billing_periods]
    paid_map: dict[int, Decimal] = {}
    if bp_ids:
        paid_result = await db.execute(
            select(Payment.billing_period_id, func.sum(Payment.amount))
            .where(Payment.billing_period_id.in_(bp_ids))
            .group_by(Payment.billing_period_id)
        )
        paid_map = {row[0]: Decimal(str(row[1])) for row in paid_result.all()}

    responses = []
    for bp in billing_periods:
        enrollment = bp.enrollment
        student    = enrollment.student if enrollment else None
        instrument = enrollment.instrument if enrollment else None
        teacher_name = (
            enrollment.teacher.name
            if enrollment and enrollment.teacher
            else "—"
        )
        responses.append(_build_bp_response(
            bp,
            paid_map.get(bp.id, Decimal("0.00")),
            teacher_name,
        ))
    return responses


@router.post(
    "/billing-periods",
    response_model=BillingPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un cobro manual (matrícula, extra, clase suelta, cuota adelantada)",
)
async def create_billing_period(
    data: BillingPeriodCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    # Verificar ownership del enrollment
    enr_result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            Enrollment.id == data.enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
        .options(selectinload(Enrollment.student), selectinload(Enrollment.teacher))
    )
    enrollment = enr_result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado.")

    # Validaciones por charge_type
    if data.charge_type == "cuota":
        if not data.period_year or not data.period_month:
            raise HTTPException(
                status_code=400,
                detail="Para cuotas es obligatorio especificar period_year y period_month."
            )
        
        existing_cuota = await db.execute(
            select(BillingPeriod).where(
                BillingPeriod.enrollment_id == data.enrollment_id,
                BillingPeriod.period_year == data.period_year,
                BillingPeriod.period_month == data.period_month,
            )
        )
        if existing_cuota.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un cobro para el período {data.period_month}/{data.period_year} en esta inscripción."
            )

    if data.charge_type == "matricula":
        # Solo una matrícula por enrollment
        existing = await db.execute(
            select(BillingPeriod).where(
                BillingPeriod.enrollment_id == data.enrollment_id,
                BillingPeriod.charge_type == "matricula",
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="Ya existe un cobro de matrícula para esta inscripción."
            )

    if data.charge_type == "clase_suelta" and not data.quantity:
        raise HTTPException(
            status_code=400,
            detail="Para clases sueltas es obligatorio especificar la cantidad de créditos."
        )

    # Calcular final_amount
    final_amount = data.base_amount - data.discount_applied
    if final_amount < 0:
        raise HTTPException(status_code=400, detail="El descuento no puede superar el monto base.")

    bp = BillingPeriod(
        enrollment_id=data.enrollment_id,
        charge_type=data.charge_type,
        description=data.description,
        quantity=data.quantity,
        period_year=data.period_year,
        period_month=data.period_month,
        base_amount=data.base_amount,
        discount_applied=data.discount_applied,
        final_amount=final_amount,
        status=BillingPeriodStatus.PENDING,
        due_date=data.due_date or date.today(),
        notes=data.notes,
    )
    db.add(bp)
    await db.commit()
    await db.refresh(bp)

    teacher_name = enrollment.teacher.name if enrollment.teacher else "—"
    return _build_bp_response(bp, Decimal("0.00"), teacher_name)


@router.patch(
    "/billing-periods/{billing_period_id}",
    response_model=BillingPeriodResponse,
    summary="Editar o condonar un período de cobro",
)
async def update_billing_period(
    billing_period_id: int,
    data: BillingPeriodUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Edita due_date o notas de un BillingPeriod.
    No permite modificar montos (son snapshot histórico).
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(BillingPeriod)
        .join(Enrollment, Enrollment.id == BillingPeriod.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            BillingPeriod.id == billing_period_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    bp = result.scalar_one_or_none()
    if not bp:
        raise HTTPException(status_code=404, detail="Período de cobro no encontrado.")

    if data.due_date is not None:
        bp.due_date = data.due_date
    if data.notes is not None:
        bp.notes = data.notes
    if data.description is not None:
        bp.description = data.description
    if data.quantity is not None:
        bp.quantity = data.quantity
    if data.base_amount is not None:
        bp.base_amount = data.base_amount
    if data.discount_applied is not None:
        bp.discount_applied = data.discount_applied
    if data.base_amount is not None or data.discount_applied is not None:
        bp.final_amount = bp.base_amount - bp.discount_applied
        if bp.final_amount < 0:
            raise HTTPException(
                status_code=400,
                detail="El descuento no puede superar el monto base."
            )

    await db.commit()
    await db.refresh(bp)

    paid_result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.billing_period_id == bp.id)
    )
    amount_paid = Decimal(str(paid_result.scalar_one()))

    teacher_name = (
        bp.enrollment.teacher.name
        if bp.enrollment and bp.enrollment.teacher
        else "—"
    )
    return _build_bp_response(bp, amount_paid, teacher_name)


@router.post(
    "/billing-periods/{billing_period_id}/waive",
    response_model=BillingPeriodResponse,
    summary="Condonar un período de cobro",
)
async def waive_billing_period(
    billing_period_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Marca un BillingPeriod como waived (condonado).
    Solo aplica si está en pending o partial.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(BillingPeriod)
        .join(Enrollment, Enrollment.id == BillingPeriod.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            BillingPeriod.id == billing_period_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    bp = result.scalar_one_or_none()
    if not bp:
        raise HTTPException(status_code=404, detail="Período de cobro no encontrado.")
    if bp.status == BillingPeriodStatus.PAID:
        raise HTTPException(status_code=409, detail="No se puede condonar un período ya pagado.")
    if bp.status == BillingPeriodStatus.WAIVED:
        raise HTTPException(status_code=409, detail="Este período ya fue condonado.")

    bp.status = BillingPeriodStatus.WAIVED
    await db.commit()
    await db.refresh(bp)

    enrollment = bp.enrollment
    student    = enrollment.student if enrollment else None
    instrument = enrollment.instrument if enrollment else None

    paid_result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.billing_period_id == bp.id)
    )
    amount_paid = Decimal(str(paid_result.scalar_one()))

    teacher_name = (
        bp.enrollment.teacher.name
        if bp.enrollment and bp.enrollment.teacher
        else "—"
    )
    return _build_bp_response(bp, amount_paid, teacher_name)


@router.delete(
    "/billing-periods/{billing_period_id}",
    summary="Eliminar un período de cobro",
)
async def delete_billing_period(
    billing_period_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Elimina un BillingPeriod y todos sus pagos asociados (cascade).
    No hay restricción por status — se puede eliminar en cualquier estado.
    Usar cuando la cuota fue generada por error.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(BillingPeriod)
        .options(selectinload(BillingPeriod.payments))
        .join(Enrollment, Enrollment.id == BillingPeriod.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            BillingPeriod.id == billing_period_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    bp = result.scalar_one_or_none()
    if not bp:
        raise HTTPException(status_code=404, detail="Período de cobro no encontrado.")

    payments_deleted = len(bp.payments)

    await db.delete(bp)
    await db.commit()

    return {
        "deleted": True,
        "billing_period_id": billing_period_id,
        "payments_deleted": payments_deleted
    }


# ════════════════════════════════════════════════════════════════════
# PAYMENTS
# ════════════════════════════════════════════════════════════════════

@router.post(
    "/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un pago de alumno",
)
async def create_payment(
    data: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Registra un pago recibido de una familia.
    Conceptos: cuota (vinculado a BillingPeriod), matricula, extra (montos libres).
    Si concept=cuota y billing_period_id es None → error.
    Si hay billing_period_id → recalcula el status del BillingPeriod automáticamente.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    enr_result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            Enrollment.id == data.enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = enr_result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    if data.concept == "cuota" and data.billing_period_id is None:
        raise HTTPException(
            status_code=400,
            detail="Para pagos de cuota es obligatorio especificar billing_period_id."
        )
    if data.concept == "clase_suelta" and data.billing_period_id is None:
        raise HTTPException(
            status_code=400,
            detail="Para clases sueltas es obligatorio especificar billing_period_id."
        )

    bp = None
    if data.billing_period_id is not None:
        bp_result = await db.execute(
            select(BillingPeriod).where(
                BillingPeriod.id == data.billing_period_id,
                BillingPeriod.enrollment_id == data.enrollment_id,
            )
        )
        bp = bp_result.scalar_one_or_none()
        if not bp:
            raise HTTPException(status_code=404, detail="Período de cobro no encontrado.")
        if bp.status == BillingPeriodStatus.WAIVED:
            raise HTTPException(status_code=409, detail="Este período fue condonado, no acepta pagos.")

    payment = Payment(
        enrollment_id=data.enrollment_id,
        billing_period_id=data.billing_period_id,
        amount=data.amount,
        concept=PaymentConcept(data.concept),
        payment_date=data.payment_date,
        payment_method=PaymentMethod(data.payment_method),
        notes=data.notes,
        reference=data.reference,
    )
    db.add(payment)
    await db.flush()

    if data.billing_period_id is not None:
        await _recalculate_billing_status(db, data.billing_period_id)

    await db.commit()
    await db.refresh(payment)

    student    = enrollment.student
    instrument = enrollment.instrument

    return PaymentResponse(
        id=payment.id,
        enrollment_id=payment.enrollment_id,
        billing_period_id=payment.billing_period_id,
        amount=payment.amount,
        concept=payment.concept.value if hasattr(payment.concept, 'value') else payment.concept,
        payment_date=payment.payment_date,
        payment_method=payment.payment_method.value if hasattr(payment.payment_method, 'value') else payment.payment_method,
        notes=payment.notes,
        reference=payment.reference,
        student_name=student.name if student else "—",
        instrument_name=instrument.name if instrument else "—",
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


@router.get(
    "/payments",
    response_model=list[PaymentResponse],
    summary="Listar pagos de alumnos",
)
async def list_payments(
    enrollment_id:     int | None = Query(None),
    billing_period_id: int | None = Query(None),
    concept:           str | None = Query(None),
    from_date:         date | None = Query(None),
    to_date:           date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        return []

    query = (
        select(Payment)
        .join(Enrollment, Enrollment.id == Payment.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(Teacher.organization_id == current_teacher.organization_id)
        .order_by(Payment.payment_date.desc())
    )

    if enrollment_id is not None:
        query = query.where(Payment.enrollment_id == enrollment_id)
    if billing_period_id is not None:
        query = query.where(Payment.billing_period_id == billing_period_id)
    if concept is not None:
        query = query.where(Payment.concept == concept)
    if from_date is not None:
        query = query.where(Payment.payment_date >= from_date)
    if to_date is not None:
        query = query.where(Payment.payment_date <= to_date)

    result = await db.execute(query)
    payments = result.scalars().all()

    responses = []
    for p in payments:
        enrollment = p.enrollment
        student    = enrollment.student if enrollment else None
        instrument = enrollment.instrument if enrollment else None
        responses.append(PaymentResponse(
            id=p.id,
            enrollment_id=p.enrollment_id,
            billing_period_id=p.billing_period_id,
            amount=p.amount,
            concept=p.concept.value if hasattr(p.concept, 'value') else p.concept,
            payment_date=p.payment_date,
            payment_method=p.payment_method.value if hasattr(p.payment_method, 'value') else p.payment_method,
            notes=p.notes,
            student_name=student.name if student else "—",
            instrument_name=instrument.name if instrument else "—",
            created_at=p.created_at,
            updated_at=p.updated_at,
        ))
    return responses


@router.delete(
    "/payments/{payment_id}",
    summary="Eliminar un pago de alumno",
)
async def delete_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Elimina un pago registrado por error.
    Si el pago estaba vinculado a un BillingPeriod, recalcula su status automáticamente.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Payment)
        .join(Enrollment, Enrollment.id == Payment.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            Payment.id == payment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")

    billing_period_id = payment.billing_period_id

    await db.delete(payment)
    await db.flush()

    if billing_period_id is not None:
        await _recalculate_billing_status(db, billing_period_id)

    await db.commit()
    return {"deleted": True, "payment_id": payment_id}


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
            Teacher.is_instructor == True,
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
            Teacher.is_instructor == True,
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


DAY_OF_WEEK_ORDER = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

class BranchHourItem(BaseModel):
    day_of_week: Literal['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    morning_open: time_type | None = None
    morning_close: time_type | None = None
    afternoon_open: time_type | None = None
    afternoon_close: time_type | None = None
    is_closed: bool = False

class BranchHourResponse(BranchHourItem):
    id: int
    branch_id: int
    model_config = ConfigDict(from_attributes=True)

class BranchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    address: str | None = Field(None, max_length=255)
    slot_duration: int = Field(45, ge=15, le=120)


class BranchResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    address: str | None = None
    active: bool
    slot_duration: int
    hours: list[BranchHourResponse] = []
    created_at: datetime_type
    updated_at: datetime_type

    model_config = ConfigDict(from_attributes=True)


class BranchUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    address: str | None = Field(None, max_length=255)
    active: bool | None = None
    slot_duration: int | None = Field(None, ge=15, le=120)


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
        slot_duration=data.slot_duration,
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
    ).options(selectinload(Branch.hours))
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
    if data.slot_duration is not None:
        branch.slot_duration = data.slot_duration

    await db.commit()
    await db.refresh(branch)
    return branch


@router.get(
    "/branches/{branch_id}/hours",
    response_model=list[BranchHourResponse],
    summary="Obtener horarios de apertura de una sucursal",
)
async def get_branch_hours(
    branch_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == current_teacher.organization_id,
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Sucursal no encontrada.")

    result = await db.execute(
        select(BranchHours)
        .where(BranchHours.branch_id == branch_id)
        .order_by(
            case(
                *((BranchHours.day_of_week == d, i) for i, d in enumerate(DAY_OF_WEEK_ORDER)),
                else_=99,
            )
        )
    )
    return result.scalars().all()


@router.put(
    "/branches/{branch_id}/hours",
    response_model=list[BranchHourResponse],
    summary="Reemplazar horarios de apertura de una sucursal (upsert completo)",
)
async def upsert_branch_hours(
    branch_id: int,
    data: list[BranchHourItem],
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == current_teacher.organization_id,
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Sucursal no encontrada.")

    # Eliminar registros existentes y reemplazar
    await db.execute(
        delete(BranchHours).where(BranchHours.branch_id == branch_id)
    )

    new_hours = [
        BranchHours(branch_id=branch_id, **item.model_dump())
        for item in data
    ]
    db.add_all(new_hours)
    await db.commit()

    result = await db.execute(
        select(BranchHours)
        .where(BranchHours.branch_id == branch_id)
        .order_by(
            case(
                *((BranchHours.day_of_week == d, i) for i, d in enumerate(DAY_OF_WEEK_ORDER)),
                else_=99,
            )
        )
    )
    return result.scalars().all()


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
        room.instruments = list(instruments)

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
    return list(instruments)


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
        Teacher.is_instructor == True,
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

    room_changed = schedule.room_id != data.room_id
    schedule.room_id = data.room_id

    if room_changed:
        await db.execute(
            update(Class)
            .where(
                Class.schedule_id == schedule.id,
                Class.date >= datetime_date.today(),
                Class.status == ClassStatus.SCHEDULED,
            )
            .values(room_id=data.room_id)
        )

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
            clean[key] = value
        # Asignar con flag_modified para forzar que SQLAlchemy detecte el cambio en JSONB
        # pyrefly: ignore [missing-import]
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
    return list(teachers)


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
    return list(students)


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

    if "title" in data_dict and data.title is not None:
        event.title = data.title
    if "description" in data_dict:
        event.description = data.description
    if "event_type" in data_dict and data.event_type is not None:
        event.event_type = data.event_type
    if "date" in data_dict and data.date is not None:
        event.date = data.date
    if "time_start" in data_dict and data.time_start is not None:
        event.time_start = data.time_start
    if "duration" in data_dict and data.duration is not None:
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
            await credit_service.apply(
                db=db, enrollment=enrollment, amount=1,
                source_type=CreditTransactionSource.RECOVERY_CLASS_DELETED,
                reference_id=class_obj.id,
                reference_type=CreditTransactionReferenceType.CLASS,
            )
            await db.flush()

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

    _LICENSE = {AttendanceStatus.LICENSE}

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
                # Buscar la transacción LICENSE original para liberar el consumed_credit_tx_id
                from app.models.credit_transaction import CreditTransaction
                license_tx_result = await db.execute(
                    select(CreditTransaction).where(
                        CreditTransaction.enrollment_id == class_obj.enrollment_id,
                        CreditTransaction.source_type == CreditTransactionSource.LICENSE,
                        CreditTransaction.reference_id == class_obj.attendance.id
                    )
                )
                license_tx = license_tx_result.scalar_one_or_none()

                # Liberar el consumed_credit_tx_id si existe (algun RECOVERY_CLASS consumió esta licencia)
                if license_tx:
                    # Buscar RECOVERY_CLASS que consumió esta licencia y liberarla
                    recovery_tx_result = await db.execute(
                        select(CreditTransaction).where(
                            CreditTransaction.consumed_credit_tx_id == license_tx.id,
                            CreditTransaction.source_type == CreditTransactionSource.RECOVERY_CLASS
                        )
                    )
                    recovery_tx = recovery_tx_result.scalar_one_or_none()
                    if recovery_tx:
                        recovery_tx.consumed_credit_tx_id = None

                await credit_service.apply(
                    db=db, enrollment=enrollment, amount=-1,
                    source_type=CreditTransactionSource.LICENSE_REVERSAL,
                    reference_id=class_obj.attendance.id,
                    reference_type=CreditTransactionReferenceType.ATTENDANCE,
                )
            elif not prev_is_license and new_is_license:
                await credit_service.apply(
                    db=db, enrollment=enrollment, amount=1,
                    source_type=CreditTransactionSource.LICENSE,
                    reference_id=class_obj.attendance.id,
                    reference_type=CreditTransactionReferenceType.ATTENDANCE,
                )

        class_obj.attendance.status = data.status
        class_obj.attendance.notes = data.notes
    else:
        # Crear registro de asistencia nuevo
        new_attendance = Attendance(
            class_id=class_obj.id,
            status=data.status,
            notes=data.notes,
        )
        db.add(new_attendance)
        await db.flush()

        if enrollment and data.status in _LICENSE:
            await credit_service.apply(
                db=db, enrollment=enrollment, amount=1,
                source_type=CreditTransactionSource.LICENSE,
                reference_id=new_attendance.id,
                reference_type=CreditTransactionReferenceType.ATTENDANCE,
            )

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

    _LICENSE = {AttendanceStatus.LICENSE}

    # Revertir crédito si corresponde
    if class_obj.attendance.status in _LICENSE and class_obj.enrollment_id:
        enr_result = await db.execute(
            select(Enrollment).where(Enrollment.id == class_obj.enrollment_id)
        )
        enrollment = enr_result.scalar_one_or_none()
        if enrollment:
            # Buscar la transacción LICENSE original para liberar el consumed_credit_tx_id
            from app.models.credit_transaction import CreditTransaction
            license_tx_result = await db.execute(
                select(CreditTransaction).where(
                    CreditTransaction.enrollment_id == class_obj.enrollment_id,
                    CreditTransaction.source_type == CreditTransactionSource.LICENSE,
                    CreditTransaction.reference_id == class_obj.attendance.id
                )
            )
            license_tx = license_tx_result.scalar_one_or_none()

            # Liberar el consumed_credit_tx_id si existe (algun RECOVERY_CLASS consumió esta licencia)
            if license_tx:
                # Buscar RECOVERY_CLASS que consumió esta licencia y liberarla
                recovery_tx_result = await db.execute(
                    select(CreditTransaction).where(
                        CreditTransaction.consumed_credit_tx_id == license_tx.id,
                        CreditTransaction.source_type == CreditTransactionSource.RECOVERY_CLASS
                    )
                )
                recovery_tx = recovery_tx_result.scalar_one_or_none()
                if recovery_tx:
                    recovery_tx.consumed_credit_tx_id = None

            await credit_service.apply(
                db=db, enrollment=enrollment, amount=-1,
                source_type=CreditTransactionSource.LICENSE_REVERSAL,
                reference_id=class_obj.attendance.id,
                reference_type=CreditTransactionReferenceType.ATTENDANCE,
            )

    teacher_id = class_obj.teacher_id
    attendance_id = class_obj.attendance.id

    # Eliminar asistencia y regresar clase a scheduled
    await db.delete(class_obj.attendance)
    class_obj.status = ClassStatus.SCHEDULED

    await db.commit()
    await notify_data_change(teacher_id, "attendance", "delete", attendance_id)
    return {"deleted": True, "class_id": class_id}


# ────────────────────────────────────────────────────
# DISPONIBILIDAD DE PROFESORES
# ────────────────────────────────────────────────────

class AvailabilityCreate(BaseModel):
    day: str = Field(..., pattern="^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$")
    time_start: time_module
    time_end: time_module

    @model_validator(mode='after')
    def validate_range(self):
        if self.time_start >= self.time_end:
            raise ValueError("time_start debe ser anterior a time_end")
        return self


class AvailabilityUpdate(BaseModel):
    day: str | None = Field(None, pattern="^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)$")
    time_start: time_module | None = None
    time_end: time_module | None = None
    active: bool | None = None

    @model_validator(mode='after')
    def validate_range(self):
        if self.time_start and self.time_end:
            if self.time_start >= self.time_end:
                raise ValueError("time_start debe ser anterior a time_end")
        return self


class AvailabilityResponse(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str = ""
    day: str
    time_start: time_module
    time_end: time_module
    active: bool
    created_at: datetime_type
    updated_at: datetime_type

    model_config = ConfigDict(from_attributes=True)


# Función auxiliar para verificar que un teacher pertenece a la organización
async def _get_teacher_for_org(db: AsyncSession, teacher_id: int, org_id: int) -> Teacher:
    """Verifica que teacher_id pertenece a la organización org_id."""
    result = await db.execute(
        select(Teacher).where(
            Teacher.id == teacher_id,
            Teacher.organization_id == org_id,
            Teacher.is_instructor == True,
        )
    )
    teacher = result.scalar_one_or_none()
    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profesor no encontrado en tu organización."
        )
    return teacher


# ────────────────────────────────────────────────────
# GET /admin/teachers/{teacher_id}/availability
# ────────────────────────────────────────────────────
@router.get(
    "/teachers/{teacher_id}/availability",
    response_model=list[AvailabilityResponse],
    summary="Listar disponibilidad de un profesor",
)
async def list_teacher_availability(
    teacher_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Lista todos los bloques de disponibilidad de un profesor.
    Incluye bloques activos e inactivos, ordenados por día y hora.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    await _get_teacher_for_org(db, teacher_id, current_teacher.organization_id)

    result = await db.execute(
        select(TeacherAvailability)
        .where(TeacherAvailability.teacher_id == teacher_id)
        .order_by(
            # Ordenar por día de la semana (lunes→domingo)
            case(
                *( (TeacherAvailability.day == day, i) for i, day in enumerate(
                    ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                ) ),
                else_=99
            ),
            TeacherAvailability.time_start
        )
    )
    return result.scalars().all()


# ────────────────────────────────────────────────────
# POST /admin/teachers/{teacher_id}/availability
# ────────────────────────────────────────────────────
@router.post(
    "/teachers/{teacher_id}/availability",
    response_model=AvailabilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear bloque de disponibilidad",
)
async def create_teacher_availability(
    teacher_id: int,
    data: AvailabilityCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Crea un nuevo bloque de disponibilidad para un profesor.
    Verifica que no haya solapamiento con otros bloques activos del mismo día.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    await _get_teacher_for_org(db, teacher_id, current_teacher.organization_id)

    # Verificar solapamiento con disponibilidades activas del mismo día
    overlap_result = await db.execute(
        select(TeacherAvailability).where(
            TeacherAvailability.teacher_id == teacher_id,
            TeacherAvailability.day == data.day,
            TeacherAvailability.active == True,
            TeacherAvailability.time_start < data.time_end,
            TeacherAvailability.time_end > data.time_start
        )
    )
    if overlap_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe un bloque de disponibilidad en ese día que se solapa con el horario indicado."
        )

    availability = TeacherAvailability(
        teacher_id=teacher_id,
        day=data.day,
        time_start=data.time_start,
        time_end=data.time_end,
        active=True
    )

    db.add(availability)
    await db.commit()
    await db.refresh(availability)

    return availability


# ────────────────────────────────────────────────────
# PATCH /admin/teachers/{teacher_id}/availability/{availability_id}
# ────────────────────────────────────────────────────
@router.patch(
    "/teachers/{teacher_id}/availability/{availability_id}",
    response_model=AvailabilityResponse,
    summary="Actualizar bloque de disponibilidad",
)
async def update_teacher_availability(
    teacher_id: int,
    availability_id: int,
    data: AvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Actualiza un bloque de disponibilidad.
    Si se modifican day/time_start/time_end, verifica que no haya solapamiento.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    await _get_teacher_for_org(db, teacher_id, current_teacher.organization_id)

    result = await db.execute(
        select(TeacherAvailability).where(
            TeacherAvailability.id == availability_id,
            TeacherAvailability.teacher_id == teacher_id
        )
    )
    availability = result.scalar_one_or_none()
    if not availability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bloque de disponibilidad no encontrado."
        )

    # Si se modifican day/time_start/time_end, verificar solapamiento
    if data.day or data.time_start or data.time_end:
        new_day = data.day if data.day is not None else availability.day
        new_time_start = data.time_start if data.time_start is not None else availability.time_start
        new_time_end = data.time_end if data.time_end is not None else availability.time_end

        overlap_result = await db.execute(
            select(TeacherAvailability).where(
                TeacherAvailability.teacher_id == teacher_id,
                TeacherAvailability.day == new_day,
                TeacherAvailability.active == True,
                TeacherAvailability.time_start < new_time_end,
                TeacherAvailability.time_end > new_time_start,
                TeacherAvailability.id != availability_id  # Excluir el registro actual
            )
        )
        if overlap_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe un bloque de disponibilidad en ese día que se solapa con el horario indicado."
            )

    # Aplicar cambios
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(availability, field, value)

    await db.commit()
    await db.refresh(availability)

    return availability


# ────────────────────────────────────────────────────
# DELETE /admin/teachers/{teacher_id}/availability/{availability_id}
# ────────────────────────────────────────────────────
@router.delete(
    "/teachers/{teacher_id}/availability/{availability_id}",
    summary="Eliminar bloque de disponibilidad",
)
async def delete_teacher_availability(
    teacher_id: int,
    availability_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Elimina un bloque de disponibilidad.
    """
    if not current_teacher.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tu cuenta no está asociada a ninguna organización.",
        )

    await _get_teacher_for_org(db, teacher_id, current_teacher.organization_id)

    result = await db.execute(
        select(TeacherAvailability).where(
            TeacherAvailability.id == availability_id,
            TeacherAvailability.teacher_id == teacher_id
        )
    )
    availability = result.scalar_one_or_none()
    if not availability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bloque de disponibilidad no encontrado."
        )

    await db.delete(availability)
    await db.commit()

    return {"deleted": True, "availability_id": availability_id}


# ────────────────────────────────────────────────────
# GET /admin/availability (endpoint de lectura para la Agenda)
# ────────────────────────────────────────────────────
@router.get(
    "/availability",
    response_model=list[AvailabilityResponse],
    summary="Listar disponibilidad de profesores (para Agenda)",
)
async def list_availability(
    teacher_id: int | None = Query(None, description="Filtrar por teacher_id"),
    instrument_id: int | None = Query(None, description="Filtrar por instrumento (cátedra)"),
    day: str | None = Query(None, description="Filtrar por día de la semana"),
    active_only: bool = Query(True, description="Solo bloques activos"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Lista disponibilidad de profesores con filtros opcionales.
    Útil para la Agenda para mostrar disponibilidad de profesores.
    """
    if not current_teacher.organization_id:
        return []

    query = select(TeacherAvailability).options(
        selectinload(TeacherAvailability.teacher)
    ).join(Teacher).where(
        Teacher.organization_id == current_teacher.organization_id,
        Teacher.is_instructor == True,
    )

    if teacher_id is not None:
        query = query.where(TeacherAvailability.teacher_id == teacher_id)

    if instrument_id is not None:
        query = (
            query
            .join(
                Enrollment,
                (Enrollment.teacher_id == TeacherAvailability.teacher_id) &
                (Enrollment.instrument_id == instrument_id) &
                (Enrollment.status == EnrollmentStatus.ACTIVE)
            )
            .distinct()
        )

    if day is not None:
        query = query.where(TeacherAvailability.day == day)

    if active_only:
        query = query.where(TeacherAvailability.active == True)

    # Add CASE expression to SELECT for DISTINCT compatibility
    day_order_case = case(
        *( (TeacherAvailability.day == d, i) for i, d in enumerate(
            ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        ) ),
        else_=99
    )
    query = query.add_columns(day_order_case.label('day_order'))

    query = query.order_by(
        TeacherAvailability.teacher_id,
        day_order_case,
        TeacherAvailability.time_start
    )

    result = await db.execute(query)
    return result.scalars().all()


# ════════════════════════════════════════════════════════════
# PERSONNEL PAYMENTS
# ════════════════════════════════════════════════════════════

# ────────────────────────────────────────────────────
# POST /admin/personnel-payments/preview
# ────────────────────────────────────────────────────
@router.post(
    "/personnel-payments/preview",
    response_model=PersonnelPaymentPreviewResponse,
    summary="Calcular pago de personal sin guardar",
)
async def preview_personnel_payment(
    body: PersonnelPaymentPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Calcula clases cobrables y monto para un teacher en el período indicado.
    No escribe nada en la base de datos. Usar antes de crear el pago.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    teacher = await _get_teacher_for_org(db, body.teacher_id, current_teacher.organization_id)

    if body.period_from > body.period_to:
        raise HTTPException(status_code=400, detail="period_from debe ser anterior o igual a period_to.")

    calc = await calculate_teacher_payment(db, teacher, body.period_from, body.period_to)

    return PersonnelPaymentPreviewResponse(
        teacher_id=teacher.id,
        teacher_name=teacher.name,
        **calc,
    )


# ────────────────────────────────────────────────────
# POST /admin/personnel-payments
# ────────────────────────────────────────────────────
@router.post(
    "/personnel-payments",
    response_model=PersonnelPaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear liquidación de pago de personal",
)
async def create_personnel_payment(
    body: PersonnelPaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Crea un PersonnelPayment con status=pending.
    El monto se calcula automáticamente en base al período y las clases marcadas.
    El campo adjustment permite agregar bono (+) o descuento (-) manual.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    teacher = await _get_teacher_for_org(db, body.teacher_id, current_teacher.organization_id)

    if body.period_from > body.period_to:
        raise HTTPException(status_code=400, detail="period_from debe ser anterior o igual a period_to.")

    # Verificar que no exista ya un pago para este período exacto
    existing = await db.execute(
        select(PersonnelPayment).where(
            PersonnelPayment.teacher_id == teacher.id,
            PersonnelPayment.period_from == body.period_from,
            PersonnelPayment.period_to   == body.period_to,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Ya existe un pago para este profesor y período."
        )

    calc = await calculate_teacher_payment(db, teacher, body.period_from, body.period_to)

    total = calc["amount_calculated"] + body.adjustment

    payment = PersonnelPayment(
        teacher_id=teacher.id,
        period_from=body.period_from,
        period_to=body.period_to,
        adjustment=body.adjustment,
        notes=body.notes,
        total_amount=total,
        status=PersonnelPaymentStatus.PENDING,
        **calc,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


# ────────────────────────────────────────────────────
# GET /admin/personnel-payments
# ────────────────────────────────────────────────────
@router.get(
    "/personnel-payments",
    response_model=list[PersonnelPaymentResponse],
    summary="Listar liquidaciones de personal",
)
async def list_personnel_payments(
    teacher_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    from_date: date | None = Query(None, description="Filtrar period_from >= from_date"),
    to_date: date | None = Query(None, description="Filtrar period_to <= to_date"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    if not current_teacher.organization_id:
        return []

    query = (
        select(PersonnelPayment)
        .join(Teacher, Teacher.id == PersonnelPayment.teacher_id)
        .where(Teacher.organization_id == current_teacher.organization_id)
        .order_by(PersonnelPayment.period_from.desc(), Teacher.name)
    )

    if teacher_id is not None:
        query = query.where(PersonnelPayment.teacher_id == teacher_id)
    if status_filter is not None:
        query = query.where(PersonnelPayment.status == status_filter)
    if from_date is not None:
        query = query.where(PersonnelPayment.period_from >= from_date)
    if to_date is not None:
        query = query.where(PersonnelPayment.period_to <= to_date)

    result = await db.execute(query)
    return result.scalars().all()


# ────────────────────────────────────────────────────
# PATCH /admin/personnel-payments/{payment_id}
# ────────────────────────────────────────────────────
@router.patch(
    "/personnel-payments/{payment_id}",
    response_model=PersonnelPaymentResponse,
    summary="Editar liquidación pendiente (y opcionalmente recalcular)",
)
async def update_personnel_payment(
    payment_id: int,
    body: PersonnelPaymentUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Edita adjustment y/o notes de un pago en status=pending.
    Si se envía period_from o period_to, recalcula las clases y amount_calculated.
    Solo funciona mientras el pago esté en status=pending.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(PersonnelPayment)
        .join(Teacher, Teacher.id == PersonnelPayment.teacher_id)
        .where(
            PersonnelPayment.id == payment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    if payment.status != PersonnelPaymentStatus.PENDING:
        raise HTTPException(status_code=409, detail="Solo se pueden editar liquidaciones en estado pending.")

    # Si cambia el período, recalcular
    recalculate = body.period_from is not None or body.period_to is not None
    new_period_from = body.period_from or payment.period_from
    new_period_to   = body.period_to   or payment.period_to

    if new_period_from > new_period_to:
        raise HTTPException(status_code=400, detail="period_from debe ser anterior o igual a period_to.")

    if recalculate:
        teacher = await _get_teacher_for_org(db, payment.teacher_id, current_teacher.organization_id)
        calc = await calculate_teacher_payment(db, teacher, new_period_from, new_period_to)
        for field, value in calc.items():
            setattr(payment, field, value)
        payment.period_from = new_period_from
        payment.period_to   = new_period_to

    if body.adjustment is not None:
        payment.adjustment = body.adjustment
    if body.notes is not None:
        payment.notes = body.notes

    payment.total_amount = payment.amount_calculated + payment.adjustment

    await db.commit()
    await db.refresh(payment)
    return payment


# ────────────────────────────────────────────────────
# POST /admin/personnel-payments/{payment_id}/pay
# ────────────────────────────────────────────────────
@router.post(
    "/personnel-payments/{payment_id}/pay",
    response_model=PersonnelPaymentResponse,
    summary="Marcar liquidación como pagada",
)
async def pay_personnel_payment(
    payment_id: int,
    body: PersonnelPaymentPayRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Marca un pago pending como paid y registra los datos de la factura emitida
    por el profesor: número, fecha y notas opcionales.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(PersonnelPayment)
        .join(Teacher, Teacher.id == PersonnelPayment.teacher_id)
        .where(
            PersonnelPayment.id == payment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    if payment.status != PersonnelPaymentStatus.PENDING:
        raise HTTPException(status_code=409, detail="La liquidación ya fue pagada.")

    payment.status         = PersonnelPaymentStatus.PAID
    payment.invoice_number = body.invoice_number
    payment.invoice_date   = body.invoice_date
    payment.invoice_notes  = body.invoice_notes

    await db.commit()
    await db.refresh(payment)
    return payment


# ────────────────────────────────────────────────────
# DELETE /admin/personnel-payments/{payment_id}
# ────────────────────────────────────────────────────
@router.delete(
    "/personnel-payments/{payment_id}",
    summary="Eliminar liquidación pendiente",
)
async def delete_personnel_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Elimina una liquidación SOLO si está en status=pending.
    Usar para corregir errores antes de confirmar el pago.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(PersonnelPayment)
        .join(Teacher, Teacher.id == PersonnelPayment.teacher_id)
        .where(
            PersonnelPayment.id == payment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Liquidación no encontrada.")
    if payment.status != PersonnelPaymentStatus.PENDING:
        raise HTTPException(status_code=409, detail="Solo se pueden eliminar liquidaciones en estado pending.")

    await db.delete(payment)
    await db.commit()
    return {"deleted": True, "payment_id": payment_id}


# ────────────────────────────────────────────────────
# GET /admin/personnel-payments/pending-alert
# ────────────────────────────────────────────────────
@router.get(
    "/personnel-payments/pending-alert",
    response_model=list[PendingAlertTeacher],
    summary="Teachers activos sin pago generado en el mes anterior",
)
async def personnel_payments_pending_alert(
    year:  int | None = Query(None, description="Año a verificar. Default: mes anterior"),
    month: int | None = Query(None, description="Mes a verificar (1-12). Default: mes anterior"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Devuelve los teachers activos que NO tienen ningún PersonnelPayment
    cuyo period_from cae dentro del mes indicado.
    Útil para alertar: "Faltan X profesores sin liquidación para este mes".
    Default: verifica el mes anterior al actual.
    """
    if not current_teacher.organization_id:
        return []

    today = date.today()
    if year is None or month is None:
        # Mes anterior
        if today.month == 1:
            check_year, check_month = today.year - 1, 12
        else:
            check_year, check_month = today.year, today.month - 1
    else:
        check_year, check_month = year, month

    month_start = date(check_year, check_month, 1)
    if check_month == 12:
        month_end = date(check_year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(check_year, check_month + 1, 1) - timedelta(days=1)

    # Teachers activos de la organización
    teachers_result = await db.execute(
        select(Teacher).where(
            Teacher.organization_id == current_teacher.organization_id,
            Teacher.active == True,
        )
    )
    all_teachers = teachers_result.scalars().all()

    # Teachers que YA tienen un pago con period_from en ese mes
    paid_result = await db.execute(
        select(PersonnelPayment.teacher_id).where(
            PersonnelPayment.teacher_id.in_([t.id for t in all_teachers]),
            PersonnelPayment.period_from >= month_start,
            PersonnelPayment.period_from <= month_end,
        )
    )
    teachers_with_payment = {row[0] for row in paid_result.all()}

    return [
        PendingAlertTeacher(id=t.id, name=t.name, payment_mode=t.payment_mode)
        for t in all_teachers
        if t.id not in teachers_with_payment
    ]


# ────────────────────────────────────────────────────
# FEE DISCOUNTS (Descuentos de cuota por enrollment)
# ────────────────────────────────────────────────────

class FeeDiscountCreate(BaseModel):
    discount_type: str = Field(..., pattern="^(percentage|fixed)$")
    discount_value: Decimal = Field(..., gt=0)
    valid_from_year: int
    valid_from_month: int = Field(..., ge=1, le=12)
    valid_until_year: int | None = None
    valid_until_month: int | None = Field(None, ge=1, le=12)
    reason: str | None = Field(None, max_length=255)
    active: bool = True


class FeeDiscountUpdate(BaseModel):
    discount_type: str | None = Field(None, pattern="^(percentage|fixed)$")
    discount_value: Decimal | None = Field(None, gt=0)
    valid_from_year: int | None = None
    valid_from_month: int | None = Field(None, ge=1, le=12)
    valid_until_year: int | None = None
    valid_until_month: int | None = Field(None, ge=1, le=12)
    reason: str | None = None
    active: bool | None = None


class FeeDiscountResponse(BaseModel):
    id: int
    enrollment_id: int
    discount_type: str
    discount_value: Decimal
    valid_from_year: int
    valid_from_month: int
    valid_until_year: int | None
    valid_until_month: int | None
    reason: str | None
    active: bool
    created_at: datetime_type
    updated_at: datetime_type
    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/enrollments/{enrollment_id}/discounts",
    response_model=FeeDiscountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear descuento de cuota para un enrollment",
)
async def create_fee_discount(
    enrollment_id: int,
    data: FeeDiscountCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Crea un descuento de cuota (porcentaje o fijo) para un enrollment específico."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    discount = FeeDiscount(
        enrollment_id=enrollment_id,
        discount_type=DiscountType(data.discount_type),
        discount_value=data.discount_value,
        valid_from_year=data.valid_from_year,
        valid_from_month=data.valid_from_month,
        valid_until_year=data.valid_until_year,
        valid_until_month=data.valid_until_month,
        reason=data.reason,
        active=data.active,
    )
    db.add(discount)
    await db.commit()
    await db.refresh(discount)
    return discount


@router.get(
    "/enrollments/{enrollment_id}/discounts",
    response_model=list[FeeDiscountResponse],
    summary="Listar descuentos de un enrollment",
)
async def list_fee_discounts(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Lista todos los descuentos de cuota de un enrollment, ordenados por fecha de vigencia."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    discounts_result = await db.execute(
        select(FeeDiscount)
        .where(FeeDiscount.enrollment_id == enrollment_id)
        .order_by(FeeDiscount.valid_from_year.desc(), FeeDiscount.valid_from_month.desc())
    )
    discounts = discounts_result.scalars().all()
    return discounts


@router.patch(
    "/fee-discounts/{discount_id}",
    response_model=FeeDiscountResponse,
    summary="Actualizar un descuento de cuota",
)
async def update_fee_discount(
    discount_id: int,
    data: FeeDiscountUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Actualiza campos de un descuento de cuota existente."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(FeeDiscount)
        .join(Enrollment, Enrollment.id == FeeDiscount.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            FeeDiscount.id == discount_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    discount = result.scalar_one_or_none()
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado en tu organización.")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "discount_type" and value is not None:
            discount.discount_type = DiscountType(value)
        else:
            setattr(discount, field, value)

    await db.commit()
    await db.refresh(discount)
    return discount


@router.delete(
    "/fee-discounts/{discount_id}",
    summary="Eliminar un descuento de cuota",
)
async def delete_fee_discount(
    discount_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Elimina un descuento de cuota."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(FeeDiscount)
        .join(Enrollment, Enrollment.id == FeeDiscount.enrollment_id)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            FeeDiscount.id == discount_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    discount = result.scalar_one_or_none()
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado en tu organización.")

    await db.delete(discount)
    await db.commit()
    return {"deleted": True, "discount_id": discount_id}


# ────────────────────────────────────────────────────
# EXPENSES (Gastos operativos)
# ────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    amount: Decimal = Field(..., gt=0)
    category: str = Field(..., pattern="^(alquiler|servicios|materiales|marketing|mantenimiento|otro)$")
    description: str = Field(..., min_length=1, max_length=500)
    expense_date: datetime_date
    recurring: bool = False
    receipt_note: str | None = Field(None, max_length=255)


class ExpenseUpdate(BaseModel):
    amount: Decimal | None = Field(None, gt=0)
    category: str | None = Field(None, pattern="^(alquiler|servicios|materiales|marketing|mantenimiento|otro)$")
    description: str | None = Field(None, min_length=1, max_length=500)
    expense_date: datetime_date | None = None
    recurring: bool | None = None
    receipt_note: str | None = None


class ExpenseResponse(BaseModel):
    id: int
    organization_id: int
    amount: Decimal
    category: str
    description: str
    expense_date: datetime_date
    recurring: bool
    receipt_note: str | None
    created_at: datetime_type
    updated_at: datetime_type
    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/expenses",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un gasto operativo",
)
async def create_expense(
    data: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Registra un gasto operativo de la organización."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    expense = Expense(
        organization_id=current_teacher.organization_id,
        amount=data.amount,
        category=ExpenseCategory(data.category),
        description=data.description,
        expense_date=data.expense_date,
        recurring=data.recurring,
        receipt_note=data.receipt_note,
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return expense


@router.get(
    "/expenses",
    response_model=list[ExpenseResponse],
    summary="Listar gastos operativos",
)
async def list_expenses(
    category: str | None = Query(None),
    from_date: datetime_date | None = Query(None),
    to_date: datetime_date | None = Query(None),
    recurring: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Lista gastos operativos de la organización con filtros opcionales."""
    if not current_teacher.organization_id:
        return []

    query = select(Expense).where(
        Expense.organization_id == current_teacher.organization_id
    ).order_by(Expense.expense_date.desc())

    if category is not None:
        query = query.where(Expense.category == ExpenseCategory(category))
    if from_date is not None:
        query = query.where(Expense.expense_date >= from_date)
    if to_date is not None:
        query = query.where(Expense.expense_date <= to_date)
    if recurring is not None:
        query = query.where(Expense.recurring == recurring)

    result = await db.execute(query)
    return result.scalars().all()


@router.patch(
    "/expenses/{expense_id}",
    response_model=ExpenseResponse,
    summary="Actualizar un gasto operativo",
)
async def update_expense(
    expense_id: int,
    data: ExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Actualiza campos de un gasto operativo existente."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.organization_id == current_teacher.organization_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Gasto no encontrado en tu organización.")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "category" and value is not None:
            expense.category = ExpenseCategory(value)
        else:
            setattr(expense, field, value)

    await db.commit()
    await db.refresh(expense)
    return expense


@router.delete(
    "/expenses/{expense_id}",
    summary="Eliminar un gasto operativo",
)
async def delete_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Elimina un gasto operativo."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Expense).where(
            Expense.id == expense_id,
            Expense.organization_id == current_teacher.organization_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Gasto no encontrado en tu organización.")

    await db.delete(expense)
    await db.commit()
    return {"deleted": True, "expense_id": expense_id}


# ────────────────────────────────────────────────────
# ENROLLMENT ADMIN (Gestión admin de inscripciones)
# ────────────────────────────────────────────────────

class AdminEnrollmentResponse(BaseModel):
    id: int
    student_id: int
    student_name: str
    instrument_id: int
    instrument_name: str
    teacher_id: int
    teacher_name: str
    status: str
    level: str | None
    format: str
    enrolled_date: datetime_date
    suspended_until: datetime_date | None
    suspended_at: datetime_date | None
    suspended_reason: str | None
    withdrawn_date: datetime_date | None
    credits: int
    base_monthly_fee: Decimal
    enrollment_fee: Decimal
    created_at: datetime_type
    updated_at: datetime_type
    model_config = ConfigDict(from_attributes=True)


class AdminEnrollmentUpdate(BaseModel):
    """Solo los campos que admin puede editar directamente."""
    level: str | None = None
    base_monthly_fee: Decimal | None = Field(None, ge=0)
    enrollment_fee: Decimal | None = Field(None, ge=0)
    credits: int | None = Field(None, ge=0)
    notes: str | None = None


class AdminEnrollmentSuspend(BaseModel):
    suspended_until: datetime_date
    suspended_reason: str | None = Field(None, max_length=255)


class AdminEnrollmentWithdraw(BaseModel):
    withdrawn_date: datetime_date


def _build_admin_enrollment_response(enrollment, student, instrument, teacher) -> dict:
    return {
        "id": enrollment.id,
        "student_id": enrollment.student_id,
        "student_name": student.name if student else "—",
        "instrument_id": enrollment.instrument_id,
        "instrument_name": instrument.name if instrument else "—",
        "teacher_id": enrollment.teacher_id,
        "teacher_name": teacher.name if teacher else "—",
        "status": enrollment.status.value if hasattr(enrollment.status, 'value') else enrollment.status,
        "level": enrollment.level.value if enrollment.level and hasattr(enrollment.level, 'value') else enrollment.level,
        "format": enrollment.format.value if hasattr(enrollment.format, 'value') else enrollment.format,
        "enrolled_date": enrollment.enrolled_date,
        "suspended_until": enrollment.suspended_until,
        "suspended_at": enrollment.suspended_at,
        "suspended_reason": enrollment.suspended_reason,
        "withdrawn_date": enrollment.withdrawn_date,
        "credits": enrollment.credits,
        "base_monthly_fee": enrollment.base_monthly_fee,
        "enrollment_fee": enrollment.enrollment_fee,
        "created_at": enrollment.created_at,
        "updated_at": enrollment.updated_at,
    }


@router.get(
    "/enrollments",
    response_model=list[AdminEnrollmentResponse],
    summary="Listar inscripciones (admin)",
)
async def list_admin_enrollments(
    student_id: int | None = Query(None),
    teacher_id: int | None = Query(None),
    status: str | None = Query(None, alias="status"),
    instrument_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Lista inscripciones de la organización con filtros opcionales."""
    if not current_teacher.organization_id:
        return []

    query = (
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .join(Student, Student.id == Enrollment.student_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.instrument),
            selectinload(Enrollment.teacher),
        )
        .where(Teacher.organization_id == current_teacher.organization_id)
    )

    if student_id is not None:
        query = query.where(Enrollment.student_id == student_id)
    if teacher_id is not None:
        query = query.where(Enrollment.teacher_id == teacher_id)
    if status is not None:
        query = query.where(Enrollment.status == EnrollmentStatus(status))
    if instrument_id is not None:
        query = query.where(Enrollment.instrument_id == instrument_id)

    query = query.order_by(Teacher.name, Student.name)
    result = await db.execute(query)
    enrollments = result.scalars().all()

    return [
        AdminEnrollmentResponse.model_validate(_build_admin_enrollment_response(
            e, e.student, e.instrument, e.teacher
        ))
        for e in enrollments
    ]


@router.get(
    "/enrollments/{enrollment_id}",
    response_model=AdminEnrollmentResponse,
    summary="Obtener inscripción (admin)",
)
async def get_admin_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Obtiene detalles de una inscripción específica."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.instrument),
            selectinload(Enrollment.teacher),
        )
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    return AdminEnrollmentResponse.model_validate(_build_admin_enrollment_response(
        enrollment, enrollment.student, enrollment.instrument, enrollment.teacher
    ))


@router.patch(
    "/enrollments/{enrollment_id}",
    response_model=AdminEnrollmentResponse,
    summary="Actualizar inscripción (admin)",
)
async def update_admin_enrollment(
    enrollment_id: int,
    data: AdminEnrollmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Actualiza campos editables de una inscripción (level, fees, credits)."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.instrument),
            selectinload(Enrollment.teacher),
        )
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "level" and value is not None:
            enrollment.level = EnrollmentLevel(value)
        elif field == "credits":
            pass  # se maneja abajo
        elif field != "notes":
            setattr(enrollment, field, value)

    # Ajuste manual de créditos con nota obligatoria
    if "credits" in update_data and update_data["credits"] is not None:
        note = update_data.get("notes") or data.notes
        if not note:
            raise HTTPException(
                status_code=400,
                detail="Se requiere el campo 'notes' como motivo al modificar créditos manualmente.",
            )
        await credit_service.apply_manual(
            db=db,
            enrollment=enrollment,
            new_credits=update_data["credits"],
            note=note,
            created_by=current_teacher.id,
        )

    await db.commit()
    await db.refresh(enrollment)

    return AdminEnrollmentResponse.model_validate(_build_admin_enrollment_response(
        enrollment, enrollment.student, enrollment.instrument, enrollment.teacher
    ))


@router.post(
    "/enrollments/{enrollment_id}/suspend",
    response_model=AdminEnrollmentResponse,
    summary="Suspender inscripción (admin)",
)
async def suspend_admin_enrollment(
    enrollment_id: int,
    data: AdminEnrollmentSuspend,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Suspende una inscripción activa. No elimina clases futuras."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.instrument),
            selectinload(Enrollment.teacher),
        )
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    if enrollment.status != EnrollmentStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Solo se pueden suspender inscripciones activas.")

    enrollment.status = EnrollmentStatus.SUSPENDED
    enrollment.suspended_until = data.suspended_until
    enrollment.suspended_at = date.today()
    enrollment.suspended_reason = data.suspended_reason

    await db.commit()
    await db.refresh(enrollment)

    return AdminEnrollmentResponse.model_validate(_build_admin_enrollment_response(
        enrollment, enrollment.student, enrollment.instrument, enrollment.teacher
    ))


@router.post(
    "/enrollments/{enrollment_id}/reactivate",
    response_model=AdminEnrollmentResponse,
    summary="Reactivar inscripción (admin)",
)
async def reactivate_admin_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Reactiva una inscripción suspendida. No regenera clases."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.instrument),
            selectinload(Enrollment.teacher),
        )
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    if enrollment.status != EnrollmentStatus.SUSPENDED:
        raise HTTPException(status_code=409, detail="Solo se pueden reactivar inscripciones suspendidas.")

    enrollment.status = EnrollmentStatus.ACTIVE
    enrollment.suspended_until = None
    enrollment.suspended_at = None
    enrollment.suspended_reason = None

    await db.commit()
    await db.refresh(enrollment)

    return AdminEnrollmentResponse.model_validate(_build_admin_enrollment_response(
        enrollment, enrollment.student, enrollment.instrument, enrollment.teacher
    ))


@router.post(
    "/enrollments/{enrollment_id}/withdraw",
    response_model=AdminEnrollmentResponse,
    summary="Retirar inscripción (admin)",
)
async def withdraw_admin_enrollment(
    enrollment_id: int,
    data: AdminEnrollmentWithdraw,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """Retira una inscripción (cambia estado a withdrawn)."""
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.instrument),
            selectinload(Enrollment.teacher),
        )
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado en tu organización.")

    if enrollment.status == EnrollmentStatus.WITHDRAWN:
        raise HTTPException(status_code=409, detail="La inscripción ya está retirada.")

    enrollment.status = EnrollmentStatus.WITHDRAWN
    enrollment.withdrawn_date = data.withdrawn_date

    await db.commit()
    await db.refresh(enrollment)

    return AdminEnrollmentResponse.model_validate(_build_admin_enrollment_response(
        enrollment, enrollment.student, enrollment.instrument, enrollment.teacher
    ))


@router.post(
    "/enrollments/{enrollment_id}/generate-matricula",
    response_model=BillingPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generar cobro de matrícula para una inscripción",
)
async def generate_matricula(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("org.manage_users")),
):
    """
    Genera un BillingPeriod de tipo 'matricula' para la inscripción indicada.
    Idempotente: devuelve error si ya existe uno.
    Solo aplica si enrollment_fee > 0.
    """
    if not current_teacher.organization_id:
        raise HTTPException(status_code=400, detail="Sin organización asociada.")

    enr_result = await db.execute(
        select(Enrollment)
        .join(Teacher, Teacher.id == Enrollment.teacher_id)
        .where(
            Enrollment.id == enrollment_id,
            Teacher.organization_id == current_teacher.organization_id,
        )
        .options(selectinload(Enrollment.teacher))
    )
    enrollment = enr_result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")

    if not enrollment.enrollment_fee or enrollment.enrollment_fee <= 0:
        raise HTTPException(
            status_code=400,
            detail="Esta inscripción no tiene matrícula configurada."
        )

    existing = await db.execute(
        select(BillingPeriod).where(
            BillingPeriod.enrollment_id == enrollment_id,
            BillingPeriod.charge_type == "matricula",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Ya existe un cobro de matrícula para esta inscripción."
        )

    bp = BillingPeriod(
        enrollment_id=enrollment_id,
        charge_type="matricula",
        description=None,
        quantity=None,
        period_year=None,
        period_month=None,
        base_amount=enrollment.enrollment_fee,
        discount_applied=Decimal("0.00"),
        final_amount=enrollment.enrollment_fee,
        status=BillingPeriodStatus.PENDING,
        due_date=date.today(),
        notes=None,
    )
    db.add(bp)
    await db.commit()
    await db.refresh(bp)

    teacher_name = enrollment.teacher.name if enrollment.teacher else "—"
    return _build_bp_response(bp, Decimal("0.00"), teacher_name)


class AgendaClassItem(BaseModel):
    """Clase individual con contexto completo para la agenda."""
    id: int
    date: datetime_date
    time: str
    duration: int
    type: str
    format: str
    status: str
    notes: str | None
    student_id: int | None
    student_name: str | None
    teacher_id: int
    teacher_name: str
    instrument_id: int | None
    instrument_name: str | None
    room_id: int | None
    room_name: str | None
    branch_id: int | None
    branch_name: str | None
    schedule_id: int | None
    attendance_status: str | None
    group_class_ids: list[int] | None = None
    model_config = ConfigDict(from_attributes=True)


class AgendaEventTeacher(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class AgendaEventItem(BaseModel):
    """Evento institucional con contexto para la agenda."""
    id: int
    title: str
    date: datetime_date
    time_start: str
    duration: int
    event_type: str
    room_id: int | None
    room_name: str | None
    description: str | None
    guest_name: str | None
    notes: str | None
    teachers: list[AgendaEventTeacher]
    student_count: int
    model_config = ConfigDict(from_attributes=True)


class AgendaResponse(BaseModel):
    """Respuesta completa del endpoint de agenda."""
    from_date: datetime_date
    to_date: datetime_date
    classes: list[AgendaClassItem]
    events: list[AgendaEventItem]


@router.get(
    "/agenda",
    response_model=AgendaResponse,
    summary="Obtener datos de agenda (clases y eventos)",
)
async def get_admin_agenda(
    from_date: datetime_date = Query(..., description="Fecha inicial del rango"),
    to_date: datetime_date = Query(..., description="Fecha final del rango"),
    teacher_id: int | None = Query(None, description="Filtrar por teacher_id"),
    room_id: int | None = Query(None, description="Filtrar por room_id"),
    instrument_id: int | None = Query(None, description="Filtrar por instrument_id"),
    branch_id: int | None = Query(None, description="Filtrar por branch_id de la sala"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(require_permission("students.view_enrollment")),
):
    if not current_teacher.organization_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sin organización asociada.")

    if to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="to_date debe ser mayor o igual a from_date.",
        )

    if (to_date - from_date).days > 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rango máximo es 60 días.",
        )

    classes_stmt = (
        select(
            Class,
            Student.id.label("student_id"),
            Student.name.label("student_name"),
            Teacher.name.label("teacher_name"),
            Instrument.id.label("instrument_id"),
            Instrument.name.label("instrument_name"),
            Room.name.label("room_name"),
            Branch.id.label("branch_id"),
            Branch.name.label("branch_name"),
            Attendance.status.label("attendance_status"),
        )
        .join(Teacher, Teacher.id == Class.teacher_id)
        .join(Enrollment, Enrollment.id == Class.enrollment_id, isouter=True)
        .join(Student, Student.id == Enrollment.student_id, isouter=True)
        .join(Instrument, Instrument.id == Enrollment.instrument_id, isouter=True)
        .join(Room, Room.id == Class.room_id, isouter=True)
        .join(Branch, Branch.id == Room.branch_id, isouter=True)
        .join(Attendance, Attendance.class_id == Class.id, isouter=True)
        .where(
            Teacher.organization_id == current_teacher.organization_id,
            Class.date >= from_date,
            Class.date <= to_date,
            Class.status != ClassStatus.CANCELLED,
        )
    )

    if teacher_id is not None:
        classes_stmt = classes_stmt.where(Class.teacher_id == teacher_id)
    if room_id is not None:
        classes_stmt = classes_stmt.where(Class.room_id == room_id)
    if instrument_id is not None:
        classes_stmt = classes_stmt.where(Enrollment.instrument_id == instrument_id)
    if branch_id is not None:
        classes_stmt = classes_stmt.where(
            or_(Class.room_id.is_(None), Room.branch_id == branch_id)
        )

    classes_stmt = classes_stmt.order_by(Class.date, Class.time)
    class_rows = (await db.execute(classes_stmt)).all()

    classes: list[AgendaClassItem] = []
    grouped_groups = {}

    for row in class_rows:
        cls = row[0]
        cls_format = cls.format.value if hasattr(cls.format, 'value') else cls.format
        
        if cls_format == 'group':
            key = (cls.date, cls.time, cls.room_id, cls.teacher_id)
            if key not in grouped_groups:
                grouped_groups[key] = {
                    "base_row": row,
                    "class_ids": [],
                    "count": 0
                }
            grouped_groups[key]["class_ids"].append(cls.id)
            grouped_groups[key]["count"] += 1
        else:
            classes.append(AgendaClassItem(
                id=cls.id,
                date=cls.date,
                time=cls.time.strftime("%H:%M"),
                duration=cls.duration,
                type=cls.type.value if hasattr(cls.type, 'value') else cls.type,
                format=cls_format,
                status=cls.status.value if hasattr(cls.status, 'value') else cls.status,
                notes=cls.notes,
                student_id=row.student_id,
                student_name=row.student_name,
                teacher_id=cls.teacher_id,
                teacher_name=row.teacher_name,
                instrument_id=row.instrument_id,
                instrument_name=row.instrument_name,
                room_id=cls.room_id,
                room_name=row.room_name,
                branch_id=row.branch_id,
                branch_name=row.branch_name,
                schedule_id=cls.schedule_id,
                attendance_status=(
                    row.attendance_status.value
                    if row.attendance_status and hasattr(row.attendance_status, 'value')
                    else row.attendance_status
                ),
            ))

    for key, data in grouped_groups.items():
        row = data["base_row"]
        cls = row[0]
        count = data["count"]
        classes.append(AgendaClassItem(
            id=data["class_ids"][0],
            date=cls.date,
            time=cls.time.strftime("%H:%M"),
            duration=cls.duration,
            type=cls.type.value if hasattr(cls.type, 'value') else cls.type,
            format='group',
            status=cls.status.value if hasattr(cls.status, 'value') else cls.status,
            notes=cls.notes,
            student_id=None,
            student_name=f"Clase Grupal ({count} alumnos)",
            teacher_id=cls.teacher_id,
            teacher_name=row.teacher_name,
            instrument_id=None,
            instrument_name=None,
            room_id=cls.room_id,
            room_name=row.room_name,
            branch_id=row.branch_id,
            branch_name=row.branch_name,
            schedule_id=cls.schedule_id,
            attendance_status=None,
            group_class_ids=data["class_ids"]
        ))

    events_stmt = (
        select(Event)
        .where(
            Event.organization_id == current_teacher.organization_id,
            Event.date >= from_date,
            Event.date <= to_date,
        )
        .options(
            selectinload(Event.teachers),
            selectinload(Event.students),
            selectinload(Event.room),
        )
        .order_by(Event.date, Event.time_start)
    )

    if room_id is not None:
        events_stmt = events_stmt.where(Event.room_id == room_id)

    event_rows = (await db.execute(events_stmt)).scalars().all()

    events: list[AgendaEventItem] = []
    for ev in event_rows:
        events.append(AgendaEventItem(
            id=ev.id,
            title=ev.title,
            date=ev.date,
            time_start=ev.time_start.strftime("%H:%M"),
            duration=ev.duration,
            event_type=ev.event_type,
            room_id=ev.room_id,
            room_name=ev.room.name if ev.room else None,
            description=ev.description,
            guest_name=ev.guest_name,
            notes=ev.notes,
            teachers=[AgendaEventTeacher(id=t.id, name=t.name) for t in ev.teachers],
            student_count=len(ev.students or []),
        ))

    return AgendaResponse(
        from_date=from_date,
        to_date=to_date,
        classes=classes,
        events=events,
    )
