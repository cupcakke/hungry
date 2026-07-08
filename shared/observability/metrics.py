import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from prometheus_client import Counter, Gauge, Histogram, Info, CollectorRegistry, REGISTRY
from prometheus_client import start_http_server as start_prometheus_http_server

from payment_platform.shared.config import settings


F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class MetricConfig:
    name: str
    description: str
    labels: Optional[List[str]] = None


class MetricsCollector:
    def __init__(self, namespace: str = "payment_platform", registry: CollectorRegistry = REGISTRY) -> None:
        self.namespace = namespace
        self.registry = registry
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._infos: Dict[str, Info] = {}
        self._setup_default_metrics()

    def _setup_default_metrics(self) -> None:
        self._create_counter(
            "http_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status_code"],
        )
        self._create_counter(
            "payments_total",
            "Total number of payment transactions",
            ["status", "currency", "payment_method_type"],
        )
        self._create_counter(
            "payment_amount_total",
            "Total payment amount processed",
            ["currency", "status"],
        )
        self._create_counter(
            "refunds_total",
            "Total number of refunds",
            ["status", "currency"],
        )
        self._create_counter(
            "subscriptions_total",
            "Total number of subscription events",
            ["event", "status"],
        )
        self._create_counter(
            "webhooks_total",
            "Total number of webhook deliveries",
            ["status", "event_type"],
        )
        self._create_counter(
            "errors_total",
            "Total number of errors",
            ["type", "code"],
        )
        self._create_histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        self._create_histogram(
            "payment_processing_duration_seconds",
            "Payment processing duration in seconds",
            ["payment_method_type", "status"],
            buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
        )
        self._create_histogram(
            "webhook_delivery_duration_seconds",
            "Webhook delivery duration in seconds",
            ["status"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
        )
        self._create_gauge(
            "active_subscriptions",
            "Number of active subscriptions",
            ["plan_id"],
        )
        self._create_gauge(
            "pending_payments",
            "Number of pending payments",
            [],
        )
        self._create_gauge(
            "queue_size",
            "Current queue size",
            ["queue_name"],
        )
        self._create_gauge(
            "database_connections",
            "Number of database connections",
            ["state"],
        )
        self._create_info(
            "application_info",
            "Application information",
        )

    def _create_counter(
        self,
        name: str,
        description: str,
        labels: List[str],
    ) -> Counter:
        full_name = f"{self.namespace}_{name}"
        if full_name not in self._counters:
            self._counters[full_name] = Counter(
                full_name,
                description,
                labels,
                registry=self.registry,
            )
        return self._counters[full_name]

    def _create_gauge(
        self,
        name: str,
        description: str,
        labels: List[str],
    ) -> Gauge:
        full_name = f"{self.namespace}_{name}"
        if full_name not in self._gauges:
            self._gauges[full_name] = Gauge(
                full_name,
                description,
                labels,
                registry=self.registry,
            )
        return self._gauges[full_name]

    def _create_histogram(
        self,
        name: str,
        description: str,
        labels: List[str],
        buckets: Optional[List[float]] = None,
    ) -> Histogram:
        full_name = f"{self.namespace}_{name}"
        if full_name not in self._histograms:
            self._histograms[full_name] = Histogram(
                full_name,
                description,
                labels,
                buckets=buckets,
                registry=self.registry,
            )
        return self._histograms[full_name]

    def _create_info(
        self,
        name: str,
        description: str,
    ) -> Info:
        full_name = f"{self.namespace}_{name}"
        if full_name not in self._infos:
            self._infos[full_name] = Info(
                full_name,
                description,
                registry=self.registry,
            )
        return self._infos[full_name]

    def increment_counter(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None,
        value: float = 1.0,
    ) -> None:
        full_name = f"{self.namespace}_{name}"
        counter = self._counters.get(full_name)
        if counter:
            if labels:
                counter.labels(**labels).inc(value)
            else:
                counter.inc(value)

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        full_name = f"{self.namespace}_{name}"
        gauge = self._gauges.get(full_name)
        if gauge:
            if labels:
                gauge.labels(**labels).set(value)
            else:
                gauge.set(value)

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        full_name = f"{self.namespace}_{name}"
        histogram = self._histograms.get(full_name)
        if histogram:
            if labels:
                histogram.labels(**labels).observe(value)
            else:
                histogram.observe(value)

    def set_info(self, name: str, info: Dict[str, str]) -> None:
        full_name = f"{self.namespace}_{name}"
        info_metric = self._infos.get(full_name)
        if info_metric:
            info_metric.info(info)

    @contextmanager
    def track_time(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.observe_histogram(name, duration, labels)

    def track_http_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration: float,
    ) -> None:
        self.increment_counter(
            "http_requests_total",
            {"method": method, "endpoint": endpoint, "status_code": str(status_code)},
        )
        self.observe_histogram(
            "http_request_duration_seconds",
            duration,
            {"method": method, "endpoint": endpoint},
        )

    def track_payment(
        self,
        status: str,
        currency: str,
        payment_method_type: str,
        amount: Optional[int] = None,
        duration: Optional[float] = None,
    ) -> None:
        labels = {
            "status": status,
            "currency": currency,
            "payment_method_type": payment_method_type,
        }
        self.increment_counter("payments_total", labels)
        if amount is not None:
            self.increment_counter(
                "payment_amount_total",
                {"currency": currency, "status": status},
                amount / 100,
            )
        if duration is not None:
            self.observe_histogram(
                "payment_processing_duration_seconds",
                duration,
                {"payment_method_type": payment_method_type, "status": status},
            )

    def track_webhook(
        self,
        event_type: str,
        status: str,
        duration: Optional[float] = None,
    ) -> None:
        self.increment_counter(
            "webhooks_total",
            {"event_type": event_type, "status": status},
        )
        if duration is not None:
            self.observe_histogram(
                "webhook_delivery_duration_seconds",
                duration,
                {"status": status},
            )

    def track_error(self, error_type: str, error_code: str) -> None:
        self.increment_counter(
            "errors_total",
            {"type": error_type, "code": error_code},
        )

    def set_active_subscriptions(self, plan_id: str, count: int) -> None:
        self.set_gauge("active_subscriptions", count, {"plan_id": plan_id})

    def set_pending_payments(self, count: int) -> None:
        self.set_gauge("pending_payments", count)

    def set_queue_size(self, queue_name: str, size: int) -> None:
        self.set_gauge("queue_size", size, {"queue_name": queue_name})

    def set_database_connections(self, state: str, count: int) -> None:
        self.set_gauge("database_connections", count, {"state": state})


metrics = MetricsCollector()


def increment_counter(name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0) -> None:
    metrics.increment_counter(name, labels, value)


def observe_histogram(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    metrics.observe_histogram(name, value, labels)


def set_gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    metrics.set_gauge(name, value, labels)


def track_time(name: str, labels: Optional[Dict[str, str]] = None) -> Any:
    return metrics.track_time(name, labels)


def track_payment_metrics(
    status: str,
    currency: str,
    payment_method_type: str,
    amount: Optional[int] = None,
    duration: Optional[float] = None,
) -> None:
    metrics.track_payment(status, currency, payment_method_type, amount, duration)


def track_webhook_metrics(
    event_type: str,
    status: str,
    duration: Optional[float] = None,
) -> None:
    metrics.track_webhook(event_type, status, duration)


def start_metrics_server(port: Optional[int] = None) -> None:
    if port is None:
        port = settings.observability.metrics_port
    start_prometheus_http_server(port)
