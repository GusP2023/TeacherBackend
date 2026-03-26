"""
Script para regenerar clases de todos los enrollments activos.

LOGICA:
- Genera desde HOY hasta fin del mes actual + 2 meses completos
- Ejemplo: Hoy 19 dic -> genera hasta 28 feb (dic + ene + feb)
- Respeta los dias de la semana de cada schedule

Uso:
    cd C:/ProfesorSYS/backend
    python -m app.scripts.regenerate_classes
"""

import asyncio
from datetime import date, timedelta

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.schedule import Schedule, DayOfWeek
from app.models.class_model import Class, ClassStatus, ClassType
from app.models.student import Student
from app.core.holidays import is_holiday


# Mapeo de días
DAY_MAP = {
    DayOfWeek.MONDAY: 0,
    DayOfWeek.TUESDAY: 1,
    DayOfWeek.WEDNESDAY: 2,
    DayOfWeek.THURSDAY: 3,
    DayOfWeek.FRIDAY: 4,
    DayOfWeek.SATURDAY: 5,
    DayOfWeek.SUNDAY: 6,
}


def get_last_day_of_month(year: int, month: int) -> date:
    """Obtiene el último día de un mes."""
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def calculate_end_date(start_date: date, months_ahead: int = 2) -> date:
    """
    Calcula la fecha final: último día del mes actual + N meses completos.
    
    Ejemplo con months_ahead=2:
    - start_date = 19 dic 2025 → end_date = 28 feb 2026
    - start_date = 10 ene 2026 → end_date = 31 mar 2026
    """
    month = start_date.month + months_ahead
    year = start_date.year
    
    while month > 12:
        month -= 12
        year += 1
    
    return get_last_day_of_month(year, month)


