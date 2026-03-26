"""
CRUD operations for Schedule model
"""

import logging
from datetime import date, time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_, or_, func, extract
from sqlalchemy.orm import selectinload
from app.models.schedule import Schedule, DayOfWeek
from app.models.attendance import Attendance
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.class_model import ClassFormat, Class, ClassType, ClassStatus
from app.models.student import Student
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.core.config import settings
from app.jobs.class_generator import generate_classes_for_enrollment

logger = logging.getLogger(__name__)


async def get(db: AsyncSession, schedule_id: int) -> Schedule | None:
    """
    Obtener un horario por ID
    
    Args:
        db: Sesión de base de datos
        schedule_id: ID del horario
    
    Returns:
        Schedule si existe, None si no
    """
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    teacher_id: int,
    skip: int = 0,
    limit: int = 100
) -> list[Schedule]:
    """
    Obtener múltiples horarios de un profesor

    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar

    Returns:
        Lista de Schedules del profesor, ordenados por día y hora
    """
    result = await db.execute(
        select(Schedule)
        .options(selectinload(Schedule.enrollment))  # Cargar enrollment para validaciones
        .where(Schedule.teacher_id == teacher_id)
        .offset(skip)
        .limit(limit)
        .order_by(Schedule.day, Schedule.time)
    )
    return list(result.scalars().all())


async def get_by_enrollment(
    db: AsyncSession,
    enrollment_id: int
) -> list[Schedule]:
    """
    Obtener todos los horarios de una inscripción
    
    Un alumno puede tener múltiples horarios para el mismo instrumento
    Ejemplo: Piano los Lunes 16:00 y Jueves 18:00
    
    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción
    
    Returns:
        Lista de Schedules de la inscripción, ordenados por día y hora
    """
    result = await db.execute(
        select(Schedule)
        .where(Schedule.enrollment_id == enrollment_id)
        .order_by(Schedule.day, Schedule.time)
    )
    return list(result.scalars().all())


