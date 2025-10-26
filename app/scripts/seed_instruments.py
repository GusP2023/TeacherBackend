"""
Script para insertar instrumentos iniciales en la base de datos

Ejecutar:
    python -m app.scripts.seed_instruments
    
O si ya existen y quieres recrearlos:
    python -m app.scripts.seed_instruments --reset
    
Para listar instrumentos:
    python -m app.scripts.seed_instruments --list
"""

import asyncio
import sys
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.instrument import Instrument


# Lista de instrumentos iniciales
INSTRUMENTS = [
    {"name": "Piano"},
    {"name": "Guitarra"},
    {"name": "Violín"},
    {"name": "Canto"},
    {"name": "Batería"},
    {"name": "Violonchelo"},
]


async def seed_instruments(reset: bool = False):
    """
    Insertar instrumentos iniciales en la base de datos
    
    Args:
        reset: Si True, elimina instrumentos existentes antes de insertar
    """
    async with async_session_maker() as db:
        try:
            print("\n" + "="*60)
            print("🎵 SEED INSTRUMENTOS - ProfesorSYS")
            print("="*60 + "\n")
            
            # Si reset, eliminar instrumentos existentes
            if reset:
                print("⚠️  Modo RESET activado")
                result = await db.execute(select(Instrument))
                existing = result.scalars().all()
                
                if existing:
                    print(f"🗑️  Eliminando {len(existing)} instrumentos existentes...")
                    for inst in existing:
                        await db.delete(inst)
                    await db.commit()
                    print("✅ Instrumentos eliminados\n")
                else:
                    print("ℹ️  No hay instrumentos para eliminar\n")
            
            # Verificar instrumentos existentes
            result = await db.execute(select(Instrument))
            existing_instruments = {inst.name: inst for inst in result.scalars().all()}
            
            if existing_instruments and not reset:
                print(f"ℹ️  Ya existen {len(existing_instruments)} instrumentos en la base de datos")
                print("💡 Usa --reset para recrear todos los instrumentos\n")
                print("Instrumentos existentes:")
                for name in existing_instruments.keys():
                    print(f"   - {name}")
                return
            
            # Insertar instrumentos
            print(f"📝 Insertando {len(INSTRUMENTS)} instrumentos...\n")
            
            created_count = 0
            for inst_data in INSTRUMENTS:
                instrument = Instrument(**inst_data)
                db.add(instrument)
                created_count += 1
                print(f"   ✓ {inst_data['name']}")
            
            await db.commit()
            
            print(f"\n✅ {created_count} instrumentos insertados correctamente")
            print("\n" + "="*60)
            print("🎉 SEED COMPLETADO")
            print("="*60 + "\n")
            
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            await db.rollback()
            raise


async def list_instruments():
    """
    Listar todos los instrumentos en la base de datos
    """
    async with async_session_maker() as db:
        result = await db.execute(select(Instrument).order_by(Instrument.name))
        instruments = result.scalars().all()
        
        print("\n" + "="*60)
        print("🎵 INSTRUMENTOS EN LA BASE DE DATOS")
        print("="*60 + "\n")
        
        if not instruments:
            print("ℹ️  No hay instrumentos en la base de datos")
            print("💡 Ejecuta: python -m app.scripts.seed_instruments\n")
        else:
            print(f"Total: {len(instruments)} instrumentos\n")
            for inst in instruments:
                status = "✅ Activo" if inst.active else "❌ Inactivo"
                print(f"  [{inst.id}] {inst.name:20} - {status}")
        
        print("\n" + "="*60 + "\n")


def main():
    """
    Función principal - maneja argumentos de línea de comandos
    """
    # Verificar argumentos
    reset = "--reset" in sys.argv
    list_mode = "--list" in sys.argv
    
    if list_mode:
        # Modo listar
        asyncio.run(list_instruments())
    else:
        # Modo seed
        asyncio.run(seed_instruments(reset=reset))


if __name__ == "__main__":
    main()