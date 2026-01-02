"""
Adapters para proveedores de pago.
Implementación del patrón Adapter para abstraer diferentes pasarelas.
"""

from app.adapters.base import PaymentProvider, PaymentResult, WebhookEvent
from app.adapters.stripe_adapter import StripeAdapter
from app.adapters.mock_adapter import MockAdapter
from app.adapters.factory import get_payment_provider

__all__ = [
    "PaymentProvider",
    "PaymentResult",
    "WebhookEvent",
    "StripeAdapter",
    "MockAdapter",
    "get_payment_provider",
]
