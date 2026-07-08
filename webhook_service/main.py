import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment_platform.shared.config import settings
from payment_platform.shared.logging import setup_logging, get_logger, bind_context
from payment_platform.shared.observability.metrics import metrics
from payment_platform.webhook_service.api.routes.webhooks import router as webhook_router

logger = get_logger(__name__)

_start_time = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting webhook delivery service")
    yield
    logger.info("Shutting down webhook delivery service")


app = FastAPI(
    title="Payment Platform Webhook Service",
    description="Service for delivering webhooks with retry support, dead letter queue, and event replay",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "webhook-service",
        "version": "1.0.0",
        "uptime_seconds": int((datetime.now(timezone.utc) - _start_time).total_seconds()),
    }


@app.get("/metrics")
async def metrics_endpoint():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/")
async def root():
    return {
        "service": "Payment Platform Webhook Service",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
        },
    )


def run_webhook():
    import uvicorn
    uvicorn.run(
        "payment_platform.webhook_service.main:app",
        host="0.0.0.0",
        port=8002,
        log_config=None,
        reload=True,
    )


if __name__ == "__main__":
    run_webhook()
