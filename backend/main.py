import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from payment_platform.shared.config import settings
from payment_platform.shared.logging import setup_logging, get_logger, bind_context, clear_context
from payment_platform.shared.exceptions import PaymentPlatformError
from payment_platform.backend.api import router as api_router
from payment_platform.backend.infrastructure.database import init_db, close_db
from payment_platform.shared.observability.middleware import (
    ObservabilityMiddleware,
    RequestMetricsMiddleware,
    TracingMiddleware,
    SecurityHeadersMiddleware,
)
from payment_platform.shared.observability.health import health_checker, register_default_health_checks

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting payment platform", version=settings.app_version)
    register_default_health_checks()
    await init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down payment platform")
    await close_db()
    logger.info("Database connections closed")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.api.title,
        description=settings.api.description,
        version=settings.app_version,
        docs_url=settings.api.docs_url if not settings.is_production else None,
        redoc_url=settings.api.redoc_url if not settings.is_production else None,
        openapi_url=settings.api.openapi_url if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.security.cors_origins,
        allow_credentials=settings.security.cors_allow_credentials,
        allow_methods=settings.security.cors_allow_methods,
        allow_headers=settings.security.cors_allow_headers,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(TracingMiddleware)
    app.add_middleware(RequestMetricsMiddleware)
    app.add_middleware(ObservabilityMiddleware)

    @app.exception_handler(PaymentPlatformError)
    async def payment_platform_error_handler(request: Request, exc: PaymentPlatformError) -> JSONResponse:
        logger.error(
            "Payment platform error",
            error_type=type(exc).__name__,
            error_code=exc.code,
            message=exc.message,
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.detail,
                    "type": "http_error",
                    "code": str(exc.status_code),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error.get("loc", []))
            errors.append({
                "field": field,
                "message": error.get("msg", "Validation error"),
                "type": error.get("type", "validation_error"),
            })
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "message": "Request validation failed",
                    "type": "validation_error",
                    "code": "invalid_request",
                    "details": {"errors": errors},
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "message": "An internal error occurred" if settings.is_production else str(exc),
                    "type": "internal_error",
                    "code": "internal_error",
                }
            },
        )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next: Callable) -> Response:
        clear_context()
        request_id = request.headers.get("x-request-id")
        if not request_id:
            import uuid
            request_id = str(uuid.uuid4())
        bind_context(request_id=request_id)
        account_id = request.headers.get("stripe-account")
        if account_id:
            bind_context(account_id=account_id)
            request.state.account_id = account_id
        else:
            request.state.account_id = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
            request.state.api_key = api_key
            bind_context(api_key_prefix=api_key[:13] if len(api_key) >= 13 else api_key)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    app.include_router(api_router, prefix="/v1")

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": settings.app_version}

    @app.get("/readiness")
    async def readiness_check():
        from payment_platform.shared.observability.health import readiness_checker
        is_ready = await readiness_checker.is_ready()
        if is_ready:
            return {"status": "ready"}
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )

    @app.get("/liveness")
    async def liveness_check():
        from payment_platform.shared.observability.health import liveness_checker
        liveness_checker.heartbeat()
        if liveness_checker.is_alive():
            return {"status": "alive"}
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_alive"},
        )

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
            "name": settings.app_name,
            "version": settings.app_version,
            "documentation": "/docs" if not settings.is_production else None,
        }

    return app


app = create_app()


def run_api():
    import uvicorn
    uvicorn.run(
        "payment_platform.backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        workers=1 if settings.is_development else 4,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    run_api()
