"""
Enrollments endpoints - CRUD + suspend/reactivate/withdraw

Endpoints completos para gestionar inscripciones incluyendo:
- CRUD básico
- Suspensión (elimina clases futuras)
- Reactivación (valida horario y genera clases)
- Retiro definitivo
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from typing import Optional
import re
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.crud import enrollment, student, instrument
from app.models.teacher import Teacher
from app.api.v1.websocket import notify_data_change
from sqlalchemy import select, and_, or_
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentUpdate,
    EnrollmentResponse,
    EnrollmentSuspendRequest,
    EnrollmentReactivateRequest,
    EnrollmentSuspendResponse,
    EnrollmentReactivateResponse,
)
from app.schemas.suspension import (
    SuspendEnrollmentRequest,
    ReactivateEnrollmentRequest,
)
from app.jobs.class_generator import generate_classes_for_enrollment
from app.models.schedule import Schedule
from app.models.enrollment import EnrollmentStatus
from sqlalchemy import update as sa_update

router = APIRouter()


# ========================================
# CRUD BÁSICO
# ========================================

@router.get("/", response_model=list[EnrollmentResponse])
async def list_enrollments(
    skip: int = Query(0, ge=0, description="Registros a saltar"),
    limit: int = Query(100, ge=1, le=100, description="Máximo de registros"),
    teacher_id: int | None = Query(None, description="ID del profesor para filtrar inscripciones"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Listar todas las inscripciones del profesor o de un profesor específico en la misma organización"""
    if teacher_id is not None:
        if current_teacher.organization_id:
            teacher_obj = await db.get(Teacher, teacher_id)
            if not teacher_obj or teacher_obj.organization_id != current_teacher.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes permiso para ver las inscripciones de este profesor"
                )
        elif teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver las inscripciones de otro profesor"
            )
        target_teacher_id = teacher_id
    else:
        target_teacher_id = current_teacher.id

    enrollments = await enrollment.get_multi(
        db,
        teacher_id=target_teacher_id,
        skip=skip,
        limit=limit
    )
    return enrollments


@router.post("/", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    enrollment_data: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Crear una inscripción nueva"""
    # Validar que el alumno existe y pertenece al profesor
    student_obj = await student.get(db, enrollment_data.student_id)
    
    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Alumno {enrollment_data.student_id} no encontrado"
        )

    if current_teacher.organization_id:
        student_teacher = await db.get(Teacher, student_obj.teacher_id)
        if not student_teacher or student_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para inscribir este alumno"
            )

        if enrollment_data.teacher_id is not None:
            selected_teacher = await db.get(Teacher, enrollment_data.teacher_id)
            if not selected_teacher or selected_teacher.organization_id != current_teacher.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes permiso para crear una inscripción para el profesor seleccionado"
                )
        else:
            enrollment_data.teacher_id = student_obj.teacher_id
    else:
        if student_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para inscribir este alumno"
            )
        enrollment_data.teacher_id = current_teacher.id

    # Validar que el instrumento existe y está activo
    instrument_obj = await instrument.get(db, enrollment_data.instrument_id)
    
    if not instrument_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Instrumento {enrollment_data.instrument_id} no encontrado"
        )
    
    if not instrument_obj.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El instrumento '{instrument_obj.name}' no está disponible"
        )
    
    # NO sobrescribir teacher_id aquí: ya fue validado arriba
    # Si el admin seleccionó un profesor válido, se respeta ese teacher_id
    # Si no, ya fue asignado correctamente arriba

    new_enrollment = await enrollment.create(db, enrollment_data)
    await notify_data_change(enrollment_data.teacher_id, "enrollment", "create", new_enrollment.id)
    return new_enrollment


@router.get("/student/{student_id}", response_model=list[EnrollmentResponse])
async def get_student_enrollments(
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Obtener todas las inscripciones de un alumno"""
    # Sin filtrar por active — el admin puede ver inscripciones de alumnos inactivos
    from app.models.student import Student as StudentModel
    raw_result = await db.execute(select(StudentModel).where(StudentModel.id == student_id))
    student_obj = raw_result.scalar_one_or_none()

    if not student_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {student_id} no encontrado"
        )
    
    result = await db.execute(select(Teacher).where(Teacher.id == student_obj.teacher_id))
    student_teacher = result.scalar_one_or_none()
    
    if current_teacher.organization_id:
        if not student_teacher or student_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver este alumno"
            )
    else:
        if student_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver este alumno"
            )
    
    enrollments = await enrollment.get_by_student(db, student_id)

    # Enriquecer con teacher_name
    for e in enrollments:
        if not hasattr(e, 'teacher_name') or e.teacher_name is None:
            t = await db.get(Teacher, e.teacher_id)
            e.teacher_name = t.name if t else None

    return enrollments


