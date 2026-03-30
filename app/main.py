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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.scheduler import start_scheduler, shutdown_scheduler
from app.core.security import should_refresh_token, refresh_access_token

# ========================================
# IMPORTAR ROUTERS
# ========================================
from app.api.v1 import (
    auth_router,
    admin_router,
    teachers_router,
    students_router,
    instruments_router,
    enrollments_router,
    schedules_router,
    classes_router,
    attendances_router,
    jobs_router,
    sync_router,
    batch_router,
    websocket_router
)

# ========================================
# IMPORTAR MODELOS (IMPORTANTE)
# ========================================
# SQLAlchemy necesita que los modelos estén importados
# para crear las tablas correctamente
from app.models import (
    Base,
    Organization,
    Invitation,
    SecurityLog,
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
# MIDDLEWARE DE TOKEN REFRESH (SLIDING WINDOW)
# ========================================

class TokenRefreshMiddleware(BaseHTTPMiddleware):
    """
    Middleware que implementa sliding window para tokens JWT.

    En cada respuesta exitosa (200-299):
    1. Verifica si el token actual tiene menos de 25 días de vida
    2. Si es así, emite un nuevo token con 30 días adicionales
    3. Incluye el nuevo token en el header X-New-Token

    El frontend debe detectar este header y guardar automáticamente el nuevo token.

    Esto permite que usuarios activos nunca vean expirar su sesión,
    mientras que usuarios inactivos por más de 30 días deben reautenticarse.
    """

    async def dispatch(self, request: Request, call_next):
        # Procesar la petición normalmente
        response: Response = await call_next(request)

        # Solo procesar respuestas exitosas (200-299)
        if 200 <= response.status_code < 300:
            # Intentar extraer token del header Authorization
            auth_header = request.headers.get("Authorization")

            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "")

                try:
                    # Verificar si el token debe ser refrescado
                    if should_refresh_token(token):
                        # Emitir nuevo token
                        new_token = refresh_access_token(token)

                        # Añadir header con nuevo token
                        response.headers["X-New-Token"] = new_token

                except Exception:
                    # Si hay cualquier error, no hacer nada
                    # (evitar que el middleware rompa peticiones legítimas)
                    pass

        return response


# ========================================
# CREAR APLICACIÓN FASTAPI
# ========================================
# Swagger UI deshabilitado en producción (expone todos los endpoints públicamente)
_docs_url  = "/docs"  if settings.ENVIRONMENT != "production" else None
_redoc_url = "/redoc" if settings.ENVIRONMENT != "production" else None

# Instancia global del rate limiter importada desde core.limiter
from app.core.limiter import limiter

app = FastAPI(
    title="ProfesorSYS API",
    description="Sistema de gestión para profesores de música",
    version="1.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

# Registrar rate limiter en la app
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429,
        content={"detail": "Demasiados intentos. Espera un momento antes de volver a intentarlo."},
    ),
)

# ========================================
# CONFIGURAR CORS
# ========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],
)

# ========================================
# TOKEN REFRESH MIDDLEWARE
# ========================================

# IMPORTANTE: Debe ir DESPUÉS de CORS para que el header X-New-Token sea accesible
app.add_middleware(TokenRefreshMiddleware)

# ========================================
# EVENTOS DE CICLO DE VIDA
# ========================================

@app.on_event("startup")
async def startup_event():
    print(">> Iniciando ProfesorSYS API...")
    print(f">> Entorno: {settings.ENVIRONMENT}")
    print(f">> Base de datos: {settings.DATABASE_URL.split('@')[1]}")

    # Validación crítica: SECRET_KEY en producción
    if settings.ENVIRONMENT == "production":
        if settings.SECRET_KEY == "dev-secret-key-change-in-production":
            raise RuntimeError(
                "FATAL: SECRET_KEY no configurada. "
                "Genera una con: openssl rand -hex 32"
            )

    # Iniciar scheduler de jobs automáticos
    start_scheduler()

    # ── WARMUP DE BASE DE DATOS (Neon free tier) ─────────────────────────────
    # Neon se suspende tras 5 minutos de inactividad y tarda 1-3s en despertar.
    # Sin este warmup, la primera request real (login, full sync) carga con ese
    # retraso o falla si el cliente tiene un timeout corto.
    #
    # Se reintenta hasta 3 veces con 2s de pausa entre intentos.
    # Si los 3 fallan, la app sigue iniciando: Neon despertará con la
    # primera query real (solo esa request verá el retraso residual).
    # ─────────────────────────────────────────────────────────────────────────
    import asyncio
    from sqlalchemy import text
    from app.core.database import async_session_maker

    print(">> Despertando base de datos (Neon warmup)...")
    _db_ready = False
    for attempt in range(1, 4):
        try:
            async with async_session_maker() as session:
                await session.execute(text("SELECT 1"))
            print(f">> Base de datos lista (intento {attempt}/3)")
            _db_ready = True
            break
        except Exception as e:
            print(f">> Warmup BD intento {attempt}/3 fallido: {e}")
            if attempt < 3:
                await asyncio.sleep(2)

    if not _db_ready:
        print(">> Warmup no completado — Neon despertará con la primera request")

    print(">> Aplicacion lista")


@app.on_event("shutdown")
async def shutdown_event():
    print(">> Cerrando ProfesorSYS API...")
    shutdown_scheduler()


# ========================================
# RUTAS PRINCIPALES
# ========================================

@app.get("/")
async def root():
    return {
        "message": "ProfesorSYS API",
        "version": "1.0.0",
        "status": "online",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Endpoint liviano para verificar que el servidor está activo.
    Usado por la app móvil para detectar si el backend es alcanzable."""
    return {"status": "ok"}


# ========================================
# INCLUIR ROUTERS (API v1)
# ========================================

app.include_router(auth_router,        prefix=f"{settings.API_V1_PREFIX}/auth",        tags=["Authentication"])
app.include_router(admin_router,       prefix=f"{settings.API_V1_PREFIX}/admin",        tags=["Admin"])
app.include_router(teachers_router,    prefix=f"{settings.API_V1_PREFIX}/teachers",     tags=["Teachers"])
app.include_router(students_router,    prefix=f"{settings.API_V1_PREFIX}/students",     tags=["Students"])
app.include_router(instruments_router, prefix=f"{settings.API_V1_PREFIX}/instruments",  tags=["Instruments"])
app.include_router(enrollments_router, prefix=f"{settings.API_V1_PREFIX}/enrollments",  tags=["Enrollments"])
app.include_router(schedules_router,   prefix=f"{settings.API_V1_PREFIX}/schedules",    tags=["Schedules"])
app.include_router(classes_router,     prefix=f"{settings.API_V1_PREFIX}/classes",      tags=["Classes"])
app.include_router(attendances_router, prefix=f"{settings.API_V1_PREFIX}/attendances",  tags=["Attendances"])
app.include_router(jobs_router,        prefix=f"{settings.API_V1_PREFIX}/jobs",         tags=["Jobs"])
app.include_router(websocket_router,   prefix=f"{settings.API_V1_PREFIX}",              tags=["WebSocket"])
app.include_router(sync_router,        prefix=f"{settings.API_V1_PREFIX}/sync",         tags=["Sync"])
app.include_router(batch_router,       prefix=f"{settings.API_V1_PREFIX}/batch",        tags=["Batch"])


# ========================================
# MANEJO DE ERRORES
# ========================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={
        "error": "Not Found",
        "message": "El recurso solicitado no existe",
        "path": str(request.url),
    })


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    return JSONResponse(status_code=500, content={
        "error": "Internal Server Error",
        "message": "Ocurrió un error interno en el servidor",
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
