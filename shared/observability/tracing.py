import functools
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, TypeVar

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import Span, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from payment_platform.shared.config import settings


F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class TracingContext:
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    baggage: Dict[str, str] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)


_tracer: Optional[Tracer] = None
_propagator = TraceContextTextMapPropagator()


def setup_tracing(service_name: Optional[str] = None) -> Tracer:
    global _tracer
    if service_name is None:
        service_name = settings.app_name
    resource = Resource.create({SERVICE_NAME: service_name})
    sampler = TraceIdRatioBased(settings.observability.tracing_sample_rate)
    provider = TracerProvider(resource=resource, sampler=sampler)
    if settings.observability.tracing_enabled:
        if settings.observability.tracing_provider == "otlp":
            exporter = OTLPSpanExporter(
                endpoint=settings.observability.tracing_endpoint or "http://localhost:4317",
            )
        elif settings.observability.tracing_provider == "console":
            exporter = ConsoleSpanExporter()
        else:
            exporter = ConsoleSpanExporter()
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name, settings.app_version)
    return _tracer


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = setup_tracing()
    return _tracer


@contextmanager
def start_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    kind: trace.SpanKind = trace.SpanKind.INTERNAL,
) -> Span:
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=kind) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


def add_span_attributes(**kwargs: Any) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        for key, value in kwargs.items():
            span.set_attribute(key, value)


def record_exception(exception: Exception, attributes: Optional[Dict[str, Any]] = None) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.record_exception(exception, attributes=attributes)
        span.set_status(Status(StatusCode.ERROR, str(exception)))


def trace_function(
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        span_name = name or func.__name__

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    record_exception(e)
                    raise

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    record_exception(e)
                    raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def inject_trace_context(carrier: Dict[str, str]) -> None:
    _propagator.inject(carrier)


def extract_trace_context(carrier: Dict[str, str]) -> Context:
    return _propagator.extract(carrier)


def get_current_trace_id() -> Optional[str]:
    span = trace.get_current_span()
    if span.is_recording():
        return format(span.context.trace_id, "032x")
    return None


def get_current_span_id() -> Optional[str]:
    span = trace.get_current_span()
    if span.is_recording():
        return format(span.context.span_id, "016x")
    return None


class TraceContextManager:
    def __init__(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self.name = name
        self.attributes = attributes or {}
        self.span: Optional[Span] = None
        self.start_time: Optional[float] = None

    def __enter__(self) -> "TraceContextManager":
        self.start_time = time.perf_counter()
        tracer = get_tracer()
        self.span = tracer.start_span(self.name)
        for key, value in self.attributes.items():
            self.span.set_attribute(key, value)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.span:
            if exc_type is not None:
                self.span.record_exception(exc_val)
                self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
            else:
                self.span.set_status(Status(StatusCode.OK))
            if self.start_time:
                duration = time.perf_counter() - self.start_time
                self.span.set_attribute("duration_ms", duration * 1000)
            self.span.end()

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        if self.span:
            self.span.add_event(name, attributes=attributes)

    def set_attribute(self, key: str, value: Any) -> None:
        if self.span:
            self.span.set_attribute(key, value)


def trace_payment_operation(payment_intent_id: str, operation: str) -> TraceContextManager:
    return TraceContextManager(
        f"payment.{operation}",
        {
            "payment_intent_id": payment_intent_id,
            "operation": operation,
        },
    )


def trace_refund_operation(refund_id: str, charge_id: str) -> TraceContextManager:
    return TraceContextManager(
        "refund.create",
        {
            "refund_id": refund_id,
            "charge_id": charge_id,
        },
    )


def trace_webhook_delivery(event_id: str, endpoint_url: str) -> TraceContextManager:
    return TraceContextManager(
        "webhook.deliver",
        {
            "event_id": event_id,
            "endpoint_url": endpoint_url,
        },
    )


def trace_database_operation(operation: str, table: str) -> TraceContextManager:
    return TraceContextManager(
        f"database.{operation}",
        {
            "db.operation": operation,
            "db.table": table,
        },
    )
