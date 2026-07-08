import asyncio
import json
import time
import os
import sys
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from celery import shared_task, chain, signature
from celery.exceptions import MaxRetriesExceededError
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment_platform.worker_service.celery_app import celery_app
from payment_platform.shared.logging import get_logger
from payment_platform.shared.observability.metrics import metrics
from payment_platform.shared.config import settings
from payment_platform.backend.infrastructure.database import async_session_factory
from payment_platform.backend.infrastructure.persistence import (
    EventRepository,
    WebhookEndpointRepository,
    EventDeliveryRepository,
)

logger = get_logger(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="deliver_webhook",
    bind=True,
    max_retries=10,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,
)
def deliver_webhook(self, event_id: str, endpoint_id: Optional[str] = None):
    return run_async(_deliver_webhook(self, event_id, endpoint_id))


async def _deliver_webhook(task, event_id: str, endpoint_id: Optional[str]):
    session = None
    http_client = None
    try:
        session = async_session_factory()
        event_repo = EventRepository(session)
        event = await event_repo.get_by_id(event_id)
        
        if not event:
            logger.error("Event not found", event_id=event_id)
            return {"status": "error", "error": "event_not_found"}
        
        endpoint_repo = WebhookEndpointRepository(session)
        
        if endpoint_id:
            endpoints = [await endpoint_repo.get_by_id(endpoint_id)]
        else:
            endpoints = await endpoint_repo.get_enabled_for_account(event.account_id)
        
        endpoints = [e for e in endpoints if e and e.status == "enabled"]
        
        if not endpoints:
            logger.info("No enabled endpoints for event", event_id=event_id)
            return {"status": "skipped", "reason": "no_endpoints"}
        
        delivery_repo = EventDeliveryRepository(session)
        results = []
        
        for endpoint in endpoints:
            if event.type not in (endpoint.enabled_events or []):
                if "*" not in (endpoint.enabled_events or []):
                    continue
            
            delivery = await delivery_repo.create_delivery(
                event_id=event_id,
                webhook_endpoint_id=endpoint.id,
                webhook_url=endpoint.url,
                account_id=event.account_id,
            )
            
            payload = json.dumps({
                "id": event.id,
                "object": "event",
                "api_version": event.api_version,
                "created": event.created,
                "data": event.data,
                "livemode": event.livemode,
                "type": event.type,
            }, default=str)
            
            timestamp = int(time.time())
            signature = _generate_webhook_signature(payload, endpoint.secret, timestamp)
            
            headers = {
                "Content-Type": "application/json",
                "Stripe-Signature": signature,
                "User-Agent": "PaymentPlatform-Webhook/1.0",
                "Stripe-Event-ID": event_id,
                "Stripe-Attempt": str(delivery.attempt_number),
            }
            
            http_client = httpx.AsyncClient(timeout=settings.webhook.timeout_seconds)
            start_time = time.time()
            
            try:
                response = await http_client.post(
                    endpoint.url,
                    content=payload,
                    headers=headers,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                
                if 200 <= response.status_code < 300:
                    await delivery_repo.update(
                        delivery.id,
                        status="succeeded",
                        status_code=response.status_code,
                        response_body=response.text[:10000],
                        duration_ms=duration_ms,
                        delivered_at=datetime.now(timezone.utc),
                    )
                    metrics.track_webhook(event.type, "succeeded", duration_ms / 1000)
                    results.append({"endpoint_id": endpoint.id, "status": "succeeded"})
                    logger.info("Webhook delivered", event_id=event_id, endpoint_id=endpoint.id, status_code=response.status_code)
                else:
                    await _handle_delivery_failure(
                        session, delivery_repo, delivery, endpoint,
                        f"HTTP {response.status_code}: {response.text[:500]}",
                        duration_ms, event
                    )
                    results.append({"endpoint_id": endpoint.id, "status": "failed", "status_code": response.status_code})
                    
            except httpx.TimeoutException as e:
                duration_ms = int((time.time() - start_time) * 1000)
                await _handle_delivery_failure(
                    session, delivery_repo, delivery, endpoint,
                    f"Timeout after {settings.webhook.timeout_seconds}s",
                    duration_ms, event
                )
                results.append({"endpoint_id": endpoint.id, "status": "timeout"})
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0
                await _handle_delivery_failure(
                    session, delivery_repo, delivery, endpoint,
                    str(e), duration_ms, event
                )
                results.append({"endpoint_id": endpoint.id, "status": "error", "error": str(e)})
        
        await session.commit()
        
        succeeded = sum(1 for r in results if r["status"] == "succeeded")
        logger.info("Webhook delivery batch completed", event_id=event_id, succeeded=succeeded, total=len(results))
        return {"status": "completed", "results": results}
        
    except Exception as e:
        logger.error("Error delivering webhook", event_id=event_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if http_client:
            await http_client.aclose()
        if session:
            await session.close()


async def _handle_delivery_failure(session, delivery_repo, delivery, endpoint, error_message, duration_ms, event):
    delivery.status = "failed"
    delivery.error_message = error_message
    delivery.duration_ms = duration_ms
    delivery.attempt_number += 1
    
    max_attempts = settings.webhook.max_retries
    
    if delivery.attempt_number < max_attempts:
        retry_intervals = settings.webhook.retry_intervals
        idx = min(delivery.attempt_number - 1, len(retry_intervals) - 1)
        retry_delay = retry_intervals[idx]
        delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay)
        delivery.status = "pending"
    else:
        delivery.status = "failed"
        delivery.next_retry_at = None
        
        if settings.webhook.dead_letter_enabled:
            await _move_to_dead_letter(session, delivery, event, endpoint, error_message)
    
    metrics.track_webhook(event.type, "failed", duration_ms / 1000 if duration_ms else 0)
    logger.warning("Webhook delivery failed", delivery_id=delivery.id, attempt=delivery.attempt_number, error=error_message)


async def _move_to_dead_letter(session, delivery, event, endpoint, error_message):
    from sqlalchemy import text
    
    await session.execute(
        text("""
            INSERT INTO webhook_dead_letter_queue 
            (event_id, webhook_endpoint_id, webhook_url, payload, error_message, attempt_count, created_at)
            VALUES (:event_id, :endpoint_id, :url, :payload, :error, :attempts, NOW())
        """),
        {
            "event_id": event.id,
            "endpoint_id": endpoint.id,
            "url": endpoint.url,
            "payload": json.dumps(event.data),
            "error": error_message,
            "attempts": delivery.attempt_number,
        }
    )
    logger.info("Webhook moved to dead letter queue", event_id=event.id, endpoint_id=endpoint.id)


def _generate_webhook_signature(payload: str, secret: str, timestamp: int) -> str:
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


@celery_app.task(
    name="retry_webhook_delivery",
    bind=True,
    max_retries=1,
)
def retry_webhook_delivery(self):
    return run_async(_retry_webhook_delivery(self))


async def _retry_webhook_delivery(task):
    session = None
    try:
        session = async_session_factory()
        delivery_repo = EventDeliveryRepository(session)
        
        pending_deliveries = await delivery_repo.get_pending_deliveries(limit=100)
        
        retried_count = 0
        for delivery in pending_deliveries:
            signature(
                "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
                args=[delivery.event_id, delivery.webhook_endpoint_id],
                kwargs={},
                queue="webhooks",
            ).apply_async()
            retried_count += 1
        
        logger.info("Webhook retry batch completed", retried_count=retried_count)
        return {"status": "completed", "retried_count": retried_count}
        
    except Exception as e:
        logger.error("Error retrying webhooks", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="process_webhook_dead_letter",
    bind=True,
    max_retries=1,
)
def process_webhook_dead_letter(self):
    return run_async(_process_webhook_dead_letter(self))


async def _process_webhook_dead_letter(task):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import text
        
        result = await session.execute(
            text("""
                SELECT id, event_id, webhook_endpoint_id, webhook_url, payload, error_message, attempt_count
                FROM webhook_dead_letter_queue
                WHERE processed_at IS NULL
                ORDER BY created_at ASC
                LIMIT 50
            """)
        )
        dead_letter_items = result.fetchall()
        
        processed_count = 0
        requeued_count = 0
        archived_count = 0
        
        for item in dead_letter_items:
            item_id, event_id, endpoint_id, url, payload, error_message, attempt_count = item
            
            if attempt_count >= 15:
                await session.execute(
                    text("""
                        UPDATE webhook_dead_letter_queue 
                        SET processed_at = NOW(), status = 'archived'
                        WHERE id = :id
                    """),
                    {"id": item_id}
                )
                archived_count += 1
                logger.info("Dead letter item archived", item_id=item_id, event_id=event_id)
            else:
                event_repo = EventRepository(session)
                event = await event_repo.get_by_id(event_id)
                
                if event:
                    signature(
                        "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
                        args=[event_id, endpoint_id],
                        kwargs={},
                        queue="webhooks",
                    ).apply_async()
                    
                    await session.execute(
                        text("""
                            UPDATE webhook_dead_letter_queue 
                            SET attempt_count = attempt_count + 1, last_retry_at = NOW()
                            WHERE id = :id
                        """),
                        {"id": item_id}
                    )
                    requeued_count += 1
                else:
                    await session.execute(
                        text("""
                            UPDATE webhook_dead_letter_queue 
                            SET processed_at = NOW(), status = 'event_not_found'
                            WHERE id = :id
                        """),
                        {"id": item_id}
                    )
                    archived_count += 1
                
            processed_count += 1
        
        await session.commit()
        
        logger.info("Dead letter queue processed", processed=processed_count, requeued=requeued_count, archived=archived_count)
        return {
            "status": "completed",
            "processed": processed_count,
            "requeued": requeued_count,
            "archived": archived_count,
        }
        
    except Exception as e:
        logger.error("Error processing dead letter queue", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()
