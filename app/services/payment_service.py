"""
Servicio principal de pagos.
Orquesta la lógica de negocio para crear y gestionar pagos.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import PaymentProvider, get_payment_provider
from app.adapters.base import PaymentResultStatus
from app.db.models import Payment
from app.db.repositories import PaymentRepository
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentIntentResponse,
    PaymentResponse,
    PaymentStatus,
)
from app.utils.exceptions import (
    PaymentNotFoundError,
    PaymentProviderError,
    InvalidPaymentStateError,
)


logger = structlog.get_logger(__name__)


class PaymentService:
    """
    Servicio para gestión de pagos.
    
    Coordina entre el repositorio de BD y el proveedor de pago externo.
    """
    
    def __init__(
        self,
        db: AsyncSession,
        payment_provider: PaymentProvider | None = None,
    ):
        self.db = db
        self.repo = PaymentRepository(db)
        self._provider = payment_provider or get_payment_provider()
    
    @property
    def provider(self) -> PaymentProvider:
        return self._provider
    
    async def create_payment(
        self,
        request: PaymentCreateRequest,
        idempotency_key: str | None = None,
    ) -> PaymentIntentResponse:
        """
        Crea un nuevo pago.
        
        1. Crea registro en BD con estado PENDING
        2. Llama al proveedor de pago para crear el payment intent
        3. Actualiza el registro con los datos del proveedor
        
        Args:
            request: Datos del pago
            idempotency_key: Clave de idempotencia opcional
            
        Returns:
            PaymentIntentResponse con checkout_url o client_secret
        """
        # Verificar idempotencia en BD
        if idempotency_key:
            existing = await self.repo.get_by_idempotency_key(idempotency_key)
            if existing:
                logger.info(
                    "Returning existing payment (idempotency)",
                    payment_id=str(existing.id),
                    idempotency_key=idempotency_key,
                )
                return PaymentIntentResponse(
                    payment_id=existing.id,
                    client_secret=None,
                    checkout_url=existing.checkout_url,
                    status=PaymentStatus(existing.status),
                    provider=existing.provider,
                )
        
        # Crear registro en BD
        payment = await self.repo.create(
            amount=request.amount,
            currency=request.currency.value,
            payment_type=request.payment_type.value,
            provider=self.provider.provider_name,
            user_id=request.user_id,
            campaign_id=request.campaign_id,
            animal_id=request.animal_id,
            refugio_id=request.refugio_id,
            payer_email=request.payer_email,
            payer_name=request.payer_name,
            description=request.description,
            metadata=request.metadata,
            idempotency_key=idempotency_key,
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )
        
        logger.info(
            "Payment record created",
            payment_id=str(payment.id),
            amount=float(request.amount),
            currency=request.currency.value,
        )
        
        # Llamar al proveedor de pago
        try:
            result = await self.provider.create_payment(
                amount=request.amount,
                currency=request.currency.value,
                payment_id=payment.id,
                description=request.description or f"Donación Love4Pets - {request.payment_type.value}",
                metadata={
                    "payment_id": str(payment.id),
                    "payment_type": request.payment_type.value,
                    **(request.metadata or {}),
                },
                customer_email=request.payer_email,
                success_url=request.success_url,
                cancel_url=request.cancel_url,
            )
            
            # Mapear estado del resultado
            if result.status == PaymentResultStatus.FAILED:
                status = PaymentStatus.FAILED
            elif result.status == PaymentResultStatus.SUCCESS:
                status = PaymentStatus.SUCCEEDED
            else:
                status = PaymentStatus.PENDING
            
            # Actualizar registro con datos del proveedor
            await self.repo.update_status(
                payment_id=payment.id,
                status=status,
                provider_payment_id=result.provider_payment_id,
                checkout_url=result.checkout_url,
                failure_reason=result.failure_reason,
            )
            
            logger.info(
                "Payment intent created with provider",
                payment_id=str(payment.id),
                provider=self.provider.provider_name,
                provider_payment_id=result.provider_payment_id,
            )
            
            return PaymentIntentResponse(
                payment_id=payment.id,
                client_secret=result.client_secret,
                checkout_url=result.checkout_url,
                status=status,
                provider=self.provider.provider_name,
            )
            
        except Exception as e:
            logger.error(
                "Failed to create payment with provider",
                payment_id=str(payment.id),
                error=str(e),
            )
            
            # Marcar como fallido en BD
            await self.repo.update_status(
                payment_id=payment.id,
                status=PaymentStatus.FAILED,
                failure_reason=str(e),
            )
            
            raise PaymentProviderError(self.provider.provider_name, str(e))
    
    async def get_payment(self, payment_id: UUID) -> PaymentResponse:
        """
        Obtiene un pago por ID.
        
        Args:
            payment_id: ID del pago
            
        Returns:
            PaymentResponse con los datos del pago
            
        Raises:
            PaymentNotFoundError: Si el pago no existe
        """
        payment = await self.repo.get_by_id(payment_id)
        
        if not payment:
            raise PaymentNotFoundError(str(payment_id))
        
        return self._to_response(payment)
    
    async def get_payment_by_provider_id(self, provider_payment_id: str) -> PaymentResponse:
        """
        Obtiene un pago por ID del proveedor.
        
        Útil para procesar webhooks.
        """
        payment = await self.repo.get_by_provider_id(provider_payment_id)
        
        if not payment:
            raise PaymentNotFoundError(f"provider_id:{provider_payment_id}")
        
        return self._to_response(payment)
    
    async def update_payment_status(
        self,
        payment_id: UUID,
        status: PaymentStatus,
        failure_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentResponse:
        """
        Actualiza el estado de un pago.
        
        Usado principalmente para procesar webhooks del proveedor.
        """
        payment = await self.repo.get_by_id(payment_id)
        
        if not payment:
            raise PaymentNotFoundError(str(payment_id))
        
        # Validar transición de estado
        valid_transitions = {
            PaymentStatus.PENDING: [PaymentStatus.PROCESSING, PaymentStatus.SUCCEEDED, PaymentStatus.FAILED, PaymentStatus.CANCELED],
            PaymentStatus.PROCESSING: [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED],
            PaymentStatus.SUCCEEDED: [PaymentStatus.REFUNDED],
            PaymentStatus.FAILED: [],
            PaymentStatus.CANCELED: [],
            PaymentStatus.REFUNDED: [],
        }
        
        current_status = PaymentStatus(payment.status)
        if status not in valid_transitions.get(current_status, []):
            raise InvalidPaymentStateError(
                str(payment_id),
                current_status.value,
                f"transition to {status.value}",
            )
        
        updated = await self.repo.update_status(
            payment_id=payment_id,
            status=status,
            failure_reason=failure_reason,
            metadata=metadata,
        )
        
        logger.info(
            "Payment status updated",
            payment_id=str(payment_id),
            old_status=current_status.value,
            new_status=status.value,
        )
        
        return self._to_response(updated)
    
    async def cancel_payment(self, payment_id: UUID) -> PaymentResponse:
        """
        Cancela un pago pendiente.
        """
        payment = await self.repo.get_by_id(payment_id)
        
        if not payment:
            raise PaymentNotFoundError(str(payment_id))
        
        if payment.status != PaymentStatus.PENDING.value:
            raise InvalidPaymentStateError(
                str(payment_id),
                payment.status,
                "cancel",
            )
        
        # Cancelar en el proveedor si tiene provider_payment_id
        if payment.provider_payment_id:
            try:
                await self.provider.cancel_payment(payment.provider_payment_id)
            except Exception as e:
                logger.warning(
                    "Failed to cancel payment with provider",
                    payment_id=str(payment_id),
                    error=str(e),
                )
        
        # Actualizar en BD
        updated = await self.repo.update_status(
            payment_id=payment_id,
            status=PaymentStatus.CANCELED,
            failure_reason="Canceled by user",
        )
        
        return self._to_response(updated)
    
    async def refund_payment(
        self,
        payment_id: UUID,
        amount: Decimal | None = None,
        reason: str | None = None,
    ) -> PaymentResponse:
        """
        Realiza un reembolso total o parcial.
        """
        payment = await self.repo.get_by_id(payment_id)
        
        if not payment:
            raise PaymentNotFoundError(str(payment_id))
        
        if payment.status != PaymentStatus.SUCCEEDED.value:
            raise InvalidPaymentStateError(
                str(payment_id),
                payment.status,
                "refund",
            )
        
        if not payment.provider_payment_id:
            raise PaymentProviderError(
                payment.provider,
                "No provider payment ID for refund",
            )
        
        # Realizar reembolso en el proveedor
        try:
            refund_result = await self.provider.refund_payment(
                provider_payment_id=payment.provider_payment_id,
                amount=amount,
                reason=reason,
            )
            
            if refund_result.status == PaymentResultStatus.FAILED:
                raise PaymentProviderError(
                    payment.provider,
                    refund_result.failure_reason or "Refund failed",
                )
            
            # Actualizar en BD
            updated = await self.repo.update_status(
                payment_id=payment_id,
                status=PaymentStatus.REFUNDED,
                metadata={
                    **(payment.metadata or {}),
                    "refund_id": refund_result.provider_refund_id,
                    "refund_amount": float(refund_result.amount),
                    "refund_reason": reason,
                },
            )
            
            logger.info(
                "Payment refunded",
                payment_id=str(payment_id),
                refund_amount=float(refund_result.amount),
            )
            
            return self._to_response(updated)
            
        except Exception as e:
            logger.error(
                "Failed to refund payment",
                payment_id=str(payment_id),
                error=str(e),
            )
            raise PaymentProviderError(payment.provider, str(e))
    
    async def get_campaign_stats(self, campaign_id: UUID) -> dict[str, Any]:
        """
        Obtiene estadísticas de pagos para una campaña.
        """
        total = await self.repo.get_campaign_total(campaign_id)
        payments = await self.repo.list_by_campaign(campaign_id, limit=100)
        
        return {
            "campaign_id": str(campaign_id),
            "total_raised": float(total),
            "total_donations": len(payments),
            "currency": "usd",  # TODO: Soportar múltiples monedas
        }
    
    def _to_response(self, payment: Payment) -> PaymentResponse:
        """Convierte modelo de BD a schema de respuesta."""
        return PaymentResponse(
            id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            status=PaymentStatus(payment.status),
            payment_type=payment.payment_type,
            user_id=payment.user_id,
            campaign_id=payment.campaign_id,
            animal_id=payment.animal_id,
            refugio_id=payment.refugio_id,
            payer_email=payment.payer_email,
            payer_name=payment.payer_name,
            provider=payment.provider,
            provider_payment_id=payment.provider_payment_id,
            checkout_url=payment.checkout_url,
            description=payment.description,
            metadata=payment.metadata or {},
            failure_reason=payment.failure_reason,
            idempotency_key=payment.idempotency_key,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
        )