async def check_schedule_conflict(
    db: AsyncSession,
    teacher_id: int,
    day: str,
    time: str,
    duration: int,
    exclude_schedule_id: int | None = None,
    enrollment_id: int | None = None
) -> Schedule | None:
    """
    Verificar si existe un conflicto de horario para el profesor

    Un conflicto ocurre cuando:
    - Mismo profesor, mismo día, horarios que se superponen
    - EXCEPCIÓN: Horarios grupales NO generan conflicto entre sí (hasta el límite)

    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
        day: Día de la semana (monday, tuesday, etc)
        time: Hora de inicio (ej: "16:00:00")
        duration: Duración en minutos
        exclude_schedule_id: ID del schedule a excluir (para updates)
        enrollment_id: ID del enrollment (para consultar el formato)

    Returns:
        Schedule conflictivo si existe, None si no hay conflicto
    """
    from datetime import datetime, timedelta

    # DEBUG: Mostrar datos de entrada
    logger.info(f"\n=== VALIDANDO CONFLICTO ===")
    logger.info(f"Teacher ID: {teacher_id}")
    logger.info(f"Día: {day}")
    logger.info(f"Hora: {time} (tipo: {type(time)})")
    logger.info(f"Duración: {duration}")
    logger.info(f"Enrollment ID: {enrollment_id}")

    # Convertir time string a datetime para cálculos
    if isinstance(time, str):
        time_obj = datetime.strptime(time, "%H:%M:%S").time()
    else:
        time_obj = time

    # Calcular hora de fin del nuevo horario
    start_datetime = datetime.combine(datetime.today(), time_obj)
    end_datetime = start_datetime + timedelta(minutes=duration)
    end_time = end_datetime.time()

    logger.info(f"Hora inicio: {time_obj}, Hora fin: {end_time}")

    # Si se pasa enrollment_id, consultar el formato
    current_format = None
    if enrollment_id:
        result = await db.execute(
            select(Enrollment).where(Enrollment.id == enrollment_id)
        )
        enrollment = result.scalar_one_or_none()
        if enrollment:
            current_format = enrollment.format
            logger.info(f"Formato del enrollment: {current_format}")

    # Buscar schedules del mismo profesor y día que estén activos
    # Cargar enrollments para verificar formato
    query = select(Schedule).options(
        selectinload(Schedule.enrollment)
    ).where(
        and_(
            Schedule.teacher_id == teacher_id,
            Schedule.day == day,
            Schedule.active == True,
            or_(
                Schedule.valid_until == None,
                Schedule.valid_until >= datetime.today().date()
            )
        )
    )

    if exclude_schedule_id:
        query = query.where(Schedule.id != exclude_schedule_id)

    result = await db.execute(query)
    existing_schedules = result.scalars().all()

    logger.info(f"Schedules existentes encontrados: {len(existing_schedules)}")

    # Verificar superposición de horarios
    for existing in existing_schedules:
        existing_start = existing.time
        existing_end_datetime = datetime.combine(
            datetime.today(),
            existing_start
        ) + timedelta(minutes=existing.duration)
        existing_end = existing_end_datetime.time()

        logger.info(f"  Comparando con schedule ID {existing.id}: {existing_start} - {existing_end}")
        logger.info(f"  ¿{time_obj} < {existing_end}? {time_obj < existing_end}")
        logger.info(f"  ¿{end_time} > {existing_start}? {end_time > existing_start}")

        # Verificar si los horarios se superponen
        # (nuevo_inicio < existente_fin) AND (nuevo_fin > existente_inicio)
        if time_obj < existing_end and end_time > existing_start:
            # HAY SUPERPOSICIÓN DE TIEMPO
            logger.info(f"  → HAY SUPERPOSICIÓN DE TIEMPO")

            # Si ambos son GRUPALES con el mismo horario EXACTO, NO es conflicto
            # (permitir múltiples alumnos en el mismo slot grupal)
            if current_format == ClassFormat.GROUP and existing.enrollment:
                existing_format = existing.enrollment.format
                logger.info(f"  → Formato actual: {current_format}, Formato existente: {existing_format}")

                # Mismo horario exacto (mismo inicio y duración)
                is_exact_match = (
                    time_obj == existing_start and
                    duration == existing.duration
                )
                logger.info(f"  → ¿Mismo horario exacto? {is_exact_match} (time: {time_obj}=={existing_start}, duration: {duration}=={existing.duration})")

                if existing_format == ClassFormat.GROUP and is_exact_match:
                    logger.info(f"  ✓ Ambos son GRUPALES en el mismo slot - NO es conflicto")
                    continue  # No es conflicto, pueden compartir slot
                else:
                    logger.warning(f"  ✗ No cumplen condiciones para compartir slot")

            # Si llegamos aquí, SÍ es un conflicto
            logger.warning(f"  ¡CONFLICTO DETECTADO CON SCHEDULE {existing.id}!")
            return existing

    logger.info(f"No hay conflictos\n")
    return None


