"""
Schemas para webhooks entrantes y salientes.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, TimestampMixin
from app.schemas.partner import WebhookEventType


class WebhookStatus(str, Enum):
    """Estado de entrega de un webhook."""
    
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


class WebhookDirection(str, Enum):
    """Dirección del webhook."""
    
    INCOMING = "incoming"   # De proveedores externos (Stripe, etc.)
    OUTGOING = "outgoing"   # Hacia partners B2B


# ============================================
# Webhooks Entrantes (de Stripe, etc.)
# ============================================

class StripeWebhookEvent(BaseModel):
    """Evento de webhook de Stripe (estructura simplificada)."""
    
    id: str
    type: str
    data: dict[str, Any]
    created: int
    livemode: bool = False


class NormalizedWebhookEvent(BaseSchema):
    """Evento de webhook normalizado (formato interno)."""
    
    event_type: str = Field(..., description="Tipo de evento normalizado")
    provider: str = Field(..., description="Proveedor origen (stripe, mercadopago, etc.)")
    provider_event_id: str = Field(..., description="ID del evento en el proveedor")
    
    # Payload normalizado
    payment_id: UUID | None = None
    amount: int | None = None
    currency: str | None = None
    status: str | None = None
    
    # Datos crudos del proveedor
    raw_data: dict[str, Any] = Field(default_factory=dict)
    
    # Timestamps
    occurred_at: datetime
    received_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# Webhooks Salientes (hacia Partners B2B)
# ============================================

class OutgoingWebhookPayload(BaseSchema):
    """Payload de webhook saliente hacia partners."""
    
    id: UUID = Field(..., description="ID único del webhook")
    event: WebhookEventType = Field(..., description="Tipo de evento")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Datos del evento
    data: dict[str, Any] = Field(..., description="Datos del evento")
    
    # Metadatos
    source: str = "love4pets"
    version: str = "1.0"


class WebhookDeliveryAttempt(BaseSchema):
    """Registro de intento de entrega de webhook."""
    
    webhook_id: UUID
    partner_id: UUID
    attempt_number: int
    status_code: int | None = None
    response_body: str | None = None
    error_message: str | None = None
    attempted_at: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: int | None = None


class WebhookLog(BaseSchema, TimestampMixin):
    """Log de webhook (para auditoría)."""
    
    id: UUID
    direction: WebhookDirection
    event_type: str
    
    # Para incoming
    provider: str | None = None
    provider_event_id: str | None = None
    
    # Para outgoing
    partner_id: UUID | None = None
    partner_name: str | None = None
    
    # Estado
    status: WebhookStatus
    attempts: int = 0
    last_attempt_at: datetime | None = None
    
    # Datos
    payload: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] | None = None


# ============================================
# Schemas para verificación HMAC
# ============================================

class WebhookSignature(BaseModel):
    """Datos de firma de webhook."""
    
    timestamp: int = Field(..., description="Unix timestamp")
    signature: str = Field(..., description="Firma HMAC-SHA256")
    
    @classmethod
    def from_header(cls, header: str) -> "WebhookSignature":
        """
        Parsea el header de firma.
        Formato esperado: "t=1234567890,v1=signature_hex"
        """
        parts = {}
        for item in header.split(","):
            key, value = item.split("=", 1)
            parts[key] = value
        
        return cls(
            timestamp=int(parts.get("t", 0)),
            signature=parts.get("v1", "")
        )
