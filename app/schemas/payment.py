"""
Schemas para pagos y transacciones.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import BaseSchema, TimestampMixin


class PaymentStatus(str, Enum):
    """Estados posibles de un pago."""
    
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class PaymentType(str, Enum):
    """Tipos de pago soportados."""
    
    DONATION = "donation"           # Donación general
    CAMPAIGN = "campaign"           # Donación a campaña específica
    ADOPTION_FEE = "adoption_fee"   # Cuota de adopción
    SPONSORSHIP = "sponsorship"     # Apadrinamiento


class Currency(str, Enum):
    """Monedas soportadas."""
    
    USD = "usd"
    EUR = "eur"
    MXN = "mxn"


# ============================================
# Request Schemas (entrada)
# ============================================

class PaymentCreateRequest(BaseSchema):
    """Request para crear un nuevo pago."""
    
    amount: Decimal = Field(..., gt=0, description="Monto del pago en la unidad menor (centavos)")
    currency: Currency = Currency.USD
    payment_type: PaymentType = PaymentType.DONATION
    
    # Referencias opcionales
    user_id: UUID | None = Field(None, description="ID del usuario que realiza el pago")
    campaign_id: UUID | None = Field(None, description="ID de la campaña (si aplica)")
    animal_id: UUID | None = Field(None, description="ID del animal (si aplica)")
    refugio_id: UUID | None = Field(None, description="ID del refugio beneficiario")
    
    # Datos del pagador (si no hay user_id)
    payer_email: str | None = Field(None, description="Email del pagador")
    payer_name: str | None = Field(None, description="Nombre del pagador")
    
    # Metadatos adicionales
    description: str | None = Field(None, max_length=500)
    metadata: dict[str, Any] | None = Field(default_factory=dict)
    
    # URL de retorno después del pago
    success_url: str | None = None
    cancel_url: str | None = None
    
    @field_validator("amount", mode="before")
    @classmethod
    def convert_amount(cls, v):
        """Convierte a Decimal si es necesario."""
        if isinstance(v, (int, float)):
            return Decimal(str(v))
        return v


class PaymentUpdateRequest(BaseSchema):
    """Request para actualizar estado de un pago (interno)."""
    
    status: PaymentStatus
    provider_payment_id: str | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] | None = None


# ============================================
# Response Schemas (salida)
# ============================================

class PaymentResponse(BaseSchema, TimestampMixin):
    """Respuesta con datos de un pago."""
    
    id: UUID
    amount: Decimal
    currency: Currency
    status: PaymentStatus
    payment_type: PaymentType
    
    # Referencias
    user_id: UUID | None = None
    campaign_id: UUID | None = None
    animal_id: UUID | None = None
    refugio_id: UUID | None = None
    
    # Datos del pagador
    payer_email: str | None = None
    payer_name: str | None = None
    
    # Datos del proveedor
    provider: str  # "stripe", "mock", etc.
    provider_payment_id: str | None = None
    
    # URLs
    checkout_url: str | None = None
    
    # Extra
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
    
    # Idempotencia
    idempotency_key: str | None = None


class PaymentIntentResponse(BaseSchema):
    """Respuesta al crear un payment intent (para frontend)."""
    
    payment_id: UUID
    client_secret: str | None = None  # Para Stripe Elements
    checkout_url: str | None = None   # Para Stripe Checkout
    status: PaymentStatus
    provider: str


class PaymentSummary(BaseSchema):
    """Resumen de pago (para listados)."""
    
    id: UUID
    amount: Decimal
    currency: Currency
    status: PaymentStatus
    payment_type: PaymentType
    payer_name: str | None = None
    created_at: datetime