@router.get("/{enrollment_id}", response_model=EnrollmentResponse)
async def get_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Obtener una inscripción específica por ID"""
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver esta inscripción"
            )
    
    return enrollment_obj


@router.patch("/{enrollment_id}", response_model=EnrollmentResponse)
async def update_enrollment(
    enrollment_id: int,
    enrollment_data: EnrollmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Actualizar una inscripción existente"""
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para actualizar esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para actualizar esta inscripción"
            )
    
    # Validar nuevo instrumento si se está cambiando
    if enrollment_data.instrument_id is not None:
        instrument_obj = await instrument.get(db, enrollment_data.instrument_id)
        if not instrument_obj:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Instrumento {enrollment_data.instrument_id} no encontrado"
            )
        if not instrument_obj.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El instrumento '{instrument_obj.name}' no está disponible"
            )

    # Validar nuevo profesor si se está cambiando
    if enrollment_data.teacher_id is not None:
        new_teacher = await db.get(Teacher, enrollment_data.teacher_id)
        if not new_teacher:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Profesor {enrollment_data.teacher_id} no encontrado"
            )
        if current_teacher.organization_id:
            if new_teacher.organization_id != current_teacher.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="El profesor seleccionado no pertenece a esta organización"
                )
        else:
            # Profesor independiente no puede reasignar a otro profesor
            if enrollment_data.teacher_id != current_teacher.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tenés permiso para reasignar este enrollment"
                )

    # Detectar si se está reactivando (cambio a ACTIVE)
    # Nota: enrollment_data.status es opcional, puede ser None
    is_reactivating = (
        enrollment_data.status == EnrollmentStatus.ACTIVE and
        enrollment_obj.status != EnrollmentStatus.ACTIVE
    )

    # Detectar cambio de enrolled_date antes de actualizar
    old_enrolled_date = enrollment_obj.enrolled_date
    new_enrolled_date = enrollment_data.enrolled_date  # None si no cambió

    updated_enrollment = await enrollment.update(db, enrollment_id, enrollment_data)

    # Enriquecer con teacher_name e instrument_name para la respuesta
    if updated_enrollment is not None:
        if not hasattr(updated_enrollment, 'teacher_name') or updated_enrollment.teacher_name is None:
            teacher_obj = await db.get(Teacher, updated_enrollment.teacher_id)
            if teacher_obj:
                updated_enrollment.teacher_name = teacher_obj.name
        if not hasattr(updated_enrollment, 'instrument_name') or updated_enrollment.instrument_name is None:
            instrument_obj = await instrument.get(db, updated_enrollment.instrument_id)
            if instrument_obj:
                updated_enrollment.instrument_name = instrument_obj.name

    # Si se reactivó manualmente vía PATCH:
    # 1. Reactivar schedules (asumimos que quiere recuperar su horario anterior)
    # 2. Generar clases
    if is_reactivating:
        print(f"🔄 [UpdateEnrollment] Reactivación manual detectada para Enrollment {enrollment_id}")
        
        # 1. Reactivar sólo los schedules que estaban vigentes al momento de la suspensión
        #    Evitar reactivar schedules históricos anteriores que sólo existen para historial.
        today = date.today()
        await db.execute(
            sa_update(Schedule)
            .where(
                and_(
                    Schedule.enrollment_id == enrollment_id,
                    Schedule.valid_from <= today,
                    or_(
                        Schedule.valid_until.is_(None),
                        Schedule.valid_until >= today,
                    )
                )
            )
            .values(active=True)
        )
        await db.flush() # Asegurar que estén activos antes de generar
        
        # 2. Generar clases
        gen_result = await generate_classes_for_enrollment(
            db, 
            enrollment_id, 
            months_ahead=2,
            from_date=today
        )
        
        if "error" in gen_result:
            print(f"⚠️ [UpdateEnrollment] Error generando clases: {gen_result['error']}")
        else:
            print(f"✅ [UpdateEnrollment] Clases generadas: {gen_result['created']}")
            
        # Commit final (aunque update() ya hizo uno, necesitamos guardar los schedules y classes)
        await db.commit()

    # Si cambió enrolled_date: reconciliar clases
    elif new_enrolled_date and new_enrolled_date != old_enrolled_date:
        from sqlalchemy import delete as sa_delete, and_, select
        from app.models.class_model import Class, ClassStatus, ClassType
        from app.models.attendance import Attendance

        print(f"📅 [UpdateEnrollment] enrolled_date cambió: {old_enrolled_date} → {new_enrolled_date}")

        # Actualizar valid_from de todos los schedules activos para que coincida
        await db.execute(
            sa_update(Schedule)
            .where(
                and_(
                    Schedule.enrollment_id == enrollment_id,
                    Schedule.active == True,
                )
            )
            .values(valid_from=new_enrolled_date)
        )

        if new_enrolled_date > old_enrolled_date:
            # Fecha se movió hacia adelante: eliminar clases sin asistencia antes de la nueva fecha
            # (las que tienen asistencia se mantienen para histórico)
            classes_with_att_subq = (
                select(Attendance.class_id)
                .where(Attendance.class_id == Class.id)
                .correlate(Class)
                .exists()
            )
            del_result = await db.execute(
                sa_delete(Class).where(
                    and_(
                        Class.enrollment_id == enrollment_id,
                        Class.date < new_enrolled_date,
                        Class.type == ClassType.REGULAR,
                        Class.status == ClassStatus.SCHEDULED,
                        ~classes_with_att_subq,
                    )
                )
            )
            print(f"✅ [UpdateEnrollment] {del_result.rowcount} clases eliminadas antes de la nueva fecha")

        # Siempre generar clases faltantes desde la nueva fecha (idempotente: salta las existentes)
        gen_result = await generate_classes_for_enrollment(
            db,
            enrollment_id,
            months_ahead=2,
            from_date=new_enrolled_date,
        )
        print(f"✅ [UpdateEnrollment] Clases generadas tras cambio de fecha: {gen_result.get('created', 0)}")
        await db.commit()

    await notify_data_change(current_teacher.id, "enrollment", "update", updated_enrollment.id)
    return updated_enrollment


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Eliminar una inscripción FÍSICAMENTE (hard-delete)"""
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para eliminar esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para eliminar esta inscripción"
            )
        
    success = await enrollment.remove(db, enrollment_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar la inscripción"
        )
    await notify_data_change(current_teacher.id, "enrollment", "delete", enrollment_id)
    return None


# ========================================
# SUSPENSIÓN / REACTIVACIÓN / RETIRO
# ========================================

@router.put("/{enrollment_id}/suspend", status_code=status.HTTP_200_OK)
async def suspend_enrollment_put(
    enrollment_id: int,
    data: SuspendEnrollmentRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Suspende un enrollment desde una fecha específica.

    Validaciones:
    - Enrollment debe existir y pertenecer al profesor
    - No puede haber clases con asistencia marcada después de suspended_at
    - suspended_until debe ser >= suspended_at (si se especifica)

    Acciones:
    - Cambia status a 'suspended'
    - Marca schedules como is_active=false
    - Elimina clases regulares futuras (mantiene recuperaciones)
    - Crea registro en suspension_history
    """
    from app.crud.enrollment import validate_suspension, suspend_enrollment as suspend_enroll_crud
    from app.models.enrollment import Enrollment, EnrollmentStatus
    from sqlalchemy import select, and_

    # Verificar que enrollment existe
    enroll_result = await db.execute(
        select(Enrollment).where(
            Enrollment.id == enrollment_id
        )
    )
    enrollment_obj = enroll_result.scalar_one_or_none()

    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment no encontrado"
        )

    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para realizar esta acción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para realizar esta acción"
            )

    if enrollment_obj.status == EnrollmentStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enrollment ya está suspendido"
        )

    # Validar fechas
    if data.suspended_until and data.suspended_until < data.suspended_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha 'hasta' debe ser mayor o igual a la fecha 'desde'"
        )

    # Validar conflictos con asistencias
    conflicting_dates = await validate_suspension(
        db,
        enrollment_id,
        data.suspended_at,
        data.suspended_until
    )

    if conflicting_dates:
        # Formatear fechas para mensaje
        dates_str = ", ".join([d.strftime('%d-%b') for d in conflicting_dates[:3]])
        if len(conflicting_dates) > 3:
            dates_str += f" (y {len(conflicting_dates) - 3} más)"

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede suspender. Las siguientes clases tienen asistencia marcada: {dates_str}"
        )

    # Ejecutar suspensión
    try:
        result = await suspend_enroll_crud(
            db,
            enrollment_id,
            data.suspended_at,
            data.suspended_until,
            data.reason
        )

        await notify_data_change(current_teacher.id, "enrollment", "suspend", result.id)
        return {
            "id": result.id,
            "status": result.status.value,
            "suspended_at": result.suspended_at,
            "suspended_until": result.suspended_until,
            "message": "Enrollment suspendido exitosamente"
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al suspender enrollment: {str(e)}"
        )


