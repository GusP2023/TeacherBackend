"""
Generador Automático de Clases

Este módulo contiene la lógica principal para generar clases automáticamente
desde los horarios (Schedules) de los alumnos.

REGLAS DE NEGOCIO:
1. Generar clases desde HOY (o valid_from si es futuro) hasta fin del mes actual + 2 meses completos
   - Ejemplo: Hoy 19 dic → hasta 28 feb (dic + ene + feb)
   - Ejemplo: valid_from 10 ene → hasta 31 mar (ene + feb + mar)
2. Job mensual ejecuta día 10 de cada mes a las 2 AM
3. Saltar clases duplicadas (misma fecha/hora/enrollment)
4. NO generar en feriados
5. Solo generar para enrollments con status='active'
6. Respetar valid_from / valid_until de los Schedules
7. Al cambiar horario: ELIMINAR clases futuras del horario viejo
8. Formato heredado desde Enrollment.format

FUNCIONES PRINCIPALES:
- generate_classes_for_enrollment(): Generar clases para un enrollment
- generate_monthly_classes(): Job mensual automático
- delete_future_classes_for_schedule(): Eliminar clases al cambiar horario
"""

import logging
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import MultipleResultsFound

from app.models.schedule import Schedule, DayOfWeek
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.attendance import Attendance
from app.core.holidays import is_holiday
from sqlalchemy import exists

logger = logging.getLogger(__name__)


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
# UTILIDADES DE FECHA
# ============================================

def get_last_day_of_month(year: int, month: int) -> date:
    """Obtiene el último día de un mes dado."""
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def add_months(d: date, months: int) -> date:
    """Añade N meses a una fecha, retornando la fecha exacta + N meses (mismo día si posible, último del mes si no)."""
    new_month = d.month + months
    new_year = d.year + (new_month - 1) // 12
    new_month = ((new_month - 1) % 12) + 1
    try:
        return date(new_year, new_month, d.day)
    except ValueError:
        # Día no existe en el mes nuevo, usar último día del mes
        if new_month == 2:
            return date(new_year, 2, 28 if not (new_year % 4 == 0 and (new_year % 100 != 0 or new_year % 400 == 0)) else 29)
        elif new_month in [4, 6, 9, 11]:
            return date(new_year, new_month, 30)
        else:
            return date(new_year, new_month, 31)


# ============================================
# GENERACIÓN PARA UN ENROLLMENT (ONBOARDING)
# ============================================

async def generate_classes_for_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    months_ahead: int = 2,
    from_date: date = None
) -> dict:
    """
    Genera clases para una inscripción específica.

    Genera clases desde `from_date` (o hoy si no se especifica) hasta el final
    del mes actual + `months_ahead` meses completos.

    Ejemplos (con months_ahead=2):
    - from_date = 19 dic 2025 → genera hasta 28 feb 2026 (dic + ene + feb)
    - from_date = 10 ene 2026 → genera hasta 31 mar 2026 (ene + feb + mar)

    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción
        months_ahead: Cuántos meses completos adicionales generar (default: 2)
        from_date: Fecha desde la cual generar (default: hoy)

    Returns:
        dict: Estadísticas de generación
            {
                "created": 16,
                "skipped": 2,
                "errors": [],
                "date_range": {"start": "2025-12-19", "end": "2026-02-28"}
            }
    """
    # Fecha de inicio por defecto: hoy
    if from_date is None:
        from_date = date.today()

    # Obtener enrollment y validar
    enrollment = await db.get(Enrollment, enrollment_id)

    if not enrollment:
        logger.warning(f"generate_classes_for_enrollment: enrollment {enrollment_id} no existe")
        return {"error": "Enrollment no existe", "created": 0, "skipped": 0, "errors": []}

    if enrollment.status != EnrollmentStatus.ACTIVE:
        logger.warning(f"generate_classes_for_enrollment: enrollment {enrollment_id} inactivo (status={enrollment.status})")
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

    stats = {"created": 0, "skipped": 0, "errors": [], "schedules_processed": 0}

    # Para cada Schedule, generar clases
    for schedule in schedules:
        result = await _generate_classes_for_schedule(
            db, schedule, enrollment, months_ahead, from_date
        )
        stats["created"] += result["created"]
        stats["skipped"] += result["skipped"]
        stats["errors"].extend(result["errors"])
        stats["schedules_processed"] += 1
        
        if "date_range" not in stats and "date_range" in result:
            stats["date_range"] = result["date_range"]

    await db.commit()
    return stats