async def create(db: AsyncSession, schedule_data: ScheduleCreate) -> Schedule:
    """
    Crear un horario nuevo (template recurrente)

    Este horario se usará para generar clases automáticamente
    Ejemplo: "Martes 16:00" genera clases todos los martes

    VALIDACIÓN: No permite crear horarios que se superpongan con otros
    del mismo profesor en el mismo día

    Args:
        db: Sesión de base de datos
        schedule_data: Datos del horario a crear

    Returns:
        Schedule creado con id asignado

    Raises:
        ValueError: Si hay conflicto de horarios
    """
    # Verificar conflicto de horarios
    conflict = await check_schedule_conflict(
        db,
        teacher_id=schedule_data.teacher_id,
        day=schedule_data.day,
        time=schedule_data.time,
        duration=schedule_data.duration,
        enrollment_id=schedule_data.enrollment_id
    )

    if conflict:
        from datetime import datetime, timedelta
        conflict_end_time = datetime.combine(
            datetime.today(),
            conflict.time
        ) + timedelta(minutes=conflict.duration)

        raise ValueError(
            f"Conflicto de horario: Ya existe una clase el {conflict.day} "
            f"de {conflict.time.strftime('%H:%M')} a {conflict_end_time.strftime('%H:%M')} "
            f"(Inscripción ID: {conflict.enrollment_id})"
        )

    schedule = Schedule(**schedule_data.model_dump())

    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)

    # 🔥 GENERAR CLASES AUTOMÁTICAMENTE (mes actual + mes siguiente)
    logger.info(f"Generando clases automáticas para enrollment {schedule_data.enrollment_id}...")
    try:
        stats = await generate_classes_for_enrollment(
            db,
            enrollment_id=schedule_data.enrollment_id,
            months_ahead=1,  # Mes actual + 1 mes siguiente = 2 meses
            from_date=schedule.valid_from  # 🔥 USAR VALID_FROM para incluir primera clase
        )
        logger.info(f"Clases generadas: {stats}")
    except Exception as e:
        logger.error(f"Error al generar clases automáticas: {e}")
        # No fallar el create del schedule si la generación falla
        # El schedule queda creado pero sin clases (se pueden generar después)

    return schedule


async def update(
    db: AsyncSession,
    schedule_id: int,
    schedule_data: ScheduleUpdate
) -> Schedule | None:
    """
    Actualizar un horario existente

    VALIDACIÓN: Si se cambia día, hora o duración, verifica que no haya conflictos

    Args:
        db: Sesión de base de datos
        schedule_id: ID del horario a actualizar
        schedule_data: Datos a actualizar (solo campos no None)

    Returns:
        Schedule actualizado si existe, None si no

    Raises:
        ValueError: Si hay conflicto de horarios al actualizar
    """
    # Obtener el horario
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule_obj = result.scalar_one_or_none()

    if not schedule_obj:
        return None

    # Actualizar solo campos que no sean None
    update_data = schedule_data.model_dump(exclude_unset=True)

    # Si se está modificando día, hora o duración, validar conflictos
    if any(field in update_data for field in ['day', 'time', 'duration']):
        new_day = update_data.get('day', schedule_obj.day)
        new_time = update_data.get('time', schedule_obj.time)
        new_duration = update_data.get('duration', schedule_obj.duration)

        conflict = await check_schedule_conflict(
            db,
            teacher_id=schedule_obj.teacher_id,
            day=new_day,
            time=new_time,
            duration=new_duration,
            exclude_schedule_id=schedule_id,
            enrollment_id=schedule_obj.enrollment_id
        )

        if conflict:
            from datetime import datetime, timedelta
            conflict_end_time = datetime.combine(
                datetime.today(),
                conflict.time
            ) + timedelta(minutes=conflict.duration)

            raise ValueError(
                f"Conflicto de horario: Ya existe una clase el {conflict.day} "
                f"de {conflict.time.strftime('%H:%M')} a {conflict_end_time.strftime('%H:%M')} "
                f"(Inscripción ID: {conflict.enrollment_id})"
            )

    for field, value in update_data.items():
        setattr(schedule_obj, field, value)

    await db.commit()
    await db.refresh(schedule_obj)

    return schedule_obj


