"""
Interfaz base abstracta para proveedores de pago.
Define el contrato que todos los adapters deben implementar.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


class PaymentResultStatus(str, Enum):
    """Estado del resultado de una operación de pago."""
    
    SUCCESS = "success"
    PENDING = "pending"
    FAILED = "failed"
    REQUIRES_ACTION = "requires_action"  # Ej: 3D Secure


@dataclass
class PaymentResult:
    """
    Resultado normalizado de una operación de pago.
    Todos los adapters deben retornar esta estructura.
    """
    
    status: PaymentResultStatus
    provider: str  # "stripe", "mock", etc.
    provider_payment_id: str  # ID del pago en el proveedor
    
    # Datos del pago
    amount: Decimal
    currency: str
    
    # URLs para el cliente
    client_secret: str | None = None  # Para Stripe Elements
    checkout_url: str | None = None   # Para Stripe Checkout
    
    # Información adicional
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class WebhookEvent:
    """
    Evento de webhook normalizado.
    Representa un evento recibido de cualquier proveedor en formato común.
    """
    
    event_type: str  # Tipo normalizado: "payment.succeeded", "payment.failed", etc.
    provider: str
    provider_event_id: str
    
    # Datos del pago asociado
    provider_payment_id: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    status: str | None = None
    
    # Metadatos
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)
    
    # Timestamp del evento
    occurred_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RefundResult:
    """Resultado de una operación de reembolso."""
    
    status: PaymentResultStatus
    provider: str
    provider_refund_id: str
    provider_payment_id: str
    amount: Decimal
    currency: str
    failure_reason: str | None = None


class PaymentProvider(ABC):
    """
    Interfaz abstracta para proveedores de pago.
    
    Todos los adapters de pasarelas de pago (Stripe, MercadoPago, etc.)
    deben implementar esta interfaz para garantizar interoperabilidad.
    """
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Nombre del proveedor (ej: 'stripe', 'mercadopago')."""
        pass
    
    @abstractmethod
    async def create_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_id: UUID,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        customer_email: str | None = None,
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PaymentResult:
        """
        Crea un nuevo pago/payment intent.
        
        Args:
            amount: Monto en la unidad menor (centavos para USD)
            currency: Código de moneda ISO (usd, eur, mxn)
            payment_id: ID interno del pago en nuestra BD
            description: Descripción del pago
            metadata: Metadatos adicionales
            customer_email: Email del cliente
            success_url: URL de redirección en caso de éxito
            cancel_url: URL de redirección en caso de cancelación
            
        Returns:
            PaymentResult con los datos del pago creado
        """
        pass
    
    @abstractmethod
    async def retrieve_payment(self, provider_payment_id: str) -> PaymentResult:
        """
        Obtiene el estado actual de un pago.
        
        Args:
            provider_payment_id: ID del pago en el proveedor
            
        Returns:
            PaymentResult con el estado actual
        """
        pass
    
    @abstractmethod
    async def cancel_payment(self, provider_payment_id: str) -> PaymentResult:
        """
        Cancela un pago pendiente.
        
        Args:
            provider_payment_id: ID del pago en el proveedor
            
        Returns:
            PaymentResult con el resultado de la cancelación
        """
        pass
    
    @abstractmethod
    async def refund_payment(
        self,
        provider_payment_id: str,
        amount: Decimal | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        """
        Realiza un reembolso total o parcial.
        
        Args:
            provider_payment_id: ID del pago en el proveedor
            amount: Monto a reembolsar (None = total)
            reason: Razón del reembolso
            
        Returns:
            RefundResult con los datos del reembolso
        """
        pass
    
    @abstractmethod
    def construct_webhook_event(
        self,
        payload: bytes,
        signature: str,
    ) -> WebhookEvent:
        """
        Construye y valida un evento de webhook.
        
        Args:
            payload: Cuerpo crudo del request
            signature: Header de firma del webhook
            
        Returns:
            WebhookEvent normalizado
            
        Raises:
            ValueError: Si la firma es inválida
        """
        pass
    
    def normalize_event_type(self, provider_event_type: str) -> str:
        """
        Normaliza el tipo de evento del proveedor a nuestro formato interno.
        
        Por defecto retorna el mismo valor. Los adapters pueden sobreescribir
        este método para mapear tipos de eventos específicos.
        """
        return provider_event_type
