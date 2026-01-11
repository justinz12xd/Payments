"""
Configuración de la base de datos y sesión async.
"""

import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.config import settings


logger = structlog.get_logger(__name__)

# Convertir URL de postgresql:// a postgresql+asyncpg://
# y remover parámetros no soportados por asyncpg (como pgbouncer)
database_url = settings.DATABASE_URL
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Remover parámetros no soportados por asyncpg
parsed = urlparse(database_url)
query_params = parse_qs(parsed.query)
# Remover 'pgbouncer' y otros parámetros no soportados
unsupported_params = ['pgbouncer', 'sslmode']
for param in unsupported_params:
    query_params.pop(param, None)
# Agregar prepared_statement_cache_size=0 directamente en la URL (para asyncpg)
query_params['prepared_statement_cache_size'] = ['0']
# Reconstruir la URL con los parámetros
clean_query = urlencode(query_params, doseq=True)
database_url = urlunparse((
    parsed.scheme,
    parsed.netloc,
    parsed.path,
    parsed.params,
    clean_query,
    parsed.fragment
))

# Crear engine async con configuración para pgbouncer
# CRÍTICO: json_serializer y json_deserializer para manejar JSONB correctamente
engine = create_async_engine(
    database_url,
    echo=settings.DEBUG,
    poolclass=NullPool,  # Recomendado para pgbouncer - no mantiene conexiones
    future=True,
    # Serializar diccionarios Python a JSON strings para asyncpg
    json_serializer=lambda obj: json.dumps(obj),
    json_deserializer=lambda s: json.loads(s) if isinstance(s, str) else s,
    connect_args={
        "prepared_statement_cache_size": 0,  # Deshabilitar cache de prepared statements
        "command_timeout": 60,
    },
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency que provee una sesión de base de datos.
    
    Uso con FastAPI:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager para usar fuera de FastAPI dependencies.
    
    Uso:
        async with get_db_context() as db:
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Inicializa la base de datos.
    Crea todas las tablas si no existen.
    """
    from app.db.models import Base
    
    logger.info("Initializing database...")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database initialized successfully")


async def close_db() -> None:
    """Cierra las conexiones de la base de datos."""
    await engine.dispose()
    logger.info("Database connections closed")
