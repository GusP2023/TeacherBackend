"""
Script para aplicar migración: 015_add_time_to_notes

Cambia la columna due_date de DATE a TIMESTAMPTZ.
"""
import asyncio
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

async def apply_migration():
    """Aplica la migración SQL."""
    migration_file = Path(__file__).parent / "015_add_time_to_notes.sql"

    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    url = str(settings.DATABASE_URL)
    if "sslmode=require" in url:
        url = url.replace("?sslmode=require", "")
        engine = create_async_engine(url, connect_args={"ssl": "require"})
    else:
        engine = create_async_engine(url)

    async_session_maker = async_sessionmaker(engine, class_=AsyncSession)

    async with async_session_maker() as session:
        try:
            await session.execute(text(sql))
            await session.commit()
            print("Migración aplicada exitosamente")
            print("   - Columna due_date actualizada a TIMESTAMPTZ en enrollment_notes")
        except Exception as e:
            print(f"Error al aplicar migración: {e}")
            await session.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(apply_migration())