# ============================================
# GENERACIÓN PARA UN SCHEDULE ESPECÍFICO
# ============================================

async def _generate_classes_for_schedule(
    db: AsyncSession,
    schedule: Schedule,
    enrollment: Enrollment,
    months_ahead: int,
    from_date: date
) -> dict:
    """
    Genera clases para un horario específico (función interna).

    Args:
        db: Sesión de base de datos
        schedule: Horario desde el cual generar
        enrollment: Inscripción asociada
        months_ahead: Cuántos meses completos adicionales generar
        from_date: Fecha base desde la cual calcular

    Returns:
        dict: Estadísticas {created, skipped, errors, date_range}
    """
    stats = {"created": 0, "skipped": 0, "errors": []}

    # BUG FIX: Respetar valid_from del schedule.
    # Si el alumno se inscribió DESPUÉS de from_date, no generar clases
    # anteriores a su inscripción.
    start_date = max(from_date, schedule.valid_from)

    # Fecha final: último día del mes actual + months_ahead meses completos
    # Ejemplo: start_date = 19 dic, months_ahead = 2 → end_date = 28 feb
    end_date = add_months(start_date, months_ahead)

    # Si hay valid_until en el schedule, usar el menor
    if schedule.valid_until:
        end_date = min(end_date, schedule.valid_until)

    stats["date_range"] = {"start": str(start_date), "end": str(end_date)}

    if end_date < start_date:
        msg = f"Rango inválido para schedule {schedule.id}: end_date {end_date} < start_date {start_date}"
        stats["errors"].append(msg)
        logger.warning(msg)
        return stats

    # Obtener día de la semana objetivo (0=Lunes, 6=Domingo)
    target_weekday = DAY_MAP[schedule.day]

    # Encontrar el primer día que coincida con el día de la semana del Schedule
    current_date = start_date
    days_searched = 0
    while current_date.weekday() != target_weekday:
        current_date += timedelta(days=1)
        days_searched += 1
        
        # Protección: si no encontramos el día en 7 días, hay un error
        if days_searched > 7:
            stats["errors"].append(
                f"No se pudo encontrar {schedule.day} desde {start_date}"
            )
            return stats

    # Generar clases semana por semana
    classes_to_insert = []
    while current_date <= end_date:
        # Verificar si es feriado
        if is_holiday(current_date):
            stats["skipped"] += 1
            current_date += timedelta(weeks=1)
            continue

        classes_to_insert.append({
            'schedule_id': schedule.id,
            'enrollment_id': enrollment.id,
            'teacher_id': schedule.teacher_id,
            'date': current_date,
            'time': schedule.time,
            'duration': schedule.duration,
            'status': ClassStatus.SCHEDULED,
            'type': ClassType.REGULAR,
            'format': enrollment.format
        })

        # Avanzar una semana
        current_date += timedelta(weeks=1)

    # Insertar clases en bulk con ON CONFLICT DO NOTHING
    if classes_to_insert:
        try:
            stmt = insert(Class).values(classes_to_insert)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=['enrollment_id', 'date', 'time', 'type']
            )
            result = await db.execute(stmt)
            stats["created"] = result.rowcount
        except Exception as e:
            stats["errors"].append(f"Error al insertar clases: {str(e)}")

    return stats


# ============================================
# JOB MENSUAL AUTOMÁTICO
# ============================================