async def validate_slot_availability(
    db: AsyncSession,
    teacher_id: int,
    day: str,
    time: str,
    format: ClassFormat
) -> dict:
    """
    Validar disponibilidad de un slot (día + hora) para un formato específico

    Reglas:
    1. Un horario puede ser SOLO individual O SOLO grupal (no mezclar)
    2. Horarios grupales tienen límite de MAX_GROUP_CLASS_SIZE alumnos
    3. Horarios individuales tienen límite de 1 alumno

    Args:
        db: Sesión de base de datos
        teacher_id: ID del profesor
        day: Día de la semana (monday, tuesday, etc)
        time: Hora (ej: "15:00:00" o "15:00")
        format: Formato deseado (individual o group)

    Returns:
        dict con:
        - available: bool (True si se puede inscribir)
        - message: str (mensaje para mostrar al usuario)
        - current_students: int (cuántos alumnos hay actualmente)
        - max_students: int (capacidad máxima del slot)
        - existing_format: str | None (formato actual del slot si ya existe)
        - conflict: bool (True si hay conflicto de formato)
    """
    from datetime import datetime

    # Convertir time string a objeto time de Python
    if isinstance(time, str):
        # Normalizar: agregar segundos si faltan
        if len(time) == 5:  # "15:00"
            time = f"{time}:00"
        # Convertir a objeto time
        time_obj = datetime.strptime(time, "%H:%M:%S").time()
    else:
        time_obj = time

    # Buscar schedules en este slot con enrollments cargados
    result = await db.execute(
        select(Schedule)
        .options(selectinload(Schedule.enrollment))
        .join(Enrollment, Schedule.enrollment_id == Enrollment.id)
        .where(
            and_(
                Schedule.teacher_id == teacher_id,
                Schedule.day == day,
                Schedule.time == time_obj,  # Usar objeto time, no string
                Schedule.active == True,
                Enrollment.status == EnrollmentStatus.ACTIVE,  # Solo contar enrollments activos
                or_(
                    Schedule.valid_until == None,
                    Schedule.valid_until >= datetime.today().date()
                )
            )
        )
    )
    schedules = result.scalars().all()

    # Si el slot está vacío, está disponible
    if not schedules:
        max_capacity = settings.MAX_GROUP_CLASS_SIZE if format == ClassFormat.GROUP else 1
        return {
            "available": True,
            "message": "Horario disponible",
            "current_students": 0,
            "max_students": max_capacity,
            "existing_format": None,
            "conflict": False
        }

    # Obtener formato del primer schedule (todos deben tener el mismo)
    # El formato está en el Enrollment, no en Schedule
    first_schedule = schedules[0]

    # Acceder al enrollment que ya fue cargado con selectinload
    if not first_schedule.enrollment:
        # Fallback: cargar enrollment si no está disponible
        result = await db.execute(
            select(Enrollment).where(Enrollment.id == first_schedule.enrollment_id)
        )
        first_enrollment = result.scalar_one()
        existing_format = first_enrollment.format
    else:
        existing_format = first_schedule.enrollment.format

    # Verificar conflicto de formato
    if existing_format != format:
        format_name = "individual" if existing_format == ClassFormat.INDIVIDUAL else "grupal"
        return {
            "available": False,
            "message": f"Este horario es {format_name}",
            "current_students": len(schedules),
            "max_students": settings.MAX_GROUP_CLASS_SIZE if existing_format == ClassFormat.GROUP else 1,
            "existing_format": existing_format.value,
            "conflict": True
        }

    # Mismo formato, verificar capacidad
    current_count = len(schedules)

    if existing_format == ClassFormat.INDIVIDUAL:
        # Individual: máximo 1 alumno
        return {
            "available": False,
            "message": "Horario individual ocupado",
            "current_students": current_count,
            "max_students": 1,
            "existing_format": existing_format.value,
            "conflict": False
        }

    # Grupal: verificar capacidad
    max_capacity = settings.MAX_GROUP_CLASS_SIZE

    if current_count >= max_capacity:
        return {
            "available": False,
            "message": f"Horario Grupal lleno ({current_count}/{max_capacity})",
            "current_students": current_count,
            "max_students": max_capacity,
            "existing_format": existing_format.value,
            "conflict": False
        }

    # Hay espacio disponible en grupal
    return {
        "available": True,
        "message": f"Horario Grupal con {current_count}/{max_capacity} alumnos",
        "current_students": current_count,
        "max_students": max_capacity,
        "existing_format": existing_format.value,
        "conflict": False
    }


