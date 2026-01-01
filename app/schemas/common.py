"""
Schemas comunes y base para reutilización.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, ConfigDict


# TypeVar para respuestas genéricas
T = TypeVar("T")


class BaseSchema(BaseModel):
    """Schema base con configuración común."""
    
    model_config = ConfigDict(
        from_attributes=True,  # Permite crear desde ORM models
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class TimestampMixin(BaseModel):
    """Mixin para campos de timestamp."""
    
    created_at: datetime
    updated_at: datetime | None = None


class PaginationParams(BaseModel):
    """Parámetros de paginación."""
    
    page: int = 1
    page_size: int = 20
    
    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Respuesta paginada genérica."""
    
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class APIResponse(BaseModel, Generic[T]):
    """Respuesta estándar de la API."""
    
    success: bool = True
    message: str | None = None
    data: T | None = None
    errors: list[str] | None = None


class ErrorResponse(BaseModel):
    """Respuesta de error estándar."""
    
    success: bool = False
    message: str
    errors: list[str] | None = None
    request_id: str | None = None
