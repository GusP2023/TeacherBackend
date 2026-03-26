"""
Script de diagnóstico para ver schedules y clases generadas.

Uso:
    cd C:/ProfesorSYS/backend
    python -m app.scripts.diagnose_schedules
"""

import asyncio
from datetime import date, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.schedule import Schedule
from app.models.class_model import Class
from app.models.student import Student


async def diagnose():
    """Diagnóstico completo de schedules y clases."""
    
    print("=" * 70)
    print("🔍 DIAGNÓSTICO DE SCHEDULES Y CLASES")
    print("=" * 70)
    
    async with async_session_maker() as db:
        # 1. Obtener todos los enrollments activos
        result = await db.execute(
            select(Enrollment).where(Enrollment.status == EnrollmentStatus.ACTIVE)
        )
        enrollments = result.scalars().all()
        
        print(f"\n📋 ENROLLMENTS ACTIVOS: {len(enrollments)}\n")
        
        for enrollment in enrollments:
            # Obtener estudiante
            student = await db.get(Student, enrollment.student_id)
            student_name = student.name if student else "Desconocido"
            
            print(f"  ┌─ Enrollment #{enrollment.id}: {student_name}")
            print(f"  │  Formato: {enrollment.format}")
            print(f"  │  Instrumento ID: {enrollment.instrument_id}")
            
            # Obtener schedules del enrollment
            sched_result = await db.execute(
                select(Schedule).where(
                    Schedule.enrollment_id == enrollment.id,
                    Schedule.active == True
                )
            )
            schedules = sched_result.scalars().all()
            
            print(f"  │")
            print(f"  │  📅 SCHEDULES ({len(schedules)}):")
            
            if not schedules:
                print(f"  │     ⚠️ NO HAY SCHEDULES DEFINIDOS")
            
            for schedule in schedules:
                print(f"  │     - {schedule.day.value} {schedule.time} ({schedule.duration}min)")
                print(f"  │       valid_from: {schedule.valid_from}")
                print(f"  │       valid_until: {schedule.valid_until or 'Sin límite'}")
                print(f"  │       active: {schedule.active}")
            
            # Obtener clases del enrollment
            class_result = await db.execute(
                select(Class).where(Class.enrollment_id == enrollment.id).order_by(Class.date)
            )
            classes = list(class_result.scalars().all())
            
            print(f"  │")
            print(f"  │  📚 CLASES GENERADAS ({len(classes)}):")
            
            if not classes:
                print(f"  │     ⚠️ NO HAY CLASES GENERADAS")
            else:
                # Mostrar rango de fechas
                first_class = classes[0]
                last_class = classes[-1]
                print(f"  │     Primera: {first_class.date} {first_class.time}")
                print(f"  │     Última:  {last_class.date} {last_class.time}")
                
                # Agrupar por día de la semana
                by_weekday = {}
                for cls in classes:
                    day_name = cls.date.strftime("%A")
                    if day_name not in by_weekday:
                        by_weekday[day_name] = 0
                    by_weekday[day_name] += 1
                
                print(f"  │     Por día: {by_weekday}")
            
            print(f"  └" + "─" * 50)
            print()
        
        # Resumen global
        total_classes = await db.execute(select(func.count(Class.id)))
        total = total_classes.scalar()
        
        # Clases esta semana
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Lunes
        week_end = week_start + timedelta(days=5)  # Sábado
        
        this_week_result = await db.execute(
            select(func.count(Class.id)).where(
                Class.date >= week_start,
                Class.date <= week_end
            )
        )
        this_week = this_week_result.scalar()
        
        print("=" * 70)
        print(f"📊 RESUMEN GLOBAL:")
        print(f"   - Total clases en BD: {total}")
        print(f"   - Clases esta semana ({week_start} a {week_end}): {this_week}")
        print(f"   - Hoy es: {today} ({today.strftime('%A')})")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(diagnose())
