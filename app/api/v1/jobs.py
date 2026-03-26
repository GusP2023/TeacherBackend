"""
Jobs Endpoints - Generación de clases y tareas automatizadas

Endpoints para ejecutar manualmente los jobs del sistema:
- Generación mensual de clases
- Generación para enrollment específico
- Eliminación de clases futuras al cambiar horario
- Cancelación de clases por suspensión/retiro
"""

from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import log_event, Actions
from app.core.security import get_current_teacher
from app.models.teacher import Teacher
from app.jobs.class_generator import (
    generate_classes_for_enrollment,
    generate_monthly_classes,
    delete_future_classes_for_schedule,
    cancel_future_classes_for_enrollment,
    regenerate_classes_manual
)

router = APIRouter()


# ============================================
# MODELOS DE REQUEST/RESPONSE
# ============================================

class RegenerateClassesRequest(BaseModel):
    """Request para regenerar clases manualmente"""
    from_date: str  # Formato: YYYY-MM-DD
    
    class Config:
        json_schema_extra = {
            "example": {
                "from_date": "2026-02-15"
            }
        }





# ============================================
# GENERACIÓN MANUAL DE CLASES
# ============================================

@router.post("/generate-classes")
async def trigger_monthly_class_generation(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Genera clases del próximo mes para todos los enrollments activos (MANUAL)

    Este endpoint ejecuta manualmente el job mensual que normalmente
    corre automáticamente día 10 de cada mes.

    Útil para:
    - Testing
    - Generación inicial del sistema
    - Re-generar después de cambios masivos

    Returns:
        Estadísticas de generación:
        - created: Clases creadas
        - skipped: Clases saltadas (duplicadas o feriados)
        - enrollments_processed: Cantidad de inscripciones procesadas
        - errors: Lista de errores si ocurrieron
    """
    result = await generate_monthly_classes(db)

    return {
        "message": "Generación mensual completada",
        "stats": result
    }


@router.post("/generate-classes/{enrollment_id}")
async def generate_for_specific_enrollment(
    enrollment_id: int,
    months: int = Query(default=2, ge=1, le=6, description="Meses a generar (1-6)"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Genera clases para una inscripción específica (ONBOARDING)

    Usado principalmente al inscribir un nuevo alumno.
    Genera clases para los próximos N meses desde valid_from del Schedule.

    Args:
        enrollment_id: ID de la inscripción
        months: Cuántos meses generar (default: 2, máximo: 6)

    Returns:
        Estadísticas de generación:
        - created: Clases creadas
        - skipped: Clases saltadas
        - errors: Lista de errores

    Raises:
        400: Si el enrollment no existe o está inactivo
    """
    result = await generate_classes_for_enrollment(db, enrollment_id, months)

    if "error" in result:
        raise HTTPException(
            status_code=400,
            detail=result["error"]
        )

    return {
        "message": f"Clases generadas exitosamente para enrollment {enrollment_id}",
        "enrollment_id": enrollment_id,
        "months_generated": months,
        "created": result["created"],
        "skipped": result["skipped"],
        "errors": result.get("errors", [])
    }


# ============================================
# REGENERACIÓN MANUAL DE CLASES (FRONTEND)
# ============================================

@router.post("/regenerate-classes")
async def regenerate_classes_endpoint(
    http_request: Request,
    request: RegenerateClassesRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Regenera clases manualmente desde una fecha específica hacia 3 meses exactos.
    
    (RESET TOTAL - elimina TODAS las clases futuras scheduled >= from_date)
    
    VALIDACIONES DE SEGURIDAD:
    ✅ Elimina TODAS las clases futuras scheduled (pierde asistencias futuras)
    ✅ No toca recuperaciones (type='recovery')
    ✅ Solo procesa enrollments activos
    ✅ Respeta vigencia de schedules
    ✅ Transacción segura (rollback si hay error)
    
    FLUJO:
    - Usuario selecciona fecha inicio (ej: 2026-03-01)
    - Se eliminan TODAS las clases scheduled >= from_date
    - Se generan clases nuevas exactamente 3 meses: 1-mar → 1-jun
    - Solo se crean clases según schedules activos
    
    Args:
        request: Body contiene from_date en formato YYYY-MM-DD
    
    Returns:
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
    
    Raises:
        400: Formato de fecha inválido
        
    Example:
        POST /api/v1/jobs/regenerate-classes
        Body: { "from_date": "2026-03-01" }
    """
    # Validar formato de fecha
    try:
        from_date_obj = date_type.fromisoformat(request.from_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Formato de fecha inválido: {request.from_date}. Use YYYY-MM-DD"
        )

    # Ejecutar regeneración con manejo adicional de errores
    try:
        result = await regenerate_classes_manual(db, from_date_obj, current_teacher.id)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        # registrar en logs de servidor
        print("[jobs] excepción no capturada en regenerate_classes_manual:\n", tb)
        raise HTTPException(status_code=500, detail=str(exc))

    # Loguear el reset total (exitoso o fallido) — es la operación más destructiva
    stats = result.get("stats", {})
    await log_event(
        db, http_request,
        action=Actions.RESET_TOTAL,
        teacher_id=current_teacher.id,
        success=result.get("success", False),
        detail=(
            f"from_date={request.from_date} | "
            f"deleted={stats.get('classes_deleted', 0)} | "
            f"created={stats.get('classes_created', 0)}"
        ),
    )

    if not result.get("success", False):
        print(f"[jobs] regeneración manual fallida: {result.get('message')}")

    return result


# ============================================
# ELIMINACIÓN DE CLASES (CAMBIO DE HORARIO)
# ============================================

@router.delete("/schedules/{schedule_id}/future-classes")
async def delete_schedule_future_classes(
    schedule_id: int,
    from_date: str = Query(..., description="Fecha desde la cual eliminar (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    ELIMINA clases futuras de un horario (AL CAMBIAR DE HORARIO)

    Usado cuando un alumno cambia de horario.
    Las clases se ELIMINAN físicamente de la BD (no se cancelan).

    Solo elimina clases con status='scheduled' (no las completadas).

    Args:
        schedule_id: ID del horario viejo
        from_date: Fecha desde la cual eliminar en formato YYYY-MM-DD

    Returns:
        Cantidad de clases eliminadas

    Example:
        DELETE /api/v1/jobs/schedules/1/future-classes?from_date=2025-11-01
    """
    try:
        date_obj = date_type.fromisoformat(from_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Formato de fecha inválido: {from_date}. Use YYYY-MM-DD"
        )

    count = await delete_future_classes_for_schedule(db, schedule_id, date_obj)

    return {
        "message": f"{count} clases eliminadas exitosamente",
        "schedule_id": schedule_id,
        "from_date": from_date,
        "deleted": count
    }


# ============================================
# CANCELACIÓN DE CLASES (SUSPENSIÓN/RETIRO)
# ============================================

@router.post("/enrollments/{enrollment_id}/cancel-future-classes")
async def cancel_enrollment_future_classes(
    enrollment_id: int,
    from_date: str = Query(..., description="Fecha desde la cual cancelar (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    CANCELA clases futuras de una inscripción (SUSPENSIÓN/RETIRO)

    Usado cuando un alumno se suspende o retira.
    Las clases se CANCELAN (status='cancelled'), NO se eliminan.

    Se mantienen en la BD para histórico.

    Args:
        enrollment_id: ID de la inscripción
        from_date: Fecha desde la cual cancelar en formato YYYY-MM-DD

    Returns:
        Cantidad de clases canceladas

    Example:
        POST /api/v1/jobs/enrollments/1/cancel-future-classes?from_date=2025-11-01
    """
    try:
        date_obj = date_type.fromisoformat(from_date)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Formato de fecha inválido: {from_date}. Use YYYY-MM-DD"
        )

    count = await cancel_future_classes_for_enrollment(db, enrollment_id, date_obj)

    return {
        "message": f"{count} clases canceladas exitosamente",
        "enrollment_id": enrollment_id,
        "from_date": from_date,
        "cancelled": count
    }
