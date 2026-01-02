"""
Tests de integración para endpoints de la API.
"""

import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """Tests para endpoints de salud."""
    
    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient):
        """Test endpoint raíz."""
        response = await client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "version" in data
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        """Test endpoint de health check."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestPaymentEndpoints:
    """Tests para endpoints de pagos."""
    
    @pytest.mark.asyncio
    async def test_create_payment(self, client: AsyncClient, sample_payment_data):
        """Test crear un pago."""
        response = await client.post("/payments", json=sample_payment_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["payment_id"] is not None
        assert data["data"]["status"] == "pending"
        assert data["data"]["provider"] == "mock"
    
    @pytest.mark.asyncio
    async def test_create_payment_with_idempotency(
        self, client: AsyncClient, sample_payment_data
    ):
        """Test idempotencia al crear pagos."""
        idempotency_key = "test-idempotency-key-123"
        headers = {"Idempotency-Key": idempotency_key}
        
        # Primera llamada
        response1 = await client.post(
            "/payments", json=sample_payment_data, headers=headers
        )
        assert response1.status_code == 201
        payment_id_1 = response1.json()["data"]["payment_id"]
        
        # Segunda llamada con la misma key
        response2 = await client.post(
            "/payments", json=sample_payment_data, headers=headers
        )
        assert response2.status_code == 201
        payment_id_2 = response2.json()["data"]["payment_id"]
        
        # Debe retornar el mismo pago
        assert payment_id_1 == payment_id_2
    
    @pytest.mark.asyncio
    async def test_get_payment(self, client: AsyncClient, sample_payment_data):
        """Test obtener un pago por ID."""
        # Crear pago
        create_response = await client.post("/payments", json=sample_payment_data)
        payment_id = create_response.json()["data"]["payment_id"]
        
        # Obtener pago
        response = await client.get(f"/payments/{payment_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] == payment_id
    
    @pytest.mark.asyncio
    async def test_get_payment_not_found(self, client: AsyncClient):
        """Test obtener pago que no existe."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(f"/payments/{fake_id}")
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_cancel_payment(self, client: AsyncClient, sample_payment_data):
        """Test cancelar un pago pendiente."""
        # Crear pago
        create_response = await client.post("/payments", json=sample_payment_data)
        payment_id = create_response.json()["data"]["payment_id"]
        
        # Cancelar
        response = await client.post(f"/payments/{payment_id}/cancel")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["status"] == "canceled"


class TestPartnerEndpoints:
    """Tests para endpoints de partners."""
    
    @pytest.mark.asyncio
    async def test_register_partner(self, client: AsyncClient, sample_partner_data):
        """Test registrar un partner."""
        response = await client.post("/partners/register", json=sample_partner_data)
        
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["id"] is not None
        assert data["data"]["secret"] is not None
        assert data["data"]["secret"].startswith("whsec_")
    
    @pytest.mark.asyncio
    async def test_list_partners(self, client: AsyncClient, sample_partner_data):
        """Test listar partners."""
        # Registrar un partner
        await client.post("/partners/register", json=sample_partner_data)
        
        # Listar
        response = await client.get("/partners")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1
    
    @pytest.mark.asyncio
    async def test_get_partner(self, client: AsyncClient, sample_partner_data):
        """Test obtener un partner por ID."""
        # Registrar
        register_response = await client.post(
            "/partners/register", json=sample_partner_data
        )
        partner_id = register_response.json()["data"]["id"]
        
        # Obtener
        response = await client.get(f"/partners/{partner_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == partner_id
        # El secret no debe estar en la respuesta de GET
        assert "secret" not in data["data"]
    
    @pytest.mark.asyncio
    async def test_rotate_partner_secret(self, client: AsyncClient, sample_partner_data):
        """Test rotar secret de partner."""
        # Registrar
        register_response = await client.post(
            "/partners/register", json=sample_partner_data
        )
        partner_id = register_response.json()["data"]["id"]
        old_secret = register_response.json()["data"]["secret"]
        
        # Rotar
        response = await client.post(f"/partners/{partner_id}/rotate-secret")
        
        assert response.status_code == 200
        data = response.json()
        new_secret = data["data"]["new_secret"]
        
        assert new_secret != old_secret
        assert new_secret.startswith("whsec_")
    
    @pytest.mark.asyncio
    async def test_deactivate_partner(self, client: AsyncClient, sample_partner_data):
        """Test desactivar un partner."""
        # Registrar
        register_response = await client.post(
            "/partners/register", json=sample_partner_data
        )
        partner_id = register_response.json()["data"]["id"]
        
        # Desactivar
        response = await client.post(f"/partners/{partner_id}/deactivate")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["status"] == "inactive"
    
    @pytest.mark.asyncio
    async def test_register_duplicate_partner(
        self, client: AsyncClient, sample_partner_data
    ):
        """Test registrar partner duplicado."""
        # Registrar primero
        await client.post("/partners/register", json=sample_partner_data)
        
        # Intentar registrar de nuevo con mismo nombre
        response = await client.post("/partners/register", json=sample_partner_data)
        
        assert response.status_code == 409  # Conflict
