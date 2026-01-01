"""
Schemas del microservicio de pagos.
Exporta todos los schemas para fácil acceso.
"""

# Common
from app.schemas.common import (
    APIResponse,
    BaseSchema,
    ErrorResponse,
    PaginatedResponse,
    PaginationParams,
    TimestampMixin,
)

# Payment
from app.schemas.payment import (
    Currency,
    PaymentCreateRequest,
    PaymentIntentResponse,
    PaymentResponse,
    PaymentStatus,
    PaymentSummary,
    PaymentType,
    PaymentUpdateRequest,
)

# Partner
from app.schemas.partner import (
    PartnerRegisterRequest,
    PartnerRegisterResponse,
    PartnerResponse,
    PartnerSecretRotateResponse,
    PartnerStatus,
    PartnerUpdateRequest,
    WebhookEventType,
)

# Webhook
from app.schemas.webhook import (
    NormalizedWebhookEvent,
    OutgoingWebhookPayload,
    StripeWebhookEvent,
    WebhookDeliveryAttempt,
    WebhookDirection,
    WebhookLog,
    WebhookSignature,
    WebhookStatus,
)

__all__ = [
    # Common
    "APIResponse",
    "BaseSchema",
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationParams",
    "TimestampMixin",
    # Payment
    "Currency",
    "PaymentCreateRequest",
    "PaymentIntentResponse",
    "PaymentResponse",
    "PaymentStatus",
    "PaymentSummary",
    "PaymentType",
    "PaymentUpdateRequest",
    # Partner
    "PartnerRegisterRequest",
    "PartnerRegisterResponse",
    "PartnerResponse",
    "PartnerSecretRotateResponse",
    "PartnerStatus",
    "PartnerUpdateRequest",
    "WebhookEventType",
    # Webhook
    "NormalizedWebhookEvent",
    "OutgoingWebhookPayload",
    "StripeWebhookEvent",
    "WebhookDeliveryAttempt",
    "WebhookDirection",
    "WebhookLog",
    "WebhookSignature",
    "WebhookStatus",
]
