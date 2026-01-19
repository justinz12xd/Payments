"""
Payment Microservice - Love4Pets
FastAPI application entry point.
"""

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes import payments_router, webhooks_router, partners_router, adoptions_router
from app.db.database import init_db, close_db
from app.utils.idempotency import close_redis


# Configurar logging estructurado
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer() if settings.ENVIRONMENT == "production" 
        else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestión del ciclo de vida de la aplicación."""
    # Startup
    logger.info(
        "Starting Payment Service",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        payment_provider=settings.PAYMENT_PROVIDER,
    )
    
    # Inicializar base de datos
    await init_db()
    
    yield
    
    # Shutdown
    logger.info("Shutting down Payment Service")
    await close_db()
    await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Microservicio de pagos para Love4Pets con soporte para Stripe y webhooks B2B",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restringir en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Añade request_id a cada petición para trazabilidad."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    
    # Bind request_id al logger
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint."""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "payment_provider": settings.PAYMENT_PROVIDER,
    }


# Incluir routers
app.include_router(payments_router, prefix="/api/payments", tags=["Payments"])
app.include_router(webhooks_router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(partners_router, prefix="/api/partners", tags=["Partners"])
app.include_router(adoptions_router, prefix="/api/adoptions", tags=["Adoptions B2B"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=True)
