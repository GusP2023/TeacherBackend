"""
Aplicación principal FastAPI - ProfesorSYS

Sistema de gestión para profesores de música.

Características:
- API RESTful con FastAPI
- PostgreSQL con SQLAlchemy 2.0+
- Autenticación JWT
- CORS configurado
- Validación con Pydantic

Arquitectura:
    Teacher → Student → Enrollment → Instrument
                            ↓
                      Schedule → Class → Attendance

Para iniciar el servidor:
    uvicorn app.main:app --reload
    
Para crear las tablas:
    python -m app.core.init_db
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.scheduler import start_scheduler, shutdown_scheduler

# ========================================
# IMPORTAR ROUTERS
# ========================================
from app.api.v1 import (
    auth_router,
    teachers_router,
    students_router,
    instruments_router,
    enrollments_router,
    schedules_router,
    classes_router,
    attendances_router,
    jobs_router
)

# ========================================
# IMPORTAR MODELOS (IMPORTANTE)
# ========================================
# SQLAlchemy necesita que los modelos estén importados
# para crear las tablas correctamente
from app.models import (
    Base,
    Teacher,
    Student,
    Instrument,
    Enrollment,
    Schedule,
    Class,
    Attendance,
    # Enums
    EnrollmentStatus,
    EnrollmentLevel,
    DayOfWeek,
    ClassStatus,
    ClassType,
    ClassFormat,
    AttendanceStatus,
)

# ========================================
# CREAR APLICACIÓN FASTAPI
# ========================================
app = FastAPI(
    title="ProfesorSYS API",
    description="Sistema de gestión para profesores de música",
    version="1.0.0",
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
)

# ========================================
# CONFIGURAR CORS
# ========================================

# CORS dinámico según entorno
# Desarrollo: localhost
# Producción: dominios específicos desde variable de entorno ALLOWED_ORIGINS
origins = settings.ALLOWED_ORIGINS.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,  # ✅ Solo orígenes permitidos (configurable por entorno)
    allow_credentials=True,  # Permite cookies/auth headers
    allow_methods=["*"],  # Permite todos los métodos (GET, POST, PUT, DELETE, etc)
    allow_headers=["*"],  # Permite todos los headers
)

# ========================================
# EVENTOS DE CICLO DE VIDA
# ========================================
@app.on_event("startup")
async def startup_event():
    """
    Se ejecuta al iniciar la aplicación.

    Aquí puedes:
    - Verificar conexión a BD
    - Inicializar servicios
    - Cargar datos en caché
    """
    print(">> Iniciando ProfesorSYS API...")
    print(f">> Entorno: {settings.ENVIRONMENT}")
    print(f">> Base de datos: {settings.DATABASE_URL.split('@')[1]}")  # Oculta credenciales

    # Iniciar scheduler de jobs automáticos
    start_scheduler()

    print(">> Aplicacion lista")


@app.on_event("shutdown")
async def shutdown_event():
    """
    Se ejecuta al cerrar la aplicación.

    Aquí puedes:
    - Cerrar conexiones
    - Limpiar recursos
    - Guardar estado
    """
    print(">> Cerrando ProfesorSYS API...")

    # Detener scheduler
    shutdown_scheduler()


# ========================================
# RUTAS PRINCIPALES
# ========================================
@app.get("/")
async def root():
    """
    Endpoint raíz - Verifica que la API esté funcionando.
    """
    return {
        "message": "ProfesorSYS API",
        "version": "1.0.0",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """
    Health check - Verifica el estado de la aplicación.
    
    Útil para:
    - Monitoreo
    - Load balancers
    - Docker health checks
    """
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
    }


# ========================================
# INCLUIR ROUTERS (API v1)
# ========================================
app.include_router(
    auth_router,
    prefix=f"{settings.API_V1_PREFIX}/auth",
    tags=["Authentication"]
)

app.include_router(
    teachers_router,
    prefix=f"{settings.API_V1_PREFIX}/teachers",
    tags=["Teachers"]
)

app.include_router(
    students_router,
    prefix=f"{settings.API_V1_PREFIX}/students",
    tags=["Students"]
)

app.include_router(
    instruments_router,
    prefix=f"{settings.API_V1_PREFIX}/instruments",
    tags=["Instruments"]
)

app.include_router(
    enrollments_router,
    prefix=f"{settings.API_V1_PREFIX}/enrollments",
    tags=["Enrollments"]
)

app.include_router(
    schedules_router,
    prefix=f"{settings.API_V1_PREFIX}/schedules",
    tags=["Schedules"]
)

app.include_router(
    classes_router,
    prefix=f"{settings.API_V1_PREFIX}/classes",
    tags=["Classes"]
)

app.include_router(
    attendances_router,
    prefix=f"{settings.API_V1_PREFIX}/attendances",
    tags=["Attendances"]
)

app.include_router(
    jobs_router,
    prefix=f"{settings.API_V1_PREFIX}/jobs",
    tags=["Jobs"]
)


# ========================================
# MANEJO DE ERRORES
# ========================================
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Maneja errores 404 (No encontrado)"""
    return {
        "error": "Not Found",
        "message": "El recurso solicitado no existe",
        "path": str(request.url),
    }


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Maneja errores 500 (Error interno del servidor)"""
    return {
        "error": "Internal Server Error",
        "message": "Ocurrió un error interno en el servidor",
    }


if __name__ == "__main__":
    """
    Punto de entrada cuando se ejecuta directamente.
    
    En producción, usar:
        uvicorn app.main:app --host 0.0.0.0 --port 8000
    """
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Auto-reload en desarrollo
        log_level="info",
    )