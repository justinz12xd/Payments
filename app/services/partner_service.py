"""
Servicio para gestión de partners B2B.
"""

from datetime import datetime, timedelta
from typing import Sequence
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Partner
from app.db.repositories import PartnerRepository
from app.schemas.partner import (
    PartnerRegisterRequest,
    PartnerRegisterResponse,
    PartnerResponse,
    PartnerSecretRotateResponse,
    PartnerStatus,
    PartnerUpdateRequest,
    WebhookEventType,
)
from app.utils.exceptions import PartnerNotFoundError, PartnerAlreadyExistsError


logger = structlog.get_logger(__name__)


class PartnerService:
    """
    Servicio para gestión de partners B2B.
    
    Maneja registro, actualización y rotación de secrets de partners.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PartnerRepository(db)
    
    async def register_partner(
        self,
        request: PartnerRegisterRequest,
    ) -> PartnerRegisterResponse:
        """
        Registra un nuevo partner.
        
        Genera un secret HMAC único que debe ser guardado de forma segura
        por el partner.
        
        Args:
            request: Datos de registro
            
        Returns:
            PartnerRegisterResponse con el secret (¡única vez!)
            
        Raises:
            PartnerAlreadyExistsError: Si ya existe un partner con ese nombre
        """
        # Verificar si ya existe
        existing = await self.repo.get_by_name(request.name)
        if existing:
            raise PartnerAlreadyExistsError(request.name)
        
        # Crear partner
        partner, secret = await self.repo.create(
            name=request.name,
            webhook_url=str(request.webhook_url),
            events=request.events,
            description=request.description,
            contact_email=request.contact_email,
        )
        
        logger.info(
            "Partner registered",
            partner_id=str(partner.id),
            name=partner.name,
            events=[e for e in partner.events],
        )
        
        return PartnerRegisterResponse(
            id=partner.id,
            name=partner.name,
            webhook_url=partner.webhook_url,
            events=[WebhookEventType(e) for e in partner.events],
            secret=secret,
            status=PartnerStatus(partner.status),
        )
    
    async def get_partner(self, partner_id: UUID) -> PartnerResponse:
        """
        Obtiene un partner por ID.
        
        Args:
            partner_id: ID del partner
            
        Returns:
            PartnerResponse (sin secret)
            
        Raises:
            PartnerNotFoundError: Si el partner no existe
        """
        partner = await self.repo.get_by_id(partner_id)
        
        if not partner:
            raise PartnerNotFoundError(str(partner_id))
        
        return self._to_response(partner)
    
    async def list_partners(self) -> list[PartnerResponse]:
        """
        Lista todos los partners activos.
        
        Returns:
            Lista de PartnerResponse
        """
        partners = await self.repo.list_active()
        return [self._to_response(p) for p in partners]
    
    async def list_partners_for_event(
        self,
        event_type: WebhookEventType,
    ) -> Sequence[Partner]:
        """
        Lista partners suscritos a un tipo de evento.
        
        Retorna los modelos de BD (con secret) para uso interno.
        """
        return await self.repo.list_by_event(event_type.value)
    
    async def update_partner(
        self,
        partner_id: UUID,
        request: PartnerUpdateRequest,
    ) -> PartnerResponse:
        """
        Actualiza un partner.
        
        Args:
            partner_id: ID del partner
            request: Datos a actualizar
            
        Returns:
            PartnerResponse actualizado
            
        Raises:
            PartnerNotFoundError: Si el partner no existe
        """
        partner = await self.repo.get_by_id(partner_id)
        
        if not partner:
            raise PartnerNotFoundError(str(partner_id))
        
        # Si cambia el nombre, verificar que no exista
        if request.name and request.name != partner.name:
            existing = await self.repo.get_by_name(request.name)
            if existing:
                raise PartnerAlreadyExistsError(request.name)
        
        updated = await self.repo.update(
            partner_id=partner_id,
            name=request.name,
            webhook_url=str(request.webhook_url) if request.webhook_url else None,
            events=request.events,
            status=request.status,
            description=request.description,
            contact_email=request.contact_email,
        )
        
        logger.info(
            "Partner updated",
            partner_id=str(partner_id),
        )
        
        return self._to_response(updated)
    
    async def rotate_secret(
        self,
        partner_id: UUID,
        grace_period_hours: int = 24,
    ) -> PartnerSecretRotateResponse:
        """
        Rota el secret de un partner.
        
        El secret anterior sigue siendo válido durante el periodo de gracia
        para permitir una transición suave.
        
        Args:
            partner_id: ID del partner
            grace_period_hours: Horas de validez del secret anterior
            
        Returns:
            PartnerSecretRotateResponse con el nuevo secret
            
        Raises:
            PartnerNotFoundError: Si el partner no existe
        """
        partner, new_secret = await self.repo.rotate_secret(
            partner_id=partner_id,
            grace_period_hours=grace_period_hours,
        )
        
        if not partner:
            raise PartnerNotFoundError(str(partner_id))
        
        logger.info(
            "Partner secret rotated",
            partner_id=str(partner_id),
            grace_period_hours=grace_period_hours,
        )
        
        return PartnerSecretRotateResponse(
            id=partner.id,
            new_secret=new_secret,
            old_secret_valid_until=datetime.utcnow() + timedelta(hours=grace_period_hours),
        )
    
    async def deactivate_partner(self, partner_id: UUID) -> PartnerResponse:
        """
        Desactiva un partner.
        
        El partner dejará de recibir webhooks pero no se elimina.
        """
        partner = await self.repo.get_by_id(partner_id)
        
        if not partner:
            raise PartnerNotFoundError(str(partner_id))
        
        updated = await self.repo.update(
            partner_id=partner_id,
            status=PartnerStatus.INACTIVE,
        )
        
        logger.info(
            "Partner deactivated",
            partner_id=str(partner_id),
        )
        
        return self._to_response(updated)
    
    async def verify_partner_secret(
        self,
        partner_id: UUID,
        secret: str,
    ) -> bool:
        """
        Verifica si un secret es válido para un partner.
        
        Considera tanto el secret actual como el anterior si está
        en periodo de gracia.
        """
        return await self.repo.verify_secret(partner_id, secret)
    
    def _to_response(self, partner: Partner) -> PartnerResponse:
        """Convierte modelo de BD a schema de respuesta (sin secret)."""
        return PartnerResponse(
            id=partner.id,
            name=partner.name,
            webhook_url=partner.webhook_url,
            events=[WebhookEventType(e) for e in partner.events],
            status=PartnerStatus(partner.status),
            description=partner.description,
            contact_email=partner.contact_email,
            total_webhooks_sent=partner.total_webhooks_sent,
            last_webhook_at=partner.last_webhook_at,
            created_at=partner.created_at,
            updated_at=partner.updated_at,
        )
