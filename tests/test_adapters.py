"""
Tests para el MockAdapter.
"""

import json
from decimal import Decimal
from uuid import uuid4

import pytest

from app.adapters.mock_adapter import MockAdapter
from app.adapters.base import PaymentResultStatus


class TestMockAdapter:
    """Tests para MockAdapter."""
    
    @pytest.fixture
    def adapter(self):
        """Crea un adapter mock con 100% de éxito."""
        adapter = MockAdapter(success_rate=1.0)
        adapter.clear_payments()
        return adapter
    
    @pytest.fixture
    def failing_adapter(self):
        """Crea un adapter mock con 0% de éxito."""
        adapter = MockAdapter(success_rate=0.0)
        adapter.clear_payments()
        return adapter
    
    @pytest.mark.asyncio
    async def test_create_payment_success(self, adapter: MockAdapter):
        """Test crear un pago exitosamente."""
        payment_id = uuid4()
        
        result = await adapter.create_payment(
            amount=Decimal("1000"),
            currency="usd",
            payment_id=payment_id,
            description="Test payment",
            customer_email="test@example.com",
        )
        
        assert result.status == PaymentResultStatus.PENDING
        assert result.provider == "mock"
        assert result.provider_payment_id.startswith("cs_")
        assert result.amount == Decimal("1000")
        assert result.currency == "usd"
        assert result.checkout_url is not None
    
    @pytest.mark.asyncio
    async def test_retrieve_payment(self, adapter: MockAdapter):
        """Test obtener estado de un pago."""
        payment_id = uuid4()
        
        # Crear pago
        create_result = await adapter.create_payment(
            amount=Decimal("500"),
            currency="usd",
            payment_id=payment_id,
        )
        
        # Obtener pago
        result = await adapter.retrieve_payment(create_result.provider_payment_id)
        
        assert result.status == PaymentResultStatus.PENDING
        assert result.provider_payment_id == create_result.provider_payment_id
    
    @pytest.mark.asyncio
    async def test_cancel_payment(self, adapter: MockAdapter):
        """Test cancelar un pago pendiente."""
        payment_id = uuid4()
        
        # Crear pago
        create_result = await adapter.create_payment(
            amount=Decimal("500"),
            currency="usd",
            payment_id=payment_id,
        )
        
        # Cancelar
        result = await adapter.cancel_payment(create_result.provider_payment_id)
        
        assert result.status == PaymentResultStatus.FAILED
        assert result.failure_reason == "Canceled by user"
    
    @pytest.mark.asyncio
    async def test_simulate_payment_completion_success(self, adapter: MockAdapter):
        """Test simular completación exitosa de pago."""
        payment_id = uuid4()
        
        # Crear pago
        create_result = await adapter.create_payment(
            amount=Decimal("1000"),
            currency="usd",
            payment_id=payment_id,
        )
        
        # Simular completación
        event = await adapter.simulate_payment_completion(
            create_result.provider_payment_id
        )
        
        assert event.event_type == "payment.succeeded"
        assert event.provider == "mock"
        assert event.amount == Decimal("1000")
    
    @pytest.mark.asyncio
    async def test_simulate_payment_completion_failure(self, failing_adapter: MockAdapter):
        """Test simular fallo de pago."""
        payment_id = uuid4()
        
        # Crear pago
        create_result = await failing_adapter.create_payment(
            amount=Decimal("1000"),
            currency="usd",
            payment_id=payment_id,
        )
        
        # Simular completación (fallará por success_rate=0)
        event = await failing_adapter.simulate_payment_completion(
            create_result.provider_payment_id
        )
        
        assert event.event_type == "payment.failed"
    
    @pytest.mark.asyncio
    async def test_refund_payment(self, adapter: MockAdapter):
        """Test reembolsar un pago."""
        payment_id = uuid4()
        
        # Crear y completar pago
        create_result = await adapter.create_payment(
            amount=Decimal("1000"),
            currency="usd",
            payment_id=payment_id,
        )
        await adapter.simulate_payment_completion(create_result.provider_payment_id)
        
        # Reembolsar
        result = await adapter.refund_payment(
            create_result.provider_payment_id,
            reason="Customer request",
        )
        
        assert result.status == PaymentResultStatus.SUCCESS
        assert result.amount == Decimal("1000")
        assert result.provider_refund_id.startswith("re_")
    
    def test_webhook_signature_generation_and_verification(self, adapter: MockAdapter):
        """Test generación y verificación de firma de webhook."""
        payload = json.dumps({
            "type": "payment.succeeded",
            "id": "evt_123",
            "data": {"object": {"id": "cs_123", "amount": 1000}},
        }).encode()
        
        # Generar firma
        signature = adapter.generate_webhook_signature(payload)
        
        assert signature.startswith("t=")
        assert ",v1=" in signature
        
        # Verificar firma
        event = adapter.construct_webhook_event(payload, signature)
        
        assert event.event_type == "payment.succeeded"
        assert event.provider == "mock"
    
    def test_invalid_webhook_signature_rejected(self, adapter: MockAdapter):
        """Test que firma inválida es rechazada."""
        payload = b'{"type": "test"}'
        invalid_signature = "t=123,v1=invalid_signature"
        
        with pytest.raises(ValueError, match="Invalid webhook signature"):
            adapter.construct_webhook_event(payload, invalid_signature)
