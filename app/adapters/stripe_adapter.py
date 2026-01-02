"""
Adapter para Stripe.
Implementa PaymentProvider usando el SDK oficial de Stripe.
"""

import stripe
import structlog
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.adapters.base import (
    PaymentProvider,
    PaymentResult,
    PaymentResultStatus,
    RefundResult,
    WebhookEvent,
)
from app.config import settings


logger = structlog.get_logger(__name__)


class StripeAdapter(PaymentProvider):
    """
    Adapter para Stripe Payments.
    
    Usa Stripe Checkout Session para pagos simples.
    Soporta verificación de webhooks con firma.
    """
    
    # Mapeo de estados de Stripe a estados internos
    STATUS_MAP = {
        "requires_payment_method": PaymentResultStatus.PENDING,
        "requires_confirmation": PaymentResultStatus.PENDING,
        "requires_action": PaymentResultStatus.REQUIRES_ACTION,
        "processing": PaymentResultStatus.PENDING,
        "requires_capture": PaymentResultStatus.PENDING,
        "canceled": PaymentResultStatus.FAILED,
        "succeeded": PaymentResultStatus.SUCCESS,
    }
    
    # Mapeo de tipos de evento de Stripe a formato interno
    EVENT_TYPE_MAP = {
        "checkout.session.completed": "payment.succeeded",
        "checkout.session.expired": "payment.failed",
        "payment_intent.succeeded": "payment.succeeded",
        "payment_intent.payment_failed": "payment.failed",
        "payment_intent.canceled": "payment.canceled",
        "charge.refunded": "payment.refunded",
        "charge.dispute.created": "payment.disputed",
    }
    
    def __init__(self, api_key: str | None = None, webhook_secret: str | None = None):
        """
        Inicializa el adapter de Stripe.
        
        Args:
            api_key: Stripe secret key (usa config si no se proporciona)
            webhook_secret: Stripe webhook secret (usa config si no se proporciona)
        """
        self._api_key = api_key or settings.STRIPE_SECRET_KEY
        self._webhook_secret = webhook_secret or settings.STRIPE_WEBHOOK_SECRET
        
        # Configurar cliente de Stripe
        stripe.api_key = self._api_key
        
        logger.info("StripeAdapter initialized")
    
    @property
    def provider_name(self) -> str:
        return "stripe"
    
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
        """Crea una Stripe Checkout Session."""
        try:
            # Preparar metadatos (Stripe solo acepta strings)
            stripe_metadata = {
                "payment_id": str(payment_id),
                **(metadata or {}),
            }
            # Convertir todos los valores a string
            stripe_metadata = {k: str(v) for k, v in stripe_metadata.items()}
            
            # URLs por defecto si no se proporcionan
            default_success_url = "http://localhost:3000/payments/success?session_id={CHECKOUT_SESSION_ID}"
            default_cancel_url = "http://localhost:3000/payments/cancel"
            
            # Crear Checkout Session
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "unit_amount": int(amount),  # Stripe usa centavos
                            "product_data": {
                                "name": description or "Donación Love4Pets",
                            },
                        },
                        "quantity": 1,
                    }
                ],
                metadata=stripe_metadata,
                customer_email=customer_email,
                success_url=success_url or default_success_url,
                cancel_url=cancel_url or default_cancel_url,
            )
            
            logger.info(
                "Stripe Checkout Session created",
                session_id=session.id,
                payment_id=str(payment_id),
            )
            
            return PaymentResult(
                status=PaymentResultStatus.PENDING,
                provider=self.provider_name,
                provider_payment_id=session.id,
                amount=amount,
                currency=currency,
                checkout_url=session.url,
                metadata=stripe_metadata,
                raw_response=dict(session),
            )
            
        except stripe.error.StripeError as e:
            logger.error(
                "Stripe payment creation failed",
                error=str(e),
                payment_id=str(payment_id),
            )
            return PaymentResult(
                status=PaymentResultStatus.FAILED,
                provider=self.provider_name,
                provider_payment_id="",
                amount=amount,
                currency=currency,
                failure_reason=str(e),
            )
    
    async def retrieve_payment(self, provider_payment_id: str) -> PaymentResult:
        """Obtiene el estado de una Checkout Session."""
        try:
            session = stripe.checkout.Session.retrieve(provider_payment_id)
            
            # Mapear estado
            status = PaymentResultStatus.PENDING
            if session.payment_status == "paid":
                status = PaymentResultStatus.SUCCESS
            elif session.status == "expired":
                status = PaymentResultStatus.FAILED
            
            return PaymentResult(
                status=status,
                provider=self.provider_name,
                provider_payment_id=session.id,
                amount=Decimal(session.amount_total or 0),
                currency=session.currency or "usd",
                checkout_url=session.url,
                raw_response=dict(session),
            )
            
        except stripe.error.StripeError as e:
            logger.error("Failed to retrieve Stripe session", error=str(e))
            raise ValueError(f"Failed to retrieve payment: {e}")
    
    async def cancel_payment(self, provider_payment_id: str) -> PaymentResult:
        """Expira una Checkout Session (no se puede cancelar directamente)."""
        try:
            session = stripe.checkout.Session.expire(provider_payment_id)
            
            return PaymentResult(
                status=PaymentResultStatus.FAILED,
                provider=self.provider_name,
                provider_payment_id=session.id,
                amount=Decimal(session.amount_total or 0),
                currency=session.currency or "usd",
                failure_reason="Canceled by user",
            )
            
        except stripe.error.StripeError as e:
            logger.error("Failed to cancel Stripe session", error=str(e))
            raise ValueError(f"Failed to cancel payment: {e}")
    
    async def refund_payment(
        self,
        provider_payment_id: str,
        amount: Decimal | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        """Realiza un reembolso."""
        try:
            # Primero obtener el payment intent de la session
            session = stripe.checkout.Session.retrieve(provider_payment_id)
            payment_intent_id = session.payment_intent
            
            if not payment_intent_id:
                raise ValueError("No payment intent found for this session")
            
            # Crear reembolso
            refund_params: dict[str, Any] = {
                "payment_intent": payment_intent_id,
            }
            if amount:
                refund_params["amount"] = int(amount)
            if reason:
                refund_params["reason"] = "requested_by_customer"
            
            refund = stripe.Refund.create(**refund_params)
            
            return RefundResult(
                status=PaymentResultStatus.SUCCESS if refund.status == "succeeded" else PaymentResultStatus.PENDING,
                provider=self.provider_name,
                provider_refund_id=refund.id,
                provider_payment_id=provider_payment_id,
                amount=Decimal(refund.amount),
                currency=refund.currency,
            )
            
        except stripe.error.StripeError as e:
            logger.error("Failed to refund", error=str(e))
            return RefundResult(
                status=PaymentResultStatus.FAILED,
                provider=self.provider_name,
                provider_refund_id="",
                provider_payment_id=provider_payment_id,
                amount=amount or Decimal(0),
                currency="usd",
                failure_reason=str(e),
            )
    
    def construct_webhook_event(
        self,
        payload: bytes,
        signature: str,
    ) -> WebhookEvent:
        """Construye y valida un evento de webhook de Stripe."""
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature,
                secret=self._webhook_secret,
            )
            
            # Extraer datos del evento
            event_data = event.data.object
            
            # Intentar obtener datos del pago
            provider_payment_id = None
            amount = None
            currency = None
            
            if hasattr(event_data, "id"):
                provider_payment_id = event_data.id
            if hasattr(event_data, "amount_total"):
                amount = Decimal(event_data.amount_total)
            elif hasattr(event_data, "amount"):
                amount = Decimal(event_data.amount)
            if hasattr(event_data, "currency"):
                currency = event_data.currency
            
            # Extraer metadata si existe
            metadata = {}
            if hasattr(event_data, "metadata"):
                metadata = dict(event_data.metadata)
            
            return WebhookEvent(
                event_type=self.normalize_event_type(event.type),
                provider=self.provider_name,
                provider_event_id=event.id,
                provider_payment_id=provider_payment_id,
                amount=amount,
                currency=currency,
                metadata=metadata,
                raw_data=event.to_dict(),
            )
            
        except stripe.error.SignatureVerificationError as e:
            logger.error("Invalid Stripe webhook signature", error=str(e))
            raise ValueError(f"Invalid webhook signature: {e}")
        except Exception as e:
            logger.error("Failed to construct webhook event", error=str(e))
            raise ValueError(f"Failed to process webhook: {e}")
    
    def normalize_event_type(self, provider_event_type: str) -> str:
        """Mapea tipos de evento de Stripe a formato interno."""
        return self.EVENT_TYPE_MAP.get(provider_event_type, provider_event_type)
