import asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from payment_platform.webhook_service.domain.models import (
    DeliveryStatus,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookRetryPolicy,
    DeadLetterEntry,
)
from payment_platform.webhook_service.services.dead_letter_service import DeadLetterService


class WebhookRetryService:
    DEFAULT_MAX_RETRIES = 5
    DEFAULT_BASE_DELAY = 60
    DEFAULT_MAX_DELAY = 86400
    DEFAULT_JITTER_FACTOR = 0.1
    RETRY_INTERVALS = [60, 300, 900, 1800, 3600, 7200, 14400, 28800]

    def __init__(
        self,
        dead_letter_service: Optional[DeadLetterService] = None,
        default_max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self._dead_letter_service = dead_letter_service or DeadLetterService()
        self._policies: Dict[str, WebhookRetryPolicy] = {}
        self._retry_queue: Dict[str, List[WebhookDelivery]] = {}
        self._default_max_retries = default_max_retries

    def create_policy(
        self,
        endpoint_id: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        exponential_backoff: bool = True,
        base_delay_seconds: int = DEFAULT_BASE_DELAY,
        max_delay_seconds: int = DEFAULT_MAX_DELAY,
        jitter_factor: float = DEFAULT_JITTER_FACTOR,
        retry_intervals: Optional[List[int]] = None,
    ) -> WebhookRetryPolicy:
        policy = WebhookRetryPolicy(
            endpoint_id=endpoint_id,
            max_retries=max_retries,
            exponential_backoff=exponential_backoff,
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
            jitter_factor=jitter_factor,
            retry_intervals=retry_intervals or self.RETRY_INTERVALS[:max_retries],
        )
        self._policies[endpoint_id] = policy
        return policy

    def get_policy(self, endpoint_id: str) -> WebhookRetryPolicy:
        if endpoint_id not in self._policies:
            return self.create_policy(endpoint_id)
        return self._policies[endpoint_id]

    def calculate_delay(
        self,
        attempt_number: int,
        policy: Optional[WebhookRetryPolicy] = None,
    ) -> int:
        if policy is None:
            base_delay = self.DEFAULT_BASE_DELAY
            max_delay = self.DEFAULT_MAX_DELAY
            jitter_factor = self.DEFAULT_JITTER_FACTOR
            exponential = True
        else:
            base_delay = policy.base_delay_seconds
            max_delay = policy.max_delay_seconds
            jitter_factor = policy.jitter_factor
            exponential = policy.exponential_backoff
        if exponential:
            delay = base_delay * (2 ** (attempt_number - 1))
            delay = min(delay, max_delay)
        else:
            intervals = policy.retry_intervals if policy else self.RETRY_INTERVALS
            if attempt_number <= len(intervals):
                delay = intervals[attempt_number - 1]
            else:
                delay = intervals[-1] if intervals else base_delay
        if jitter_factor > 0:
            jitter = delay * jitter_factor * random.random()
            delay = int(delay + jitter)
        return delay

    def max_retries_reached(
        self,
        delivery: WebhookDelivery,
        policy: Optional[WebhookRetryPolicy] = None,
    ) -> bool:
        max_retries = policy.max_retries if policy else self._default_max_retries
        return delivery.attempt_number >= max_retries

    async def schedule_retry(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookEndpoint,
        event_payload: Dict[str, Any],
        failure_reason: Optional[str] = None,
    ) -> Tuple[bool, Optional[DeadLetterEntry]]:
        policy = self.get_policy(endpoint.id)
        if self.max_retries_reached(delivery, policy):
            dead_letter_entry = await self._dead_letter_service.store(
                original_event_id=delivery.event_id,
                original_endpoint_id=delivery.endpoint_id,
                original_payload=event_payload,
                failure_reason=failure_reason or "Max retries exceeded",
                failure_count=delivery.attempt_number,
                account_id=endpoint.account_id,
                last_response_code=delivery.response_code,
                last_error_message=delivery.error_message,
            )
            delivery.status = DeliveryStatus.DEAD_LETTER
            return False, dead_letter_entry
        delay_seconds = self.calculate_delay(delivery.attempt_number, policy)
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        delivery.next_retry_at = next_retry_at
        delivery.attempt_number += 1
        delivery.status = DeliveryStatus.PENDING
        if endpoint.id not in self._retry_queue:
            self._retry_queue[endpoint.id] = []
        self._retry_queue[endpoint.id].append(delivery)
        return True, None

    async def get_pending_retries(self, limit: int = 100) -> List[WebhookDelivery]:
        now = datetime.now(timezone.utc)
        pending = []
        for endpoint_id, deliveries in self._retry_queue.items():
            for delivery in deliveries:
                if delivery.next_retry_at and delivery.next_retry_at <= now:
                    if delivery.status == DeliveryStatus.PENDING:
                        pending.append(delivery)
        pending.sort(key=lambda x: x.next_retry_at or datetime.min.replace(tzinfo=timezone.utc))
        return pending[:limit]

    async def clear_retry(self, delivery: WebhookDelivery) -> None:
        if delivery.endpoint_id in self._retry_queue:
            self._retry_queue[delivery.endpoint_id] = [
                d for d in self._retry_queue[delivery.endpoint_id]
                if d.id != delivery.id
            ]

    async def get_retry_schedule(self, endpoint_id: str) -> List[WebhookDelivery]:
        return self._retry_queue.get(endpoint_id, [])

    async def cancel_retries(self, endpoint_id: str) -> int:
        cancelled_count = 0
        if endpoint_id in self._retry_queue:
            cancelled_count = len(self._retry_queue[endpoint_id])
            del self._retry_queue[endpoint_id]
        return cancelled_count

    async def get_retry_stats(self) -> Dict[str, Any]:
        total_pending = 0
        endpoint_stats = {}
        for endpoint_id, deliveries in self._retry_queue.items():
            pending_count = len([d for d in deliveries if d.status == DeliveryStatus.PENDING])
            total_pending += pending_count
            endpoint_stats[endpoint_id] = {
                "pending_retries": pending_count,
                "next_retry": min(
                    [d.next_retry_at for d in deliveries if d.next_retry_at],
                    default=None
                ),
            }
        return {
            "total_pending_retries": total_pending,
            "endpoints": endpoint_stats,
        }

    def calculate_backoff_with_jitter(
        self,
        attempt: int,
        base_delay: int = DEFAULT_BASE_DELAY,
        max_delay: int = DEFAULT_MAX_DELAY,
        jitter_factor: float = DEFAULT_JITTER_FACTOR,
    ) -> int:
        delay = base_delay * (2 ** (attempt - 1))
        delay = min(delay, max_delay)
        if jitter_factor > 0:
            jitter = delay * jitter_factor * random.random()
            delay = int(delay + jitter)
        return delay

    async def should_retry(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookEndpoint,
    ) -> bool:
        if endpoint.status != DeliveryStatus.ENABLED if hasattr(DeliveryStatus, 'ENABLED') else endpoint.status.value != "enabled":
            return False
        if delivery.attempt_number >= self.DEFAULT_MAX_RETRIES:
            return False
        if delivery.response_code:
            if delivery.response_code == 410:
                return False
            if delivery.response_code >= 400 and delivery.response_code < 500:
                if delivery.response_code not in [408, 429]:
                    return False
        return True
