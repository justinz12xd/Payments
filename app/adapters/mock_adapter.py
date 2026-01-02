"""
Mock Adapter para desarrollo y testing.
Simula el comportamiento de una pasarela de pago.
"""

import hashlib
import hmac
import json
import random
import structlog
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.adapters.base import (
    PaymentProvider,
    PaymentResult,
    PaymentResultStatus,
    RefundResult,
    WebhookEvent,
)


logger = structlog.get_logger(__name__)


class MockAdapter(PaymentProvider):
    """
    Adapter mock para desarrollo y testing.
    
    Simula el comportamiento de una pasarela de pago real:
    - 90% de pagos exitosos
    - 10% de pagos fallidos (para testing)
    
    Útil para desarrollo local sin necesidad de credenciales reales.
    """
    
    # Almacenamiento en memoria para simular persistencia
    _payments: dict[str, dict[str, Any]] = {}
    _refunds: dict[str, dict[str, Any]] = {}
    
    # Secret para validación de webhooks mock
    MOCK_WEBHOOK_SECRET = "mock_webhook_secret_for_testing"
    
    def __init__(self, success_rate: float = 0.9):
        """
        Inicializa el adapter mock.
        
        Args:
            success_rate: Probabilidad de éxito (0.0 a 1.0)
        """
        self._success_rate = success_rate
        logger.info("MockAdapter initialized", success_rate=success_rate)
    
    @property
    def provider_name(self) -> str:
        return "mock"
    
    def _generate_mock_id(self, prefix: str = "mock") -> str:
        """Genera un ID mock similar al formato de Stripe."""
        return f"{prefix}_{uuid4().hex[:24]}"
    
    def _should_succeed(self) -> bool:
        """Determina si el pago debe ser exitoso basado en success_rate."""
        return random.random() < self._success_rate
    
    async def create_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_id: UUID,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        customer_email: str | None = None,
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PaymentResult:
        """Crea un pago mock."""
        mock_payment_id = self._generate_mock_id("cs")
        
        # Simular resultado
        will_succeed = self._should_succeed()
        
        # Generar URL de checkout mock
        checkout_url = f"http://localhost:3000/mock-checkout/{mock_payment_id}"
        
        # Guardar en memoria
        payment_data = {
            "id": mock_payment_id,
            "internal_payment_id": str(payment_id),
            "amount": int(amount),
            "currency": currency.lower(),
            "status": "pending",
            "description": description,
            "customer_email": customer_email,
            "metadata": metadata or {},
            "will_succeed": will_succeed,
            "created_at": datetime.utcnow().isoformat(),
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        self._payments[mock_payment_id] = payment_data
        
        logger.info(
            "Mock payment created",
            mock_payment_id=mock_payment_id,
            payment_id=str(payment_id),
            will_succeed=will_succeed,
        )
        
        return PaymentResult(
            status=PaymentResultStatus.PENDING,
            provider=self.provider_name,
            provider_payment_id=mock_payment_id,
            amount=amount,
            currency=currency,
            checkout_url=checkout_url,
            metadata={
                "payment_id": str(payment_id),
                **(metadata or {}),
            },
            raw_response=payment_data,
        )
    
    async def retrieve_payment(self, provider_payment_id: str) -> PaymentResult:
        """Obtiene el estado de un pago mock."""
        payment_data = self._payments.get(provider_payment_id)
        
        if not payment_data:
            raise ValueError(f"Payment not found: {provider_payment_id}")
        
        # Mapear estado
        status_map = {
            "pending": PaymentResultStatus.PENDING,
            "succeeded": PaymentResultStatus.SUCCESS,
            "failed": PaymentResultStatus.FAILED,
            "canceled": PaymentResultStatus.FAILED,
        }
        
        return PaymentResult(
            status=status_map.get(payment_data["status"], PaymentResultStatus.PENDING),
            provider=self.provider_name,
            provider_payment_id=provider_payment_id,
            amount=Decimal(payment_data["amount"]),
            currency=payment_data["currency"],
            failure_reason=payment_data.get("failure_reason"),
            metadata=payment_data.get("metadata", {}),
            raw_response=payment_data,
        )
    
    async def cancel_payment(self, provider_payment_id: str) -> PaymentResult:
        """Cancela un pago mock."""
        payment_data = self._payments.get(provider_payment_id)
        
        if not payment_data:
            raise ValueError(f"Payment not found: {provider_payment_id}")
        
        if payment_data["status"] != "pending":
            raise ValueError(f"Cannot cancel payment with status: {payment_data['status']}")
        
        # Actualizar estado
        payment_data["status"] = "canceled"
        payment_data["failure_reason"] = "Canceled by user"
        
        return PaymentResult(
            status=PaymentResultStatus.FAILED,
            provider=self.provider_name,
            provider_payment_id=provider_payment_id,
            amount=Decimal(payment_data["amount"]),
            currency=payment_data["currency"],
            failure_reason="Canceled by user",
        )
    
    async def refund_payment(
        self,
        provider_payment_id: str,
        amount: Decimal | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        """Realiza un reembolso mock."""
        payment_data = self._payments.get(provider_payment_id)
        
        if not payment_data:
            raise ValueError(f"Payment not found: {provider_payment_id}")
        
        if payment_data["status"] != "succeeded":
            return RefundResult(
                status=PaymentResultStatus.FAILED,
                provider=self.provider_name,
                provider_refund_id="",
                provider_payment_id=provider_payment_id,
                amount=amount or Decimal(0),
                currency=payment_data["currency"],
                failure_reason="Can only refund succeeded payments",
            )
        
        refund_amount = amount or Decimal(payment_data["amount"])
        refund_id = self._generate_mock_id("re")
        
        # Guardar refund
        self._refunds[refund_id] = {
            "id": refund_id,
            "payment_id": provider_payment_id,
            "amount": int(refund_amount),
            "currency": payment_data["currency"],
            "reason": reason,
            "status": "succeeded",
            "created_at": datetime.utcnow().isoformat(),
        }
        
        # Actualizar estado del pago
        payment_data["status"] = "refunded"
        
        return RefundResult(
            status=PaymentResultStatus.SUCCESS,
            provider=self.provider_name,
            provider_refund_id=refund_id,
            provider_payment_id=provider_payment_id,
            amount=refund_amount,
            currency=payment_data["currency"],
        )
    
    def construct_webhook_event(
        self,
        payload: bytes,
        signature: str,
    ) -> WebhookEvent:
        """Construye y valida un evento de webhook mock."""
        # Validar firma
        expected_signature = hmac.new(
            self.MOCK_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        # Formato de firma: "t=timestamp,v1=signature"
        sig_parts = {}
        for part in signature.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                sig_parts[key] = value
        
        received_sig = sig_parts.get("v1", "")
        
        if not hmac.compare_digest(received_sig, expected_signature):
            raise ValueError("Invalid webhook signature")
        
        # Parsear payload
        try:
            event_data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON payload: {e}")
        
        return WebhookEvent(
            event_type=event_data.get("type", "unknown"),
            provider=self.provider_name,
            provider_event_id=event_data.get("id", self._generate_mock_id("evt")),
            provider_payment_id=event_data.get("data", {}).get("object", {}).get("id"),
            amount=Decimal(event_data.get("data", {}).get("object", {}).get("amount", 0)),
            currency=event_data.get("data", {}).get("object", {}).get("currency", "usd"),
            metadata=event_data.get("data", {}).get("object", {}).get("metadata", {}),
            raw_data=event_data,
        )
    
    # ============================================
    # Métodos auxiliares para testing
    # ============================================
    
    async def simulate_payment_completion(self, provider_payment_id: str) -> WebhookEvent:
        """
        Simula la completación de un pago (útil para testing).
        
        Retorna el evento de webhook que se generaría.
        """
        payment_data = self._payments.get(provider_payment_id)
        
        if not payment_data:
            raise ValueError(f"Payment not found: {provider_payment_id}")
        
        # Determinar si éxito o fallo basado en will_succeed
        if payment_data["will_succeed"]:
            payment_data["status"] = "succeeded"
            event_type = "payment.succeeded"
        else:
            payment_data["status"] = "failed"
            payment_data["failure_reason"] = "Card declined (simulated)"
            event_type = "payment.failed"
        
        logger.info(
            "Mock payment completed",
            mock_payment_id=provider_payment_id,
            status=payment_data["status"],
        )
        
        return WebhookEvent(
            event_type=event_type,
            provider=self.provider_name,
            provider_event_id=self._generate_mock_id("evt"),
            provider_payment_id=provider_payment_id,
            amount=Decimal(payment_data["amount"]),
            currency=payment_data["currency"],
            metadata=payment_data.get("metadata", {}),
            raw_data=payment_data,
        )
    
    def generate_webhook_signature(self, payload: bytes) -> str:
        """
        Genera una firma de webhook válida para testing.
        
        Args:
            payload: Cuerpo del webhook como bytes
            
        Returns:
            Header de firma en formato "t=timestamp,v1=signature"
        """
        timestamp = int(datetime.utcnow().timestamp())
        signature = hmac.new(
            self.MOCK_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        return f"t={timestamp},v1={signature}"
    
    def clear_payments(self) -> None:
        """Limpia todos los pagos mock (para testing)."""
        self._payments.clear()
        self._refunds.clear()
        logger.info("Mock payments cleared")
