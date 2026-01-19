"""
Endpoints para notificaciones de adopción B2B.

Este módulo permite que la API REST de Love4Pets notifique al servicio
de pagos cuando se crea una adopción, para que este envíe webhooks
firmados a todos los partners suscritos.
"""

import json
from datetime import datetime
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.adoption import (
    AdoptionNotifyRequest,
    AdoptionNotifyResponse,
    AdoptionWebhookPayload,
    TestWebhookRequest,
    TestWebhookResponse,
)
from app.schemas.common import APIResponse
from app.schemas.partner import WebhookEventType
from app.services import PartnerService, WebhookService


logger = structlog.get_logger(__name__)

router = APIRouter()


async def get_services(
    db: AsyncSession = Depends(get_db),
) -> tuple[PartnerService, WebhookService]:
    """Dependency para obtener servicios."""
    return PartnerService(db), WebhookService(db)


@router.post(
    "/notify",
    response_model=APIResponse[AdoptionNotifyResponse],
    status_code=status.HTTP_200_OK,
    summary="Notificar adopción a partners B2B",
    description="""
    Endpoint interno para notificar una adopción a todos los partners B2B suscritos.
    
    Este endpoint debe ser llamado por la API REST de Love4Pets cuando se crea
    una nueva adopción. El servicio de pagos se encargará de:
    
    1. Construir el payload del webhook
    2. Firmarlo con HMAC-SHA256
    3. Enviarlo a todos los partners suscritos al evento `adoption.created`
    4. Registrar los webhooks enviados para auditoría
    
    **Ejemplo de uso desde tu API REST (Rust):**
    ```
    POST http://localhost:8001/adoptions/notify
    Content-Type: application/json
    
    {
        "adoption_id": "uuid-de-la-adopcion",
        "status": "pending",
        "adopter": {
            "name": "Juan Pérez",
            "email": "juan@email.com",
            "phone": "0999999999"
        },
        "animal": {
            "id": "uuid-del-animal",
            "name": "Firulais",
            "species": "Perro"
        },
        "shelter": {
            "id": "uuid-del-refugio",
            "name": "Refugio Happy Pets"
        }
    }
    ```
    
    **Lo que recibirá tu compañero (Partner):**
    
    El webhook llegará a la URL que registró con firma HMAC en el header
    `X-Webhook-Signature`. El payload incluirá el email del adoptante
    y toda la información de la adopción.
    """,
)
async def notify_adoption(
    request: AdoptionNotifyRequest,
    services: tuple[PartnerService, WebhookService] = Depends(get_services),
):
    """
    Notifica una adopción a todos los partners suscritos.
    
    Envía un webhook firmado con HMAC a cada partner que esté
    suscrito al evento 'adoption.created'.
    """
    partner_service, webhook_service = services
    
    logger.info(
        "Adoption notification received",
        adoption_id=request.adoption_id,
        adopter_email=request.adopter.email,
    )
    
    # Obtener partners suscritos a eventos de adopción
    partners = await partner_service.list_partners_for_event(
        WebhookEventType.ADOPTION_CREATED
    )
    
    if not partners:
        logger.info("No partners subscribed to adoption.created event")
        return APIResponse(
            success=True,
            message="No partners subscribed to adoption events",
            data=AdoptionNotifyResponse(
                success=True,
                message="No partners subscribed",
                webhooks_sent=0,
                webhook_ids=[],
            ),
        )
    
    # Construir payload del webhook (simplificado)
    webhook_payload = AdoptionWebhookPayload(
        event="adoption.created",
        timestamp=datetime.utcnow(),
        adopter_email=request.adopter.email,
        adopter_name=request.adopter.name,
    )
    
    # Enviar webhook a cada partner
    webhook_ids = []
    
    for partner in partners:
        try:
            webhook_id = await webhook_service.send_webhook_to_partner(
                partner=partner,
                event_type=WebhookEventType.ADOPTION_CREATED,
                data=webhook_payload.model_dump(mode="json"),
                payment_id=None,  # No es un pago
            )
            
            if webhook_id:
                webhook_ids.append(str(webhook_id))
                logger.info(
                    "Adoption webhook sent",
                    partner=partner.name,
                    webhook_id=str(webhook_id),
                )
                
        except Exception as e:
            logger.error(
                "Failed to send adoption webhook",
                partner=partner.name,
                error=str(e),
            )
    
    return APIResponse(
        success=True,
        message=f"Adoption notification sent to {len(webhook_ids)} partners",
        data=AdoptionNotifyResponse(
            success=True,
            message=f"Webhooks sent to {len(webhook_ids)} partners",
            webhooks_sent=len(webhook_ids),
            webhook_ids=webhook_ids,
        ),
    )


