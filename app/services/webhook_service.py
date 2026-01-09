"""
Servicio para gestión de webhooks.
Procesa webhooks entrantes y envía webhooks salientes a partners.
"""

import json
import time
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_payment_provider, PaymentProvider
from app.adapters.base import WebhookEvent
from app.adapters.factory import get_provider_by_name
from app.db.models import Partner, WebhookLog
from app.db.repositories import PartnerRepository, PaymentRepository, WebhookLogRepository
from app.schemas.partner import WebhookEventType
from app.schemas.payment import PaymentStatus
from app.schemas.webhook import OutgoingWebhookPayload, WebhookDirection
from app.utils.hmac_utils import create_webhook_signature_header
from app.utils.exceptions import (
    PaymentNotFoundError,
    WebhookVerificationError,
    WebhookDeliveryError,
)
from app.config import settings


logger = structlog.get_logger(__name__)

# Timeout para envío de webhooks
WEBHOOK_TIMEOUT_SECONDS = 10


class WebhookService:
    """
    Servicio para gestión de webhooks.
    
    - Procesa webhooks entrantes de proveedores de pago (Stripe)
    - Envía webhooks salientes a partners B2B
    - Notifica a n8n para orquestación
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.payment_repo = PaymentRepository(db)
        self.partner_repo = PartnerRepository(db)
        self.webhook_repo = WebhookLogRepository(db)
    
    async def process_stripe_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> dict[str, Any]:
        """
        Procesa un webhook de Stripe.
        
        1. Valida la firma
        2. Normaliza el evento
        3. Actualiza el estado del pago
        4. Registra el webhook
        5. Dispara webhooks a partners suscritos
        6. Notifica a n8n
        
        Args:
            payload: Cuerpo crudo del webhook
            signature: Header Stripe-Signature
            
        Returns:
            Dict con resultado del procesamiento
        """
        provider = get_provider_by_name("stripe")
        
        # Validar y construir evento
        try:
            event = provider.construct_webhook_event(payload, signature)
        except ValueError as e:
            raise WebhookVerificationError(str(e))
        
        logger.info(
            "Stripe webhook received",
            event_type=event.event_type,
            provider_event_id=event.provider_event_id,
        )
        
        # Verificar que no hayamos procesado este evento antes
        existing = await self.webhook_repo.get_by_provider_event_id(event.provider_event_id)
        if existing:
            logger.info(
                "Webhook already processed",
                webhook_id=str(existing.id),
                provider_event_id=event.provider_event_id,
            )
            return {"status": "already_processed", "webhook_id": str(existing.id)}
        
        # Procesar según tipo de evento
        payment_id = await self._process_payment_event(event)
        
        # Registrar webhook entrante
        webhook_log = await self.webhook_repo.create_incoming(
            event_type=event.event_type,
            provider=event.provider,
            provider_event_id=event.provider_event_id,
            payload=event.raw_data,
            payment_id=payment_id,
        )
        
        # Disparar webhooks a partners
        if payment_id:
            await self._dispatch_to_partners(
                event_type=event.event_type,
                payment_id=payment_id,
            )
        
        # Notificar a n8n si está configurado
        await self._notify_n8n(event, payment_id)
        
        return {
            "status": "processed",
            "webhook_id": str(webhook_log.id),
            "event_type": event.event_type,
            "payment_id": str(payment_id) if payment_id else None,
        }
    
    async def process_mock_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> dict[str, Any]:
        """Procesa un webhook del proveedor mock."""
        provider = get_provider_by_name("mock")
        
        try:
            event = provider.construct_webhook_event(payload, signature)
        except ValueError as e:
            raise WebhookVerificationError(str(e))
        
        payment_id = await self._process_payment_event(event)
        
        webhook_log = await self.webhook_repo.create_incoming(
            event_type=event.event_type,
            provider=event.provider,
            provider_event_id=event.provider_event_id,
            payload=event.raw_data,
            payment_id=payment_id,
        )
        
        if payment_id:
            await self._dispatch_to_partners(event.event_type, payment_id)
        
        await self._notify_n8n(event, payment_id)
        
        return {
            "status": "processed",
            "webhook_id": str(webhook_log.id),
            "event_type": event.event_type,
        }
    
    async def _process_payment_event(self, event: WebhookEvent) -> UUID | None:
        """
        Procesa un evento de pago y actualiza el estado en BD.
        
        Returns:
            ID del pago afectado o None
        """
        if not event.provider_payment_id:
            return None
        
        # Buscar pago por provider_payment_id
        payment = await self.payment_repo.get_by_provider_id(event.provider_payment_id)
        
        if not payment:
            # Intentar buscar por metadata.payment_id
            if event.metadata and "payment_id" in event.metadata:
                try:
                    payment_id = UUID(event.metadata["payment_id"])
                    payment = await self.payment_repo.get_by_id(payment_id)
                except (ValueError, TypeError):
                    pass
        
        if not payment:
            logger.warning(
                "Payment not found for webhook event",
                provider_payment_id=event.provider_payment_id,
            )
            return None
        
        # Mapear tipo de evento a estado
        status_map = {
            "payment.succeeded": PaymentStatus.SUCCEEDED,
            "payment.failed": PaymentStatus.FAILED,
            "payment.canceled": PaymentStatus.CANCELED,
            "payment.refunded": PaymentStatus.REFUNDED,
        }
        
        new_status = status_map.get(event.event_type)
        
        if new_status and payment.status != new_status.value:
            await self.payment_repo.update_status(
                payment_id=payment.id,
                status=new_status,
            )
            
            logger.info(
                "Payment status updated from webhook",
                payment_id=str(payment.id),
                new_status=new_status.value,
            )
        
        return payment.id
    
    async def _dispatch_to_partners(
        self,
        event_type: str,
        payment_id: UUID,
    ) -> list[UUID]:
        """
        Envía webhooks a todos los partners suscritos al evento.
        
        Returns:
            Lista de IDs de webhook logs creados
        """
        # Mapear evento a WebhookEventType
        try:
            webhook_event = WebhookEventType(event_type)
        except ValueError:
            logger.debug(
                "Event type not in partner events",
                event_type=event_type,
            )
            return []
        
        # Obtener partners suscritos
        partners = await self.partner_repo.list_by_event(event_type)
        
        if not partners:
            return []
        
        # Obtener datos del pago
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            return []
        
        # Construir payload
        payload_data = {
            "payment_id": str(payment.id),
            "amount": float(payment.amount),
            "currency": payment.currency,
            "status": payment.status,
            "payment_type": payment.payment_type,
            "campaign_id": str(payment.campaign_id) if payment.campaign_id else None,
            "refugio_id": str(payment.refugio_id) if payment.refugio_id else None,
            "metadata": payment.payment_metadata,
        }
        
        webhook_ids = []
        
        for partner in partners:
            webhook_id = await self.send_webhook_to_partner(
                partner=partner,
                event_type=webhook_event,
                data=payload_data,
                payment_id=payment_id,
            )
            if webhook_id:
                webhook_ids.append(webhook_id)
        
        return webhook_ids
    
    async def send_webhook_to_partner(
        self,
        partner: Partner,
        event_type: WebhookEventType,
        data: dict[str, Any],
        payment_id: UUID | None = None,
    ) -> UUID | None:
        """
        Envía un webhook a un partner específico.
        
        Args:
            partner: Partner destino
            event_type: Tipo de evento
            data: Datos del evento
            payment_id: ID del pago relacionado (opcional)
            
        Returns:
            ID del webhook log creado
        """
        # Crear payload
        webhook_payload = OutgoingWebhookPayload(
            id=uuid4(),
            event=event_type,
            timestamp=datetime.utcnow(),
            data=data,
        )
        
        payload_bytes = json.dumps(
            webhook_payload.model_dump(mode="json"),
            default=str,
        ).encode("utf-8")
        
        # Crear firma
        signature = create_webhook_signature_header(payload_bytes, partner.secret)
        
        # Crear log antes de enviar
        webhook_log = await self.webhook_repo.create_outgoing(
            event_type=event_type.value,
            partner_id=partner.id,
            partner_name=partner.name,
            payload=webhook_payload.model_dump(mode="json"),
            payment_id=payment_id,
        )
        
        # Enviar webhook
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    partner.webhook_url,
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": signature,
                        "X-Webhook-Id": str(webhook_payload.id),
                        "X-Event-Type": event_type.value,
                        "User-Agent": "Love4Pets-Payments/1.0",
                    },
                )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            if response.status_code >= 200 and response.status_code < 300:
                await self.webhook_repo.mark_delivered(
                    webhook_id=webhook_log.id,
                    response_status_code=response.status_code,
                    response={"body": response.text[:500]},  # Limitar tamaño
                    duration_ms=duration_ms,
                )
                
                # Actualizar estadísticas del partner
                await self.partner_repo.increment_webhooks_sent(partner.id)
                
                logger.info(
                    "Webhook delivered",
                    webhook_id=str(webhook_log.id),
                    partner=partner.name,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )
            else:
                await self.webhook_repo.mark_failed(
                    webhook_id=webhook_log.id,
                    error_message=f"HTTP {response.status_code}: {response.text[:200]}",
                    response_status_code=response.status_code,
                    duration_ms=duration_ms,
                )
                
                logger.warning(
                    "Webhook delivery failed",
                    webhook_id=str(webhook_log.id),
                    partner=partner.name,
                    status_code=response.status_code,
                )
            
            return webhook_log.id
            
        except httpx.TimeoutException:
            duration_ms = int((time.time() - start_time) * 1000)
            await self.webhook_repo.mark_failed(
                webhook_id=webhook_log.id,
                error_message="Request timeout",
                duration_ms=duration_ms,
            )
            logger.error(
                "Webhook timeout",
                webhook_id=str(webhook_log.id),
                partner=partner.name,
            )
            return webhook_log.id
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            await self.webhook_repo.mark_failed(
                webhook_id=webhook_log.id,
                error_message=str(e),
                duration_ms=duration_ms,
            )
            logger.error(
                "Webhook delivery error",
                webhook_id=str(webhook_log.id),
                partner=partner.name,
                error=str(e),
            )
            return webhook_log.id
    
    async def _notify_n8n(
        self,
        event: WebhookEvent,
        payment_id: UUID | None,
    ) -> None:
        """
        Notifica a n8n sobre el evento para orquestación.
        """
        if not settings.N8N_WEBHOOK_URL:
            return
        
        try:
            payload = {
                "event_type": event.event_type,
                "provider": event.provider,
                "payment_id": str(payment_id) if payment_id else None,
                "timestamp": datetime.utcnow().isoformat(),
                "data": event.raw_data,
            }
            
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    settings.N8N_WEBHOOK_URL,
                    json=payload,
                )
            
            logger.info("n8n notified", event_type=event.event_type)
            
        except Exception as e:
            # No fallar si n8n no está disponible
            logger.warning("Failed to notify n8n", error=str(e))
    
    async def retry_pending_webhooks(self) -> int:
        """
        Reintenta webhooks pendientes.
        
        Returns:
            Número de webhooks reintentados
        """
        pending = await self.webhook_repo.get_pending_retries()
        
        for webhook in pending:
            partner = await self.partner_repo.get_by_id(webhook.partner_id)
            if not partner:
                continue
            
            # Reenviar
            await self._retry_webhook(webhook, partner)
        
        return len(pending)
    
    async def _retry_webhook(
        self,
        webhook: WebhookLog,
        partner: Partner,
    ) -> None:
        """Reintenta enviar un webhook."""
        payload_bytes = json.dumps(webhook.payload, default=str).encode("utf-8")
        signature = create_webhook_signature_header(payload_bytes, partner.secret)
        
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    partner.webhook_url,
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": signature,
                        "X-Webhook-Id": str(webhook.id),
                        "X-Retry-Count": str(webhook.attempts),
                    },
                )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            if 200 <= response.status_code < 300:
                await self.webhook_repo.mark_delivered(
                    webhook_id=webhook.id,
                    response_status_code=response.status_code,
                    duration_ms=duration_ms,
                )
                await self.partner_repo.increment_webhooks_sent(partner.id)
            else:
                await self.webhook_repo.mark_failed(
                    webhook_id=webhook.id,
                    error_message=f"HTTP {response.status_code}",
                    response_status_code=response.status_code,
                    duration_ms=duration_ms,
                )
                
        except Exception as e:
            await self.webhook_repo.mark_failed(
                webhook_id=webhook.id,
                error_message=str(e),
            )
