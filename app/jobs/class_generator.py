"""
Generador Automático de Clases

Este módulo contiene la lógica principal para generar clases automáticamente
desde los horarios (Schedules) de los alumnos.

REGLAS DE NEGOCIO:
1. Generar clases 2 meses adelante desde la inscripción
2. Job mensual ejecuta día 10 de cada mes a las 2 AM
3. Saltar clases duplicadas (misma fecha/hora/enrollment)
4. NO generar en feriados
5. Solo generar para enrollments con status='active'
6. Respetar valid_from / valid_until de los Schedules
7. Al cambiar horario: ELIMINAR clases futuras del horario viejo
8. Formato heredado desde Enrollment.format

FUNCIONES PRINCIPALES:
- generate_classes_for_enrollment(): Generar 2 meses para un enrollment (onboarding)
- generate_monthly_classes(): Job mensual automático
- delete_future_classes_for_schedule(): Eliminar clases al cambiar horario
"""

from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.schedule import Schedule, DayOfWeek
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.core.holidays import is_holiday


# ============================================
# MAPEO DE DÍAS DE LA SEMANA
# ============================================

DAY_MAP = {
    DayOfWeek.MONDAY: 0,
    DayOfWeek.TUESDAY: 1,
    DayOfWeek.WEDNESDAY: 2,
    DayOfWeek.THURSDAY: 3,
    DayOfWeek.FRIDAY: 4,
    DayOfWeek.SATURDAY: 5,
    DayOfWeek.SUNDAY: 6,
}


# ============================================
# GENERACIÓN PARA UN ENROLLMENT (ONBOARDING)
# ============================================

async def generate_classes_for_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    months_ahead: int = 2
) -> dict:
    """
    Genera clases para una inscripción específica

    Usado principalmente en el onboarding cuando se inscribe un alumno.
    Genera clases para los próximos N meses desde valid_from del Schedule.

    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción
        months_ahead: Cuántos meses generar (default: 2)

    Returns:
        dict: Estadísticas de generación
            {
                "created": 16,
                "skipped": 2,
                "errors": []
            }

    Example:
        >>> # Al inscribir alumno en onboarding
        >>> result = await generate_classes_for_enrollment(db, enrollment_id=1, months_ahead=2)
        >>> print(f"Clases generadas: {result['created']}")
    """
    # Obtener enrollment y validar
    enrollment = await db.get(Enrollment, enrollment_id)

    if not enrollment:
        return {"error": "Enrollment no existe", "created": 0, "skipped": 0, "errors": []}

    if enrollment.status != EnrollmentStatus.ACTIVE:
        return {
            "error": f"Enrollment no está activo (status: {enrollment.status})",
            "created": 0,
            "skipped": 0,
            "errors": []
        }

    # Obtener schedules activos de esta inscripción
    result = await db.execute(
        select(Schedule).where(
            and_(
                Schedule.enrollment_id == enrollment_id,
                Schedule.active == True
            )
        )
    )
    schedules = result.scalars().all()

    if not schedules:
        return {
            "error": "No hay horarios definidos para este enrollment",
            "created": 0,
            "skipped": 0,
            "errors": []
        }

    stats = {"created": 0, "skipped": 0, "errors": []}

    # Para cada Schedule, generar clases
    for schedule in schedules:
        result = await _generate_classes_for_schedule(
            db, schedule, enrollment, months_ahead
        )
        stats["created"] += result["created"]
        stats["skipped"] += result["skipped"]
        stats["errors"].extend(result["errors"])

    await db.commit()
    return stats


# ============================================
# GENERACIÓN PARA UN SCHEDULE ESPECÍFICO
# ============================================

