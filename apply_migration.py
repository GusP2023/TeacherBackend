"""
Script para aplicar la migración: Agregar campo 'format' a enrollments

Ejecutar: python apply_migration.py
"""

import asyncio
import sys
from pathlib import Path

# Agregar el directorio raíz al path
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from app.core.database import engine


async def apply_migration():
    """Aplica la migración SQL para agregar el campo format"""

    migration_sql = """
    -- Agregar columna 'format' a la tabla enrollments
    DO $$
    BEGIN
        -- Verificar si la columna ya existe
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'enrollments' AND column_name = 'format'
        ) THEN
            -- Agregar columna con valor por defecto
            ALTER TABLE enrollments
            ADD COLUMN format VARCHAR(20) NOT NULL DEFAULT 'individual';

            -- Agregar constraint
            ALTER TABLE enrollments
            ADD CONSTRAINT check_enrollment_format
            CHECK (format IN ('individual', 'group'));

            RAISE NOTICE 'Columna format agregada exitosamente';
        ELSE
            RAISE NOTICE 'La columna format ya existe, saltando migración';
        END IF;
    END $$;
    """

    try:
        print("🔄 Aplicando migración: Agregar campo 'format' a enrollments...")

        async with engine.begin() as conn:
            await conn.execute(migration_sql)

        print("✅ Migración aplicada exitosamente!")
        print("\n📋 Verificando columna...")

        # Verificar que la columna existe
        verify_sql = """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = 'enrollments' AND column_name = 'format';
        """

        async with engine.connect() as conn:
            result = await conn.execute(verify_sql)
            row = result.fetchone()

            if row:
                print(f"   ✅ Columna: {row[0]}")
                print(f"   ✅ Tipo: {row[1]}")
                print(f"   ✅ Nullable: {row[2]}")
                print(f"   ✅ Default: {row[3]}")
            else:
                print("   ❌ No se pudo verificar la columna")

    except Exception as e:
        print(f"❌ Error al aplicar migración: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(apply_migration())
