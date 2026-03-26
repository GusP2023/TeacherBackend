"""
Script para aplicar migración: 002_add_manual_credit_dates

Aplica la migración que agrega el campo manual_credit_dates a la tabla enrollments
"""
import asyncio
from pathlib import Path
from app.database import async_session_maker

async def apply_migration():
    """Aplica la migración SQL"""
    
    # Leer archivo SQL
    migration_file = Path(__file__).parent / "002_add_manual_credit_dates.sql"
    
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()
    
    # Ejecutar
    async with async_session_maker() as session:
        try:
            await session.execute(sql)
            await session.commit()
            print("✅ Migración aplicada exitosamente")
            print("   - Campo manual_credit_dates agregado a tabla enrollments")
        except Exception as e:
            print(f"❌ Error al aplicar migración: {e}")
            await session.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(apply_migration())