@router.post("/{enrollment_id}/suspend", response_model=EnrollmentSuspendResponse)
async def suspend_enrollment(
    enrollment_id: int,
    request: EnrollmentSuspendRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Suspender una inscripción temporalmente.
    
    Acciones automáticas:
    - Cambia status → 'suspended'
    - Guarda fecha de suspensión y motivo (opcional)
    - ELIMINA todas las clases futuras (scheduled)
    """
    # Verificar permisos
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para suspender esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para suspender esta inscripción"
            )
    
    # Ejecutar suspensión
    result = await enrollment.suspend(
        db,
        enrollment_id,
        reason=request.reason,
        until_date=request.suspended_until
    )
    
    if "error" in result and result["enrollment"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    suspended = result["enrollment"]
    
    return EnrollmentSuspendResponse(
        enrollment_id=suspended.id,
        status=suspended.status,
        suspended_at=suspended.suspended_at,
        suspended_reason=suspended.suspended_reason,
        classes_deleted=result["classes_deleted"],
        message=f"Inscripción suspendida. Se eliminaron {result['classes_deleted']} clases futuras."
    )


@router.put("/{enrollment_id}/reactivate", status_code=status.HTTP_200_OK)
async def reactivate_enrollment_put(
    enrollment_id: int,
    data: ReactivateEnrollmentRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Reactiva un enrollment suspendido.

    Validaciones:
    - Enrollment debe existir, pertenecer al profesor y estar suspendido
    - Horarios deben estar disponibles desde reactivate_from
    - Debe especificar al menos 1 horario

    Acciones:
    - Cambia status a 'active'
    - Crea nuevos schedules (is_active=true)
    - Genera clases desde reactivate_from
    - Actualiza suspension_history con reactivated_at
    """
    from app.crud.enrollment import reactivate_enrollment as reactivate_enroll_crud
    from app.crud.schedule import check_schedule_availability_dates
    from app.models.enrollment import Enrollment, EnrollmentStatus
    from app.models.class_model import Class
    from sqlalchemy import select, and_

    # Verificar enrollment
    enroll_result = await db.execute(
        select(Enrollment).where(
            Enrollment.id == enrollment_id
        )
    )
    enrollment_obj = enroll_result.scalar_one_or_none()

    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment no encontrado"
        )

    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para realizar esta acción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para realizar esta acción"
            )

    if enrollment_obj.status != EnrollmentStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enrollment no está suspendido"
        )

    if not data.schedules or len(data.schedules) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe especificar al menos un horario"
        )

    # Validar disponibilidad de cada horario
    conflicts_all = []
    for schedule_data in data.schedules:
        conflicts = await check_schedule_availability_dates(
            db=db,
            day=schedule_data.day,
            time_str=schedule_data.time,
            teacher_id=current_teacher.id,
            from_date=data.reactivate_from
        )

        if conflicts:
            conflicts_all.extend(conflicts)

    if conflicts_all:
        # Formatear conflictos
        conflict_msgs = []
        for c in conflicts_all[:3]:
            conflict_msgs.append(
                f"{c['date'].strftime('%d-%b')} - {c['student_name']} ({c['type']})"
            )

        if len(conflicts_all) > 3:
            conflict_msgs.append(f"y {len(conflicts_all) - 3} más")

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Horarios ocupados en: {', '.join(conflict_msgs)}"
        )

    # Ejecutar reactivación
    try:
        # Convertir schedules de Pydantic a dict
        schedules_dict = [
            {
                "day": s.day,
                "time": s.time,
                "duration": s.duration,
                "end_date": s.end_date
            }
            for s in data.schedules
        ]
        
        result = await reactivate_enroll_crud(
            db=db,
            enrollment_id=enrollment_id,
            reactivate_from=data.reactivate_from,
            schedules_data=schedules_dict,
            confirm_delete_classes=data.confirm_delete_classes
        )

        # Si REQUIERE CONFIRMACIÓN
        if not result.get("success") and result.get("requires_confirmation"):
            classes_to_delete = [
                {
                    "class_id": c["class_id"],
                    "date": c["date"].isoformat() if hasattr(c["date"], "isoformat") else str(c["date"]),
                    "day": c["day"],
                    "time": str(c["time"]),
                    "student_name": enrollment_obj.student.name if enrollment_obj.student else "Unknown"
                }
                for c in result.get("validation", {}).get("own_classes_without_attendance", [])
            ]
            
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "requires_confirmation": True,
                    "classes_to_delete": classes_to_delete,
                    "message": f"El alumno tiene {len(classes_to_delete)} clases que serán eliminadas. ¿Continuar?"
                }
            )

        # Si hay error en la reactivación
        if not result.get("success"):
            validation = result.get("validation", {})
            error_msg = result.get("error", "Error desconocido")
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # ÉXITO - Enrollment fue reactivado
        enrollment = result.get("enrollment")
        await notify_data_change(current_teacher.id, "enrollment", "reactivate", enrollment.id)
        return {
            "id": enrollment.id,
            "status": enrollment.status.value,
            "schedules_created": result.get("schedules_created", 0),
            "classes_generated": result.get("classes_generated", 0),
            "classes_deleted": result.get("classes_deleted", 0),
            "message": "Enrollment reactivado exitosamente"
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al reactivar enrollment: {str(e)}"
        )