async def regenerate_all_classes(clean_future: bool = True):
    """
    Regenera clases para todos los enrollments activos.
    
    Args:
        clean_future: Si True, elimina clases futuras antes de regenerar
    """
    
    print("=" * 70)
    print("🔄 REGENERANDO CLASES PARA TODOS LOS ENROLLMENTS ACTIVOS")
    print("=" * 70)
    
    # today = date.today()
    today = date(2026, 1, 19) # Hardcoded for user context
    end_date = calculate_end_date(today, months_ahead=2)
    
    print(f"\n📅 Rango de generación:")
    print(f"   Desde: {today} ({today.strftime('%A')})")
    print(f"   Hasta: {end_date} ({end_date.strftime('%A')})")
    print(f"   Total días: {(end_date - today).days + 1}")
    
    async with async_session_maker() as db:
        # 1. Limpiar clases futuras si se solicita
        if clean_future:
            print(f"\n🧹 Eliminando clases futuras (desde {today})...")
            result = await db.execute(
                delete(Class).where(
                    and_(
                        Class.date >= today,
                        Class.status == ClassStatus.SCHEDULED
                    )
                )
            )
            await db.commit()
            print(f"   ✅ Eliminadas {result.rowcount} clases futuras")
        
        # 2. Obtener todos los enrollments activos
        result = await db.execute(
            select(Enrollment).where(Enrollment.status == EnrollmentStatus.ACTIVE)
        )
        enrollments = result.scalars().all()
        
        print(f"\n📋 Encontrados {len(enrollments)} enrollments activos\n")
        
        total_created = 0
        total_skipped = 0
        
        for enrollment in enrollments:
            # Obtener estudiante
            student = await db.get(Student, enrollment.student_id)
            student_name = student.name if student else f"ID:{enrollment.student_id}"
            
            print(f"  ┌─ {student_name} (Enrollment #{enrollment.id}, Formato: {enrollment.format})")
            
            # Obtener schedules del enrollment
            sched_result = await db.execute(
                select(Schedule).where(
                    and_(
                        Schedule.enrollment_id == enrollment.id,
                        Schedule.active == True
                    )
                )
            )
            schedules = sched_result.scalars().all()
            
            if not schedules:
                print(f"  │  ⚠️ Sin horarios definidos")
                print(f"  └" + "─" * 50)
                continue
            
            enrollment_created = 0
            enrollment_skipped = 0
            
            for schedule in schedules:
                # Determinar fecha de inicio para este schedule
                # Usar el mayor entre: hoy, valid_from del schedule
                schedule_start = max(today, schedule.valid_from)
                
                # Si valid_until existe y es menor que end_date, usar valid_until
                schedule_end = end_date
                if schedule.valid_until and schedule.valid_until < end_date:
                    schedule_end = schedule.valid_until
                
                target_weekday = DAY_MAP[schedule.day]
                
                # Encontrar el primer día que coincida
                current_date = schedule_start
                days_searched = 0
                while current_date.weekday() != target_weekday and days_searched < 7:
                    current_date += timedelta(days=1)
                    days_searched += 1
                
                if days_searched >= 7:
                    print(f"  │  ❌ No se encontró {schedule.day.value} desde {schedule_start}")
                    continue
                
                schedule_created = 0
                schedule_skipped = 0
                
                # Generar clases semana por semana
                while current_date <= schedule_end:
                    # Verificar feriados
                    if is_holiday(current_date):
                        schedule_skipped += 1
                        current_date += timedelta(weeks=1)
                        continue
                    
                    # Verificar duplicados
                    # Verificar duplicados; limitar a 1 fila para no fallar si ya
                    # existen múltiples registros corruptos
                    exists = await db.execute(
                        select(Class.id).where(
                            and_(
                                Class.schedule_id == schedule.id,
                                Class.date == current_date,
                                Class.time == schedule.time
                            )
                        ).limit(1)
                    )
                    
                    if exists.scalar_one_or_none() is not None:
                        schedule_skipped += 1
                        current_date += timedelta(weeks=1)
                        continue
                    
                    # Crear clase
                    new_class = Class(
                        schedule_id=schedule.id,
                        enrollment_id=enrollment.id,
                        teacher_id=schedule.teacher_id,
                        date=current_date,
                        time=schedule.time,
                        duration=schedule.duration,
                        status=ClassStatus.SCHEDULED,
                        type=ClassType.REGULAR,
                        format=enrollment.format
                    )
                    db.add(new_class)
                    schedule_created += 1
                    
                    current_date += timedelta(weeks=1)
                
                print(f"  │  📅 {schedule.day.value} {schedule.time}: +{schedule_created} clases")
                enrollment_created += schedule_created
                enrollment_skipped += schedule_skipped
            
            total_created += enrollment_created
            total_skipped += enrollment_skipped
            print(f"  │  Total: {enrollment_created} creadas, {enrollment_skipped} saltadas")
            print(f"  └" + "─" * 50)
        
        await db.commit()
        
        # Verificar resultado
        count_result = await db.execute(
            select(Class).where(
                and_(
                    Class.date >= today,
                    Class.date <= end_date
                )
            )
        )
        final_count = len(count_result.scalars().all())
        
        print("\n" + "=" * 70)
        print(f"📊 RESUMEN:")
        print(f"   - Enrollments procesados: {len(enrollments)}")
        print(f"   - Clases creadas: {total_created}")
        print(f"   - Clases saltadas: {total_skipped}")
        print(f"   - Total clases en rango {today} a {end_date}: {final_count}")
        print("=" * 70)
        
        # Mostrar distribución por semana
        print("\n📅 DISTRIBUCIÓN POR SEMANA:")
        current_week_start = today - timedelta(days=today.weekday())
        
        while current_week_start <= end_date:
            week_end = current_week_start + timedelta(days=5)  # Lunes a Sábado
            
            week_result = await db.execute(
                select(Class).where(
                    and_(
                        Class.date >= current_week_start,
                        Class.date <= week_end
                    )
                )
            )
            week_classes = week_result.scalars().all()
            
            if week_classes:
                # Agrupar por día
                by_day = {}
                for cls in week_classes:
                    day_name = cls.date.strftime("%a")
                    if day_name not in by_day:
                        by_day[day_name] = 0
                    by_day[day_name] += 1
                
                days_str = ", ".join([f"{d}:{c}" for d, c in sorted(by_day.items())])
                print(f"   {current_week_start} - {week_end}: {len(week_classes)} clases ({days_str})")
            
            current_week_start += timedelta(weeks=1)


if __name__ == "__main__":
    asyncio.run(regenerate_all_classes(clean_future=True))
