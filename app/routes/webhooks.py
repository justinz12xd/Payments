"""
Endpoints para webhooks entrantes.
"""

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services import WebhookService
from app.utils.exceptions import WebhookVerificationError


logger = structlog.get_logger(__name__)

router = APIRouter()


async def get_webhook_service(
    db: AsyncSession = Depends(get_db),
) -> WebhookService:
    """Dependency para obtener WebhookService."""
    return WebhookService(db)


@router.post(
    "/stripe",
    status_code=status.HTTP_200_OK,
    summary="Webhook de Stripe",
    description="""
    Endpoint para recibir webhooks de Stripe.
    
    - Valida la firma del webhook usando el header `Stripe-Signature`
    - Actualiza el estado del pago en la BD
    - Dispara webhooks a partners suscritos
    - Notifica a n8n para orquestación
    
    **Importante**: Este endpoint debe ser configurado en el dashboard de Stripe.
    """,
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
    service: WebhookService = Depends(get_webhook_service),
):
    """Procesa un webhook de Stripe."""
    # Leer body crudo para validar firma
    payload = await request.body()
    
    if not stripe_signature:
        logger.warning("Missing Stripe-Signature header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )
    
    try:
        result = await service.process_stripe_webhook(payload, stripe_signature)
        
        logger.info(
            "Stripe webhook processed",
            event_type=result.get("event_type"),
            status=result.get("status"),
        )
        
        return {"received": True, **result}
        
    except WebhookVerificationError as e:
        logger.error("Stripe webhook verification failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook verification failed: {e.message}",
        )
    except Exception as e:
        logger.error("Stripe webhook processing error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process webhook",
        )


@router.post(
    "/mock",
    status_code=status.HTTP_200_OK,
    summary="Webhook de Mock Provider",
    description="""
    Endpoint para recibir webhooks del proveedor mock (desarrollo).
    
    Útil para testing sin necesidad de Stripe.
    
    Header requerido: `X-Webhook-Signature` con formato `t=<timestamp>,v1=<signature>`
    """,
)
async def mock_webhook(
    request: Request,
    webhook_signature: str = Header(alias="X-Webhook-Signature"),
    service: WebhookService = Depends(get_webhook_service),
):
    """Procesa un webhook del proveedor mock."""
    payload = await request.body()
    
    if not webhook_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Webhook-Signature header",
        )
    
    try:
        result = await service.process_mock_webhook(payload, webhook_signature)
        
        logger.info(
            "Mock webhook processed",
            event_type=result.get("event_type"),
        )
        
        return {"received": True, **result}
        
    except WebhookVerificationError as e:
        logger.error("Mock webhook verification failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook verification failed: {e.message}",
        )


@router.post(
    "/partner",
    status_code=status.HTTP_200_OK,
    summary="Webhook entrante de Partner B2B",
    description="""
    Endpoint para recibir webhooks de otros grupos/partners.
    
    - Valida firma HMAC via header `X-Webhook-Signature`
    - Formato: `t=<timestamp>,v1=<signature>`
    
    Este endpoint permite la comunicación bidireccional entre grupos.
    """,
)
async def partner_webhook(
    request: Request,
    webhook_signature: str = Header(alias="X-Webhook-Signature"),
    partner_id: str = Header(alias="X-Partner-Id"),
    service: WebhookService = Depends(get_webhook_service),
):
    """Procesa un webhook de un partner B2B."""
    from uuid import UUID
    from app.db.repositories import PartnerRepository
    from app.utils.hmac_utils import verify_webhook_signature_header
    
    payload = await request.body()
    
    # Obtener partner para verificar secret
    partner_repo = PartnerRepository(service.db)
    try:
        partner_uuid = UUID(partner_id)
        partner = await partner_repo.get_by_id(partner_uuid)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid partner ID format",
        )
    
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found",
        )
    
    # Verificar firma (probar secret actual y anterior si existe)
    is_valid, error = verify_webhook_signature_header(
        payload, webhook_signature, partner.secret
    )
    
    if not is_valid and partner.previous_secret:
        is_valid, error = verify_webhook_signature_header(
            payload, webhook_signature, partner.previous_secret
        )
    
    if not is_valid:
        logger.warning(
            "Partner webhook verification failed",
            partner_id=partner_id,
            error=error,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Webhook verification failed: {error}",
        )
    
    # Parsear payload
    import json
    try:
        event_data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )
    
    logger.info(
        "Partner webhook received",
        partner_name=partner.name,
        event_type=event_data.get("event"),
    )
    
    # TODO: Procesar evento del partner según tu lógica de negocio
    # Por ejemplo: actualizar itinerario si es tour.purchased, etc.
    
    return {
        "received": True,
        "partner": partner.name,
        "event": event_data.get("event"),
    }