@router.post(
    "/notify/status-change",
    response_model=APIResponse[AdoptionNotifyResponse],
    status_code=status.HTTP_200_OK,
    summary="Notificar cambio de estado de adopción",
    description="""
    Notifica a partners cuando cambia el estado de una adopción.
    
    Estados posibles:
    - `pending` → `approved` (adopción aprobada)
    - `pending` → `rejected` (adopción rechazada)
    - `approved` → `completed` (adopción completada)
    """,
)
async def notify_adoption_status_change(
    request: AdoptionNotifyRequest,
    services: tuple[PartnerService, WebhookService] = Depends(get_services),
):
    """Notifica cambio de estado de adopción."""
    partner_service, webhook_service = services
    
    # Determinar tipo de evento según estado
    event_type_map = {
        "approved": WebhookEventType.ADOPTION_APPROVED,
        "completed": WebhookEventType.ADOPTION_COMPLETED,
    }
    
    event_type = event_type_map.get(
        request.status.lower(),
        WebhookEventType.ADOPTION_CREATED
    )
    
    # Obtener partners suscritos
    partners = await partner_service.list_partners_for_event(event_type)
    
    if not partners:
        return APIResponse(
            success=True,
            message=f"No partners subscribed to {event_type.value} event",
            data=AdoptionNotifyResponse(
                success=True,
                message="No partners subscribed",
                webhooks_sent=0,
                webhook_ids=[],
            ),
        )
    
    # Construir y enviar webhooks (simplificado)
    webhook_payload = AdoptionWebhookPayload(
        event=event_type.value,
        timestamp=datetime.utcnow(),
        adopter_email=request.adopter.email,
        adopter_name=request.adopter.name,
    )
    
    webhook_ids = []
    
    for partner in partners:
        try:
            webhook_id = await webhook_service.send_webhook_to_partner(
                partner=partner,
                event_type=event_type,
                data=webhook_payload.model_dump(mode="json"),
                payment_id=None,
            )
            
            if webhook_id:
                webhook_ids.append(str(webhook_id))
                
        except Exception as e:
            logger.error(
                "Failed to send adoption status webhook",
                partner=partner.name,
                error=str(e),
            )
    
    return APIResponse(
        success=True,
        message=f"Status change notification sent to {len(webhook_ids)} partners",
        data=AdoptionNotifyResponse(
            success=True,
            message=f"Webhooks sent to {len(webhook_ids)} partners",
            webhooks_sent=len(webhook_ids),
            webhook_ids=webhook_ids,
        ),
    )