@router.post("/{enrollment_id}/reactivate", response_model=EnrollmentReactivateResponse)
async def reactivate_enrollment(
    enrollment_id: int,
    request: EnrollmentReactivateRequest = EnrollmentReactivateRequest(),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Reactivar una inscripción suspendida.
    
    Flujo:
    1. Valida disponibilidad del horario anterior (si use_previous_schedule=True)
    2. Si hay conflicto → retorna error con lista de conflictos
    3. Si está disponible → activa y genera clases
    """
    # Verificar permisos
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para reactivar esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para reactivar esta inscripción"
            )
    
    # Ejecutar reactivación
    result = await enrollment.reactivate(
        db,
        enrollment_id,
        use_previous_schedule=request.use_previous_schedule
    )
    
    if "error" in result:
        # Si hay conflictos de horario, retornar los detalles
        if result.get("schedule_conflicts"):
            return EnrollmentReactivateResponse(
                enrollment_id=enrollment_id,
                status=enrollment_obj.status,  # Sigue siendo suspended
                previous_schedule_available=False,
                classes_generated=0,
                schedule_conflicts=result["schedule_conflicts"],
                message="El horario anterior está ocupado. Debes asignar un nuevo horario."
            )
        
        # Otro tipo de error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    reactivated = result["enrollment"]
    
    return EnrollmentReactivateResponse(
        enrollment_id=reactivated.id,
        status=reactivated.status,
        previous_schedule_available=result.get("previous_schedule_available", True),
        classes_generated=result.get("classes_generated", 0),
        schedule_conflicts=[],
        message=f"Inscripción reactivada. Se generaron {result.get('classes_generated', 0)} clases."
    )


@router.post("/{enrollment_id}/withdraw", response_model=EnrollmentSuspendResponse)
async def withdraw_enrollment(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Retirar una inscripción definitivamente.
    
    Acciones automáticas:
    - Cambia status → 'withdrawn'
    - ELIMINA todas las clases futuras
    - Desactiva los schedules
    - Mantiene historial de clases pasadas
    """
    # Verificar permisos
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para retirar esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para retirar esta inscripción"
            )
    
    # Ejecutar retiro
    result = await enrollment.withdraw(db, enrollment_id)
    
    if "error" in result and result["enrollment"] is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    withdrawn = result["enrollment"]
    await notify_data_change(current_teacher.id, "enrollment", "withdraw", withdrawn.id)
    
    return EnrollmentSuspendResponse(
        enrollment_id=withdrawn.id,
        status=withdrawn.status,
        suspended_at=withdrawn.withdrawn_date,  # Usamos suspended_at del response para withdrawn_date
        suspended_reason=None,
        classes_deleted=result["classes_deleted"],
        message=f"Inscripción retirada definitivamente. Se eliminaron {result['classes_deleted']} clases futuras."
    )


