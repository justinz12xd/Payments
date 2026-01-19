"""
Schemas para notificaciones de adopción B2B.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr

from app.schemas.common import BaseSchema


class AdopterInfo(BaseSchema):
    """Información del adoptante."""
    
    name: str = Field(..., description="Nombre del adoptante")
    email: EmailStr = Field(..., description="Email del adoptante")
    phone: str | None = Field(None, description="Teléfono del adoptante")
    address: str | None = Field(None, description="Dirección del adoptante")
    message: str | None = Field(None, description="Mensaje del adoptante")


class AnimalInfo(BaseSchema):
    """Información del animal adoptado."""
    
    id: str = Field(..., description="ID del animal")
    name: str = Field(..., description="Nombre del animal")
    species: str | None = Field(None, description="Especie del animal")
    breed: str | None = Field(None, description="Raza del animal")
    age: str | None = Field(None, description="Edad del animal")
    image_url: str | None = Field(None, description="URL de la imagen del animal")


class ShelterInfo(BaseSchema):
    """Información del refugio."""
    
    id: str = Field(..., description="ID del refugio")
    name: str | None = Field(None, description="Nombre del refugio")
    email: str | None = Field(None, description="Email del refugio")


class AdoptionNotifyRequest(BaseSchema):
    """
    Request para notificar una adopción a partners B2B.
    
    Este endpoint permite que tu API REST notifique al servicio de pagos
    cuando se crea una adopción, para que este envíe webhooks firmados
    a todos los partners suscritos al evento 'adoption.created'.
    """
    
    adoption_id: str = Field(..., description="ID de la adopción")
    status: str = Field(default="pending", description="Estado de la adopción")
    adopter: AdopterInfo = Field(..., description="Información del adoptante")
    animal: AnimalInfo = Field(..., description="Información del animal")
    shelter: ShelterInfo = Field(..., description="Información del refugio")
    metadata: dict[str, Any] | None = Field(None, description="Metadatos adicionales")


class AdoptionNotifyResponse(BaseSchema):
    """Response de la notificación de adopción."""
    
    success: bool = Field(..., description="Si la operación fue exitosa")
    message: str = Field(..., description="Mensaje de resultado")
    webhooks_sent: int = Field(default=0, description="Número de webhooks enviados")
    webhook_ids: list[str] = Field(default_factory=list, description="IDs de los webhooks enviados")


class AdoptionWebhookPayload(BaseSchema):
    """
    Payload del webhook de adopción que se envía a partners.
    
    Este es el formato simplificado que recibirá tu compañero cuando le llegue
    la notificación de adopción.
    """
    
    event: str = Field(default="adoption.created", description="Tipo de evento")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp del evento")
    
    # Datos esenciales del adoptante (lo que tu compañero necesita)
    adopter_email: str = Field(..., description="Email del adoptante")
    adopter_name: str = Field(..., description="Nombre del adoptante")
    adopter_phone: str | None = Field(None, description="Teléfono del adoptante")
    
    # Datos del animal
    adoption_id: str | None = Field(None, description="ID de la adopción")
    animal_id: str | None = Field(None, description="ID del animal")
    animal_name: str | None = Field(None, description="Nombre del animal")
    animal_species: str | None = Field(None, description="Especie del animal")
    
    # Datos del refugio
    shelter_id: str | None = Field(None, description="ID del refugio")
    shelter_name: str | None = Field(None, description="Nombre del refugio")


class TestWebhookRequest(BaseSchema):
    """
    Request para enviar un webhook de prueba a partners.
    
    Usa este endpoint desde /docs para probar el envío de webhooks
    a tu compañero sin necesidad de hacer el flujo completo.
    """
    
    event_type: str = Field(
        default="adoption.completed",
        description="Tipo de evento: adoption.created, adoption.approved, adoption.completed",
        json_schema_extra={"examples": ["adoption.completed", "adoption.approved", "adoption.created"]}
    )
    partner_webhook_url: str | None = Field(
        None,
        description="URL específica del partner (opcional, si no se provee se envía a todos los partners suscritos)"
    )
    
    # Datos del adoptante
    adopter_email: EmailStr = Field(
        default="test@example.com",
        description="Email del adoptante"
    )
    adopter_name: str = Field(
        default="Usuario de Prueba",
        description="Nombre del adoptante"
    )
    adopter_phone: str | None = Field(
        default="0999999999",
        description="Teléfono del adoptante"
    )
    
    # Datos del animal
    adoption_id: str = Field(
        default="test-adoption-123",
        description="ID de la adopción"
    )
    animal_id: str = Field(
        default="test-animal-456",
        description="ID del animal"
    )
    animal_name: str = Field(
        default="Firulais",
        description="Nombre del animal"
    )
    animal_species: str = Field(
        default="Perro",
        description="Especie del animal"
    )
    
    # Datos del refugio
    shelter_id: str = Field(
        default="test-shelter-789",
        description="ID del refugio"
    )
    shelter_name: str = Field(
        default="Refugio Love4Pets",
        description="Nombre del refugio"
    )


class TestWebhookResponse(BaseSchema):
    """Response del webhook de prueba."""
    
    success: bool = Field(..., description="Si el envío fue exitoso")
    message: str = Field(..., description="Mensaje de resultado")
    payload_sent: dict = Field(..., description="Payload que se envió")
    webhooks_sent: int = Field(default=0, description="Número de webhooks enviados")
    webhook_ids: list[str] = Field(default_factory=list, description="IDs de los webhooks")