@router.post(
    "/test-webhook",
    response_model=APIResponse[TestWebhookResponse],
    status_code=status.HTTP_200_OK,
    summary="🧪 Enviar webhook de PRUEBA a partners",
    description="""
    **ENDPOINT DE PRUEBA** para enviar webhooks a tu compañero.
    
    Usa este endpoint desde la interfaz de Swagger (/docs) para probar
    el envío de webhooks sin necesidad de hacer el flujo completo de adopción.
    
    ## Eventos disponibles:
    - `adoption.created` - Nueva solicitud de adopción
    - `adoption.approved` - Adopción aprobada por el refugio
    - `adoption.completed` - Adopción completada
    
    ## Payload que recibirá tu compañero:
    ```json
    {
        "event": "adoption.completed",
        "timestamp": "2026-01-19T10:30:00Z",
        "adopter_email": "test@example.com",
        "adopter_name": "Usuario de Prueba",
        "adopter_phone": "0999999999",
        "adoption_id": "test-adoption-123",
        "animal_id": "test-animal-456",
        "animal_name": "Firulais",
        "animal_species": "Perro",
        "shelter_id": "test-shelter-789",
        "shelter_name": "Refugio Love4Pets"
    }
    ```
    
    ## Headers que recibirá:
    - `X-Webhook-Signature`: Firma HMAC-SHA256 para verificar autenticidad
    - `Content-Type`: application/json
    """,
    tags=["🧪 Testing"],
)
async def send_test_webhook(
    request: TestWebhookRequest,
    services: tuple[PartnerService, WebhookService] = Depends(get_services),
):
    """
    Envía un webhook de prueba a los partners suscritos.
    
    Ideal para probar la conexión con tu compañero del Pilar 2.
    """
    partner_service, webhook_service = services
    
    # Mapear evento a tipo
    event_type_map = {
        "adoption.created": WebhookEventType.ADOPTION_CREATED,
        "adoption.approved": WebhookEventType.ADOPTION_APPROVED,
        "adoption.completed": WebhookEventType.ADOPTION_COMPLETED,
    }
    
    event_type = event_type_map.get(
        request.event_type.lower(),
        WebhookEventType.ADOPTION_COMPLETED
    )
    
    logger.info(
        "🧪 Test webhook requested",
        event_type=request.event_type,
        adopter_email=request.adopter_email,
    )
    
    # Construir payload completo
    webhook_payload = AdoptionWebhookPayload(
        event=request.event_type,
        timestamp=datetime.utcnow(),
        adopter_email=request.adopter_email,
        adopter_name=request.adopter_name,
        adopter_phone=request.adopter_phone,
        adoption_id=request.adoption_id,
        animal_id=request.animal_id,
        animal_name=request.animal_name,
        animal_species=request.animal_species,
        shelter_id=request.shelter_id,
        shelter_name=request.shelter_name,
    )
    
    payload_dict = webhook_payload.model_dump(mode="json")
    
    # Obtener partners suscritos
    partners = await partner_service.list_partners_for_event(event_type)
    
    if not partners:
        logger.warning("No partners subscribed to event", event_type=request.event_type)
        return APIResponse(
            success=True,
            message=f"⚠️ No hay partners suscritos al evento '{request.event_type}'",
            data=TestWebhookResponse(
                success=True,
                message="No partners subscribed. Registra un partner primero en POST /api/partners/register",
                payload_sent=payload_dict,
                webhooks_sent=0,
                webhook_ids=[],
            ),
        )
    
    # Enviar a cada partner
    webhook_ids = []
    
    for partner in partners:
        try:
            webhook_id = await webhook_service.send_webhook_to_partner(
                partner=partner,
                event_type=event_type,
                data=payload_dict,
                payment_id=None,
            )
            
            if webhook_id:
                webhook_ids.append(str(webhook_id))
                logger.info(
                    "🧪 Test webhook sent successfully",
                    partner=partner.name,
                    webhook_url=partner.webhook_url,
                    webhook_id=str(webhook_id),
                )
                
        except Exception as e:
            logger.error(
                "🧪 Failed to send test webhook",
                partner=partner.name,
                error=str(e),
            )
    
    return APIResponse(
        success=True,
        message=f"✅ Webhook de prueba enviado a {len(webhook_ids)} partner(s)",
        data=TestWebhookResponse(
            success=True,
            message=f"Webhooks enviados exitosamente a {len(webhook_ids)} partners",
            payload_sent=payload_dict,
            webhooks_sent=len(webhook_ids),
            webhook_ids=webhook_ids,
        ),
    )
