import asyncio
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from celery import shared_task, chain, signature
from celery.exceptions import MaxRetriesExceededError
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment_platform.worker_service.celery_app import celery_app
from payment_platform.shared.logging import get_logger
from payment_platform.shared.observability.metrics import metrics
from payment_platform.backend.infrastructure.database import async_session_factory
from payment_platform.backend.infrastructure.persistence import (
    PaymentIntentRepository,
    ChargeRepository,
    RefundRepository,
    CustomerRepository,
    PaymentMethodRepository,
    BalanceTransactionRepository,
    EventRepository,
    WebhookEndpointRepository,
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
    name="process_payment_intent",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_payment_intent(self, payment_intent_id: str, payment_method_id: Optional[str] = None):
    return run_async(_process_payment_intent(self, payment_intent_id, payment_method_id))


async def _process_payment_intent(task, payment_intent_id: str, payment_method_id: Optional[str]):
    session = None
    try:
        session = async_session_factory()
        pi_repo = PaymentIntentRepository(session)
        payment_intent = await pi_repo.get_by_id(payment_intent_id)
        if not payment_intent:
            logger.error("Payment intent not found", payment_intent_id=payment_intent_id)
            return {"status": "error", "error": "payment_intent_not_found"}
        
        if payment_intent.status in ["succeeded", "canceled", "failed"]:
            logger.info("Payment intent already processed", payment_intent_id=payment_intent_id, status=payment_intent.status)
            return {"status": "already_processed", "payment_intent_status": payment_intent.status}
        
        customer_repo = CustomerRepository(session)
        customer = None
        if payment_intent.customer_id:
            customer = await customer_repo.get_by_id(payment_intent.customer_id)
        
        pm_repo = PaymentMethodRepository(session)
        payment_method = None
        if payment_method_id:
            payment_method = await pm_repo.get_by_id(payment_method_id)
        elif customer and customer.default_payment_method:
            payment_method = await pm_repo.get_by_id(customer.default_payment_method)
        
        if not payment_method:
            payment_intent.status = "requires_payment_method"
            await session.commit()
            return {"status": "requires_payment_method"}
        
        charge_repo = ChargeRepository(session)
        charge = await charge_repo.create_charge(
            amount=payment_intent.amount,
            currency=payment_intent.currency,
            payment_intent_id=payment_intent_id,
            customer_id=payment_intent.customer_id,
            account_id=payment_intent.account_id,
            description=f"Payment for {payment_intent_id}",
            metadata=payment_intent.metadata_,
        )
        
        is_successful = await _process_payment_with_provider(charge, payment_method, payment_intent)
        
        if is_successful:
            charge.status = "succeeded"
            charge.paid = True
            charge.captured = True
            charge.amount_captured = payment_intent.amount
            payment_intent.status = "succeeded"
            payment_intent.amount_received = payment_intent.amount
            payment_intent.latest_charge = charge.id
            
            bt_repo = BalanceTransactionRepository(session)
            await bt_repo.create_transaction(
                amount=payment_intent.amount,
                currency=payment_intent.currency,
                type="payment",
                account_id=payment_intent.account_id,
                source=charge.id,
                description=f"Payment for {payment_intent_id}",
            )
            
            event_repo = EventRepository(session)
            event = await event_repo.create_event(
                type="payment_intent.succeeded",
                data={"object": _serialize_payment_intent(payment_intent)},
                account_id=payment_intent.account_id,
            )
            
            await session.commit()
            
            chain(
                signature(
                    "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
                    args=[event.id],
                    kwargs={},
                    queue="webhooks",
                ),
            ).apply_async()
            
            metrics.track_payment("succeeded", payment_intent.amount, payment_intent.currency)
            logger.info("Payment intent processed successfully", payment_intent_id=payment_intent_id)
            return {"status": "succeeded", "charge_id": charge.id}
        else:
            charge.status = "failed"
            payment_intent.status = "requires_payment_method"
            payment_intent.last_payment_error = {"code": "card_declined", "message": "Your card was declined."}
            await session.commit()
            
            event_repo = EventRepository(session)
            await event_repo.create_event(
                type="payment_intent.payment_failed",
                data={"object": _serialize_payment_intent(payment_intent)},
                account_id=payment_intent.account_id,
            )
            await session.commit()
            
            metrics.track_payment("failed", payment_intent.amount, payment_intent.currency)
            logger.warning("Payment intent processing failed", payment_intent_id=payment_intent_id)
            return {"status": "failed", "error": "card_declined"}
            
    except Exception as e:
        logger.error("Error processing payment intent", payment_intent_id=payment_intent_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _process_payment_with_provider(charge, payment_method, payment_intent) -> bool:
    await asyncio.sleep(0.1)
    return True


def _serialize_payment_intent(payment_intent) -> Dict[str, Any]:
    return {
        "id": payment_intent.id,
        "object": "payment_intent",
        "amount": payment_intent.amount,
        "currency": payment_intent.currency,
        "status": payment_intent.status,
        "customer": payment_intent.customer_id,
        "payment_method": payment_intent.payment_method,
        "created": payment_intent.created if hasattr(payment_intent, 'created') else int(time.time()),
    }


@celery_app.task(
    name="capture_payment",
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def capture_payment(self, payment_intent_id: str, amount_to_capture: Optional[int] = None):
    return run_async(_capture_payment(self, payment_intent_id, amount_to_capture))


async def _capture_payment(task, payment_intent_id: str, amount_to_capture: Optional[int]):
    session = None
    try:
        session = async_session_factory()
        pi_repo = PaymentIntentRepository(session)
        payment_intent = await pi_repo.get_by_id(payment_intent_id)
        
        if not payment_intent:
            logger.error("Payment intent not found for capture", payment_intent_id=payment_intent_id)
            return {"status": "error", "error": "payment_intent_not_found"}
        
        if payment_intent.status != "requires_capture":
            logger.warning("Payment intent not in capture state", payment_intent_id=payment_intent_id, status=payment_intent.status)
            return {"status": "invalid_status", "current_status": payment_intent.status}
        
        capture_amount = amount_to_capture or payment_intent.amount_capturable or payment_intent.amount
        
        charge_repo = ChargeRepository(session)
        charges = await charge_repo.get_by_payment_intent(payment_intent_id)
        auth_charge = next((c for c in charges if c.status == "succeeded" and not c.captured), None)
        
        if not auth_charge:
            logger.error("No authorizing charge found", payment_intent_id=payment_intent_id)
            return {"status": "error", "error": "no_authorizing_charge"}
        
        auth_charge.captured = True
        auth_charge.amount_captured = capture_amount
        payment_intent.status = "succeeded"
        payment_intent.amount_received = capture_amount
        
        bt_repo = BalanceTransactionRepository(session)
        await bt_repo.create_transaction(
            amount=capture_amount,
            currency=payment_intent.currency,
            type="capture",
            account_id=payment_intent.account_id,
            source=auth_charge.id,
            description=f"Capture for {payment_intent_id}",
        )
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type="payment_intent.succeeded",
            data={"object": _serialize_payment_intent(payment_intent)},
            account_id=payment_intent.account_id,
        )
        
        await session.commit()
        
        signature(
            "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
            args=[event.id],
            kwargs={},
            queue="webhooks",
        ).apply_async()
        
        logger.info("Payment captured successfully", payment_intent_id=payment_intent_id, amount=capture_amount)
        return {"status": "succeeded", "captured_amount": capture_amount}
        
    except Exception as e:
        logger.error("Error capturing payment", payment_intent_id=payment_intent_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="refund_payment",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def refund_payment(self, charge_id: str, amount: Optional[int] = None, reason: Optional[str] = None):
    return run_async(_refund_payment(self, charge_id, amount, reason))


async def _refund_payment(task, charge_id: str, amount: Optional[int], reason: Optional[str]):
    session = None
    try:
        session = async_session_factory()
        charge_repo = ChargeRepository(session)
        charge = await charge_repo.get_by_id(charge_id)
        
        if not charge:
            logger.error("Charge not found for refund", charge_id=charge_id)
            return {"status": "error", "error": "charge_not_found"}
        
        if not charge.paid or charge.status != "succeeded":
            logger.warning("Charge not in refundable state", charge_id=charge_id, status=charge.status)
            return {"status": "error", "error": "charge_not_refundable"}
        
        refund_amount = amount or (charge.amount_captured - charge.amount_refunded)
        
        if refund_amount <= 0:
            logger.warning("No amount to refund", charge_id=charge_id)
            return {"status": "error", "error": "no_amount_to_refund"}
        
        if charge.amount_refunded + refund_amount > charge.amount_captured:
            logger.warning("Refund amount exceeds captured amount", charge_id=charge_id)
            return {"status": "error", "error": "refund_exceeds_captured"}
        
        refund_repo = RefundRepository(session)
        refund = await refund_repo.create_refund(
            charge_id=charge_id,
            amount=refund_amount,
            currency=charge.currency,
            reason=reason or "requested_by_customer",
            account_id=charge.account_id,
            payment_intent_id=charge.payment_intent_id,
        )
        
        refund.status = "succeeded"
        charge.amount_refunded += refund_amount
        if charge.amount_refunded >= charge.amount_captured:
            charge.refunded = True
        
        bt_repo = BalanceTransactionRepository(session)
        await bt_repo.create_transaction(
            amount=-refund_amount,
            currency=charge.currency,
            type="refund",
            account_id=charge.account_id,
            source=refund.id,
            description=f"Refund for charge {charge_id}",
        )
        
        if charge.payment_intent_id:
            pi_repo = PaymentIntentRepository(session)
            payment_intent = await pi_repo.get_by_id(charge.payment_intent_id)
            if payment_intent:
                event_repo = EventRepository(session)
                event = await event_repo.create_event(
                    type="charge.refunded",
                    data={
                        "object": {
                            "id": charge_id,
                            "object": "charge",
                            "refunded": charge.refunded,
                            "amount_refunded": charge.amount_refunded,
                        }
                    },
                    account_id=charge.account_id,
                )
                signature(
                    "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
                    args=[event.id],
                    kwargs={},
                    queue="webhooks",
                ).apply_async()
        
        await session.commit()
        
        logger.info("Refund processed successfully", refund_id=refund.id, amount=refund_amount)
        return {"status": "succeeded", "refund_id": refund.id, "refunded_amount": refund_amount}
        
    except Exception as e:
        logger.error("Error processing refund", charge_id=charge_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="process_smart_retry",
    bind=True,
    max_retries=1,
)
def process_smart_retry(self):
    return run_async(_process_smart_retry(self))


async def _process_smart_retry(task):
    session = None
    try:
        session = async_session_factory()
        pi_repo = PaymentIntentRepository(session)
        
        now = int(time.time())
        retry_window = now - (7 * 24 * 60 * 60)
        
        from sqlalchemy import select
        from payment_platform.backend.domain.models import PaymentIntent as PIModel
        
        query = (
            select(PIModel)
            .where(PIModel.status == "requires_payment_method")
            .where(PIModel.created >= retry_window)
            .where(PIModel.metadata_["smart_retry_attempt"].is_(None) if True else True)
            .limit(100)
        )
        result = await session.execute(query)
        pending_intents = list(result.scalars().all())
        
        retry_intervals = settings.payment.smart_retry_intervals
        
        retried_count = 0
        for intent in pending_intents:
            metadata = intent.metadata_ or {}
            retry_attempt = metadata.get("smart_retry_attempt", 0)
            
            if retry_attempt >= settings.payment.smart_retry_max_attempts:
                continue
            
            if retry_attempt >= len(retry_intervals):
                continue
            
            last_attempt = metadata.get("last_retry_at", intent.created)
            next_retry_days = retry_intervals[retry_attempt]
            next_retry_at = last_attempt + (next_retry_days * 24 * 60 * 60)
            
            if now < next_retry_at:
                continue
            
            metadata["smart_retry_attempt"] = retry_attempt + 1
            metadata["last_retry_at"] = now
            intent.metadata_ = metadata
            
            if intent.customer_id:
                customer_repo = CustomerRepository(session)
                customer = await customer_repo.get_by_id(intent.customer_id)
                if customer and customer.default_payment_method:
                    chain(
                        signature(
                            "payment_platform.worker_service.tasks.payment_tasks.process_payment_intent",
                            args=[intent.id, customer.default_payment_method],
                            kwargs={},
                            queue="payments",
                        ),
                    ).apply_async()
                    retried_count += 1
        
        await session.commit()
        
        logger.info("Smart retry processed", retried_count=retried_count)
        return {"status": "completed", "retried_count": retried_count}
        
    except Exception as e:
        logger.error("Error in smart retry", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="handle_failed_payment",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def handle_failed_payment(self, payment_intent_id: str, error_code: str, error_message: str):
    return run_async(_handle_failed_payment(self, payment_intent_id, error_code, error_message))


async def _handle_failed_payment(task, payment_intent_id: str, error_code: str, error_message: str):
    session = None
    try:
        session = async_session_factory()
        pi_repo = PaymentIntentRepository(session)
        payment_intent = await pi_repo.get_by_id(payment_intent_id)
        
        if not payment_intent:
            logger.error("Payment intent not found", payment_intent_id=payment_intent_id)
            return {"status": "error", "error": "payment_intent_not_found"}
        
        payment_intent.status = "requires_payment_method"
        payment_intent.last_payment_error = {
            "code": error_code,
            "message": error_message,
            "type": _map_error_code_to_type(error_code),
        }
        
        metadata = payment_intent.metadata_ or {}
        metadata["last_failure_code"] = error_code
        metadata["last_failure_at"] = int(time.time())
        payment_intent.metadata_ = metadata
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type="payment_intent.payment_failed",
            data={
                "object": _serialize_payment_intent(payment_intent),
                "error": {"code": error_code, "message": error_message},
            },
            account_id=payment_intent.account_id,
        )
        
        await session.commit()
        
        signature(
            "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
            args=[event.id],
            kwargs={},
            queue="webhooks",
        ).apply_async()
        
        metrics.track_payment("failed", payment_intent.amount, payment_intent.currency)
        logger.info("Failed payment handled", payment_intent_id=payment_intent_id, error_code=error_code)
        return {"status": "handled", "payment_intent_id": payment_intent_id}
        
    except Exception as e:
        logger.error("Error handling failed payment", payment_intent_id=payment_intent_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


def _map_error_code_to_type(error_code: str) -> str:
    error_type_map = {
        "card_declined": "card_error",
        "insufficient_funds": "card_error",
        "expired_card": "card_error",
        "incorrect_cvc": "card_error",
        "processing_error": "api_error",
        "incorrect_number": "card_error",
        "invalid_card": "card_error",
        "invalid_expiry_date": "card_error",
        "invalid_cvc": "card_error",
    }
    return error_type_map.get(error_code, "api_error")
