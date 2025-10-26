"""
Script de prueba para el job de generación de clases

Uso:
    python test_job.py                    # Simular job mensual completo
    python test_job.py --enrollment 1     # Generar para un enrollment específico
    python test_job.py --stats            # Ver estadísticas sin generar
"""

import asyncio
import sys
from datetime import date, timedelta
from sqlalchemy import select, func

from app.core.database import async_session_maker
from app.jobs.class_generator import (
    generate_monthly_classes,
    generate_classes_for_enrollment
)
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.schedule import Schedule
from app.models.class_model import Class, ClassType


async def show_stats():
    """Mostrar estadísticas del sistema"""
    async with async_session_maker() as db:
        # Contar enrollments activos
        result = await db.execute(
            select(func.count(Enrollment.id))
            .where(Enrollment.status == EnrollmentStatus.ACTIVE)
        )
        active_enrollments = result.scalar()

        # Contar schedules activos
        result = await db.execute(
            select(func.count(Schedule.id))
            .where(Schedule.active == True)
        )
        active_schedules = result.scalar()

        # Contar clases regulares generadas
        result = await db.execute(
            select(func.count(Class.id))
            .where(Class.type == ClassType.REGULAR)
        )
        total_classes = result.scalar()

        # Obtener rango de fechas de clases
        result = await db.execute(
            select(
                func.min(Class.date).label('min_date'),
                func.max(Class.date).label('max_date')
            )
            .where(Class.type == ClassType.REGULAR)
        )
        row = result.first()
        min_date = row[0] if row else None
        max_date = row[1] if row else None

        print("\n📊 ESTADÍSTICAS DEL SISTEMA")
        print("=" * 50)
        print(f"Enrollments activos:     {active_enrollments}")
        print(f"Schedules activos:       {active_schedules}")
        print(f"Clases regulares:        {total_classes}")
        if min_date and max_date:
            print(f"Rango de fechas:         {min_date} → {max_date}")
        print("=" * 50)


async def test_monthly_job():
    """Simular ejecución del job mensual"""
    print("\n🔄 EJECUTANDO JOB MENSUAL...")
    print("=" * 50)

    async with async_session_maker() as db:
        result = await generate_monthly_classes(db)

    print("\n✅ RESULTADOS:")
    print(f"  Clases creadas:   {result['created']}")
    print(f"  Clases saltadas:  {result['skipped']}")

    if result['errors']:
        print(f"\n❌ ERRORES ({len(result['errors'])}):")
        for error in result['errors']:
            print(f"  - {error}")
    else:
        print(f"\n✨ Sin errores")

    print("=" * 50)


async def test_enrollment_job(enrollment_id: int):
    """Simular generación para un enrollment específico"""
    print(f"\n🔄 GENERANDO CLASES PARA ENROLLMENT #{enrollment_id}...")
    print("=" * 50)

    async with async_session_maker() as db:
        # Verificar que el enrollment existe
        enrollment = await db.get(Enrollment, enrollment_id)
        if not enrollment:
            print(f"❌ Enrollment #{enrollment_id} no existe")
            return

        print(f"Alumno: {enrollment.student.name if enrollment.student else 'N/A'}")
        print(f"Estado: {enrollment.status}")

        result = await generate_classes_for_enrollment(
            db,
            enrollment_id=enrollment_id,
            months_ahead=1  # Mes actual + 1 mes completo
        )

    print("\n✅ RESULTADOS:")
    print(f"  Clases creadas:   {result.get('created', 0)}")
    print(f"  Clases saltadas:  {result.get('skipped', 0)}")

    if 'error' in result:
        print(f"\n❌ ERROR: {result['error']}")
    elif result.get('errors'):
        print(f"\n❌ ERRORES ({len(result['errors'])}):")
        for error in result['errors']:
            print(f"  - {error}")
    else:
        print(f"\n✨ Sin errores")

    print("=" * 50)


async def verify_generation():
    """Verificar que se generaron correctamente las clases"""
    print("\n🔍 VERIFICANDO GENERACIÓN...")
    print("=" * 50)

    async with async_session_maker() as db:
        # Obtener clases de hoy en adelante
        today = date.today()
        result = await db.execute(
            select(Class)
            .where(
                Class.type == ClassType.REGULAR,
                Class.date >= today
            )
            .order_by(Class.date, Class.time)
            .limit(10)
        )
        classes = result.scalars().all()

        if not classes:
            print("❌ No se encontraron clases futuras")
            return

        print(f"✅ Mostrando primeras 10 clases futuras:")
        print("\nFecha      | Hora  | Alumno")
        print("-" * 50)
        for cls in classes:
            student_name = cls.enrollment.student.name if cls.enrollment and cls.enrollment.student else "N/A"
            print(f"{cls.date} | {cls.time} | {student_name}")

    print("=" * 50)


async def main():
    """Función principal"""
    args = sys.argv[1:]

    if '--stats' in args:
        await show_stats()
    elif '--enrollment' in args:
        try:
            idx = args.index('--enrollment')
            enrollment_id = int(args[idx + 1])
            await test_enrollment_job(enrollment_id)
            await verify_generation()
        except (IndexError, ValueError):
            print("❌ Uso: python test_job.py --enrollment <ID>")
    elif '--verify' in args:
        await verify_generation()
    else:
        # Default: ejecutar job mensual
        await show_stats()
        await test_monthly_job()
        await verify_generation()


if __name__ == "__main__":
    print("\n🎵 ProfesorSYS - Test de Generación de Clases")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Cancelado por el usuario")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
