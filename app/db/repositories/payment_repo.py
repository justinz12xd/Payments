"""
Repositorio para operaciones de Payment.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment
from app.schemas.payment import PaymentStatus


logger = structlog.get_logger(__name__)


class PaymentRepository:
    """Repositorio para operaciones CRUD de pagos."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        amount: Decimal,
        currency: str,
        payment_type: str,
        provider: str,
        user_id: UUID | None = None,
        campaign_id: UUID | None = None,
        animal_id: UUID | None = None,
        refugio_id: UUID | None = None,
        causa_urgente_id: UUID | None = None,
        payer_email: str | None = None,
        payer_name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> Payment:
        """Crea un nuevo pago."""
        payment = Payment(
            amount=amount,
            currency=currency.lower(),
            payment_type=payment_type,
            provider=provider,
            user_id=user_id,
            campaign_id=campaign_id,
            animal_id=animal_id,
            refugio_id=refugio_id,
            causa_urgente_id=causa_urgente_id,
            payer_email=payer_email,
            payer_name=payer_name,
            description=description,
            payment_metadata=metadata or {},
            idempotency_key=idempotency_key,
            success_url=success_url,
            cancel_url=cancel_url,
            status=PaymentStatus.PENDING.value,
        )
        
        self.db.add(payment)
        await self.db.flush()
        await self.db.refresh(payment)
        
        logger.info("Payment created", payment_id=str(payment.id))
        return payment
    
    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        """Obtiene un pago por ID."""
        result = await self.db.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_provider_id(self, provider_payment_id: str) -> Payment | None:
        """Obtiene un pago por ID del proveedor."""
        result = await self.db.execute(
            select(Payment).where(Payment.provider_payment_id == provider_payment_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        """Obtiene un pago por clave de idempotencia."""
        result = await self.db.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()
    
    async def update_status(
        self,
        payment_id: UUID,
        status: PaymentStatus,
        provider_payment_id: str | None = None,
        checkout_url: str | None = None,
        failure_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Payment | None:
        """Actualiza el estado de un pago."""
        update_data: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.utcnow(),
        }
        
        if provider_payment_id is not None:
            update_data["provider_payment_id"] = provider_payment_id
        if checkout_url is not None:
            update_data["checkout_url"] = checkout_url
        if failure_reason is not None:
            update_data["failure_reason"] = failure_reason
        if metadata is not None:
            update_data["payment_metadata"] = metadata
        
        await self.db.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(**update_data)
        )
        await self.db.flush()
        
        logger.info(
            "Payment status updated",
            payment_id=str(payment_id),
            status=status.value,
        )
        
        return await self.get_by_id(payment_id)
    
    async def list_by_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[Payment]:
        """Lista pagos de un usuario."""
        result = await self.db.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
    
    async def list_by_campaign(
        self,
        campaign_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Payment]:
        """Lista pagos de una campaña."""
        result = await self.db.execute(
            select(Payment)
            .where(Payment.campaign_id == campaign_id)
            .where(Payment.status == PaymentStatus.SUCCEEDED.value)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
    
    async def get_campaign_total(self, campaign_id: UUID) -> Decimal:
        """Obtiene el total recaudado para una campaña."""
        from sqlalchemy import func
        
        result = await self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.campaign_id == campaign_id)
            .where(Payment.status == PaymentStatus.SUCCEEDED.value)
        )
        return result.scalar() or Decimal(0)

    async def get_causa_urgente_total(self, causa_urgente_id: UUID) -> Decimal:
        """Obtiene el total recaudado para una causa urgente."""
        from sqlalchemy import func
        
        result = await self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.causa_urgente_id == causa_urgente_id)
            .where(Payment.status == PaymentStatus.SUCCEEDED.value)
        )
        return result.scalar() or Decimal(0)
    
    async def list_by_causa_urgente(
        self,
        causa_urgente_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Payment]:
        """Lista pagos de una causa urgente específica."""
        result = await self.db.execute(
            select(Payment)
            .where(Payment.causa_urgente_id == causa_urgente_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
