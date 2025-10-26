from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator

from .config import settings

# Motor de base de datos ASYNC
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Verifica conexiones antes de usarlas
    echo=False,  # True para ver SQL en desarrollo
    pool_size=5,
    max_overflow=10,
    future=True  # SQLAlchemy 2.0 style
)

# Session factory ASYNC
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Permite acceder a objetos después de commit
    autocommit=False,
    autoflush=False
)

# Dependency para FastAPI (ASYNC)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency que proporciona una sesión de base de datos asíncrona.
    Se cierra automáticamente al finalizar la request.
    
    Usage:
        @app.get("/endpoint")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()