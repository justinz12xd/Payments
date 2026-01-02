"""
Endpoints para gestión de pagos.
"""

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas import (
    APIResponse,
    PaymentCreateRequest,
    PaymentIntentResponse,
    PaymentResponse,
)
from app.services import PaymentService
from app.utils.exceptions import (
    PaymentNotFoundError,
    PaymentProviderError,
    InvalidPaymentStateError,
)
from app.utils.idempotency import get_idempotency_manager_with_fallback


logger = structlog.get_logger(__name__)

router = APIRouter()


async def get_payment_service(
    db: AsyncSession = Depends(get_db),
) -> PaymentService:
    """Dependency para obtener PaymentService."""
    return PaymentService(db)


@router.post(
    "",
    response_model=APIResponse[PaymentIntentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo pago",
    description="""
    Crea un nuevo pago/donación.
    
    - Soporta idempotencia via header `Idempotency-Key`
    - Retorna una URL de checkout para completar el pago
    - El pago queda en estado `pending` hasta confirmación vía webhook
    """,
)
async def create_payment(
    request: PaymentCreateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    service: PaymentService = Depends(get_payment_service),
):
    """Crea un nuevo pago."""
    # Verificar idempotencia en cache
    if idempotency_key:
        idempotency_manager = await get_idempotency_manager_with_fallback()
        cached = await idempotency_manager.get_cached_response(idempotency_key)
        if cached:
            logger.info("Returning cached response", idempotency_key=idempotency_key)
            return APIResponse(
                success=True,
                message="Payment retrieved from cache (idempotent)",
                data=PaymentIntentResponse(**cached),
            )
        
        # Verificar si ya está siendo procesado
        if await idempotency_manager.is_processing(idempotency_key):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Request with this idempotency key is already being processed",
            )
    
    try:
        result = await service.create_payment(request, idempotency_key)
        
        # Cachear respuesta para idempotencia
        if idempotency_key:
            idempotency_manager = await get_idempotency_manager_with_fallback()
            await idempotency_manager.cache_response(
                idempotency_key,
                result.model_dump(mode="json"),
            )
            await idempotency_manager.release_lock(idempotency_key)
        
        return APIResponse(
            success=True,
            message="Payment created successfully",
            data=result,
        )
        
    except PaymentProviderError as e:
        if idempotency_key:
            idempotency_manager = await get_idempotency_manager_with_fallback()
            await idempotency_manager.release_lock(idempotency_key)
        
        logger.error("Payment provider error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Payment provider error: {e.message}",
        )
    except Exception as e:
        if idempotency_key:
            idempotency_manager = await get_idempotency_manager_with_fallback()
            await idempotency_manager.release_lock(idempotency_key)
        raise


@router.get(
    "/{payment_id}",
    response_model=APIResponse[PaymentResponse],
    summary="Obtener un pago por ID",
)
async def get_payment(
    payment_id: UUID,
    service: PaymentService = Depends(get_payment_service),
):
    """Obtiene los detalles de un pago."""
    try:
        payment = await service.get_payment(payment_id)
        return APIResponse(
            success=True,
            data=payment,
        )
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment not found: {payment_id}",
        )


@router.post(
    "/{payment_id}/cancel",
    response_model=APIResponse[PaymentResponse],
    summary="Cancelar un pago pendiente",
)
async def cancel_payment(
    payment_id: UUID,
    service: PaymentService = Depends(get_payment_service),
):
    """Cancela un pago que está en estado pendiente."""
    try:
        payment = await service.cancel_payment(payment_id)
        return APIResponse(
            success=True,
            message="Payment cancelled successfully",
            data=payment,
        )
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment not found: {payment_id}",
        )
    except InvalidPaymentStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


@router.post(
    "/{payment_id}/refund",
    response_model=APIResponse[PaymentResponse],
    summary="Reembolsar un pago",
)
async def refund_payment(
    payment_id: UUID,
    service: PaymentService = Depends(get_payment_service),
):
    """Realiza un reembolso total de un pago completado."""
    try:
        payment = await service.refund_payment(payment_id)
        return APIResponse(
            success=True,
            message="Payment refunded successfully",
            data=payment,
        )
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment not found: {payment_id}",
        )
    except InvalidPaymentStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )
    except PaymentProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=e.message,
        )


@router.get(
    "/campaigns/{campaign_id}/stats",
    response_model=APIResponse[dict],
    summary="Estadísticas de una campaña",
)
async def get_campaign_stats(
    campaign_id: UUID,
    service: PaymentService = Depends(get_payment_service),
):
    """Obtiene estadísticas de pagos para una campaña."""
    stats = await service.get_campaign_stats(campaign_id)
    return APIResponse(
        success=True,
        data=stats,
    )
