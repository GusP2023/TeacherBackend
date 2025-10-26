"""
Script de inicialización de base de datos.

Este script:
- Crea todas las tablas definidas en los modelos
- Se ejecuta una sola vez al inicio del proyecto
- Puede ejecutarse manualmente: python -m app.core.init_db

IMPORTANTE: 
- Asegúrate de que PostgreSQL esté corriendo
- Verifica que la BD 'music_school' exista
- Configura las credenciales en config.py

Tablas que se crearán:
    1. teachers
    2. instruments
    3. students
    4. enrollments
    5. schedules
    6. classes
    7. attendances

Uso:
    # Desde la raíz del proyecto
    python -m app.core.init_db
    
    # O desde código Python
    from app.core.init_db import init_db
    await init_db()
"""

import sys
import asyncio
from pathlib import Path

# Agregar el directorio raíz al path para imports
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from app.core.database import engine
from app.models import Base


async def init_db():
    """
    Crea todas las tablas en la base de datos (async).
    
    Este método:
    - Lee todos los modelos que heredan de Base
    - Genera las sentencias CREATE TABLE
    - Las ejecuta en PostgreSQL
    
    Si las tablas ya existen, no hace nada (no las recrea).
    Para recrear tablas, usar drop_db() primero.
    """
    try:
        print("🔄 Creando tablas en la base de datos...")
        print(f"📍 Conectando a: {engine.url}")
        
        # Crear todas las tablas (async)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("✅ ¡Tablas creadas exitosamente!")
        print("\n📋 Tablas creadas:")
        for table in Base.metadata.sorted_tables:
            print(f"   - {table.name}")
            
    except Exception as e:
        print(f"❌ Error al crear las tablas: {e}")
        sys.exit(1)


async def drop_db():
    """
    Elimina todas las tablas de la base de datos (async).
    
    ⚠️ CUIDADO: Esta acción es IRREVERSIBLE.
    Solo usar en desarrollo para recrear el schema.
    """
    try:
        print("⚠️  ADVERTENCIA: Esto eliminará TODAS las tablas")
        confirm = input("¿Estás seguro? (escribe 'SI' para confirmar): ")
        
        if confirm != "SI":
            print("❌ Operación cancelada")
            return
            
        print("🔄 Eliminando tablas...")
        
        # Eliminar todas las tablas (async)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        print("✅ Tablas eliminadas exitosamente")
        
    except Exception as e:
        print(f"❌ Error al eliminar las tablas: {e}")
        sys.exit(1)


async def reset_db():
    """
    Reinicia la base de datos (elimina y recrea todas las tablas).
    
    ⚠️ CUIDADO: Esta acción es IRREVERSIBLE.
    Útil para desarrollo cuando cambias el schema.
    """
    print("🔄 Reiniciando base de datos...")
    await drop_db()
    await init_db()


def main():
    """
    Punto de entrada cuando se ejecuta como script.
    
    Uso:
        python -m app.core.init_db           # Crear tablas
        python -m app.core.init_db drop      # Eliminar tablas
        python -m app.core.init_db reset     # Reiniciar (eliminar + crear)
    """
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "drop":
            asyncio.run(drop_db())
        elif command == "reset":
            asyncio.run(reset_db())
        else:
            print(f"❌ Comando desconocido: {command}")
            print("Comandos disponibles: drop, reset")
            sys.exit(1)
    else:
        # Por defecto, crear tablas
        asyncio.run(init_db())


if __name__ == "__main__":
    main()