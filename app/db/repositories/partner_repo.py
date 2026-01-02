"""
Repositorio para operaciones de Partner.
"""

import secrets
from datetime import datetime, timedelta
from typing import Any, Sequence
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Partner
from app.schemas.partner import PartnerStatus, WebhookEventType


logger = structlog.get_logger(__name__)


class PartnerRepository:
    """Repositorio para operaciones CRUD de partners B2B."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    @staticmethod
    def generate_secret() -> str:
        """Genera un secret seguro para HMAC."""
        return f"whsec_{secrets.token_urlsafe(32)}"
    
    async def create(
        self,
        name: str,
        webhook_url: str,
        events: list[WebhookEventType],
        description: str | None = None,
        contact_email: str | None = None,
    ) -> tuple[Partner, str]:
        """
        Crea un nuevo partner.
        
        Returns:
            Tupla de (Partner, secret) - El secret solo se retorna una vez
        """
        secret = self.generate_secret()
        
        partner = Partner(
            name=name,
            webhook_url=webhook_url,
            events=[e.value for e in events],
            description=description,
            contact_email=contact_email,
            secret=secret,
            status=PartnerStatus.ACTIVE.value,
        )
        
        self.db.add(partner)
        await self.db.flush()
        await self.db.refresh(partner)
        
        logger.info("Partner created", partner_id=str(partner.id), name=name)
        return partner, secret
    
    async def get_by_id(self, partner_id: UUID) -> Partner | None:
        """Obtiene un partner por ID."""
        result = await self.db.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_name(self, name: str) -> Partner | None:
        """Obtiene un partner por nombre."""
        result = await self.db.execute(
            select(Partner).where(Partner.name == name)
        )
        return result.scalar_one_or_none()
    
    async def list_active(self) -> Sequence[Partner]:
        """Lista todos los partners activos."""
        result = await self.db.execute(
            select(Partner)
            .where(Partner.status == PartnerStatus.ACTIVE.value)
            .order_by(Partner.name)
        )
        return result.scalars().all()
    
    async def list_by_event(self, event_type: str) -> Sequence[Partner]:
        """Lista partners suscritos a un tipo de evento."""
        result = await self.db.execute(
            select(Partner)
            .where(Partner.status == PartnerStatus.ACTIVE.value)
            .where(Partner.events.contains([event_type]))
        )
        return result.scalars().all()
    
    async def update(
        self,
        partner_id: UUID,
        name: str | None = None,
        webhook_url: str | None = None,
        events: list[WebhookEventType] | None = None,
        status: PartnerStatus | None = None,
        description: str | None = None,
        contact_email: str | None = None,
    ) -> Partner | None:
        """Actualiza un partner."""
        update_data: dict[str, Any] = {"updated_at": datetime.utcnow()}
        
        if name is not None:
            update_data["name"] = name
        if webhook_url is not None:
            update_data["webhook_url"] = webhook_url
        if events is not None:
            update_data["events"] = [e.value for e in events]
        if status is not None:
            update_data["status"] = status.value
        if description is not None:
            update_data["description"] = description
        if contact_email is not None:
            update_data["contact_email"] = contact_email
        
        await self.db.execute(
            update(Partner)
            .where(Partner.id == partner_id)
            .values(**update_data)
        )
        await self.db.flush()
        
        logger.info("Partner updated", partner_id=str(partner_id))
        return await self.get_by_id(partner_id)
    
    async def rotate_secret(
        self,
        partner_id: UUID,
        grace_period_hours: int = 24,
    ) -> tuple[Partner | None, str]:
        """
        Rota el secret de un partner.
        
        El secret anterior sigue siendo válido durante el periodo de gracia.
        
        Args:
            partner_id: ID del partner
            grace_period_hours: Horas de validez del secret anterior
            
        Returns:
            Tupla de (Partner actualizado, nuevo secret)
        """
        partner = await self.get_by_id(partner_id)
        if not partner:
            return None, ""
        
        new_secret = self.generate_secret()
        
        await self.db.execute(
            update(Partner)
            .where(Partner.id == partner_id)
            .values(
                previous_secret=partner.secret,
                previous_secret_valid_until=datetime.utcnow() + timedelta(hours=grace_period_hours),
                secret=new_secret,
                updated_at=datetime.utcnow(),
            )
        )
        await self.db.flush()
        
        logger.info(
            "Partner secret rotated",
            partner_id=str(partner_id),
            grace_period_hours=grace_period_hours,
        )
        
        return await self.get_by_id(partner_id), new_secret
    
    async def increment_webhooks_sent(self, partner_id: UUID) -> None:
        """Incrementa el contador de webhooks enviados."""
        await self.db.execute(
            update(Partner)
            .where(Partner.id == partner_id)
            .values(
                total_webhooks_sent=Partner.total_webhooks_sent + 1,
                last_webhook_at=datetime.utcnow(),
            )
        )
        await self.db.flush()
    
    async def verify_secret(self, partner_id: UUID, secret: str) -> bool:
        """
        Verifica si un secret es válido para un partner.
        
        Considera tanto el secret actual como el anterior (si está en periodo de gracia).
        """
        partner = await self.get_by_id(partner_id)
        if not partner:
            return False
        
        # Verificar secret actual
        if secrets.compare_digest(partner.secret, secret):
            return True
        
        # Verificar secret anterior si está en periodo de gracia
        if (
            partner.previous_secret
            and partner.previous_secret_valid_until
            and partner.previous_secret_valid_until > datetime.utcnow()
            and secrets.compare_digest(partner.previous_secret, secret)
        ):
            return True
        
        return False