async def validate_schedule_removal(
    db: AsyncSession,
    schedule_id: int,
    remove_from: date
) -> dict:
    """
    Valida que se pueda eliminar un horario desde una fecha.
    
    Validaciones:
    1. Schedule existe
    2. No hay clases con asistencia desde remove_from
    3. No hay recuperaciones futuras en ese día/hora
    
    Returns:
        {
            "valid": bool,
            "classes_with_attendance": [...],
            "recovery_conflicts": [...],
            "classes_to_delete": int
        }
    """
    from app.models.attendance import Attendance
    
    # Obtener schedule
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    
    if not schedule:
        return {
            "valid": False,
            "error": "Schedule no encontrado"
        }
    
    # 1. Buscar clases con asistencia desde remove_from
    classes_with_attendance_result = await db.execute(
        select(Class)
        .join(Attendance, Attendance.class_id == Class.id)
        .where(
            and_(
                Class.schedule_id == schedule_id,
                Class.date >= remove_from,
                Class.type == ClassType.REGULAR,
                Class.status == ClassStatus.SCHEDULED
            )
        )
        .order_by(Class.date)
    )
    classes_with_attendance = classes_with_attendance_result.scalars().all()
    
    # 2. Buscar recuperaciones futuras en ese día/hora/enrollment
    # Mapeo de días a PostgreSQL dow (0=Domingo, 1=Lunes...6=Sábado)
    PG_DAY_MAP = {
        'monday': 1,
        'tuesday': 2,
        'wednesday': 3,
        'thursday': 4,
        'friday': 5,
        'saturday': 6,
        'sunday': 0,
    }
    target_dow = PG_DAY_MAP[schedule.day.value]
    
    recovery_conflicts_result = await db.execute(
        select(Class)
        .where(
            and_(
                Class.enrollment_id == schedule.enrollment_id,
                Class.type == ClassType.RECOVERY,
                Class.date >= remove_from,
                Class.time == schedule.time,
                extract('dow', Class.date) == target_dow,
                Class.status == ClassStatus.SCHEDULED
            )
        )
        .order_by(Class.date)
    )
    recovery_conflicts = recovery_conflicts_result.scalars().all()
    
    # 3. Contar clases que SE ELIMINARÍAN
    classes_to_delete_result = await db.execute(
        select(func.count(Class.id))
        .where(
            and_(
                Class.schedule_id == schedule_id,
                Class.date >= remove_from,
                Class.type == ClassType.REGULAR,
                Class.status == ClassStatus.SCHEDULED
            )
        )
    )
    classes_to_delete = classes_to_delete_result.scalar() or 0
    
    # Determinar si es válido
    valid = (
        len(classes_with_attendance) == 0 and
        len(recovery_conflicts) == 0
    )
    
    return {
        "valid": valid,
        "classes_with_attendance": [
            {
                "class_id": cls.id,
                "date": cls.date,
                "time": cls.time
            }
            for cls in classes_with_attendance
        ],
        "recovery_conflicts": [
            {
                "class_id": cls.id,
                "date": cls.date,
                "time": cls.time
            }
            for cls in recovery_conflicts
        ],
        "classes_to_delete": classes_to_delete
    }


