"""
Modelos SQLAlchemy para el microservicio de pagos.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.schemas.payment import Currency, PaymentStatus, PaymentType
from app.schemas.partner import PartnerStatus, WebhookEventType
from app.schemas.webhook import WebhookDirection, WebhookStatus


class Base(DeclarativeBase):
    """Base para todos los modelos."""
    
    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[str]: ARRAY(String),
    }


class TimestampMixin:
    """Mixin para campos de timestamp."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )


class Payment(Base, TimestampMixin):
    """Modelo para pagos/transacciones."""
    
    __tablename__ = "payments"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Datos del pago
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="usd",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=PaymentStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    payment_type: Mapped[str] = mapped_column(
        String(20),
        default=PaymentType.DONATION.value,
        nullable=False,
    )
    
    # Referencias a entidades del sistema principal
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    animal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    refugio_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    causa_urgente_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="ID de la causa urgente para donaciones específicas",
    )
    
    # Datos del pagador (si no hay user_id)
    payer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Datos del proveedor de pago
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="mock",
    )
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )
    
    # URLs
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Metadatos
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Idempotencia
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )
    
    def __repr__(self) -> str:
        return f"<Payment {self.id} - {self.amount} {self.currency} ({self.status})>"


class Partner(Base, TimestampMixin):
    """Modelo para partners B2B registrados."""
    
    __tablename__ = "partners"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Datos del partner
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Webhook configuration
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
    )
    
    # Seguridad
    secret: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    # Secret anterior (para rotación gradual)
    previous_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previous_secret_valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Estado
    status: Mapped[str] = mapped_column(
        String(20),
        default=PartnerStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    
    # Estadísticas
    total_webhooks_sent: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    last_webhook_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    def __repr__(self) -> str:
        return f"<Partner {self.name} ({self.status})>"


class WebhookLog(Base, TimestampMixin):
    """Modelo para logs de webhooks (entrantes y salientes)."""
    
    __tablename__ = "webhook_logs"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Dirección y tipo
    direction: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    
    # Para webhooks entrantes
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
    )
    
    # Para webhooks salientes
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    partner_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    # Referencia al pago
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    
    # Estado de entrega
    status: Mapped[str] = mapped_column(
        String(20),
        default=WebhookStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Datos
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # HTTP details
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    def __repr__(self) -> str:
        return f"<WebhookLog {self.direction} {self.event_type} ({self.status})>"
