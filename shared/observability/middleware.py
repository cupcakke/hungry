import time
from typing import Any, Callable, Dict, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from payment_platform.shared.observability.metrics import metrics
from payment_platform.shared.observability.tracing import (
    get_tracer,
    add_span_attributes,
    get_current_trace_id,
)
from payment_platform.shared.logging import bind_context, clear_context


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        service_name: str = "payment_platform",
    ) -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        clear_context()
        request_id = request.headers.get("x-request-id")
        if not request_id:
            import uuid
            request_id = str(uuid.uuid4())
        bind_context(request_id=request_id)
        trace_id = request.headers.get("x-trace-id")
        if trace_id:
            bind_context(trace_id=trace_id)
        account_id = request.headers.get("stripe-account")
        if account_id:
            bind_context(account_id=account_id)
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        endpoint = self._get_endpoint(request)
        metrics.track_http_request(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
            duration=duration,
        )
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time"] = f"{duration * 1000:.2f}ms"
        current_trace_id = get_current_trace_id()
        if current_trace_id:
            response.headers["x-trace-id"] = current_trace_id
        return response

    def _get_endpoint(self, request: Request) -> str:
        path = request.url.path
        if hasattr(request, "path_params") and request.path_params:
            for key, value in request.path_params.items():
                path = path.replace(str(value), f"{{{key}}}")
        return path


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        exclude_paths: Optional[list] = None,
    ) -> None:
        super().__init__(app)
        self.exclude_paths = exclude_paths or ["/health", "/metrics", "/readiness", "/liveness"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            duration = time.perf_counter() - start_time
            endpoint = self._normalize_path(request.url.path)
            metrics.increment_counter(
                "http_requests_total",
                {
                    "method": request.method,
                    "endpoint": endpoint,
                    "status_code": str(response.status_code),
                },
            )
            metrics.observe_histogram(
                "http_request_duration_seconds",
                duration,
                {"method": request.method, "endpoint": endpoint},
            )
            return response
        except Exception as e:
            duration = time.perf_counter() - start_time
            endpoint = self._normalize_path(request.url.path)
            metrics.increment_counter(
                "http_requests_total",
                {
                    "method": request.method,
                    "endpoint": endpoint,
                    "status_code": "500",
                },
            )
            metrics.observe_histogram(
                "http_request_duration_seconds",
                duration,
                {"method": request.method, "endpoint": endpoint},
            )
            metrics.track_error(type(e).__name__, "internal_error")
            raise

    def _normalize_path(self, path: str) -> str:
        import re
        path = re.sub(r"/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "/{id}", path)
        path = re.sub(r"/\d+", "/{id}", path)
        path = re.sub(r"/(pi_|ch_|cus_|sub_|in_|cs_|pm_|acct_)[a-zA-Z0-9]+", "/{id}", path)
        return path


class TracingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        service_name: str = "payment_platform",
    ) -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        tracer = get_tracer()
        endpoint = self._normalize_path(request.url.path)
        span_name = f"{request.method} {endpoint}"
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.route", endpoint)
            span.set_attribute("http.host", request.headers.get("host", ""))
            span.set_attribute("http.scheme", request.url.scheme)
            user_agent = request.headers.get("user-agent")
            if user_agent:
                span.set_attribute("http.user_agent", user_agent)
            content_length = request.headers.get("content-length")
            if content_length:
                span.set_attribute("http.request_content_length", content_length)
            account_id = request.headers.get("stripe-account")
            if account_id:
                span.set_attribute("account_id", account_id)
            try:
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 400:
                    from opentelemetry.trace import Status, StatusCode
                    span.set_status(Status(StatusCode.ERROR))
                else:
                    from opentelemetry.trace import Status, StatusCode
                    span.set_status(Status(StatusCode.OK))
                return response
            except Exception as e:
                span.record_exception(e)
                from opentelemetry.trace import Status, StatusCode
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    def _normalize_path(self, path: str) -> str:
        import re
        path = re.sub(r"/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", "/{id}", path)
        path = re.sub(r"/\d+", "/{id}", path)
        path = re.sub(r"/(pi_|ch_|cus_|sub_|in_|cs_|pm_|acct_)[a-zA-Z0-9]+", "/{id}", path)
        return path


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 100,
        burst_size: int = 20,
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self._requests: Dict[str, list] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in ["/health", "/metrics", "/readiness", "/liveness"]:
            return await call_next(request)
        client_id = self._get_client_id(request)
        if not self._check_rate_limit(client_id):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": "Too many requests. Please retry after some time.",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    }
                },
                headers={"Retry-After": "60"},
            )
        return await call_next(request)

    def _get_client_id(self, request: Request) -> str:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:20]
        api_key = request.headers.get("stripe-api-key", "")
        if api_key:
            return api_key[:13]
        x_forwarded_for = request.headers.get("x-forwarded-for", "")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _check_rate_limit(self, client_id: str) -> bool:
        import time
        current_time = time.time()
        window_start = current_time - 60
        if client_id not in self._requests:
            self._requests[client_id] = []
        self._requests[client_id] = [
            t for t in self._requests[client_id] if t > window_start
        ]
        if len(self._requests[client_id]) >= self.requests_per_minute:
            return False
        self._requests[client_id].append(current_time)
        return True


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response
