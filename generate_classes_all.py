"""
Script para generar clases de todos los enrollments activos

Ejecutar: python generate_classes_all.py
"""

import asyncio
import sys
from pathlib import Path

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from app.core.database import get_db
from app.jobs.class_generator import generate_classes_for_enrollment
from app.models.enrollment import Enrollment, EnrollmentStatus
from sqlalchemy import select


async def generate_all():
    """Genera clases para todos los enrollments activos"""

    async for db in get_db():
        try:
            print("🔄 Buscando enrollments activos...")

            # Obtener todos los enrollments activos
            result = await db.execute(
                select(Enrollment).where(Enrollment.status == EnrollmentStatus.ACTIVE)
            )
            enrollments = result.scalars().all()

            print(f"📋 Encontrados: {len(enrollments)} enrollments activos\n")

            if not enrollments:
                print("❌ No hay enrollments activos")
                return

            total_created = 0
            total_skipped = 0

            for i, enrollment in enumerate(enrollments, 1):
                print(f"[{i}/{len(enrollments)}] Enrollment ID: {enrollment.id}")
                print(f"   Student: {enrollment.student.name if enrollment.student else 'N/A'}")
                print(f"   Instrument: {enrollment.instrument.name if enrollment.instrument else 'N/A'}")

                # Generar clases (2 meses)
                result = await generate_classes_for_enrollment(db, enrollment.id, months_ahead=2)

                if "error" in result:
                    print(f"   ❌ Error: {result['error']}\n")
                else:
                    print(f"   ✅ Creadas: {result['created']}")
                    print(f"   ⏭️  Saltadas: {result['skipped']}")

                    if result.get('errors'):
                        print(f"   ⚠️  Errores: {len(result['errors'])}")

                    total_created += result['created']
                    total_skipped += result['skipped']
                    print()

            print("=" * 50)
            print(f"✅ RESUMEN FINAL:")
            print(f"   Total clases creadas: {total_created}")
            print(f"   Total clases saltadas: {total_skipped}")
            print(f"   Enrollments procesados: {len(enrollments)}")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

        finally:
            break


if __name__ == "__main__":
    asyncio.run(generate_all())