async def remove_schedule_with_history(
    db: AsyncSession,
    schedule_id: int,
    remove_from: date
) -> dict:
    """
    Elimina un horario CON histórico (soft-delete).
    
    Flujo:
    1. Validar que se puede eliminar
    2. Eliminar clases regulares scheduled desde remove_from
    3. Marcar schedule: valid_until=remove_from, active=False
    4. NO eliminar físicamente el schedule
    
    Transacción atómica: Si falla cualquier paso → rollback
    
    Returns:
        {
            "schedule_id": int,
            "classes_deleted": int,
            "valid_until": date,
            "message": str
        }
    
    Raises:
        ValueError: Si hay conflictos que impiden la eliminación
    """
    
    # Validar
    validation = await validate_schedule_removal(db, schedule_id, remove_from)
    
    if not validation.get("valid"):
        # Formatear errores
        errors = []
        
        if validation.get("classes_with_attendance"):
            dates = [c["date"].strftime('%d-%b') for c in validation["classes_with_attendance"][:3]]
            if len(validation["classes_with_attendance"]) > 3:
                dates.append(f"y {len(validation['classes_with_attendance']) - 3} más")
            errors.append(f"Clases con asistencia: {', '.join(dates)}")
        
        if validation.get("recovery_conflicts"):
            dates = [c["date"].strftime('%d-%b') for c in validation["recovery_conflicts"][:3]]
            if len(validation["recovery_conflicts"]) > 3:
                dates.append(f"y {len(validation['recovery_conflicts']) - 3} más")
            errors.append(f"Recuperaciones en conflicto: {', '.join(dates)}")
        
        if validation.get("error"):
            errors.append(validation["error"])
        
        raise ValueError(". ".join(errors))
    
    # Obtener schedule
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one()
    
    # Eliminar clases regulares scheduled desde remove_from
    delete_result = await db.execute(
        delete(Class).where(
            and_(
                Class.schedule_id == schedule_id,
                Class.date >= remove_from,
                Class.type == ClassType.REGULAR,
                Class.status == ClassStatus.SCHEDULED
            )
        )
    )
    classes_deleted = delete_result.rowcount
    
    # Marcar schedule como inactivo (SOFT-DELETE)
    schedule.valid_until = remove_from
    schedule.active = False
    
    await db.commit()
    await db.refresh(schedule)
    
    return {
        "schedule_id": schedule.id,
        "classes_deleted": classes_deleted,
        "valid_until": schedule.valid_until,
        "message": f"Horario eliminado exitosamente. Se eliminaron {classes_deleted} clases futuras."
    }


async def remove(db: AsyncSession, schedule_id: int) -> bool:
    """
    Eliminar un horario (eliminación física)

    IMPORTANTE: Esto NO elimina las clases ya generadas
    Solo evita que se generen nuevas clases en el futuro

    Args:
        db: Sesión de base de datos
        schedule_id: ID del horario a eliminar

    Returns:
        True si se eliminó correctamente, False si no existe
    """
    # Obtener el horario
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        return False

    # Eliminar físicamente (las clases ya creadas permanecen)
    await db.delete(schedule)
    await db.commit()

    return True

# ========================================
# PASO 4: VALIDACIÓN DE DISPONIBILIDAD
# ========================================

# Mapeo de días a números (0=Lunes, 6=Domingo)
DAY_TO_NUM = {
    'monday': 0,
    'tuesday': 1,
    'wednesday': 2,
    'thursday': 3,
    'friday': 4,
    'saturday': 5,
    'sunday': 6
}


async def check_schedule_availability_dates(
    db: AsyncSession,
    day: str,
    time_str: str,
    teacher_id: int,
    from_date: date,
    to_date: date | None = None,
    exclude_enrollment_id: int | None = None
) -> list[dict]:
    """
    Verifica si un horario está disponible en un rango de fechas.

    Retorna lista de conflictos (clases que ocupan ese horario):
    - Clases regulares del mismo día/hora
    - Clases de recuperación en ese día/hora específico
    - Solo clases con status='scheduled' (las que realmente ocupan el horario)
    - Solo enrollments activos

    Args:
        day: Día de la semana (monday-sunday)
        time_str: Hora en formato HH:MM o HH:MM:SS
        teacher_id: ID del profesor
        from_date: Fecha inicial del rango
        to_date: Fecha final del rango (default: fin de año)
        exclude_enrollment_id: Opcional, excluir clases de este enrollment

    Returns:
        Lista de conflictos: [{"date": date, "type": str, "student_id": int, "student_name": str}]
    """
    from datetime import time as time_type

    if not to_date:
        # Default: hasta fin de año
        to_date = date(from_date.year, 12, 31)

    day_num = DAY_TO_NUM.get(day.lower())
    if day_num is None:
        return []

    # Convertir time string a time object
    if isinstance(time_str, str):
        time_obj = time_type.fromisoformat(time_str)
    else:
        time_obj = time_str

    # Buscar clases que REALMENTE ocupan el horario:
    # - Classes con time == time_obj
    # - Classes con date en rango [from_date, to_date]
    # - Classes con día de semana == day_num
    # - Classes con status == 'scheduled' (las únicas que ocupan horario)
    # - Classes con enrollment.status == 'active' (enrollments activos)
    # - Classes con enrollment_id != exclude_enrollment_id (si se especifica)
    
    query = (
        select(Class, Student)
        .join(Enrollment, Class.enrollment_id == Enrollment.id)
        .join(Student, Enrollment.student_id == Student.id)
        .where(
            and_(
                Class.teacher_id == teacher_id,
                Class.time == time_obj,
                Class.date >= from_date,
                Class.date <= to_date,
                Class.status == ClassStatus.SCHEDULED,  # ✅ Solo clases scheduled
                Enrollment.status == EnrollmentStatus.ACTIVE,  # ✅ Solo enrollments activos
                extract('dow', Class.date) == day_num
            )
        )
    )
    
    # Excluir clases del enrollment que se está reactivando
    if exclude_enrollment_id is not None:
        query = query.where(Class.enrollment_id != exclude_enrollment_id)
    
    result = await db.execute(query)
    conflicts = result.all()

    conflict_list = []
    for cls, student in conflicts:
        conflict_list.append({
            "date": cls.date,
            "type": cls.type.value,
            "student_id": student.id,
            "student_name": student.name
        })

    return conflict_list


