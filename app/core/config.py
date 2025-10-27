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

from pydantic import Field, validator
from typing import List, Optional
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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 días (sliding window)
    
    # ========================================
    # API
    # ========================================
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "ProfesorSYS"
    
    # ========================================
    # CORS (Cross-Origin Resource Sharing)
    # ========================================
    # 1. VARIABLE DE ENTORNO (CADENA): Aquí es donde Pydantic carga la cadena de Render.
    # Usamos ALLOWED_ORIGINS como la fuente principal de la cadena.
    CORS_ORIGINS_STR: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000", 
        alias="ALLOWED_ORIGINS" # Le decimos a Pydantic que busque la variable de entorno ALLOWED_ORIGINS
    )
    
    # 2. LISTA PROCESADA (Lo que usa el middleware)
    BACKEND_CORS_ORIGINS: List[str] = [] # Se inicializa vacía, se llena en el validador
    
    # [ELIMINA las variables ALLOWED_ORIGINS: str y BACKEND_CORS_ORIGINS: List[str] antiguas]

    # ... (otras variables)
    
    # CRÍTICO: Este método convierte la cadena del entorno en una lista que FastAPI necesita.
    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Optional[List[str]], values: dict) -> List[str] | List:
        # Usa la cadena cargada del entorno (CORS_ORIGINS_STR)
        origins_str = values.get("CORS_ORIGINS_STR", "")
        if origins_str:
            # Separa la cadena por comas y elimina espacios en blanco
            return [url.strip() for url in origins_str.split(',')]
        
        # Si no se encontró la variable, devuelve la lista vacía o el valor por defecto
        return v or []
    
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