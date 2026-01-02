"""
Factory para obtener el proveedor de pago correcto.
Implementa el patrón Factory para instanciar adapters.
"""

from functools import lru_cache
import structlog

from app.adapters.base import PaymentProvider
from app.adapters.stripe_adapter import StripeAdapter
from app.adapters.mock_adapter import MockAdapter
from app.config import settings


logger = structlog.get_logger(__name__)


# Registro de proveedores disponibles
PROVIDERS: dict[str, type[PaymentProvider]] = {
    "stripe": StripeAdapter,
    "mock": MockAdapter,
}


@lru_cache()
def get_payment_provider() -> PaymentProvider:
    """
    Factory que retorna el proveedor de pago configurado.
    
    Lee la configuración PAYMENT_PROVIDER y retorna la instancia
    correspondiente. La instancia es cacheada para reutilización.
    
    Returns:
        Instancia del PaymentProvider configurado
        
    Raises:
        ValueError: Si el proveedor no está soportado
    """
    provider_name = settings.PAYMENT_PROVIDER.lower()
    
    if provider_name not in PROVIDERS:
        raise ValueError(
            f"Payment provider '{provider_name}' not supported. "
            f"Available: {list(PROVIDERS.keys())}"
        )
    
    provider_class = PROVIDERS[provider_name]
    provider = provider_class()
    
    logger.info(
        "Payment provider initialized",
        provider=provider_name,
    )
    
    return provider


def get_provider_by_name(name: str) -> PaymentProvider:
    """
    Obtiene un proveedor específico por nombre.
    
    Útil cuando se necesita un proveedor diferente al configurado,
    por ejemplo para procesar webhooks de un proveedor específico.
    
    Args:
        name: Nombre del proveedor ("stripe", "mock")
        
    Returns:
        Instancia del PaymentProvider
        
    Raises:
        ValueError: Si el proveedor no está soportado
    """
    name = name.lower()
    
    if name not in PROVIDERS:
        raise ValueError(
            f"Payment provider '{name}' not supported. "
            f"Available: {list(PROVIDERS.keys())}"
        )
    
    return PROVIDERS[name]()