async def _generate_classes_for_schedule(
    db: AsyncSession,
    schedule: Schedule,
    enrollment: Enrollment,
    months_ahead: int
) -> dict:
    """
    Genera clases para un horario específico (función interna)

    Args:
        db: Sesión de base de datos
        schedule: Horario desde el cual generar
        enrollment: Inscripción asociada
        months_ahead: Cuántos meses COMPLETOS generar después del mes de inscripción

    Returns:
        dict: Estadísticas {created, skipped, errors}
    """
    stats = {"created": 0, "skipped": 0, "errors": []}

    # Calcular rango de fechas
    start_date = schedule.valid_from

    # Calcular fecha final:
    # - Mes de inscripción: desde valid_from hasta fin de ese mes
    # - months_ahead meses completos adicionales
    #
    # Ejemplo: valid_from = 2025-09-22, months_ahead = 1
    # - Generar desde 22-sept hasta 30-sept (resto del mes de inscripción)
    # - Generar todo octubre (1-oct hasta 31-oct)
    # - end_date = 31-oct-2025

    # Calcular último día del mes actual de inscripción
    if start_date.month == 12:
        next_month_start = date(start_date.year + 1, 1, 1)
    else:
        next_month_start = date(start_date.year, start_date.month + 1, 1)

    current_month_end = next_month_start - timedelta(days=1)

    # Agregar months_ahead meses completos
    target_month = start_date.month + months_ahead
    target_year = start_date.year

    # Ajustar si pasamos de diciembre
    while target_month > 12:
        target_month -= 12
        target_year += 1

    # Calcular último día del mes objetivo
    if target_month == 12:
        next_month_start = date(target_year + 1, 1, 1)
    else:
        next_month_start = date(target_year, target_month + 1, 1)

    end_date = next_month_start - timedelta(days=1)

    # Si hay valid_until, usar el menor
    if schedule.valid_until:
        end_date = min(end_date, schedule.valid_until)

    # Obtener día de la semana objetivo (0=Lunes, 6=Domingo)
    target_weekday = DAY_MAP[schedule.day]

    # Encontrar el primer día que coincida con el día de la semana del Schedule
    current_date = start_date
    while current_date.weekday() != target_weekday:
        current_date += timedelta(days=1)

        # Protección: si no encontramos el día en 7 días, hay un error
        if current_date > start_date + timedelta(days=7):
            stats["errors"].append(
                f"No se pudo encontrar {schedule.day} desde {start_date}"
            )
            return stats

    # Generar clases semana por semana
    while current_date <= end_date:
        # Verificar si es feriado
        if is_holiday(current_date):
            stats["skipped"] += 1
            current_date += timedelta(weeks=1)
            continue

        # Verificar si ya existe clase idéntica
        result = await db.execute(
            select(Class).where(
                and_(
                    Class.schedule_id == schedule.id,
                    Class.date == current_date,
                    Class.time == schedule.time
                )
            )
        )

        if result.scalar_one_or_none():
            # Ya existe, saltar
            stats["skipped"] += 1
            current_date += timedelta(weeks=1)
            continue

        # Crear clase nueva
        try:
            new_class = Class(
                schedule_id=schedule.id,
                enrollment_id=enrollment.id,
                teacher_id=schedule.teacher_id,
                date=current_date,
                time=schedule.time,
                duration=schedule.duration,
                status=ClassStatus.SCHEDULED,
                type=ClassType.REGULAR,
                format=enrollment.format  # ⬅️ Heredado desde Enrollment
            )

            db.add(new_class)
            stats["created"] += 1

        except Exception as e:
            stats["errors"].append(
                f"Error al crear clase {current_date} {schedule.time}: {str(e)}"
            )

        # Avanzar una semana
        current_date += timedelta(weeks=1)

    return stats


# ============================================
# JOB MENSUAL AUTOMÁTICO
# ============================================

