import asyncio
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from celery import shared_task, chain, signature
from celery.exceptions import MaxRetriesExceededError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment_platform.worker_service.celery_app import celery_app
from payment_platform.shared.logging import get_logger
from payment_platform.shared.observability.metrics import metrics
from payment_platform.shared.config import settings
from payment_platform.backend.infrastructure.database import async_session_factory
from payment_platform.backend.infrastructure.persistence import (
    SubscriptionRepository,
    InvoiceRepository,
    CustomerRepository,
    PaymentMethodRepository,
    PaymentIntentRepository,
    EventRepository,
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
    name="process_subscription_billing",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def process_subscription_billing(self):
    return run_async(_process_subscription_billing(self))


async def _process_subscription_billing(task):
    session = None
    try:
        session = async_session_factory()
        sub_repo = SubscriptionRepository(session)
        
        now = int(time.time())
        
        from sqlalchemy import select
        from payment_platform.backend.domain.models import Subscription as SubModel
        
        query = (
            select(SubModel)
            .where(SubModel.status == "active")
            .where(SubModel.current_period_end <= now + 3600)
            .where(SubModel.cancel_at_period_end == False)
            .limit(500)
        )
        result = await session.execute(query)
        due_subscriptions = list(result.scalars().all())
        
        processed_count = 0
        failed_count = 0
        
        for subscription in due_subscriptions:
            try:
                billing_result = await _bill_subscription(session, subscription)
                if billing_result["status"] == "succeeded":
                    processed_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.error("Error billing subscription", subscription_id=subscription.id, error=str(e))
                failed_count += 1
        
        await session.commit()
        
        logger.info("Subscription billing processed", processed=processed_count, failed=failed_count)
        return {"status": "completed", "processed": processed_count, "failed": failed_count}
        
    except Exception as e:
        logger.error("Error in subscription billing batch", error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _bill_subscription(session, subscription) -> Dict[str, Any]:
    invoice_repo = InvoiceRepository(session)
    invoice = await invoice_repo.create_invoice(
        customer_id=subscription.customer_id,
        currency=subscription.currency,
        account_id=subscription.account_id,
        subscription_id=subscription.id,
        auto_advance=True,
    )
    
    total = 0
    line_items = []
    items = subscription.items or []
    
    for item in items:
        price_id = item.get("price")
        quantity = item.get("quantity", 1)
        amount = item.get("amount", 0)
        line_total = amount * quantity
        total += line_total
        line_items.append({
            "price": price_id,
            "quantity": quantity,
            "amount": line_total,
        })
    
    invoice.subtotal = total
    invoice.total = total
    invoice.amount_due = total
    invoice.amount_remaining = total
    invoice.status = "open"
    invoice.line_items = line_items
    invoice.period_start = subscription.current_period_start
    invoice.period_end = subscription.current_period_end
    
    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_by_id(subscription.customer_id)
    
    payment_method_id = None
    if customer:
        if customer.default_payment_method:
            payment_method_id = customer.default_payment_method
    
    if payment_method_id:
        pi_repo = PaymentIntentRepository(session)
        payment_intent = await pi_repo.create_payment_intent(
            amount=total,
            currency=subscription.currency,
            customer_id=subscription.customer_id,
            account_id=subscription.account_id,
            metadata={"invoice_id": invoice.id, "subscription_id": subscription.id},
        )
        
        invoice.latest_payment_intent = payment_intent.id
        
        chain(
            signature(
                "payment_platform.worker_service.tasks.payment_tasks.process_payment_intent",
                args=[payment_intent.id, payment_method_id],
                kwargs={},
                queue="payments",
            ),
            signature(
                "payment_platform.worker_service.tasks.invoice_tasks.process_invoice_payment",
                args=[invoice.id],
                kwargs={},
                queue="invoices",
            ),
        ).apply_async()
        
        return {"status": "initiated", "invoice_id": invoice.id}
    else:
        invoice.status = "open"
        invoice.collection_method = "send_invoice"
        
        event_repo = EventRepository(session)
        await event_repo.create_event(
            type="invoice.created",
            data={"object": _serialize_invoice(invoice)},
            account_id=subscription.account_id,
        )
        
        signature(
            "payment_platform.worker_service.tasks.invoice_tasks.send_invoice_email",
            args=[invoice.id],
            kwargs={},
            queue="invoices",
        ).apply_async()
        
        return {"status": "invoice_created", "invoice_id": invoice.id}


def _serialize_invoice(invoice) -> Dict[str, Any]:
    return {
        "id": invoice.id,
        "object": "invoice",
        "customer": invoice.customer_id,
        "subscription": invoice.subscription_id,
        "amount_due": invoice.amount_due,
        "currency": invoice.currency,
        "status": invoice.status,
        "created": invoice.created if hasattr(invoice, 'created') else int(time.time()),
    }


@celery_app.task(
    name="handle_subscription_cancellation",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
)
def handle_subscription_cancellation(self, subscription_id: str, cancellation_reason: Optional[str] = None):
    return run_async(_handle_subscription_cancellation(self, subscription_id, cancellation_reason))


async def _handle_subscription_cancellation(task, subscription_id: str, cancellation_reason: Optional[str]):
    session = None
    try:
        session = async_session_factory()
        sub_repo = SubscriptionRepository(session)
        subscription = await sub_repo.get_by_id(subscription_id)
        
        if not subscription:
            logger.error("Subscription not found", subscription_id=subscription_id)
            return {"status": "error", "error": "subscription_not_found"}
        
        now = int(time.time())
        
        subscription.canceled_at = now
        subscription.cancellation_details = {
            "reason": cancellation_reason or "cancellation_requested",
            "comment": None,
        }
        
        if subscription.status == "active":
            subscription.status = "canceled"
            subscription.ended_at = now
        else:
            subscription.cancel_at_period_end = True
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type="customer.subscription.deleted",
            data={"object": _serialize_subscription(subscription)},
            account_id=subscription.account_id,
        )
        
        await session.commit()
        
        signature(
            "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
            args=[event.id],
            kwargs={},
            queue="webhooks",
        ).apply_async()
        
        logger.info("Subscription cancellation handled", subscription_id=subscription_id)
        return {"status": "canceled", "subscription_id": subscription_id}
        
    except Exception as e:
        logger.error("Error handling subscription cancellation", subscription_id=subscription_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


def _serialize_subscription(subscription) -> Dict[str, Any]:
    return {
        "id": subscription.id,
        "object": "subscription",
        "customer": subscription.customer_id,
        "status": subscription.status,
        "currency": subscription.currency,
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
        "canceled_at": subscription.canceled_at,
        "ended_at": subscription.ended_at,
    }


@celery_app.task(
    name="update_subscription_status",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
)
def update_subscription_status(self, subscription_id: str, new_status: str):
    return run_async(_update_subscription_status(self, subscription_id, new_status))


async def _update_subscription_status(task, subscription_id: str, new_status: str):
    session = None
    try:
        session = async_session_factory()
        sub_repo = SubscriptionRepository(session)
        subscription = await sub_repo.get_by_id(subscription_id)
        
        if not subscription:
            logger.error("Subscription not found", subscription_id=subscription_id)
            return {"status": "error", "error": "subscription_not_found"}
        
        old_status = subscription.status
        subscription.status = new_status
        
        now = int(time.time())
        if new_status == "active" and old_status in ["incomplete", "trialing"]:
            period_days = 30
            subscription.current_period_start = now
            subscription.current_period_end = now + (period_days * 24 * 60 * 60)
        
        if new_status == "past_due":
            metadata = subscription.metadata_ or {}
            metadata["past_due_since"] = now
            subscription.metadata_ = metadata
        
        if new_status == "canceled":
            subscription.ended_at = now
            subscription.canceled_at = now
        
        event_type = f"customer.subscription.{new_status}"
        if new_status == "canceled":
            event_type = "customer.subscription.deleted"
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type=event_type,
            data={"object": _serialize_subscription(subscription)},
            account_id=subscription.account_id,
        )
        
        await session.commit()
        
        signature(
            "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
            args=[event.id],
            kwargs={},
            queue="webhooks",
        ).apply_async()
        
        logger.info("Subscription status updated", subscription_id=subscription_id, old_status=old_status, new_status=new_status)
        return {"status": "updated", "subscription_id": subscription_id}
        
    except Exception as e:
        logger.error("Error updating subscription status", subscription_id=subscription_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="send_subscription_reminders",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def send_subscription_reminders(self):
    return run_async(_send_subscription_reminders(self))


async def _send_subscription_reminders(task):
    session = None
    try:
        session = async_session_factory()
        sub_repo = SubscriptionRepository(session)
        
        now = int(time.time())
        three_days = 3 * 24 * 60 * 60
        seven_days = 7 * 24 * 60 * 60
        
        from sqlalchemy import select
        from payment_platform.backend.domain.models import Subscription as SubModel
        
        trial_query = (
            select(SubModel)
            .where(SubModel.status == "trialing")
            .where(SubModel.trial_end <= now + seven_days)
            .where(SubModel.trial_end > now)
            .limit(500)
        )
        trial_result = await session.execute(trial_query)
        trial_subscriptions = list(trial_result.scalars().all())
        
        renewal_query = (
            select(SubModel)
            .where(SubModel.status == "active")
            .where(SubModel.current_period_end <= now + three_days)
            .where(SubModel.current_period_end > now)
            .limit(500)
        )
        renewal_result = await session.execute(renewal_query)
        renewal_subscriptions = list(renewal_result.scalars().all())
        
        reminders_sent = 0
        
        for subscription in trial_subscriptions:
            try:
                await _send_trial_ending_reminder(session, subscription)
                reminders_sent += 1
            except Exception as e:
                logger.error("Error sending trial reminder", subscription_id=subscription.id, error=str(e))
        
        for subscription in renewal_subscriptions:
            try:
                await _send_renewal_reminder(session, subscription)
                reminders_sent += 1
            except Exception as e:
                logger.error("Error sending renewal reminder", subscription_id=subscription.id, error=str(e))
        
        await session.commit()
        
        logger.info("Subscription reminders sent", count=reminders_sent)
        return {"status": "completed", "reminders_sent": reminders_sent}
        
    except Exception as e:
        logger.error("Error sending subscription reminders", error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _send_trial_ending_reminder(session, subscription):
    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_by_id(subscription.customer_id)
    
    if not customer or not customer.email:
        return
    
    event_repo = EventRepository(session)
    await event_repo.create_event(
        type="customer.subscription.trial_will_end",
        data={
            "object": _serialize_subscription(subscription),
            "trial_end": subscription.trial_end,
        },
        account_id=subscription.account_id,
    )
    
    logger.info("Trial ending reminder sent", subscription_id=subscription.id, customer_email=customer.email)


async def _send_renewal_reminder(session, subscription):
    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_by_id(subscription.customer_id)
    
    if not customer or not customer.email:
        return
    
    event_repo = EventRepository(session)
    await event_repo.create_event(
        type="customer.subscription.renewal_reminder",
        data={
            "object": _serialize_subscription(subscription),
            "current_period_end": subscription.current_period_end,
        },
        account_id=subscription.account_id,
    )
    
    logger.info("Renewal reminder sent", subscription_id=subscription.id, customer_email=customer.email)
