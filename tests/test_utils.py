"""
Tests para utilidades HMAC e idempotencia.
"""

import time
import pytest

from app.utils.hmac_utils import (
    generate_signature,
    verify_signature,
    create_webhook_signature_header,
    verify_webhook_signature_header,
)
from app.utils.idempotency import InMemoryIdempotencyManager


class TestHMACUtils:
    """Tests para utilidades HMAC."""
    
    def test_generate_signature(self):
        """Test generación de firma."""
        payload = b"test payload"
        secret = "test-secret"
        
        signature = generate_signature(payload, secret)
        
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 hex
    
    def test_verify_signature_valid(self):
        """Test verificación de firma válida."""
        payload = b"test payload"
        secret = "test-secret"
        
        signature = generate_signature(payload, secret)
        
        assert verify_signature(payload, signature, secret) is True
    
    def test_verify_signature_invalid(self):
        """Test verificación de firma inválida."""
        payload = b"test payload"
        secret = "test-secret"
        
        assert verify_signature(payload, "invalid", secret) is False
    
    def test_verify_signature_wrong_secret(self):
        """Test verificación con secret incorrecto."""
        payload = b"test payload"
        
        signature = generate_signature(payload, "secret-1")
        
        assert verify_signature(payload, signature, "secret-2") is False
    
    def test_create_webhook_signature_header(self):
        """Test creación de header de firma."""
        payload = b'{"event": "test"}'
        secret = "whsec_test123"
        
        header = create_webhook_signature_header(payload, secret)
        
        assert header.startswith("t=")
        assert ",v1=" in header
    
    def test_verify_webhook_signature_header_valid(self):
        """Test verificación de header válido."""
        payload = b'{"event": "test"}'
        secret = "whsec_test123"
        
        header = create_webhook_signature_header(payload, secret)
        is_valid, error = verify_webhook_signature_header(payload, header, secret)
        
        assert is_valid is True
        assert error is None
    
    def test_verify_webhook_signature_header_invalid_format(self):
        """Test verificación con formato inválido."""
        payload = b'{"event": "test"}'
        
        is_valid, error = verify_webhook_signature_header(
            payload, "invalid_header", "secret"
        )
        
        assert is_valid is False
        assert "Invalid signature header format" in error
    
    def test_verify_webhook_signature_header_expired(self):
        """Test verificación con timestamp expirado."""
        payload = b'{"event": "test"}'
        secret = "whsec_test123"
        
        # Crear header con timestamp antiguo
        old_timestamp = int(time.time()) - 600  # 10 minutos atrás
        header = create_webhook_signature_header(payload, secret, old_timestamp)
        
        is_valid, error = verify_webhook_signature_header(
            payload, header, secret, tolerance_seconds=300
        )
        
        assert is_valid is False
        assert "Timestamp out of tolerance" in error


class TestInMemoryIdempotencyManager:
    """Tests para el gestor de idempotencia en memoria."""
    
    @pytest.fixture
    def manager(self):
        return InMemoryIdempotencyManager()
    
    @pytest.mark.asyncio
    async def test_cache_and_retrieve_response(self, manager):
        """Test cachear y recuperar respuesta."""
        key = "test-key-123"
        response = {"payment_id": "123", "status": "pending"}
        
        # Cachear
        result = await manager.cache_response(key, response)
        assert result is True
        
        # Recuperar
        cached = await manager.get_cached_response(key)
        assert cached == response
    
    @pytest.mark.asyncio
    async def test_get_non_existent_key(self, manager):
        """Test obtener clave que no existe."""
        cached = await manager.get_cached_response("non-existent")
        assert cached is None
    
    @pytest.mark.asyncio
    async def test_processing_lock(self, manager):
        """Test lock de procesamiento."""
        key = "test-key-456"
        
        # Primera vez: adquirir lock
        is_processing = await manager.is_processing(key)
        assert is_processing is False  # No estaba procesando, ahora sí
        
        # Segunda vez: ya está siendo procesado
        is_processing = await manager.is_processing(key)
        assert is_processing is True
        
        # Liberar lock
        await manager.release_lock(key)
        
        # Ahora debería poder adquirir de nuevo
        is_processing = await manager.is_processing(key)
        assert is_processing is False
    
    @pytest.mark.asyncio
    async def test_delete_cached_response(self, manager):
        """Test eliminar respuesta cacheada."""
        key = "test-key-789"
        response = {"data": "test"}
        
        await manager.cache_response(key, response)
        assert await manager.get_cached_response(key) is not None
        
        await manager.delete(key)
        assert await manager.get_cached_response(key) is None
