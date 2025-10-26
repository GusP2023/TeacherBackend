"""
Módulo core - Configuración y utilidades del núcleo de la aplicación.

Exporta:
- settings: Configuración de la aplicación
- engine: Motor de SQLAlchemy
- SessionLocal: Factory de sesiones
- get_db: Dependency de FastAPI para obtener sesión de BD
- init_db: Función para crear tablas

Uso:
    from app.core import settings, get_db, init_db
"""

from .config import settings
from .database import engine, async_session_maker, get_db
from .init_db import init_db, drop_db, reset_db

__all__ = [
    # Configuración
    "settings",
    
    # Base de datos
    "engine",
    "async_session_maker",  # ✅ Nombre correcto
    "get_db",
    
    # Inicialización
    "init_db",
    "drop_db",
    "reset_db",
]