class PartialRecoverySession(BaseModel):
    date: str
    time: str
    minutes: int


@router.post("/{enrollment_id}/partial-recovery", response_model=EnrollmentResponse)
async def add_partial_recovery(
    enrollment_id: int,
    session: PartialRecoverySession,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Agregar una sesión parcial de recuperación al enrollment."""
    enrollment_obj = await enrollment.get(db, enrollment_id)
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para modificar esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para modificar esta inscripción"
            )

    date_str = session.date
    time_str = session.time
    minutes = session.minutes

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El campo 'date' debe tener el formato YYYY-MM-DD"
        )
    try:
        date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El campo 'date' no es una fecha válida"
        )

    if not re.fullmatch(r"^(?:[01]\d|2[0-3]):[0-5]\d$", time_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El campo 'time' debe tener el formato HH:MM válido"
        )

    if not isinstance(minutes, int) or minutes < 1 or minutes > 44:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El campo 'minutes' debe ser un entero entre 1 y 44"
        )

    current_sessions = enrollment_obj.partial_sessions or []
    total_minutes = sum((s.get("minutes") or 0) for s in current_sessions) + minutes
    if total_minutes > 45:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El total acumulado supera los 45 minutos"
        )

    for existing in current_sessions:
        if (
            existing.get("date") == date_str and
            existing.get("time") == time_str and
            existing.get("minutes") == minutes
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ya existe una sesión parcial idéntica"
            )

    success = await enrollment.add_partial_session(
        db,
        enrollment_id,
        {"date": date_str, "time": time_str, "minutes": minutes}
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo agregar la sesión parcial"
        )

    updated_enrollment = await enrollment.get(db, enrollment_id)
    await notify_data_change(current_teacher.id, "enrollment", "update", enrollment_id)
    return updated_enrollment


@router.delete("/{enrollment_id}/partial-recovery/{session_index}", response_model=EnrollmentResponse)
async def delete_partial_recovery(
    enrollment_id: int,
    session_index: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Eliminar una sesión parcial de recuperación por índice."""
    enrollment_obj = await enrollment.get(db, enrollment_id)
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para modificar esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para modificar esta inscripción"
            )

    current_sessions = enrollment_obj.partial_sessions or []
    if not current_sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay sesiones parciales"
        )
    if session_index < 0 or session_index >= len(current_sessions):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Índice fuera de rango"
        )

    success = await enrollment.remove_partial_session(db, enrollment_id, session_index)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo eliminar la sesión parcial"
        )

    updated_enrollment = await enrollment.get(db, enrollment_id)
    await notify_data_change(current_teacher.id, "enrollment", "update", enrollment_id)
    return updated_enrollment


