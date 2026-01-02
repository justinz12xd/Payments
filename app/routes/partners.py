"""
Endpoints para gestión de partners B2B.
"""

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas import (
    APIResponse,
    PartnerRegisterRequest,
    PartnerRegisterResponse,
    PartnerResponse,
    PartnerSecretRotateResponse,
    PartnerUpdateRequest,
)
from app.services import PartnerService
from app.utils.exceptions import PartnerNotFoundError, PartnerAlreadyExistsError


logger = structlog.get_logger(__name__)

router = APIRouter()


async def get_partner_service(
    db: AsyncSession = Depends(get_db),
) -> PartnerService:
    """Dependency para obtener PartnerService."""
    return PartnerService(db)


@router.post(
    "/register",
    response_model=APIResponse[PartnerRegisterResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo partner",
    description="""
    Registra un nuevo partner B2B para recibir webhooks.
    
    **Importante**: El `secret` retornado solo se muestra una vez.
    Debe ser guardado de forma segura por el partner para verificar
    los webhooks que reciba.
    
    El secret usa formato HMAC-SHA256 y debe usarse para validar
    el header `X-Webhook-Signature` de los webhooks entrantes.
    """,
)
async def register_partner(
    request: PartnerRegisterRequest,
    service: PartnerService = Depends(get_partner_service),
):
    """Registra un nuevo partner B2B."""
    try:
        result = await service.register_partner(request)
        
        logger.info(
            "Partner registered",
            partner_id=str(result.id),
            name=result.name,
        )
        
        return APIResponse(
            success=True,
            message="Partner registered successfully. Save the secret securely - it won't be shown again!",
            data=result,
        )
        
    except PartnerAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=e.message,
        )


@router.get(
    "",
    response_model=APIResponse[list[PartnerResponse]],
    summary="Listar partners activos",
)
async def list_partners(
    service: PartnerService = Depends(get_partner_service),
):
    """Lista todos los partners activos."""
    partners = await service.list_partners()
    return APIResponse(
        success=True,
        data=partners,
    )


@router.get(
    "/{partner_id}",
    response_model=APIResponse[PartnerResponse],
    summary="Obtener un partner por ID",
)
async def get_partner(
    partner_id: UUID,
    service: PartnerService = Depends(get_partner_service),
):
    """Obtiene los detalles de un partner."""
    try:
        partner = await service.get_partner(partner_id)
        return APIResponse(
            success=True,
            data=partner,
        )
    except PartnerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner not found: {partner_id}",
        )


@router.patch(
    "/{partner_id}",
    response_model=APIResponse[PartnerResponse],
    summary="Actualizar un partner",
)
async def update_partner(
    partner_id: UUID,
    request: PartnerUpdateRequest,
    service: PartnerService = Depends(get_partner_service),
):
    """Actualiza los datos de un partner."""
    try:
        partner = await service.update_partner(partner_id, request)
        return APIResponse(
            success=True,
            message="Partner updated successfully",
            data=partner,
        )
    except PartnerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner not found: {partner_id}",
        )
    except PartnerAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=e.message,
        )


@router.post(
    "/{partner_id}/rotate-secret",
    response_model=APIResponse[PartnerSecretRotateResponse],
    summary="Rotar el secret de un partner",
    description="""
    Rota el secret HMAC de un partner.
    
    El secret anterior sigue siendo válido durante el periodo de gracia
    (por defecto 24 horas) para permitir una transición suave.
    
    **Importante**: El nuevo secret solo se muestra una vez.
    """,
)
async def rotate_partner_secret(
    partner_id: UUID,
    grace_period_hours: Annotated[int, Query(ge=1, le=168)] = 24,
    service: PartnerService = Depends(get_partner_service),
):
    """Rota el secret de un partner."""
    try:
        result = await service.rotate_secret(partner_id, grace_period_hours)
        
        logger.info(
            "Partner secret rotated",
            partner_id=str(partner_id),
            grace_period_hours=grace_period_hours,
        )
        
        return APIResponse(
            success=True,
            message=f"Secret rotated. Old secret valid for {grace_period_hours} hours.",
            data=result,
        )
        
    except PartnerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner not found: {partner_id}",
        )


@router.post(
    "/{partner_id}/deactivate",
    response_model=APIResponse[PartnerResponse],
    summary="Desactivar un partner",
)
async def deactivate_partner(
    partner_id: UUID,
    service: PartnerService = Depends(get_partner_service),
):
    """Desactiva un partner. Dejará de recibir webhooks."""
    try:
        partner = await service.deactivate_partner(partner_id)
        return APIResponse(
            success=True,
            message="Partner deactivated",
            data=partner,
        )
    except PartnerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner not found: {partner_id}",
        )
