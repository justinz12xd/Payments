"""
Repositorio para operaciones de WebhookLog.
"""

from datetime import datetime, timedelta
from typing import Any, Sequence
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebhookLog
from app.schemas.webhook import WebhookDirection, WebhookStatus


logger = structlog.get_logger(__name__)


class WebhookLogRepository:
    """Repositorio para operaciones CRUD de logs de webhooks."""
    
    # Configuración de reintentos
    MAX_ATTEMPTS = 5
    RETRY_DELAYS_MINUTES = [1, 5, 30, 120, 720]  # 1min, 5min, 30min, 2h, 12h
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_incoming(
        self,
        event_type: str,
        provider: str,
        provider_event_id: str,
        payload: dict[str, Any],
        payment_id: UUID | None = None,
    ) -> WebhookLog:
        """Registra un webhook entrante."""
        webhook_log = WebhookLog(
            direction=WebhookDirection.INCOMING.value,
            event_type=event_type,
            provider=provider,
            provider_event_id=provider_event_id,
            payment_id=payment_id,
            payload=payload,
            status=WebhookStatus.DELIVERED.value,  # Entrantes se marcan como delivered
            attempts=1,
            last_attempt_at=datetime.utcnow(),
        )
        
        self.db.add(webhook_log)
        await self.db.flush()
        await self.db.refresh(webhook_log)
        
        logger.info(
            "Incoming webhook logged",
            webhook_id=str(webhook_log.id),
            event_type=event_type,
            provider=provider,
        )
        return webhook_log
    
    async def create_outgoing(
        self,
        event_type: str,
        partner_id: UUID,
        partner_name: str,
        payload: dict[str, Any],
        payment_id: UUID | None = None,
    ) -> WebhookLog:
        """Crea un registro para webhook saliente (pendiente de envío)."""
        webhook_log = WebhookLog(
            direction=WebhookDirection.OUTGOING.value,
            event_type=event_type,
            partner_id=partner_id,
            partner_name=partner_name,
            payment_id=payment_id,
            payload=payload,
            status=WebhookStatus.PENDING.value,
            attempts=0,
        )
        
        self.db.add(webhook_log)
        await self.db.flush()
        await self.db.refresh(webhook_log)
        
        logger.info(
            "Outgoing webhook created",
            webhook_id=str(webhook_log.id),
            event_type=event_type,
            partner_name=partner_name,
        )
        return webhook_log
    
    async def get_by_id(self, webhook_id: UUID) -> WebhookLog | None:
        """Obtiene un webhook log por ID."""
        result = await self.db.execute(
            select(WebhookLog).where(WebhookLog.id == webhook_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_provider_event_id(self, provider_event_id: str) -> WebhookLog | None:
        """Obtiene un webhook por ID del evento del proveedor."""
        result = await self.db.execute(
            select(WebhookLog).where(WebhookLog.provider_event_id == provider_event_id)
        )
        return result.scalar_one_or_none()
    
    async def mark_delivered(
        self,
        webhook_id: UUID,
        response_status_code: int,
        response: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> WebhookLog | None:
        """Marca un webhook como entregado exitosamente."""
        await self.db.execute(
            update(WebhookLog)
            .where(WebhookLog.id == webhook_id)
            .values(
                status=WebhookStatus.DELIVERED.value,
                attempts=WebhookLog.attempts + 1,
                last_attempt_at=datetime.utcnow(),
                response_status_code=response_status_code,
                response=response,
                duration_ms=duration_ms,
                next_retry_at=None,
                updated_at=datetime.utcnow(),
            )
        )
        await self.db.flush()
        
        logger.info("Webhook marked as delivered", webhook_id=str(webhook_id))
        return await self.get_by_id(webhook_id)
    
    async def mark_failed(
        self,
        webhook_id: UUID,
        error_message: str,
        response_status_code: int | None = None,
        duration_ms: int | None = None,
    ) -> WebhookLog | None:
        """
        Marca un intento de webhook como fallido.
        
        Si no se han agotado los reintentos, programa el siguiente.
        """
        webhook = await self.get_by_id(webhook_id)
        if not webhook:
            return None
        
        new_attempts = webhook.attempts + 1
        
        # Determinar si hay más reintentos
        if new_attempts >= self.MAX_ATTEMPTS:
            new_status = WebhookStatus.FAILED.value
            next_retry = None
        else:
            new_status = WebhookStatus.RETRYING.value
            delay = self.RETRY_DELAYS_MINUTES[min(new_attempts - 1, len(self.RETRY_DELAYS_MINUTES) - 1)]
            next_retry = datetime.utcnow() + timedelta(minutes=delay)
        
        await self.db.execute(
            update(WebhookLog)
            .where(WebhookLog.id == webhook_id)
            .values(
                status=new_status,
                attempts=new_attempts,
                last_attempt_at=datetime.utcnow(),
                error_message=error_message,
                response_status_code=response_status_code,
                duration_ms=duration_ms,
                next_retry_at=next_retry,
                updated_at=datetime.utcnow(),
            )
        )
        await self.db.flush()
        
        logger.warning(
            "Webhook delivery failed",
            webhook_id=str(webhook_id),
            attempts=new_attempts,
            will_retry=new_status == WebhookStatus.RETRYING.value,
        )
        return await self.get_by_id(webhook_id)
    
    async def get_pending_retries(self, limit: int = 50) -> Sequence[WebhookLog]:
        """Obtiene webhooks pendientes de reintento."""
        result = await self.db.execute(
            select(WebhookLog)
            .where(WebhookLog.status == WebhookStatus.RETRYING.value)
            .where(WebhookLog.next_retry_at <= datetime.utcnow())
            .order_by(WebhookLog.next_retry_at)
            .limit(limit)
        )
        return result.scalars().all()
    
    async def list_by_payment(self, payment_id: UUID) -> Sequence[WebhookLog]:
        """Lista todos los webhooks relacionados con un pago."""
        result = await self.db.execute(
            select(WebhookLog)
            .where(WebhookLog.payment_id == payment_id)
            .order_by(WebhookLog.created_at.desc())
        )
        return result.scalars().all()
    
    async def list_by_partner(
        self,
        partner_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[WebhookLog]:
        """Lista webhooks enviados a un partner."""
        result = await self.db.execute(
            select(WebhookLog)
            .where(WebhookLog.partner_id == partner_id)
            .order_by(WebhookLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
