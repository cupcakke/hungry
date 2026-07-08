from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class EndpointStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class EventType(str, Enum):
    PAYMENT_INTENT_CREATED = "payment_intent.created"
    PAYMENT_INTENT_SUCCEEDED = "payment_intent.succeeded"
    PAYMENT_INTENT_FAILED = "payment_intent.payment_failed"
    PAYMENT_INTENT_CANCELED = "payment_intent.canceled"
    CHARGE_SUCCEEDED = "charge.succeeded"
    CHARGE_FAILED = "charge.failed"
    CHARGE_REFUNDED = "charge.refunded"
    CHARGE_CAPTURED = "charge.captured"
    CHARGE_DISPUTE_CREATED = "charge.dispute.created"
    CHARGE_DISPUTE_UPDATED = "charge.dispute.updated"
    CHARGE_DISPUTE_CLOSED = "charge.dispute.closed"
    CUSTOMER_CREATED = "customer.created"
    CUSTOMER_UPDATED = "customer.updated"
    CUSTOMER_DELETED = "customer.deleted"
    CUSTOMER_SOURCE_CREATED = "customer.source.created"
    CUSTOMER_SOURCE_DELETED = "customer.source.deleted"
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PAYMENT_SUCCEEDED = "invoice.payment_succeeded"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
    SUBSCRIPTION_CREATED = "customer.subscription.created"
    SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    SUBSCRIPTION_DELETED = "customer.subscription.deleted"
    TRANSFER_CREATED = "transfer.created"
    TRANSFER_FAILED = "transfer.failed"
    PAYOUT_CREATED = "payout.created"
    PAYOUT_SUCCEEDED = "payout.succeeded"
    PAYOUT_FAILED = "payout.failed"
    REFUND_CREATED = "refund.created"
    REFUND_UPDATED = "refund.updated"


class SignatureAlgorithm(str, Enum):
    HMAC_SHA256 = "hmac-sha256"
    HMAC_SHA512 = "hmac-sha512"


class WebhookDelivery(BaseModel):
    id: str = Field(default_factory=lambda: f"whdl_{uuid4().hex[:24]}")
    endpoint_id: str
    event_id: str
    attempt_number: int = Field(default=1, ge=1)
    status: DeliveryStatus = Field(default=DeliveryStatus.PENDING)
    response_code: Optional[int] = Field(default=None)
    response_body: Optional[str] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    next_retry_at: Optional[datetime] = Field(default=None)
    delivered_at: Optional[datetime] = Field(default=None)

    @field_validator("endpoint_id")
    @classmethod
    def validate_endpoint_id(cls, v: str) -> str:
        if not v.startswith("we_"):
            raise ValueError("Invalid endpoint ID format")
        return v

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, v: str) -> str:
        if not v.startswith("evt_"):
            raise ValueError("Invalid event ID format")
        return v


class WebhookEndpoint(BaseModel):
    id: str = Field(default_factory=lambda: f"we_{uuid4().hex[:24]}")
    account_id: Optional[str] = Field(default=None)
    url: str
    secret: str = Field(default_factory=lambda: f"whsec_{uuid4().hex}")
    events_subscribed: List[str] = Field(default_factory=list)
    status: EndpointStatus = Field(default=EndpointStatus.ENABLED)
    failure_count: int = Field(default=0, ge=0)
    consecutive_failures: int = Field(default=0, ge=0)
    last_success_at: Optional[datetime] = Field(default=None)
    last_failure_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    disabled_at: Optional[datetime] = Field(default=None)
    description: Optional[str] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        if len(v) > 2048:
            raise ValueError("URL must be less than 2048 characters")
        return v

    def record_success(self) -> None:
        self.last_success_at = datetime.now(timezone.utc)
        self.consecutive_failures = 0
        self.updated_at = datetime.now(timezone.utc)

    def record_failure(self) -> None:
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        if self.consecutive_failures >= 10:
            self.status = EndpointStatus.DISABLED
            self.disabled_at = datetime.now(timezone.utc)

    def is_subscribed_to(self, event_type: str) -> bool:
        if "*" in self.events_subscribed:
            return True
        for pattern in self.events_subscribed:
            if pattern == event_type:
                return True
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if event_type.startswith(prefix):
                    return True
        return False


class WebhookEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:24]}")
    type: str
    data: Dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = Field(default=None)
    account_id: Optional[str] = Field(default=None)
    api_version: str = Field(default="2024-01-01")
    livemode: bool = Field(default=False)
    pending_webhooks: int = Field(default=0)
    request: Optional[Dict[str, Any]] = Field(default=None)

    def mark_processed(self) -> None:
        self.processed_at = datetime.now(timezone.utc)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "object": "event",
            "api_version": self.api_version,
            "created": int(self.created_at.timestamp()),
            "data": {
                "object": self.data,
            },
            "livemode": self.livemode,
            "pending_webhooks": self.pending_webhooks,
            "request": self.request,
            "type": self.type,
        }


class WebhookSignature(BaseModel):
    algorithm: SignatureAlgorithm = Field(default=SignatureAlgorithm.HMAC_SHA256)
    signature_value: str
    timestamp: int
    version: str = Field(default="v1")

    def to_header(self) -> str:
        return f"t={self.timestamp},{self.version}={self.signature_value}"


class WebhookRetryPolicy(BaseModel):
    id: str = Field(default_factory=lambda: f"wrp_{uuid4().hex[:24]}")
    endpoint_id: str
    max_retries: int = Field(default=5, ge=0, le=25)
    retry_intervals: List[int] = Field(default_factory=lambda: [60, 300, 900, 3600, 7200])
    exponential_backoff: bool = Field(default=True)
    base_delay_seconds: int = Field(default=60, ge=1)
    max_delay_seconds: int = Field(default=86400, ge=60)
    jitter_factor: float = Field(default=0.1, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("retry_intervals")
    @classmethod
    def validate_retry_intervals(cls, v: List[int]) -> List[int]:
        if len(v) > 25:
            raise ValueError("Cannot have more than 25 retry intervals")
        for interval in v:
            if interval < 1:
                raise ValueError("Retry intervals must be at least 1 second")
        return sorted(v)

    def get_delay_for_attempt(self, attempt_number: int) -> int:
        if self.exponential_backoff:
            delay = self.base_delay_seconds * (2 ** (attempt_number - 1))
            delay = min(delay, self.max_delay_seconds)
        else:
            if attempt_number <= len(self.retry_intervals):
                delay = self.retry_intervals[attempt_number - 1]
            else:
                delay = self.retry_intervals[-1] if self.retry_intervals else self.base_delay_seconds
        if self.jitter_factor > 0:
            import random
            jitter = delay * self.jitter_factor * random.random()
            delay = int(delay + jitter)
        return delay


class DeadLetterEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"dlq_{uuid4().hex[:24]}")
    original_event_id: str
    original_endpoint_id: str
    original_payload: Dict[str, Any]
    failure_reason: str
    failure_count: int = Field(default=1, ge=1)
    last_failure_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    account_id: Optional[str] = Field(default=None)
    last_response_code: Optional[int] = Field(default=None)
    last_error_message: Optional[str] = Field(default=None)
    replayed: bool = Field(default=False)
    replayed_at: Optional[datetime] = Field(default=None)
    replay_event_id: Optional[str] = Field(default=None)
    retention_until: Optional[datetime] = Field(default=None)

    def mark_replayed(self, replay_event_id: str) -> None:
        self.replayed = True
        self.replayed_at = datetime.now(timezone.utc)
        self.replay_event_id = replay_event_id


class DeliveryAttempt(BaseModel):
    id: str = Field(default_factory=lambda: f"watt_{uuid4().hex[:24]}")
    delivery_id: str
    attempt_number: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status_code: Optional[int] = Field(default=None)
    response_time_ms: Optional[int] = Field(default=None)
    error_type: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    request_headers: Dict[str, str] = Field(default_factory=dict)
    response_headers: Optional[Dict[str, str]] = Field(default=None)


class WebhookMetrics(BaseModel):
    endpoint_id: str
    total_deliveries: int = Field(default=0)
    successful_deliveries: int = Field(default=0)
    failed_deliveries: int = Field(default=0)
    average_latency_ms: Optional[float] = Field(default=None)
    last_delivery_at: Optional[datetime] = Field(default=None)
    p50_latency_ms: Optional[float] = Field(default=None)
    p95_latency_ms: Optional[float] = Field(default=None)
    p99_latency_ms: Optional[float] = Field(default=None)

    @property
    def success_rate(self) -> float:
        if self.total_deliveries == 0:
            return 0.0
        return self.successful_deliveries / self.total_deliveries
