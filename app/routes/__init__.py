"""
Rutas/Endpoints del microservicio de pagos.
"""

from app.routes.payments import router as payments_router
from app.routes.webhooks import router as webhooks_router
from app.routes.partners import router as partners_router
from app.routes.adoptions import router as adoptions_router

__all__ = [
    "payments_router",
    "webhooks_router",
    "partners_router",
    "adoptions_router",
]
