"""Financial generator service for calculating payments"""
from datetime import date
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.teacher import Teacher


async def calculate_teacher_payment(
    db: AsyncSession,
    teacher: "Teacher",
    period_from: date,
    period_to: date,
) -> dict:
    """
    Calcula las clases cobrables y montos para un teacher en un período dado.
    Función pura: no escribe en DB. Usada por preview y creación de pago.

    Returns dict con:
        payment_mode_snapshot, tariff_individual_snapshot, tariff_group_snapshot,
        fixed_amount_snapshot, classes_individual_count, classes_group_count,
        amount_calculated
    """
    from app.models.class_model import Class, ClassStatus
    from app.models.attendance import Attendance, AttendanceStatus

    classes_individual_count = 0
    classes_group_count = 0
    amount_calculated = Decimal("0.00")

    if teacher.payment_mode in ["per_class", "mixed"]:
        # Obtener clases del período con attendance present o absent
        classes_result = await db.execute(
            select(Class)
            .join(Attendance, Attendance.class_id == Class.id)
            .where(
                Class.teacher_id == teacher.id,
                Class.date >= period_from,
                Class.date <= period_to,
                Attendance.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.ABSENT])
            )
        )
        classes = classes_result.scalars().all()

        for c in classes:
            if c.format.value == "individual":
                classes_individual_count += 1
            elif c.format.value == "group":
                classes_group_count += 1

        if teacher.tariff_individual:
            amount_calculated += Decimal(str(teacher.tariff_individual)) * classes_individual_count
        if teacher.tariff_group:
            amount_calculated += Decimal(str(teacher.tariff_group)) * classes_group_count

    if teacher.payment_mode in ["monthly_fixed", "mixed"]:
        if teacher.monthly_salary:
            amount_calculated += Decimal(str(teacher.monthly_salary))

    return {
        "payment_mode_snapshot":      teacher.payment_mode,
        "tariff_individual_snapshot": teacher.tariff_individual,
        "tariff_group_snapshot":      teacher.tariff_group,
        "fixed_amount_snapshot":      teacher.monthly_salary,
        "classes_individual_count":   classes_individual_count if teacher.payment_mode != "monthly_fixed" else None,
        "classes_group_count":        classes_group_count if teacher.payment_mode != "monthly_fixed" else None,
        "amount_calculated":          amount_calculated,
    }