@router.delete("/{enrollment_id}/partial-recoveries", response_model=EnrollmentResponse)
async def clear_partial_recoveries(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """Limpiar todas las sesiones parciales de recuperación."""
    enrollment_obj = await enrollment.get(db, enrollment_id)
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para modificar esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para modificar esta inscripción"
            )

    success = await enrollment.clear_partial_sessions(db, enrollment_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudieron limpiar las sesiones parciales"
        )

    updated_enrollment = await enrollment.get(db, enrollment_id)
    await notify_data_change(current_teacher.id, "enrollment", "update", enrollment_id)
    return updated_enrollment


# ========================================
# VERIFICAR DISPONIBILIDAD DE HORARIO
# ========================================

@router.get("/{enrollment_id}/check-schedule", response_model=list[dict])
async def check_schedule_availability(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Verificar si los horarios del enrollment están disponibles.
    
    Útil antes de reactivar para saber si hay conflictos.
    
    Returns:
        Lista de conflictos (vacía si todo está disponible)
    """
    enrollment_obj = await enrollment.get(db, enrollment_id)
    
    if not enrollment_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inscripción {enrollment_id} no encontrada"
        )
    
    if current_teacher.organization_id:
        enrollment_teacher = await db.get(Teacher, enrollment_obj.teacher_id)
        if not enrollment_teacher or enrollment_teacher.organization_id != current_teacher.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver esta inscripción"
            )
    else:
        if enrollment_obj.teacher_id != current_teacher.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver esta inscripción"
            )
    
    conflicts = await enrollment.check_schedule_availability(
        db,
        current_teacher.id,
        enrollment_id
    )
    
    return conflicts
