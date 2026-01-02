"""
Configuración de tests y fixtures compartidos.
"""

import asyncio
from typing import AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
from app.db.models import Base
from app.db.database import get_db
from app.config import settings


# Base de datos de testing en memoria
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Crea un event loop para toda la sesión de tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Crea un engine de testing para cada test."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Crea una sesión de testing."""
    async_session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP para tests de API."""
    
    async def override_get_db():
        yield test_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest.fixture
def sample_payment_data():
    """Datos de ejemplo para crear un pago."""
    return {
        "amount": 1000,  # $10.00 en centavos
        "currency": "usd",
        "payment_type": "donation",
        "payer_email": "test@example.com",
        "payer_name": "Test User",
        "description": "Test donation",
    }


@pytest.fixture
def sample_partner_data():
    """Datos de ejemplo para registrar un partner."""
    return {
        "name": f"Test Partner {uuid4().hex[:8]}",
        "webhook_url": "https://partner.example.com/webhook",
        "events": ["payment.succeeded", "payment.failed"],
        "description": "Partner de prueba",
        "contact_email": "partner@example.com",
    }
