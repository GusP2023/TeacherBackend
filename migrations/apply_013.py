"""
Script para aplicar migración: 013_add_tutor_name_to_students

Agrega el campo tutor_name a la tabla students.
"""
import asyncio
from pathlib import Path
from app.core.database import async_session_maker

async def apply_migration():
    """Aplica la migración SQL."""
    migration_file = Path(__file__).parent / "013_add_tutor_name_to_students.sql"

    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    async with async_session_maker() as session:
        try:
            await session.execute(sql)
            await session.commit()
            print("✅ Migración aplicada exitosamente")
            print("   - Campo tutor_name agregado a tabla students")
        except Exception as e:
            print(f"❌ Error al aplicar migración: {e}")
            await session.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(apply_migration())
