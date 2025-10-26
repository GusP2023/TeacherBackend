"""
CRUD operations for Schedule model
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from app.models.schedule import Schedule
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.class_model import ClassFormat
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
            months_ahead=1  # Mes actual + 1 mes siguiente = 2 meses
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


async def delete(db: AsyncSession, schedule_id: int) -> bool:
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