"""
Configuración del microservicio de pagos.
Carga variables de entorno y define settings globales.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    """Configuración principal del servicio."""
    
    # Aplicación
    APP_NAME: str = "Love4Pets Payment Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    
    # Base de datos PostgreSQL
    DATABASE_URL: str
    
    # Supabase (opcional, para integración futura)
    SUPABASE_URL: str = ""
    
    # Redis para idempotencia
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Stripe
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str = ""
    
    # Proveedor de pago activo: "stripe" o "mock"
    PAYMENT_PROVIDER: Literal["stripe", "mock"] = "mock"
    
    # HMAC para webhooks salientes a partners
    HMAC_DEFAULT_SECRET: str = "dev-secret-change-in-production"
    
    # WebSocket Service URL (para notificar eventos)
    WEBSOCKET_SERVICE_URL: str = "http://localhost:4000"
    
    # n8n Webhook URL (para orquestación de eventos)
    N8N_WEBHOOK_URL: str = ""
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Retorna instancia cacheada de settings."""
    return Settings()


settings = get_settings()