async def generate_monthly_classes(db: AsyncSession) -> dict:
    """
    Job mensual: Genera clases del próximo mes para todos los enrollments activos

    Ejecuta automáticamente día 10 de cada mes a las 2:00 AM.
    Genera clases solo del próximo mes (no 2 meses completos).

    Args:
        db: Sesión de base de datos

    Returns:
        dict: Estadísticas de generación
            {
                "created": 120,
                "skipped": 30,
                "enrollments_processed": 15,
                "errors": []
            }

    Example:
        >>> # Ejecutado automáticamente por APScheduler
        >>> result = await generate_monthly_classes(db)
        >>> print(f"Total clases generadas: {result['created']}")
    """
    # Obtener todos los enrollments activos
    result = await db.execute(
        select(Enrollment).where(
            Enrollment.status == EnrollmentStatus.ACTIVE
        )
    )
    enrollments = result.scalars().all()

    total_stats = {
        "created": 0,
        "skipped": 0,
        "enrollments_processed": 0,
        "errors": []
    }

    for enrollment in enrollments:
        result = await generate_classes_for_enrollment(
            db,
            enrollment.id,
            months_ahead=1  # Solo próximo mes en job mensual
        )

        if "error" not in result:
            total_stats["created"] += result["created"]
            total_stats["skipped"] += result["skipped"]
            total_stats["errors"].extend(result.get("errors", []))
            total_stats["enrollments_processed"] += 1
        else:
            total_stats["errors"].append(
                f"Enrollment {enrollment.id}: {result['error']}"
            )

    await db.commit()
    return total_stats


# ============================================
# ELIMINAR CLASES FUTURAS (CAMBIO DE HORARIO)
# ============================================

async def delete_future_classes_for_schedule(
    db: AsyncSession,
    schedule_id: int,
    from_date: date
) -> int:
    """
    ELIMINA (físicamente) todas las clases futuras de un horario desde una fecha

    Usado al cambiar de horario. Las clases se eliminan de la BD, NO se cancelan.

    IMPORTANTE: Solo elimina clases con status='scheduled' (no las completadas).

    Args:
        db: Sesión de base de datos
        schedule_id: ID del horario que cambió
        from_date: Fecha desde la cual eliminar (inclusiva)

    Returns:
        int: Cantidad de clases eliminadas

    Example:
        >>> # Al cambiar horario de un alumno
        >>> deleted = await delete_future_classes_for_schedule(
        ...     db,
        ...     schedule_id=1,
        ...     from_date=date(2025, 11, 1)
        ... )
        >>> print(f"Clases eliminadas: {deleted}")
    """
    # Obtener clases futuras del Schedule (solo SCHEDULED, no completed)
    result = await db.execute(
        select(Class).where(
            and_(
                Class.schedule_id == schedule_id,
                Class.date >= from_date,
                Class.status == ClassStatus.SCHEDULED  # Solo eliminar las no completadas
            )
        )
    )
    classes = result.scalars().all()

    # ELIMINAR físicamente cada una
    count = 0
    for cls in classes:
        await db.delete(cls)
        count += 1

    await db.commit()
    return count


# ============================================
# CANCELAR CLASES FUTURAS (SUSPENSIÓN/RETIRO)
# ============================================

async def cancel_future_classes_for_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    from_date: date
) -> int:
    """
    CANCELA todas las clases futuras de una inscripción desde una fecha

    Usado cuando un enrollment se suspende o retira.
    Las clases se CANCELAN (status='cancelled'), NO se eliminan.

    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción
        from_date: Fecha desde la cual cancelar (inclusiva)

    Returns:
        int: Cantidad de clases canceladas

    Example:
        >>> # Al retirar un alumno
        >>> cancelled = await cancel_future_classes_for_enrollment(
        ...     db,
        ...     enrollment_id=1,
        ...     from_date=date(2025, 11, 1)
        ... )
        >>> print(f"Clases canceladas: {cancelled}")
    """
    # Obtener clases futuras del enrollment (solo SCHEDULED)
    result = await db.execute(
        select(Class).where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.date >= from_date,
                Class.status == ClassStatus.SCHEDULED
            )
        )
    )
    classes = result.scalars().all()

    # CANCELAR cada una (cambiar status)
    count = 0
    for cls in classes:
        cls.status = ClassStatus.CANCELLED
        count += 1

    await db.commit()
    return count
