"""
Configuración de la aplicación.

Este módulo centraliza todas las configuraciones:
- Base de datos
- Seguridad (JWT)
- API
- CORS
- Entorno (dev/prod)

Las variables pueden ser sobreescritas con variables de entorno (.env)
"""

from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Configuración de la aplicación.
    
    Prioridad de carga:
    1. Variables de entorno
    2. Archivo .env
    3. Valores por defecto (estos)
    
    Ejemplo de .env:
        DATABASE_URL=postgresql://user:pass@localhost/music_school
        SECRET_KEY=mi-clave-super-secreta
        ENVIRONMENT=production
    """
    
    # ========================================
    # ENTORNO
    # ========================================
    ENVIRONMENT: str = "development"  # development, staging, production
    DEBUG: bool = True
    
    # ========================================
    # BASE DE DATOS
    # ========================================
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/music_school"
    
    # ========================================
    # SEGURIDAD Y AUTENTICACIÓN
    # ========================================
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutos
    
    # ========================================
    # API
    # ========================================
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "ProfesorSYS"
    
    # ========================================
    # CORS (Cross-Origin Resource Sharing)
    # ========================================
    # ALLOWED_ORIGINS: Orígenes permitidos (separados por coma en variable de entorno)
    # Desarrollo: "http://localhost:3000,http://localhost:3001"
    # Producción: "https://tuapp.com,https://www.tuapp.com"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"

    # Deprecated: Usar ALLOWED_ORIGINS en su lugar
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",  # Next.js dev
        "http://localhost:3001",  # Next.js alternate port
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]
    
    # ========================================
    # TARIFAS POR DEFECTO (opcional)
    # ========================================
    DEFAULT_TARIFF_INDIVIDUAL: float = 50.00
    DEFAULT_TARIFF_GROUP: float = 36.00
    DEFAULT_CLASS_DURATION: int = 45  # minutos

    # ========================================
    # CLASES GRUPALES
    # ========================================
    MAX_GROUP_CLASS_SIZE: int = 4  # Máximo de alumnos en un horario grupal
    
    # ========================================
    # CONFIGURACIÓN DE MODELOS
    # ========================================
    class Config:
        """Configuración de Pydantic"""
        env_file = ".env"
        case_sensitive = True


# Instancia global de configuración
settings = Settings()