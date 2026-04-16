"""
Script para aplicar migración: 008_add_partial_sessions_to_enrollments

Aplica la migración que agrega el campo partial_sessions a la tabla enrollments
"""
import asyncio
from pathlib import Path
from sqlalchemy import text

async def apply_migration():
    """Aplica la migración SQL"""
    from app.core.database import async_session_maker

    # Leer archivo SQL
    migration_file = Path(__file__).parent / "008_add_partial_sessions_to_enrollments.sql"

    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    # Ejecutar cada sentencia SQL por separado
    statements = [stmt.strip() for stmt in sql.split(';') if stmt.strip()]

    async with async_session_maker() as session:
        try:
            for statement in statements:
                await session.execute(text(statement))
            await session.commit()
            print("✅ Migración aplicada exitosamente")
            print("   - Campo partial_sessions agregado a tabla enrollments")
        except Exception as e:
            print(f"❌ Error al aplicar migración: {e}")
            await session.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(apply_migration())