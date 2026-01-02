"""
Control de idempotencia para requests.
Previene procesamiento duplicado de pagos.
"""

import json
from datetime import timedelta
from typing import Any

import structlog
import redis.asyncio as redis
from redis.exceptions import RedisError

from app.config import settings


logger = structlog.get_logger(__name__)

# Tiempo de expiración de claves de idempotencia (24 horas)
IDEMPOTENCY_TTL_HOURS = 24


class IdempotencyManager:
    """
    Gestor de idempotencia usando Redis.
    
    Almacena respuestas de requests previos para retornarlas
    si se recibe la misma Idempotency-Key.
    """
    
    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client
        self._prefix = "idempotency:"
    
    def _make_key(self, idempotency_key: str) -> str:
        """Genera la clave Redis."""
        return f"{self._prefix}{idempotency_key}"
    
    async def get_cached_response(
        self,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """
        Obtiene una respuesta cacheada por Idempotency-Key.
        
        Args:
            idempotency_key: Clave de idempotencia del request
            
        Returns:
            Respuesta cacheada o None si no existe
        """
        try:
            key = self._make_key(idempotency_key)
            data = await self._redis.get(key)
            
            if data:
                logger.info(
                    "Idempotency cache hit",
                    idempotency_key=idempotency_key,
                )
                return json.loads(data)
            
            return None
            
        except RedisError as e:
            logger.error(
                "Redis error getting idempotency key",
                error=str(e),
                idempotency_key=idempotency_key,
            )
            # En caso de error de Redis, permitir que el request continúe
            return None
    
    async def cache_response(
        self,
        idempotency_key: str,
        response: dict[str, Any],
        ttl_hours: int = IDEMPOTENCY_TTL_HOURS,
    ) -> bool:
        """
        Cachea una respuesta para una Idempotency-Key.
        
        Args:
            idempotency_key: Clave de idempotencia
            response: Respuesta a cachear
            ttl_hours: Tiempo de vida en horas
            
        Returns:
            True si se guardó correctamente
        """
        try:
            key = self._make_key(idempotency_key)
            data = json.dumps(response, default=str)
            
            await self._redis.setex(
                key,
                timedelta(hours=ttl_hours),
                data,
            )
            
            logger.info(
                "Response cached for idempotency",
                idempotency_key=idempotency_key,
                ttl_hours=ttl_hours,
            )
            return True
            
        except RedisError as e:
            logger.error(
                "Redis error caching response",
                error=str(e),
                idempotency_key=idempotency_key,
            )
            return False
    
    async def is_processing(self, idempotency_key: str) -> bool:
        """
        Verifica si un request con esta key está siendo procesado.
        
        Usa un lock temporal para prevenir race conditions.
        """
        try:
            lock_key = f"{self._prefix}lock:{idempotency_key}"
            
            # Intentar adquirir lock (30 segundos de timeout)
            acquired = await self._redis.set(
                lock_key,
                "processing",
                nx=True,  # Solo si no existe
                ex=30,    # Expira en 30 segundos
            )
            
            return not acquired  # Si no pudimos adquirir, alguien más está procesando
            
        except RedisError as e:
            logger.error(
                "Redis error checking processing lock",
                error=str(e),
                idempotency_key=idempotency_key,
            )
            return False
    
    async def release_lock(self, idempotency_key: str) -> None:
        """Libera el lock de procesamiento."""
        try:
            lock_key = f"{self._prefix}lock:{idempotency_key}"
            await self._redis.delete(lock_key)
        except RedisError as e:
            logger.error(
                "Redis error releasing lock",
                error=str(e),
                idempotency_key=idempotency_key,
            )
    
    async def delete(self, idempotency_key: str) -> bool:
        """
        Elimina una entrada de idempotencia.
        
        Útil si un request falló y queremos permitir reintentos.
        """
        try:
            key = self._make_key(idempotency_key)
            await self._redis.delete(key)
            return True
        except RedisError as e:
            logger.error(
                "Redis error deleting idempotency key",
                error=str(e),
                idempotency_key=idempotency_key,
            )
            return False


# Singleton del cliente Redis
_redis_client: redis.Redis | None = None
_idempotency_manager: IdempotencyManager | None = None


async def get_redis_client() -> redis.Redis:
    """Obtiene o crea el cliente Redis."""
    global _redis_client
    
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("Redis client initialized", url=settings.REDIS_URL.split("@")[-1])
    
    return _redis_client


async def get_idempotency_manager() -> IdempotencyManager:
    """Obtiene o crea el gestor de idempotencia."""
    global _idempotency_manager
    
    if _idempotency_manager is None:
        redis_client = await get_redis_client()
        _idempotency_manager = IdempotencyManager(redis_client)
    
    return _idempotency_manager


async def close_redis() -> None:
    """Cierra la conexión de Redis."""
    global _redis_client, _idempotency_manager
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        _idempotency_manager = None
        logger.info("Redis connection closed")


class InMemoryIdempotencyManager:
    """
    Implementación en memoria para desarrollo sin Redis.
    
    NO USAR EN PRODUCCIÓN - no es persistente ni distribuido.
    """
    
    def __init__(self):
        self._cache: dict[str, dict[str, Any]] = {}
        self._locks: set[str] = set()
    
    async def get_cached_response(self, idempotency_key: str) -> dict[str, Any] | None:
        return self._cache.get(idempotency_key)
    
    async def cache_response(
        self,
        idempotency_key: str,
        response: dict[str, Any],
        ttl_hours: int = IDEMPOTENCY_TTL_HOURS,
    ) -> bool:
        self._cache[idempotency_key] = response
        return True
    
    async def is_processing(self, idempotency_key: str) -> bool:
        if idempotency_key in self._locks:
            return True
        self._locks.add(idempotency_key)
        return False
    
    async def release_lock(self, idempotency_key: str) -> None:
        self._locks.discard(idempotency_key)
    
    async def delete(self, idempotency_key: str) -> bool:
        self._cache.pop(idempotency_key, None)
        return True


async def get_idempotency_manager_with_fallback() -> IdempotencyManager | InMemoryIdempotencyManager:
    """
    Obtiene el gestor de idempotencia con fallback a memoria.
    
    Intenta conectar a Redis, si falla usa implementación en memoria.
    """
    try:
        return await get_idempotency_manager()
    except Exception as e:
        logger.warning(
            "Failed to connect to Redis, using in-memory idempotency",
            error=str(e),
        )
        return InMemoryIdempotencyManager()