async def generate_monthly_classes(db: AsyncSession) -> dict:
    """
    Job mensual: Genera clases para todos los enrollments activos.

    Ejecuta automáticamente día 10 de cada mes a las 2:00 AM.
    Genera clases desde hoy hasta fin del mes actual + 2 meses.

    Args:
        db: Sesión de base de datos

    Returns:
        dict: Estadísticas de generación
    """
    # Obtener todos los enrollments activos
    result = await db.execute(
        select(Enrollment).where(
            Enrollment.status == EnrollmentStatus.ACTIVE
        )
    )
    enrollments = result.scalars().all()

    logger.info(f"generate_monthly_classes: procesando {len(enrollments)} enrollments")

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
            months_ahead=2,  # Mes actual + 2 meses completos = 3 meses total
            from_date=date.today()
        )

        if "error" not in result:
            total_stats["created"] += result["created"]
            total_stats["skipped"] += result["skipped"]
            total_stats["errors"].extend(result.get("errors", []))
            total_stats["enrollments_processed"] += 1
            logger.info(f"generate_monthly_classes: enrollment {enrollment.id} -> created {result['created']} skipped {result['skipped']}")
        else:
            total_stats["errors"].append(
                f"Enrollment {enrollment.id}: {result['error']}"
            )
            logger.warning(f"generate_monthly_classes: enrollment {enrollment.id} error {result['error']}")

    await db.commit()
    return total_stats


# ============================================
# REGENERAR CLASES MANUALMENTE (FRONTEND)
# ============================================

async def regenerate_classes_manual(
    db: AsyncSession,
    from_date: date,
    teacher_id: int
) -> dict:
    """
    Regenera clases manualmente desde una fecha específica hacia 3 meses exactos.
    
    VALIDACIONES DE SEGURIDAD (RESET TOTAL):
    1. Elimina TODAS las clases futuras scheduled >= from_date (pierde asistencias futuras)
    2. No toca recuperaciones (solo 'regular' y 'extra')
    3. Solo genera para enrollments ACTIVOS (no suspendidos/retirados)
    4. Respeta vigencia de schedules (valid_from/valid_until)
    5. Transacción TODO-o-NADA (rollback si hay error)
    6. Requiere conexión a backend (backend debe estar activo)
    
    RANGO DE FECHAS:
    - Permite seleccionar hasta 1 mes atrás desde hoy
    - Genera exactamente 3 meses desde la fecha seleccionada
    - Ejemplo: Si seleccionas 1-mar, genera hasta 1-jun
    
    FLUJO:
    - Usuario selecciona fecha inicio (puede ser 1 mes atrás o más adelante)
    - Se eliminan TODAS las clases scheduled >= from_date (reset total)
    - Se generan clases nuevas según schedules activos desde from_date
    
    Args:
        db: Sesión de base de datos (requiere backend activo)
        from_date: Fecha inicial para regeneración (YYYY-MM-DD)
        teacher_id: ID del profesor (para filtrar sus enrollments)
    
    Returns:
        dict: Estadísticas con validaciones y resultados
        {
            "success": bool,
            "message": str,
            "stats": {
                "enrollments_processed": int,
                "classes_deleted": int,
                "classes_created": int,
                "skipped": int,
                "errors": [str]
            },
            "validation_warnings": [str]
        }
    """
    stats = {
        "enrollments_processed": 0,
        "classes_deleted": 0,
        "classes_created": 0,
        "skipped": 0,
        "errors": []
    }
    warnings = []
    
    try:
        # ====== VALIDACIÓN 1: Verificar fecha ======
        today = date.today()
        min_date = today - timedelta(days=30)  # Permite hasta 1 mes atrás
        
        if from_date < min_date:
            return {
                "success": False,
                "message": f"La fecha no puede ser anterior a {min_date}",
                "stats": stats,
                "validation_warnings": []
            }
        
        # ====== CALCULAR RANGO: exactamente 3 meses ======
        end_date = add_months(from_date, 3)
        
        # ====== OBTENER ENROLLMENTS DEL PROFESOR (SOLO ACTIVOS) ======
        result = await db.execute(
            select(Enrollment).where(
                and_(
                    Enrollment.teacher_id == teacher_id,
                    Enrollment.status == EnrollmentStatus.ACTIVE
                )
            )
        )
        enrollments = result.scalars().all()
        
        if not enrollments:
            return {
                "success": False,
                "message": "No hay inscripciones activas para este profesor",
                "stats": stats,
                "validation_warnings": []
            }
        
        # ====== PROCESAR CADA ENROLLMENT ======
        for enrollment in enrollments:
            # ====== FASE 1: ELIMINAR CLASES FUTURAS SIN ASISTENCIA (RESET SEGURO) ======
            # BUG FIX: Solo eliminar clases que NO tienen asistencia registrada.
            # Las clases con asistencia ya marcada se preservan y luego son
            # saltadas como duplicados en la regeneración.
            classes_with_attendance_subq = (
                select(Attendance.class_id).where(
                    Attendance.class_id == Class.id
                ).correlate(Class).exists()
            )

            result = await db.execute(
                delete(Class).where(
                    and_(
                        Class.enrollment_id == enrollment.id,
                        Class.date >= from_date,
                        Class.date <= end_date,
                        Class.status == ClassStatus.SCHEDULED,
                        Class.type != ClassType.RECOVERY,  # NO tocar recuperaciones
                        ~classes_with_attendance_subq       # NO tocar clases con asistencia
                    )
                )
            )
            stats["classes_deleted"] += result.rowcount
            
            # ====== FASE 2: GENERAR NUEVAS CLASES ======
            result = await generate_classes_for_enrollment(
                db,
                enrollment.id,
                months_ahead=3,  # Exactamente 3 meses
                from_date=from_date
            )
            
            if "error" not in result:
                stats["classes_created"] += result["created"]
                stats["skipped"] += result["skipped"]
                stats["errors"].extend(result.get("errors", []))
                stats["enrollments_processed"] += 1
            else:
                warnings.append(
                    f"Enrollment {enrollment.id}: {result['error']}"
                )
        
        await db.commit()
        
        return {
            "success": True,
            "message": f"Regeneración completada: {stats['classes_created']} clases creadas, {stats['classes_deleted']} eliminadas",
            "stats": stats,
            "validation_warnings": warnings
        }
        
    except MultipleResultsFound as mr:
        await db.rollback()
        # error específico para filas múltiples
        stats["errors"].append(f"MultipleResultsFound: {mr}")
        return {
            "success": False,
            "message": f"Error en regeneración (filas múltiples): {mr}",
            "stats": stats,
            "validation_warnings": warnings
        }
    except Exception as e:
        await db.rollback()
        import traceback
        tb = traceback.format_exc()
        stats["errors"].append(f"Error crítico: {str(e)}")
        return {
            "success": False,
            "message": f"Error en regeneración: {str(e)}\n{tb}",
            "stats": stats,
            "validation_warnings": warnings
        }

