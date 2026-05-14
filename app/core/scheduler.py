"""
Configuración de APScheduler

Sistema de jobs automatizados con APScheduler.

JOBS CONFIGURADOS:
1. Generación mensual de clases (día 10 de cada mes a las 2:00 AM)

IMPORTANTE:
- El scheduler se inicia automáticamente con la app (startup event)
- Se detiene automáticamente al cerrar la app (shutdown event)
- Los jobs corren en el mismo proceso de FastAPI (no requiere workers externos)
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timezone

from app.core.database import get_db, async_session_maker
from app.jobs.class_generator import generate_monthly_classes
from app.models.job_run_log import JobRunLog


# ============================================
# CREAR SCHEDULER GLOBAL
# ============================================

scheduler = AsyncIOScheduler()


# ============================================
# DEFINIR JOBS
# ============================================

async def monthly_class_generation_job():
    """
    Job mensual: Genera clases del próximo mes

    Ejecuta día 10 de cada mes a las 2:00 AM
    Procesa todos los enrollments activos y genera clases para el próximo mes.

    Lógica:
    - Obtener todos los enrollments con status='active'
    - Para cada enrollment, generar clases del próximo mes
    - Saltar clases duplicadas y feriados
    - Loguear estadísticas
    """
    print("[JOB] Iniciando generación mensual de clases...")

    # Obtener sesión de base de datos
    async for db in get_db():
        try:
            from_date = date.today().replace(day=1)  # Generar clases a partir del primer día del mes actual
            result = await generate_monthly_classes(db, from_date=from_date)

            print(f"[JOB] Generación completada:")
            print(f"  - Clases creadas: {result['created']}")
            print(f"  - Clases saltadas: {result['skipped']}")
            print(f"  - Enrollments procesados: {result['enrollments_processed']}")

            if result.get('errors'):
                print(f"  - Errores: {len(result['errors'])}")
                for error in result['errors'][:5]:  # Mostrar solo primeros 5
                    print(f"    • {error}")

            # Actualizar marcador de ejecución
            current_month = date.today().strftime("%Y-%m")
            log_entry = await db.get(JobRunLog, "monthly_class_generation")
            if log_entry:
                log_entry.last_run_year_month = current_month
                log_entry.last_run_at = datetime.now(timezone.utc)
            else:
                db.add(JobRunLog(
                    job_name="monthly_class_generation",
                    last_run_year_month=current_month,
                    last_run_at=datetime.now(timezone.utc)
                ))

            await db.commit()
            print(f"[JOB] Marcador actualizado para {current_month}")

        except Exception as e:
            print(f"[JOB] Error en generación mensual: {str(e)}")

        break  # Solo usar la primera sesión


async def check_and_run_missed_job():
    """
    Verifica si el job mensual se perdió por reinicio del servidor.

    Se ejecuta una sola vez en el startup, después de que la BD está lista.
    Si ya pasó el día 6 del mes actual y el job no se ejecutó este mes,
    lo ejecuta inmediatamente y actualiza el marcador.

    Lógica:
    - Solo actuar si today.day >= 6
    - Verificar marcador en JobRunLog para "monthly_class_generation"
    - Si no existe o last_run_year_month != mes actual → ejecutar
    - Actualizar marcador después de ejecutar
    """
    today = date.today()

    # Solo actuar si ya pasó el día 6 del mes actual
    if today.day < 6:
        print("[SCHEDULER] Día < 6, no verificar job mensual")
        return

    current_month = today.strftime("%Y-%m")

    try:
        async with async_session_maker() as db:
            # Buscar el marcador para "monthly_class_generation"
            log_entry = await db.get(JobRunLog, "monthly_class_generation")

            # Si ya corrió este mes, no hacer nada
            if log_entry and log_entry.last_run_year_month == current_month:
                print(f"[SCHEDULER] Job mensual ya ejecutado este mes ({current_month}), omitiendo")
                return

            # No corrió este mes → ejecutar ahora
            print(f"[SCHEDULER] Job mensual no detectado para {current_month}, ejecutando...")
            start_of_month = date.today().replace(day=1)
            result = await generate_monthly_classes(db, from_date=start_of_month)
            print(f"[SCHEDULER] Job completado: {result}")

            # Actualizar o crear el marcador
            if log_entry:
                log_entry.last_run_year_month = current_month
                log_entry.last_run_at = datetime.now(timezone.utc)
            else:
                db.add(JobRunLog(
                    job_name="monthly_class_generation",
                    last_run_year_month=current_month,
                    last_run_at=datetime.now(timezone.utc)
                ))

            await db.commit()
            print(f"[SCHEDULER] Marcador actualizado para {current_month}")

    except Exception as e:
        print(f"[SCHEDULER] Error en check_and_run_missed_job: {str(e)} — se ejecutará con la primera request")
        # No relanzar la excepción para no interrumpir el startup


# ============================================
# INICIALIZAR SCHEDULER
# ============================================

def start_scheduler():
    """
    Inicia el scheduler y registra todos los jobs

    Se ejecuta automáticamente en el startup event de FastAPI.
    """
    # Job mensual: día 6 de cada mes a las 00:00 AM
    scheduler.add_job(
        monthly_class_generation_job,
        trigger=CronTrigger(day=6, hour=0, minute=0),
        id='generate_monthly_classes',
        name='Generación mensual de clases',
        replace_existing=True  # Reemplazar si ya existe (útil en desarrollo)
    )

    scheduler.start()
    print("[SCHEDULER] ✅ Iniciado - Job mensual configurado (día 6, 00:00 AM)")


def shutdown_scheduler():
    """
    Detiene el scheduler

    Se ejecuta automáticamente en el shutdown event de FastAPI.
    """
    scheduler.shutdown()
    print("[SCHEDULER] ❌ Detenido")


# ============================================
# FUNCIONES HELPER (OPCIONAL)
# ============================================

def get_scheduled_jobs():
    """
    Obtiene información de todos los jobs programados

    Útil para debugging y monitoreo.

    Returns:
        list: Lista de jobs programados con su información
    """
    jobs = scheduler.get_jobs()
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        }
        for job in jobs
    ]
