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

from app.core.database import get_db
from app.jobs.class_generator import generate_monthly_classes


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
            result = await generate_monthly_classes(db)

            print(f"[JOB] Generación completada:")
            print(f"  - Clases creadas: {result['created']}")
            print(f"  - Clases saltadas: {result['skipped']}")
            print(f"  - Enrollments procesados: {result['enrollments_processed']}")

            if result.get('errors'):
                print(f"  - Errores: {len(result['errors'])}")
                for error in result['errors'][:5]:  # Mostrar solo primeros 5
                    print(f"    • {error}")

        except Exception as e:
            print(f"[JOB] Error en generación mensual: {str(e)}")

        finally:
            break  # Solo usar la primera sesión


# ============================================
# INICIALIZAR SCHEDULER
# ============================================

def start_scheduler():
    """
    Inicia el scheduler y registra todos los jobs

    Se ejecuta automáticamente en el startup event de FastAPI.
    """
    # Job mensual: día 10 de cada mes a las 2:00 AM
    scheduler.add_job(
        monthly_class_generation_job,
        trigger=CronTrigger(day=10, hour=2, minute=0),
        id='generate_monthly_classes',
        name='Generación mensual de clases',
        replace_existing=True  # Reemplazar si ya existe (útil en desarrollo)
    )

    scheduler.start()
    print("[SCHEDULER] ✅ Iniciado - Job mensual configurado (día 10, 02:00 AM)")


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
