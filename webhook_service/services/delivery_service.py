import hashlib
import hmac
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

from payment_platform.webhook_service.domain.models import (
    DeliveryStatus,
    EndpointStatus,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
    WebhookSignature,
    SignatureAlgorithm,
    DeliveryAttempt,
    WebhookRetryPolicy,
)


class WebhookDeliveryService:
    DEFAULT_TIMEOUT_SECONDS = 30.0
    MAX_RESPONSE_BODY_SIZE = 10000
    MAX_RETRIES = 25
    SIGNATURE_TOLERANCE_SECONDS = 300

    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._deliveries: Dict[str, WebhookDelivery] = {}
        self._attempts: Dict[str, List[DeliveryAttempt]] = {}
        self._delivery_counter = 0

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=False,
                max_redirects=0,
            )
        return self._http_client

    def generate_signature(
        self,
        payload: str,
        secret: str,
        timestamp: Optional[int] = None,
        algorithm: SignatureAlgorithm = SignatureAlgorithm.HMAC_SHA256,
    ) -> WebhookSignature:
        if timestamp is None:
            timestamp = int(time.time())
        signed_payload = f"{timestamp}.{payload}"
        if algorithm == SignatureAlgorithm.HMAC_SHA256:
            signature_value = hmac.new(
                secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
        elif algorithm == SignatureAlgorithm.HMAC_SHA512:
            signature_value = hmac.new(
                secret.encode(),
                signed_payload.encode(),
                hashlib.sha512,
            ).hexdigest()
        else:
            signature_value = hmac.new(
                secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
        return WebhookSignature(
            algorithm=algorithm,
            signature_value=signature_value,
            timestamp=timestamp,
        )

    def verify_signature(
        self,
        payload: str,
        signature_header: str,
        secret: str,
        tolerance: int = SIGNATURE_TOLERANCE_SECONDS,
    ) -> Tuple[bool, Optional[int]]:
        parts = {}
        for part in signature_header.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                parts[key] = value
        if "t" not in parts:
            return False, None
        try:
            timestamp = int(parts["t"])
        except ValueError:
            return False, None
        current_time = int(time.time())
        if abs(current_time - timestamp) > tolerance:
            return False, timestamp
        signed_payload = f"{timestamp}.{payload}"
        expected_signature = hmac.new(
            secret.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        for key, value in parts.items():
            if key.startswith("v") and key != "t":
                if hmac.compare_digest(value, expected_signature):
                    return True, timestamp
        return False, timestamp

    async def deliver(
        self,
        endpoint: WebhookEndpoint,
        event: WebhookEvent,
        attempt_number: int = 1,
    ) -> WebhookDelivery:
        self._delivery_counter += 1
        delivery = WebhookDelivery(
            endpoint_id=endpoint.id,
            event_id=event.id,
            attempt_number=attempt_number,
            status=DeliveryStatus.IN_PROGRESS,
        )
        self._deliveries[delivery.id] = delivery
        self._attempts[delivery.id] = []
        payload = json.dumps(event.to_payload(), separators=(",", ":"))
        signature = self.generate_signature(payload, endpoint.secret)
        headers = {
            "Content-Type": "application/json",
            "Stripe-Signature": signature.to_header(),
            "User-Agent": "PaymentPlatform-Webhook/1.0",
            "Accept": "application/json",
            "Connection": "close",
        }
        start_time = time.time()
        attempt = DeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=attempt_number,
            request_headers=headers,
        )
        try:
            client = await self._get_http_client()
            response = await client.post(
                endpoint.url,
                content=payload.encode(),
                headers=headers,
            )
            duration_ms = int((time.time() - start_time) * 1000)
            attempt.status_code = response.status_code
            attempt.response_time_ms = duration_ms
            attempt.response_headers = dict(response.headers)
            delivery.response_code = response.status_code
            delivery.duration_ms = duration_ms
            response_body = response.text[:self.MAX_RESPONSE_BODY_SIZE]
            delivery.response_body = response_body
            success = self._is_successful_response(response.status_code)
            if success:
                await self.handle_response(delivery, endpoint, True, None)
            else:
                error_message = f"HTTP {response.status_code}"
                await self.handle_response(delivery, endpoint, False, error_message)
        except httpx.TimeoutException:
            duration_ms = int((time.time() - start_time) * 1000)
            attempt.response_time_ms = duration_ms
            attempt.error_type = "timeout"
            attempt.error_message = "Request timed out"
            delivery.duration_ms = duration_ms
            await self.handle_response(delivery, endpoint, False, "Request timed out")
        except httpx.ConnectError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            attempt.response_time_ms = duration_ms
            attempt.error_type = "connection_error"
            attempt.error_message = str(e)
            delivery.duration_ms = duration_ms
            await self.handle_response(delivery, endpoint, False, f"Connection error: {str(e)}")
        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            attempt.response_time_ms = duration_ms
            attempt.error_type = "http_status_error"
            attempt.error_message = str(e)
            delivery.duration_ms = duration_ms
            await self.handle_response(delivery, endpoint, False, f"HTTP error: {str(e)}")
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            attempt.response_time_ms = duration_ms
            attempt.error_type = "unknown_error"
            attempt.error_message = str(e)
            delivery.duration_ms = duration_ms
            await self.handle_response(delivery, endpoint, False, f"Unknown error: {str(e)}")
        self._attempts[delivery.id].append(attempt)
        return delivery

    def _is_successful_response(self, status_code: int) -> bool:
        return 200 <= status_code < 300

    async def handle_response(
        self,
        delivery: WebhookDelivery,
        endpoint: WebhookEndpoint,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        if success:
            delivery.status = DeliveryStatus.SUCCEEDED
            delivery.delivered_at = datetime.now(timezone.utc)
            delivery.error_message = None
            endpoint.record_success()
        else:
            delivery.status = DeliveryStatus.FAILED
            delivery.error_message = error_message
            endpoint.record_failure()

    async def track_delivery(self, delivery_id: str) -> Optional[WebhookDelivery]:
        return self._deliveries.get(delivery_id)

    async def get_delivery_attempts(self, delivery_id: str) -> List[DeliveryAttempt]:
        return self._attempts.get(delivery_id, [])

    async def list_deliveries(
        self,
        endpoint_id: Optional[str] = None,
        event_id: Optional[str] = None,
        status: Optional[DeliveryStatus] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> List[WebhookDelivery]:
        deliveries = list(self._deliveries.values())
        if endpoint_id:
            deliveries = [d for d in deliveries if d.endpoint_id == endpoint_id]
        if event_id:
            deliveries = [d for d in deliveries if d.event_id == event_id]
        if status:
            deliveries = [d for d in deliveries if d.status == status]
        deliveries.sort(key=lambda x: x.timestamp, reverse=True)
        return deliveries[offset:offset + limit]

    async def get_pending_deliveries(self, limit: int = 100) -> List[WebhookDelivery]:
        now = datetime.now(timezone.utc)
        pending = []
        for delivery in self._deliveries.values():
            if delivery.status == DeliveryStatus.PENDING:
                pending.append(delivery)
            elif delivery.status == DeliveryStatus.FAILED:
                if delivery.next_retry_at and delivery.next_retry_at <= now:
                    pending.append(delivery)
        pending.sort(key=lambda x: x.timestamp)
        return pending[:limit]

    async def get_delivery_stats(self) -> Dict[str, Any]:
        deliveries = list(self._deliveries.values())
        total = len(deliveries)
        succeeded = len([d for d in deliveries if d.status == DeliveryStatus.SUCCEEDED])
        failed = len([d for d in deliveries if d.status == DeliveryStatus.FAILED])
        pending = len([d for d in deliveries if d.status == DeliveryStatus.PENDING])
        latencies = [d.duration_ms for d in deliveries if d.duration_ms is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        return {
            "total_deliveries": total,
            "succeeded": succeeded,
            "failed": failed,
            "pending": pending,
            "success_rate": succeeded / total if total > 0 else 0,
            "average_latency_ms": avg_latency,
        }

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
