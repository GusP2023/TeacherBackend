"""
Generador Automático de Registros Financieros

Este módulo contiene la lógica principal para generar registros financieros automáticamente:
- BillingPeriod: Deudas mensuales generadas por enrollments activos
- PersonnelPayment: Liquidaciones mensuales de personal

REGLAS DE NEGOCIO:
1. generate_billing_periods: Ejecuta día 1 de cada mes a las 00:00 AM
   - Genera BillingPeriod para cada Enrollment activo
   - Aplica FeeDiscounts vigentes para calcular descuento
   - Idempotente: no duplica si ya existe para el mes
2. generate_personnel_payments: Ejecuta día 1 de cada mes a las 00:30 AM
   - Genera PersonnelPayment para cada Teacher activo
   - Calcula según payment_mode (per_class, monthly_fixed, mixed)
   - Usa el mes ANTERIOR para liquidar clases dadas
   - Idempotente: no duplica si ya existe para el mes

FUNCIONES PRINCIPALES:
- generate_billing_periods(): Job mensual automático
- generate_personnel_payments(): Job mensual automático
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, insert
from sqlalchemy import text

from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee_discount import FeeDiscount, DiscountType
from app.models.billing_period import BillingPeriod, BillingPeriodStatus
from app.models.teacher import Teacher
from app.models.personnel_payment import PersonnelPayment, PersonnelPaymentStatus
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.attendance import Attendance, AttendanceStatus

logger = logging.getLogger(__name__)


# ============================================
# UTILIDADES DE FECHA
# ============================================

def get_last_day_of_month(year: int, month: int) -> date:
    """Obtiene el último día de un mes dado."""
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def get_previous_month_range(today: date) -> tuple[date, date]:
    """
    Obtiene el rango de fechas del mes anterior.
    
    Returns:
        (first_day, last_day) del mes anterior
    """
    if today.month == 1:
        prev_month = 12
        prev_year = today.year - 1
    else:
        prev_month = today.month - 1
        prev_year = today.year
    
    first_day = date(prev_year, prev_month, 1)
    last_day = get_last_day_of_month(prev_year, prev_month)
    
    return first_day, last_day


# ============================================
# JOB 1: GENERAR BILLING PERIODS
# ============================================

async def generate_billing_periods(
    db: AsyncSession,
    target_date: date = None,
    organization_id: int | None = None,
) -> dict:
    """
    Job mensual: Genera BillingPeriod para todos los enrollments activos.
    
    Genera un BillingPeriod por cada Enrollment activo al inicio de cada mes.
    Aplica FeeDiscounts vigentes para calcular el descuento y el monto final.
    
    Reglas:
    - Solo enrollments con status = 'active'
    - Enrollments con status = 'suspended' o 'withdrawn' → NO generan período
    - Si ya existe BillingPeriod para enrollment+año+mes → saltar (idempotente)
    - due_date = día 5 del mes correspondiente
    - Calcula discount_applied sumando descuentos activos
    - final_amount = max(base_amount - discount_applied, 0)
    
    Args:
        db: Sesión de base de datos
        target_date: Fecha objetivo (default: hoy). Usar para testing.
    
    Returns:
        dict: Estadísticas de generación
            {
                "created": int,
                "skipped": int,
                "enrollments_processed": int,
                "errors": [str]
            }
    """
    if target_date is None:
        target_date = date.today()
    
    period_year = target_date.year
    period_month = target_date.month
    due_date = date(period_year, period_month, 5)
    
    logger.info(f"generate_billing_periods: procesando para {period_year}-{period_month:02d}")
    
    # Obtener enrollments activos
    enrollment_query = select(Enrollment).where(Enrollment.status == EnrollmentStatus.ACTIVE)
    if organization_id is not None:
        enrollment_query = (
            enrollment_query
            .join(Teacher, Teacher.id == Enrollment.teacher_id)
            .where(Teacher.organization_id == organization_id)
        )
    result = await db.execute(enrollment_query)
    enrollments = result.scalars().all()
    
    stats = {
        "created": 0,
        "skipped": 0,
        "enrollments_processed": 0,
        "errors": []
    }
    
    for enrollment in enrollments:
        try:
            # Verificar si ya existe BillingPeriod para este enrollment+mes
            existing_result = await db.execute(
                select(BillingPeriod).where(
                    and_(
                        BillingPeriod.enrollment_id == enrollment.id,
                        BillingPeriod.period_year == period_year,
                        BillingPeriod.period_month == period_month
                    )
                )
            )
            existing = existing_result.scalar_one_or_none()
            
            if existing:
                stats["skipped"] += 1
                logger.debug(f"generate_billing_periods: enrollment {enrollment.id} ya tiene período para {period_year}-{period_month:02d}")
                continue
            
            # Calcular descuento aplicado
            discount_applied = Decimal("0.00")
            
            # Buscar FeeDiscounts activos para este enrollment
            discounts_result = await db.execute(
                select(FeeDiscount).where(
                    and_(
                        FeeDiscount.enrollment_id == enrollment.id,
                        FeeDiscount.active == True,
                        # Vigencia desde
                        and_(FeeDiscount.valid_from_year < period_year).self_group() |
                        and_(
                            FeeDiscount.valid_from_year == period_year,
                            FeeDiscount.valid_from_month <= period_month
                        ).self_group(),
                        # Vigencia hasta (NULL = indefinido)
                        and_(FeeDiscount.valid_until_year.is_(None)).self_group() |
                        and_(FeeDiscount.valid_until_year > period_year).self_group() |
                        and_(
                            FeeDiscount.valid_until_year == period_year,
                            FeeDiscount.valid_until_month >= period_month
                        ).self_group()
                    )
                )
            )
            discounts = discounts_result.scalars().all()
            
            base_amount = enrollment.base_monthly_fee
            
            for discount in discounts:
                if discount.discount_type == DiscountType.PERCENTAGE:
                    # Porcentaje sobre base_amount
                    discount_amount = base_amount * (discount.discount_value / Decimal("100"))
                else:  # FIXED
                    # Monto fijo, pero no puede exceder base_amount
                    discount_amount = min(discount.discount_value, base_amount)
                
                discount_applied += discount_amount
            
            # El descuento total no puede exceder el monto base
            discount_applied = min(discount_applied, base_amount)
            
            # Calcular monto final
            final_amount = max(base_amount - discount_applied, Decimal("0.00"))
            
            # Crear BillingPeriod
            billing_period = BillingPeriod(
                enrollment_id=enrollment.id,
                period_year=period_year,
                period_month=period_month,
                base_amount=base_amount,
                discount_applied=discount_applied,
                final_amount=final_amount,
                status=BillingPeriodStatus.PENDING,
                due_date=due_date
            )
            
            db.add(billing_period)
            stats["created"] += 1
            stats["enrollments_processed"] += 1
            
            logger.info(
                f"generate_billing_periods: enrollment {enrollment.id} -> "
                f"base={base_amount}, discount={discount_applied}, final={final_amount}"
            )
            
        except Exception as e:
            error_msg = f"Error procesando enrollment {enrollment.id}: {str(e)}"
            stats["errors"].append(error_msg)
            logger.error(error_msg)
    
    await db.commit()
    
    logger.info(
        f"generate_billing_periods: completado -> "
        f"created={stats['created']}, skipped={stats['skipped']}, "
        f"errors={len(stats['errors'])}"
    )
    
    return stats


# ============================================
# JOB 2: GENERAR PERSONNEL PAYMENTS
# ============================================

async def generate_personnel_payments(db: AsyncSession, target_date: date = None) -> dict:
    """
    Job mensual: Genera PersonnelPayment para todos los teachers activos.
    
    Genera un PersonnelPayment por cada Teacher activo al inicio de cada mes.
    Calcula según payment_mode del teacher usando el mes ANTERIOR.
    
    Reglas:
    - Solo teachers con active = true
    - Si ya existe PersonnelPayment para teacher+año+mes → saltar (idempotente)
    - Calcula según payment_mode:
      * per_class: cuenta clases del mes anterior con attendance present/absent
      * monthly_fixed: usa monthly_salary directamente
      * mixed: suma ambos cálculos
    - Guarda snapshots de tarifas al momento de generar
    - Liquidación del mes ANTERIOR (las clases dadas en enero se pagan en febrero)
    
    Args:
        db: Sesión de base de datos
        target_date: Fecha objetivo (default: hoy). Usar para testing.
    
    Returns:
        dict: Estadísticas de generación
            {
                "created": int,
                "skipped": int,
                "teachers_processed": int,
                "errors": [str]
            }
    """
    if target_date is None:
        target_date = date.today()
    
    # Liquidación del mes anterior
    period_year = target_date.year
    period_month = target_date.month
    
    # Obtener rango del mes anterior para contar clases
    first_day_prev, last_day_prev = get_previous_month_range(target_date)
    
    logger.info(
        f"generate_personnel_payments: liquidando período "
        f"{first_day_prev.year}-{first_day_prev.month:02d} "
        f"({first_day_prev} a {last_day_prev})"
    )
    
    # Obtener teachers activos
    result = await db.execute(
        select(Teacher).where(Teacher.active == True)
    )
    teachers = result.scalars().all()
    
    stats = {
        "created": 0,
        "skipped": 0,
        "teachers_processed": 0,
        "errors": []
    }
    
    for teacher in teachers:
        try:
            # Verificar si ya existe PersonnelPayment para este teacher+mes
            existing_result = await db.execute(
                select(PersonnelPayment).where(
                    and_(
                        PersonnelPayment.teacher_id == teacher.id,
                        PersonnelPayment.period_year == period_year,
                        PersonnelPayment.period_month == period_month
                    )
                )
            )
            existing = existing_result.scalar_one_or_none()
            
            if existing:
                stats["skipped"] += 1
                logger.debug(
                    f"generate_personnel_payments: teacher {teacher.id} "
                    f"ya tiene liquidación para {period_year}-{period_month:02d}"
                )
                continue
            
            # Inicializar contadores y montos
            classes_individual_count = 0
            classes_group_count = 0
            amount_calculated = Decimal("0.00")
            
            # Calcular según payment_mode
            if teacher.payment_mode in ["per_class", "mixed"]:
                # Contar clases del mes anterior
                # Clases cobrables = completed + (present OR absent)
                # NO cuentan las clases con attendance='license'
                
                # Subquery para obtener clases con attendance cobrable
                attendance_subq = (
                    select(Attendance.class_id, Attendance.status).where(
                        Attendance.class_id == Class.id
                    ).correlate(Class).subquery()
                )
                
                # Buscar clases del mes anterior
                classes_result = await db.execute(
                    select(Class, attendance_subq.c.status).where(
                        and_(
                            Class.teacher_id == teacher.id,
                            Class.date >= first_day_prev,
                            Class.date <= last_day_prev,
                            Class.status == ClassStatus.COMPLETED
                        )
                    ).outerjoin(attendance_subq, Class.id == attendance_subq.c.class_id)
                )
                
                class_rows = classes_result.all()
                
                for class_row, attendance_status in class_rows:
                    # Solo contar si attendance es present o absent
                    # Si no hay attendance, no contar (no se puede liquidar sin asistencia)
                    if attendance_status in [AttendanceStatus.PRESENT, AttendanceStatus.ABSENT]:
                        if class_row.format.value == "individual":
                            classes_individual_count += 1
                        elif class_row.format.value == "group":
                            classes_group_count += 1
                
                # Calcular monto por clases
                if teacher.tariff_individual:
                    amount_calculated += Decimal(str(teacher.tariff_individual)) * classes_individual_count
                if teacher.tariff_group:
                    amount_calculated += Decimal(str(teacher.tariff_group)) * classes_group_count
            
            if teacher.payment_mode in ["monthly_fixed", "mixed"]:
                # Sumar salario fijo
                if teacher.monthly_salary:
                    amount_calculated += Decimal(str(teacher.monthly_salary))
            
            # Para monthly_fixed, los contadores de clases son NULL
            if teacher.payment_mode == "monthly_fixed":
                classes_individual_count = None
                classes_group_count = None
            
            # Crear PersonnelPayment
            personnel_payment = PersonnelPayment(
                teacher_id=teacher.id,
                period_year=period_year,
                period_month=period_month,
                payment_mode_snapshot=teacher.payment_mode,
                tariff_individual_snapshot=teacher.tariff_individual,
                tariff_group_snapshot=teacher.tariff_group,
                fixed_amount_snapshot=teacher.monthly_salary,
                classes_individual_count=classes_individual_count,
                classes_group_count=classes_group_count,
                amount_calculated=amount_calculated,
                adjustment=Decimal("0.00"),
                total_amount=amount_calculated,
                status=PersonnelPaymentStatus.PENDING
            )
            
            db.add(personnel_payment)
            stats["created"] += 1
            stats["teachers_processed"] += 1
            
            logger.info(
                f"generate_personnel_payments: teacher {teacher.id} ({teacher.name}) -> "
                f"mode={teacher.payment_mode}, "
                f"individual={classes_individual_count}, group={classes_group_count}, "
                f"amount={amount_calculated}"
            )
            
        except Exception as e:
            error_msg = f"Error procesando teacher {teacher.id}: {str(e)}"
            stats["errors"].append(error_msg)
            logger.error(error_msg)
    
    await db.commit()
    
    logger.info(
        f"generate_personnel_payments: completado -> "
        f"created={stats['created']}, skipped={stats['skipped']}, "
        f"errors={len(stats['errors'])}"
    )
    
    return stats
