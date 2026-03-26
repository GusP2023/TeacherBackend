"""
CRUD operations for Enrollment model - REACTIVACIÓN CON VALIDACIÓN COMPLETA
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, and_, or_, extract
from datetime import date, datetime, time as time_type
from typing import Optional

from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.schedule import Schedule
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.student import Student
from app.models.attendance import Attendance
from app.schemas.enrollment import EnrollmentCreate, EnrollmentUpdate


async def get(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """Obtener una inscripción por ID"""
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    return result.scalar_one_or_none()


async def get_multi(
    db: AsyncSession,
    teacher_id: int,
    skip: int = 0,
    limit: int = 100
) -> list[Enrollment]:
    """Obtener múltiples inscripciones de un profesor"""
    result = await db.execute(
        select(Enrollment)
        .where(Enrollment.teacher_id == teacher_id)
        .offset(skip)
        .limit(limit)
        .order_by(Enrollment.created_at.desc())
    )
    return list(result.scalars().all())


async def get_by_student(db: AsyncSession, student_id: int) -> list[Enrollment]:
    """Obtener todas las inscripciones de un alumno"""
    result = await db.execute(
        select(Enrollment)
        .where(Enrollment.student_id == student_id)
        .order_by(Enrollment.created_at.desc())
    )
    return list(result.scalars().all())


async def create(db: AsyncSession, enrollment_data: EnrollmentCreate) -> Enrollment:
    """Crear una inscripción nueva"""
    enrollment = Enrollment(**enrollment_data.model_dump())
    
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    
    return enrollment


async def update(
    db: AsyncSession,
    enrollment_id: int,
    enrollment_data: EnrollmentUpdate
) -> Enrollment | None:
    """Actualizar una inscripción existente"""
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return None
    
    update_data = enrollment_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(enrollment, field, value)
    
    await db.commit()
    await db.refresh(enrollment)
    
    return enrollment


async def remove(db: AsyncSession, enrollment_id: int) -> bool:
    """Eliminar una inscripción físicamente (hard-delete)"""
    result = await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return False
        
    await db.delete(enrollment)
    await db.commit()
    
    return True


# ========================================
# SUSPENSIÓN
# ========================================

async def suspend(
    db: AsyncSession,
    enrollment_id: int,
    reason: Optional[str] = None,
    until_date: Optional[date] = None
) -> dict:
    """
    Suspender una inscripción temporalmente.
    
    Acciones:
    1. Cambiar status → 'suspended'
    2. Guardar suspended_at con fecha actual
    3. Guardar suspended_reason (opcional)
    4. ELIMINAR todas las clases futuras (scheduled)
    
    Args:
        db: Sesión de base de datos
        enrollment_id: ID de la inscripción a suspender
        reason: Motivo de la suspensión (opcional)
        until_date: Fecha hasta cuándo está suspendido (opcional)
    
    Returns:
        dict con enrollment actualizado y cantidad de clases eliminadas
    """
    # Obtener la inscripción
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return {"error": "Enrollment no encontrado", "enrollment": None, "classes_deleted": 0}
    
    if enrollment.status == EnrollmentStatus.SUSPENDED:
        return {"error": "El enrollment ya está suspendido", "enrollment": enrollment, "classes_deleted": 0}
    
    today = date.today()
    
    # 1. Actualizar estado del enrollment
    enrollment.status = EnrollmentStatus.SUSPENDED
    enrollment.suspended_at = today
    enrollment.suspended_reason = reason
    enrollment.suspended_until = until_date
    
    # 2. ELIMINAR clases futuras (físicamente, no cancelar)
    # Solo eliminar clases con status='scheduled' y fecha >= hoy
    delete_result = await db.execute(
        delete(Class).where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.date >= today,
                Class.status == ClassStatus.SCHEDULED
            )
        )
    )
    classes_deleted = delete_result.rowcount
    
    await db.commit()
    await db.refresh(enrollment)
    
    return {
        "enrollment": enrollment,
        "classes_deleted": classes_deleted
    }


# ========================================
# REACTIVACIÓN - IGUAL QUE CAMBIO DE HORARIO
# ========================================

# Mapeo de días a números (0=Lunes, 6=Domingo) para PostgreSQL
DAY_TO_DOW = {
    'monday': 1,
    'tuesday': 2,
    'wednesday': 3,
    'thursday': 4,
    'friday': 5,
    'saturday': 6,
    'sunday': 0
}


async def validate_reactivation(
    db: AsyncSession,
    enrollment_id: int,
    teacher_id: int,
    reactivate_from: date,
    schedules_data: list[dict]
) -> dict:
    """
    Valida la reactivación de un enrollment con nuevos horarios.
    
    Lógica IGUAL al cambio de horario:
    1. Buscar recuperaciones del alumno que caigan en los nuevos horarios → ERROR BLOQUEANTE
    2. Buscar clases de otros alumnos activos en los nuevos horarios → ERROR BLOQUEANTE
    3. Buscar clases regulares PROPIAS del alumno en los nuevos horarios:
       a. Si tienen asistencia → ERROR BLOQUEANTE
       b. Si no tienen asistencia → RETORNAR para confirmación
    
    Returns:
        {
            "valid": bool,
            "recovery_conflicts": [...],  # Recuperaciones propias que bloquean
            "other_students_conflicts": [...],  # Clases de otros alumnos que bloquean
            "own_classes_without_attendance": [...],  # Clases propias sin asistencia (requieren confirmación)
            "own_classes_with_attendance": [...]  # Clases propias con asistencia (bloquean)
        }
    """
    
    recovery_conflicts = []
    other_students_conflicts = []
    own_classes_without_attendance = []
    own_classes_with_attendance = []
    
    for schedule_data in schedules_data:
        day = schedule_data['day']
        time_str = schedule_data['time']
        
        # Convertir time string a time object
        if isinstance(time_str, str):
            if ':' in time_str:
                parts = time_str.split(':')
                if len(parts) == 2:
                    time_obj = time_type(int(parts[0]), int(parts[1]), 0)
                else:
                    time_obj = time_type(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                time_obj = time_type.fromisoformat(time_str)
        else:
            time_obj = time_str
        
        dow = DAY_TO_DOW[day.lower()]
        
        # 1. Buscar RECUPERACIONES del mismo enrollment que caigan en este horario
        recovery_result = await db.execute(
            select(Class, Student)
            .join(Enrollment, Class.enrollment_id == Enrollment.id)
            .join(Student, Enrollment.student_id == Student.id)
            .where(
                and_(
                    Class.enrollment_id == enrollment_id,
                    Class.type == ClassType.RECOVERY,
                    Class.date >= reactivate_from,
                    Class.time == time_obj,
                    extract('dow', Class.date) == dow
                )
            )
            .order_by(Class.date)
        )
        recoveries = recovery_result.all()
        
        for cls, student in recoveries:
            recovery_conflicts.append({
                "date": cls.date,
                "day": day,
                "time": str(time_obj),
                "student_name": student.name,
                "type": "recovery"
            })
        
        # 2. Buscar clases de OTROS alumnos activos (cualquier tipo)
        other_students_result = await db.execute(
            select(Class, Student)
            .join(Enrollment, Class.enrollment_id == Enrollment.id)
            .join(Student, Enrollment.student_id == Student.id)
            .where(
                and_(
                    Class.teacher_id == teacher_id,
                    Class.enrollment_id != enrollment_id,
                    Class.date >= reactivate_from,
                    Class.time == time_obj,
                    Class.status == ClassStatus.SCHEDULED,
                    Enrollment.status == EnrollmentStatus.ACTIVE,
                    extract('dow', Class.date) == dow
                )
            )
            .order_by(Class.date)
        )
        other_classes = other_students_result.all()
        
        for cls, student in other_classes:
            other_students_conflicts.append({
                "date": cls.date,
                "day": day,
                "time": str(time_obj),
                "student_name": student.name,
                "type": cls.type.value
            })
        
        # 3. Buscar clases REGULARES PROPIAS (del enrollment que se está reactivando)
        own_classes_result = await db.execute(
            select(Class)
            .where(
                and_(
                    Class.enrollment_id == enrollment_id,
                    Class.type == ClassType.REGULAR,
                    Class.date >= reactivate_from,
                    Class.time == time_obj,
                    Class.status == ClassStatus.SCHEDULED,
                    extract('dow', Class.date) == dow
                )
            )
            .order_by(Class.date)
        )
        own_classes = own_classes_result.scalars().all()
        
        for cls in own_classes:
            # Verificar si tiene asistencia
            attendance_result = await db.execute(
                select(Attendance).where(Attendance.class_id == cls.id)
            )
            has_attendance = attendance_result.scalar_one_or_none() is not None
            
            class_data = {
                "class_id": cls.id,
                "date": cls.date,
                "day": day,
                "time": str(time_obj)
            }
            
            if has_attendance:
                own_classes_with_attendance.append(class_data)
            else:
                own_classes_without_attendance.append(class_data)
    
    # Determinar si es válido
    valid = (
        len(recovery_conflicts) == 0 and
        len(other_students_conflicts) == 0 and
        len(own_classes_with_attendance) == 0
    )
    
    return {
        "valid": valid,
        "recovery_conflicts": recovery_conflicts,
        "other_students_conflicts": other_students_conflicts,
        "own_classes_without_attendance": own_classes_without_attendance,
        "own_classes_with_attendance": own_classes_with_attendance
    }


async def reactivate_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    reactivate_from: date,
    schedules_data: list[dict],
    confirm_delete_classes: bool = False
) -> dict:
    """
    Reactiva un enrollment suspendido.

    Transacción atómica que:
    1. Valida conflictos (recuperaciones, otros alumnos, clases propias)
    2. Si hay conflictos bloqueantes → ERROR
    3. Si hay clases propias sin asistencia y NO confirm_delete_classes → RETORNAR PARA CONFIRMACIÓN
    4. Si confirm_delete_classes=True → Eliminar clases propias conflictivas
    5. Actualiza enrollment (status=active, limpia fechas suspensión)
    6. Crea nuevos schedules (active=true)
    7. Genera clases desde reactivate_from
    8. Actualiza suspension_history con reactivated_at
    
    Returns:
        {
            "success": bool,
            "enrollment": Enrollment | None,
            "validation": dict,  # Resultado de validate_reactivation
            "schedules_created": int,
            "classes_generated": int,
            "classes_deleted": int
        }
    """
    from app.models.suspension_history import SuspensionHistory
    from app.jobs.class_generator import generate_classes_for_enrollment

    # Obtener enrollment
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()

    if not enrollment:
        return {"success": False, "error": "Enrollment no encontrado"}

    # Validar conflictos
    validation = await validate_reactivation(
        db=db,
        enrollment_id=enrollment_id,
        teacher_id=enrollment.teacher_id,
        reactivate_from=reactivate_from,
        schedules_data=schedules_data
    )
    
    # Si hay recuperaciones o clases de otros alumnos → ERROR BLOQUEANTE
    if validation["recovery_conflicts"] or validation["other_students_conflicts"]:
        return {
            "success": False,
            "validation": validation,
            "error": "Hay conflictos bloqueantes"
        }
    
    # Si hay clases propias con asistencia → ERROR BLOQUEANTE
    if validation["own_classes_with_attendance"]:
        return {
            "success": False,
            "validation": validation,
            "error": "Hay clases con asistencia que no se pueden eliminar"
        }
    
    # Si hay clases propias sin asistencia y NO se confirmó → REQUIERE CONFIRMACIÓN
    if validation["own_classes_without_attendance"] and not confirm_delete_classes:
        return {
            "success": False,
            "validation": validation,
            "requires_confirmation": True
        }
    
    # AQUÍ SÍ PODEMOS CONTINUAR
    classes_deleted = 0
    
    # Eliminar clases propias conflictivas si las hay
    if validation["own_classes_without_attendance"]:
        class_ids_to_delete = [c["class_id"] for c in validation["own_classes_without_attendance"]]
        delete_result = await db.execute(
            delete(Class).where(Class.id.in_(class_ids_to_delete))
        )
        classes_deleted = delete_result.rowcount
    
    # Actualizar enrollment
    enrollment.status = EnrollmentStatus.ACTIVE
    enrollment.suspended_at = None
    enrollment.suspended_until = None
    enrollment.suspended_reason = None

    # ✅ Desactivar TODOS los schedules antiguos antes de crear nuevos
    await db.execute(
        update(Schedule)
        .where(
            and_(
                Schedule.enrollment_id == enrollment_id,
                Schedule.active == True
            )
        )
        .values(active=False)
    )

    # Crear nuevos schedules
    created_schedules = []
    for schedule_data in schedules_data:
        # Convertir time
        time_val = schedule_data['time']
        if isinstance(time_val, str):
            if ':' in time_val:
                parts = time_val.split(':')
                if len(parts) == 2:
                    time_val = time_type(int(parts[0]), int(parts[1]), 0)
                else:
                    time_val = time_type(int(parts[0]), int(parts[1]), int(parts[2]))
        
        # end_date ya viene convertido por Pydantic
        end_date_val = schedule_data.get('end_date')

        schedule = Schedule(
            enrollment_id=enrollment_id,
            teacher_id=enrollment.teacher_id,
            day=schedule_data['day'],
            time=time_val,
            duration=schedule_data.get('duration', 45),
            valid_from=reactivate_from,
            valid_until=end_date_val,
            active=True
        )
        db.add(schedule)
        await db.flush()
        created_schedules.append(schedule)

    # ✅ Eliminar clases futuras generadas de schedules antiguos
    await db.execute(
        delete(Class).where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.date >= reactivate_from,
                Class.type == ClassType.REGULAR
            )
        )
    )

    # Generar clases desde reactivate_from
    gen_result = await generate_classes_for_enrollment(
        db=db,
        enrollment_id=enrollment_id,
        months_ahead=2,
        from_date=reactivate_from
    )
    classes_generated = gen_result.get("created", 0)

    # Actualizar historial
    history_result = await db.execute(
        select(SuspensionHistory)
        .where(
            and_(
                SuspensionHistory.enrollment_id == enrollment_id,
                SuspensionHistory.reactivated_at.is_(None)
            )
        )
        .order_by(SuspensionHistory.id.desc())
    )
    last_suspension = history_result.scalars().first()

    if last_suspension:
        last_suspension.reactivated_at = reactivate_from

    await db.commit()
    await db.refresh(enrollment)

    return {
        "success": True,
        "enrollment": enrollment,
        "validation": validation,
        "schedules_created": len(created_schedules),
        "classes_generated": classes_generated,
        "classes_deleted": classes_deleted
    }


# ========================================
# FUNCIONES LEGACY (para endpoints antiguos)
# ========================================

async def check_schedule_availability(
    db: AsyncSession,
    teacher_id: int,
    enrollment_id: int
) -> list[dict]:
    """LEGACY - Usar validate_reactivation en su lugar"""
    schedules_result = await db.execute(
        select(Schedule).where(
            and_(
                Schedule.enrollment_id == enrollment_id,
                Schedule.active == True
            )
        )
    )
    schedules = schedules_result.scalars().all()
    
    if not schedules:
        return []
    
    conflicts = []
    
    for schedule in schedules:
        conflict_result = await db.execute(
            select(Schedule, Enrollment, Student)
            .join(Enrollment, Schedule.enrollment_id == Enrollment.id)
            .join(Student, Enrollment.student_id == Student.id)
            .where(
                and_(
                    Schedule.teacher_id == teacher_id,
                    Schedule.day == schedule.day,
                    Schedule.time == schedule.time,
                    Schedule.active == True,
                    Schedule.enrollment_id != enrollment_id,
                    Enrollment.status == EnrollmentStatus.ACTIVE
                )
            )
        )
        conflict = conflict_result.first()
        
        if conflict:
            conflict_schedule, conflict_enrollment, conflict_student = conflict
            conflicts.append({
                "day": schedule.day.value,
                "time": str(schedule.time),
                "is_available": False,
                "conflict_with": conflict_student.name,
                "conflict_enrollment_id": conflict_enrollment.id
            })
    
    return conflicts


async def reactivate(
    db: AsyncSession,
    enrollment_id: int,
    use_previous_schedule: bool = True
) -> dict:
    """LEGACY - Usar reactivate_enrollment en su lugar"""
    from app.jobs.class_generator import generate_classes_for_enrollment
    
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return {"error": "Enrollment no encontrado", "enrollment": None}
    
    if enrollment.status == EnrollmentStatus.ACTIVE:
        return {"error": "El enrollment ya está activo", "enrollment": enrollment}
    
    if enrollment.status == EnrollmentStatus.WITHDRAWN:
        return {"error": "No se puede reactivar un enrollment retirado", "enrollment": enrollment}
    
    conflicts = []
    if use_previous_schedule:
        conflicts = await check_schedule_availability(
            db, enrollment.teacher_id, enrollment_id
        )
        
        if conflicts:
            return {
                "error": "El horario anterior está ocupado",
                "enrollment": enrollment,
                "schedule_conflicts": conflicts,
                "classes_generated": 0
            }
    
    enrollment.status = EnrollmentStatus.ACTIVE
    enrollment.suspended_at = None
    enrollment.suspended_reason = None
    enrollment.suspended_until = None
    
    await db.commit()
    await db.refresh(enrollment)
    
    classes_generated = 0
    if use_previous_schedule:
        gen_result = await generate_classes_for_enrollment(
            db,
            enrollment_id,
            months_ahead=2,
            from_date=date.today()
        )
        classes_generated = gen_result.get("created", 0)
    
    return {
        "enrollment": enrollment,
        "schedule_conflicts": conflicts,
        "classes_generated": classes_generated,
        "previous_schedule_available": len(conflicts) == 0
    }


# ========================================
# RETIRO DEFINITIVO
# ========================================

async def withdraw(
    db: AsyncSession,
    enrollment_id: int
) -> dict:
    """Retirar una inscripción definitivamente."""
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    
    if not enrollment:
        return {"error": "Enrollment no encontrado", "enrollment": None, "classes_deleted": 0}
    
    if enrollment.status == EnrollmentStatus.WITHDRAWN:
        return {"error": "El enrollment ya está retirado", "enrollment": enrollment, "classes_deleted": 0}
    
    today = date.today()
    
    enrollment.status = EnrollmentStatus.WITHDRAWN
    enrollment.withdrawn_date = today
    
    schedules_result = await db.execute(
        select(Schedule).where(Schedule.enrollment_id == enrollment_id)
    )
    for schedule in schedules_result.scalars().all():
        schedule.active = False
    
    delete_result = await db.execute(
        delete(Class).where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.date >= today,
                Class.status == ClassStatus.SCHEDULED
            )
        )
    )
    classes_deleted = delete_result.rowcount
    
    await db.commit()
    await db.refresh(enrollment)
    
    return {
        "enrollment": enrollment,
        "classes_deleted": classes_deleted
    }


# ========================================
# SUSPENSIÓN CON VALIDACIÓN
# ========================================

async def validate_suspension(
    db: AsyncSession,
    enrollment_id: int,
    suspended_at: date,
    suspended_until: date | None
) -> list[date]:
    """Valida que no haya clases con asistencia en el rango de suspensión."""
    end_date = suspended_until if suspended_until else date(9999, 12, 31)

    result = await db.execute(
        select(Class)
        .join(Attendance, Attendance.class_id == Class.id)
        .where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.date > suspended_at,
                Class.date <= end_date
            )
        )
    )
    classes_with_attendance = result.scalars().all()

    return [cls.date for cls in classes_with_attendance]


async def suspend_enrollment(
    db: AsyncSession,
    enrollment_id: int,
    suspended_at: date,
    suspended_until: date | None,
    reason: str | None
) -> Enrollment | None:
    """Suspende un enrollment y elimina clases regulares futuras."""
    from app.models.suspension_history import SuspensionHistory

    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()

    if not enrollment:
        return None

    enrollment.status = EnrollmentStatus.SUSPENDED
    enrollment.suspended_at = suspended_at
    enrollment.suspended_until = suspended_until
    enrollment.suspended_reason = reason

    schedules_result = await db.execute(
        select(Schedule).where(Schedule.enrollment_id == enrollment_id)
    )
    for schedule in schedules_result.scalars().all():
        schedule.active = False

    end_date = suspended_until if suspended_until else date(9999, 12, 31)

    classes_result = await db.execute(
        select(Class).where(
            and_(
                Class.enrollment_id == enrollment_id,
                Class.type == ClassType.REGULAR,
                Class.date > suspended_at,
                Class.date <= end_date
            )
        )
    )
    for cls in classes_result.scalars().all():
        await db.delete(cls)

    history = SuspensionHistory(
        enrollment_id=enrollment_id,
        suspended_at=suspended_at,
        suspended_until=suspended_until,
        reason=reason
    )
    db.add(history)

    await db.commit()
    await db.refresh(enrollment)

    return enrollment
