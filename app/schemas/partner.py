"""
Schemas para partners B2B y registro de webhooks.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from app.schemas.common import BaseSchema, TimestampMixin


class WebhookEventType(str, Enum):
    """Tipos de eventos disponibles para suscripción."""
    
    # Eventos de pago
    PAYMENT_CREATED = "payment.created"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
    
    # Eventos de adopción (del sistema principal)
    ADOPTION_CREATED = "adoption.created"
    ADOPTION_APPROVED = "adoption.approved"
    ADOPTION_COMPLETED = "adoption.completed"
    
    # Eventos de campaña
    CAMPAIGN_GOAL_REACHED = "campaign.goal_reached"
    CAMPAIGN_ENDED = "campaign.ended"
    
    # Eventos genéricos para B2B
    ORDER_CREATED = "order.created"
    SERVICE_ACTIVATED = "service.activated"


class PartnerStatus(str, Enum):
    """Estados de un partner."""
    
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


# ============================================
# Request Schemas
# ============================================

class PartnerRegisterRequest(BaseSchema):
    """Request para registrar un nuevo partner."""
    
    name: str = Field(..., min_length=2, max_length=100, description="Nombre del partner")
    webhook_url: HttpUrl = Field(..., description="URL del webhook del partner")
    events: list[WebhookEventType] = Field(
        ..., 
        min_length=1,
        description="Lista de eventos a los que se suscribe"
    )
    description: str | None = Field(None, max_length=500)
    contact_email: str | None = Field(None, description="Email de contacto")


class PartnerUpdateRequest(BaseSchema):
    """Request para actualizar un partner."""
    
    name: str | None = Field(None, min_length=2, max_length=100)
    webhook_url: HttpUrl | None = None
    events: list[WebhookEventType] | None = None
    status: PartnerStatus | None = None
    description: str | None = None
    contact_email: str | None = None


# ============================================
# Response Schemas
# ============================================

class PartnerResponse(BaseSchema, TimestampMixin):
    """Respuesta con datos de un partner (sin secret)."""
    
    id: UUID
    name: str
    webhook_url: str
    events: list[WebhookEventType]
    status: PartnerStatus
    description: str | None = None
    contact_email: str | None = None
    
    # Estadísticas
    total_webhooks_sent: int = 0
    last_webhook_at: datetime | None = None


class PartnerRegisterResponse(BaseSchema):
    """Respuesta al registrar un partner (incluye secret)."""
    
    id: UUID
    name: str
    webhook_url: str
    events: list[WebhookEventType]
    secret: str = Field(..., description="Secret HMAC para verificar webhooks. ¡Guardar de forma segura!")
    status: PartnerStatus
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "Partner Tours",
                "webhook_url": "https://partner.com/webhooks/love4pets",
                "events": ["payment.succeeded", "adoption.completed"],
                "secret": "whsec_abc123...",
                "status": "active"
            }
        }


class PartnerSecretRotateResponse(BaseSchema):
    """Respuesta al rotar el secret de un partner."""
    
    id: UUID
    new_secret: str = Field(..., description="Nuevo secret HMAC")
    old_secret_valid_until: datetime = Field(
        ..., 
        description="El secret anterior será válido hasta esta fecha"
    )