async def change_schedule(
    db: AsyncSession,
    schedule_id: int,
    new_day: DayOfWeek,
    new_time: time,
    change_from: date
) -> dict:
    """
    Cambia el horario de un alumno de forma atómica.

    Flujo:
    1. Obtener schedule antiguo y su enrollment
    2. Validar que nuevo día/hora no es igual al actual
    3. Validar que no haya clases con asistencia desde change_from → error bloqueante
    4. Validar que no haya recuperaciones del mismo alumno que caigan en nuevo día/hora → error bloqueante
    5. Eliminar clases type='regular' + status='scheduled' desde change_from del schedule antiguo
    6. Marcar schedule antiguo: valid_until=change_from, active=false
    7. Crear nuevo schedule: valid_from=change_from, active=true (mismo enrollment, teacher, duration)
    8. Generar clases desde change_from para el nuevo schedule
    9. Commit. Si falla cualquier paso → rollback automático.

    Returns:
        dict con old_schedule_id, new_schedule_id, classes_deleted, classes_generated

    Raises:
        ValueError: Si nuevo día/hora es igual al actual
        ValueError: Si hay clases con asistencia (incluye fechas específicas en el mensaje)
        ValueError: Si hay recuperaciones en conflicto (incluye fechas específicas en el mensaje)
    """
    # 1. Obtener schedule antiguo
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    old_schedule = result.scalar_one_or_none()
    if not old_schedule:
        raise ValueError("Schedule no encontrado")

    # 2. Validar que nuevo día/hora es diferente
    if old_schedule.day == new_day and old_schedule.time == new_time:
        raise ValueError("El nuevo horario es igual al actual")

    enrollment_id = old_schedule.enrollment_id

    # 3. Validar clases con asistencia desde change_from
    # "tiene asistencia" = existe registro en Attendance para esa clase
    result = await db.execute(
        select(Class)
        .join(Attendance, Attendance.class_id == Class.id)
        .where(
            and_(
                Class.schedule_id == schedule_id,
                Class.date >= change_from,
                Class.type == ClassType.REGULAR,
                Class.status == ClassStatus.SCHEDULED
            )
        )
        .order_by(Class.date)
    )
    classes_with_attendance = result.scalars().all()

    if classes_with_attendance:
        dates_str = ", ".join(
            [c.date.strftime('%d-%b') for c in classes_with_attendance[:5]]
        )
        if len(classes_with_attendance) > 5:
            dates_str += f" (y {len(classes_with_attendance) - 5} más)"
        raise ValueError(
            f"No se puede cambiar el horario. Clases con asistencia marcada: {dates_str}. "
            f"Elimina las asistencias o ajusta la fecha de cambio."
        )

    # 4. Validar recuperaciones que caigan en nuevo día/hora
    # Las recuperaciones tienen schedule_id = NULL, buscar por enrollment_id
    # Un conflicto ocurre si: la fecha de la recuperación es el mismo día de semana
    # que new_day Y la hora es new_time
    #
    # Mapeo de DayOfWeek a número (PostgreSQL: dow 0=Domingo, 1=Lunes...6=Sábado)
    PG_DAY_MAP = {
        'monday': 1,
        'tuesday': 2,
        'wednesday': 3,
        'thursday': 4,
        'friday': 5,
        'saturday': 6,
        'sunday': 0,
    }
    target_dow = PG_DAY_MAP[new_day.value]

    result = await db.execute(
        select(Class).where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.type == ClassType.RECOVERY,
                Class.date >= change_from,
                Class.time == new_time,
                extract('dow', Class.date) == target_dow
            )
        )
        .order_by(Class.date)
    )
    recovery_conflicts = result.scalars().all()

    if recovery_conflicts:
        dates_str = ", ".join(
            [c.date.strftime('%d-%b') for c in recovery_conflicts[:5]]
        )
        if len(recovery_conflicts) > 5:
            dates_str += f" (y {len(recovery_conflicts) - 5} más)"
        raise ValueError(
            f"No se puede cambiar al horario {new_day.value} {new_time.strftime('%H:%M')}. "
            f"Hay recuperaciones en ese horario: {dates_str}. "
            f"Mueve o cancela las recuperaciones primero."
        )

    # 5. Eliminar clases regulares + scheduled desde change_from
    result = await db.execute(
        select(Class).where(
            and_(
                Class.schedule_id == schedule_id,
                Class.date >= change_from,
                Class.type == ClassType.REGULAR,
                Class.status == ClassStatus.SCHEDULED
            )
        )
    )
    classes_to_delete = result.scalars().all()
    classes_deleted = len(classes_to_delete)

    for cls in classes_to_delete:
        await db.delete(cls)

    # 6. Marcar schedule antiguo como histórico
    old_schedule.valid_until = change_from
    old_schedule.active = False

    # 7. Crear nuevo schedule (copia datos del antiguo excepto vigencia y estado)
    new_schedule = Schedule(
        enrollment_id=old_schedule.enrollment_id,
        teacher_id=old_schedule.teacher_id,
        day=new_day,
        time=new_time,
        duration=old_schedule.duration,
        valid_from=change_from,
        valid_until=None,  # Indefinido
        active=True
    )
    db.add(new_schedule)
    await db.flush()  # Para obtener el ID del nuevo schedule

    # 8. Generar clases desde change_from
    # Requerimiento: siempre generar hasta hoy + 2 meses, independientemente de change_from
    from datetime import date as date_type, timedelta
    
    today = date_type.today()
    # Calcular primer día de hoy + 2 meses
    target_month = today.month + 2
    target_year = today.year
    if target_month > 12:
        target_month -= 12
        target_year += 1
    target_end = date_type(target_year, target_month, 1)
    
    if change_from < today:
        # Calcular cuántos meses se necesitan desde change_from para llegar a target_end
        years_diff = target_end.year - change_from.year
        months_diff = target_end.month - change_from.month
        days_diff = target_end.day - change_from.day
        months_needed = years_diff * 12 + months_diff + (1 if days_diff > 0 else 0)
        months_ahead = max(months_needed, 2)
    else:
        # change_from es futuro o hoy: 2 meses es suficiente
        months_ahead = 2
    
    stats = await generate_classes_for_enrollment(
        db,
        enrollment_id=enrollment_id,
        months_ahead=months_ahead,
        from_date=change_from
    )
    classes_generated = stats.get("created", 0)

    # 9. Commit
    await db.commit()

    return {
        "old_schedule_id": schedule_id,
        "new_schedule_id": new_schedule.id,
        "classes_deleted": classes_deleted,
        "classes_generated": classes_generated,
    }
