import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
import uvicorn

from payment_platform.admin_service.api.routes.auth import router as auth_router
from payment_platform.admin_service.api.routes.dashboard import router as dashboard_router
from payment_platform.admin_service.api.routes.merchants import router as merchants_router
from payment_platform.admin_service.api.routes.support import router as support_router
from payment_platform.admin_service.api.routes.admin_users import router as admin_users_router
from payment_platform.admin_service.api.routes.alerts import router as alerts_router
from payment_platform.shared.exceptions import (
    PaymentError,
    NotFoundError,
    ValidationError,
    UnauthorizedError,
    InsufficientFundsError,
)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_event()
    yield
    await shutdown_event()


async def startup_event():
    pass


async def shutdown_event():
    pass


app = FastAPI(
    title="Payment Platform - Admin Service",
    description="Admin Dashboard backend service for payment platform management",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PaymentError)
async def payment_error_handler(request: Request, exc: PaymentError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(
            error=exc.__class__.__name__,
            message=str(exc),
        ).model_dump(),
    )


@app.exception_handler(NotFoundError)
async def not_found_error_handler(request: Request, exc: NotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(
            error="not_found",
            message=str(exc),
        ).model_dump(),
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error="validation_error",
            message=str(exc),
        ).model_dump(),
    )


@app.exception_handler(UnauthorizedError)
async def unauthorized_error_handler(request: Request, exc: UnauthorizedError):
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=ErrorResponse(
            error="unauthorized",
            message=str(exc),
        ).model_dump(),
    )


@app.exception_handler(InsufficientFundsError)
async def insufficient_funds_error_handler(request: Request, exc: InsufficientFundsError):
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content=ErrorResponse(
            error="insufficient_funds",
            message=str(exc),
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error.get("loc", [])),
            "message": error.get("msg", "Validation error"),
            "type": error.get("type", "unknown"),
        })

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error="validation_error",
            message="Request validation failed",
            details={"errors": errors},
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="internal_error",
            message="An unexpected error occurred",
        ).model_dump(),
    )


app.include_router(auth_router, prefix="/admin/auth", tags=["Authentication"])
app.include_router(dashboard_router, prefix="/admin/dashboard", tags=["Dashboard"])
app.include_router(merchants_router, prefix="/admin/merchants", tags=["Merchants"])
app.include_router(support_router, prefix="/admin/support", tags=["Support"])
app.include_router(admin_users_router, prefix="/admin/users", tags=["Admin Users"])
app.include_router(alerts_router, prefix="/admin/alerts", tags=["System Alerts"])


@app.get("/", response_model=HealthResponse)
async def root():
    return HealthResponse(
        status="healthy",
        service="admin-service",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        service="admin-service",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/ready")
async def readiness_check():
    return {
        "status": "ready",
        "checks": {
            "database": "connected",
            "cache": "connected",
        }
    }


class RBACMiddleware:
    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive, send)
            path = request.url.path

            public_paths = [
                "/",
                "/health",
                "/ready",
                "/docs",
                "/redoc",
                "/openapi.json",
                "/admin/auth/login",
                "/admin/auth/refresh",
            ]

            if any(path.startswith(p) for p in public_paths):
                await self.app(scope, receive, send)
                return

        await self.app(scope, receive, send)


class AuditMiddleware:
    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope, receive, send)

            if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
                pass

        await self.app(scope, receive, send)


if __name__ == "__main__":
    uvicorn.run(
        "payment_platform.admin_service.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        access_log=True,
    )