# ============================================
# ELIMINAR CLASES FUTURAS (CAMBIO DE HORARIO)
# ============================================

async def delete_future_classes_for_schedule(
    db: AsyncSession,
    schedule_id: int,
    from_date: date
) -> int:
    """
    ELIMINA (físicamente) todas las clases futuras de un horario desde una fecha.

    Usado al cambiar de horario. Las clases se eliminan de la BD, NO se cancelan.

    IMPORTANTE: Solo elimina clases con status='scheduled' (no las completadas).

    Args:
        db: Sesión de base de datos
        schedule_id: ID del horario que cambió
        from_date: Fecha desde la cual eliminar (inclusiva)

    Returns:
        int: Cantidad de clases eliminadas
    """
    result = await db.execute(
        delete(Class).where(
            and_(
                Class.schedule_id == schedule_id,
                Class.date >= from_date,
                Class.status == ClassStatus.SCHEDULED
            )
        )
    )
    await db.commit()
    return result.rowcount


# ============================================
# CANCELAR CLASES FUTURAS (SUSPENSIÓN/RETIRO)
# ============================================

async def cancel_future_classes_for_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    from_date: date
) -> int:
    """
    CANCELA clases futuras de una inscripción desde una fecha.

    Usado al suspender o retirar un alumno. Las clases se CANCELAN (status='cancelled'),
    NO se eliminan. Se mantienen en la BD para histórico.

    IMPORTANTE: Solo cancela clases con status='scheduled' (no las completadas).

    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción
        from_date: Fecha desde la cual cancelar (inclusiva)

    Returns:
        int: Cantidad de clases canceladas
    """
    # Actualizar status a 'cancelled' para clases futuras scheduled
    result = await db.execute(
        update(Class).where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.date >= from_date,
                Class.status == ClassStatus.SCHEDULED
            )
        ).values(status=ClassStatus.CANCELLED)
    )
    await db.commit()
    return result.rowcount
