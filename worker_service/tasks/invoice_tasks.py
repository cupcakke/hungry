import asyncio
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from celery import shared_task, chain, signature
from celery.exceptions import MaxRetriesExceededError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment_platform.worker_service.celery_app import celery_app
from payment_platform.shared.logging import get_logger
from payment_platform.shared.observability.metrics import metrics
from payment_platform.shared.config import settings
from payment_platform.backend.infrastructure.database import async_session_factory
from payment_platform.backend.infrastructure.persistence import (
    InvoiceRepository,
    InvoiceItemRepository,
    CustomerRepository,
    PaymentIntentRepository,
    ChargeRepository,
    SubscriptionRepository,
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
    name="generate_invoice",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
)
def generate_invoice(self, customer_id: str, subscription_id: Optional[str] = None, metadata: Optional[Dict] = None):
    return run_async(_generate_invoice(self, customer_id, subscription_id, metadata))


async def _generate_invoice(task, customer_id: str, subscription_id: Optional[str], metadata: Optional[Dict]):
    session = None
    try:
        session = async_session_factory()
        customer_repo = CustomerRepository(session)
        customer = await customer_repo.get_by_id(customer_id)
        
        if not customer:
            logger.error("Customer not found", customer_id=customer_id)
            return {"status": "error", "error": "customer_not_found"}
        
        invoice_repo = InvoiceRepository(session)
        invoice = await invoice_repo.create_invoice(
            customer_id=customer_id,
            currency=customer.currency or "usd",
            account_id=customer.account_id,
            subscription_id=subscription_id,
            metadata=metadata,
        )
        
        if subscription_id:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(subscription_id)
            if subscription:
                total = 0
                items = subscription.items or []
                
                for item in items:
                    price_id = item.get("price")
                    quantity = item.get("quantity", 1)
                    amount = item.get("amount", 0)
                    total += amount * quantity
                
                invoice.subtotal = total
                invoice.total = total
                invoice.amount_due = total
                invoice.amount_remaining = total
                invoice.period_start = subscription.current_period_start
                invoice.period_end = subscription.current_period_end
        
        invoice.status = "open"
        invoice.number = await _generate_invoice_number(session)
        
        now = int(time.time())
        due_days = settings.invoice.default_due_days
        invoice.due_date = now + (due_days * 24 * 60 * 60)
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type="invoice.created",
            data={"object": _serialize_invoice(invoice)},
            account_id=invoice.account_id,
        )
        
        await session.commit()
        
        chain(
            signature(
                "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
                args=[event.id],
                kwargs={},
                queue="webhooks",
            ),
            signature(
                "payment_platform.worker_service.tasks.invoice_tasks.send_invoice_email",
                args=[invoice.id],
                kwargs={},
                queue="invoices",
            ),
        ).apply_async()
        
        logger.info("Invoice generated", invoice_id=invoice.id, customer_id=customer_id)
        return {"status": "created", "invoice_id": invoice.id}
        
    except Exception as e:
        logger.error("Error generating invoice", customer_id=customer_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _generate_invoice_number(session) -> str:
    from sqlalchemy import select, func
    from payment_platform.backend.domain.models import Invoice as InvoiceModel
    
    query = select(func.max(InvoiceModel.number))
    result = await session.execute(query)
    max_number = result.scalar()
    
    if max_number:
        try:
            next_num = int(max_number.replace("INV-", "")) + 1
        except ValueError:
            next_num = 1
    else:
        next_num = 1
    
    return f"INV-{next_num:06d}"


def _serialize_invoice(invoice) -> Dict[str, Any]:
    return {
        "id": invoice.id,
        "object": "invoice",
        "customer": invoice.customer_id,
        "subscription": invoice.subscription_id,
        "amount_due": invoice.amount_due,
        "amount_paid": invoice.amount_paid,
        "amount_remaining": invoice.amount_remaining,
        "currency": invoice.currency,
        "status": invoice.status,
        "number": invoice.number,
        "due_date": invoice.due_date,
        "created": invoice.created if hasattr(invoice, 'created') else int(time.time()),
    }


@celery_app.task(
    name="send_invoice_email",
    bind=True,
    max_retries=5,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_invoice_email(self, invoice_id: str):
    return run_async(_send_invoice_email(self, invoice_id))


async def _send_invoice_email(task, invoice_id: str):
    session = None
    try:
        session = async_session_factory()
        invoice_repo = InvoiceRepository(session)
        invoice = await invoice_repo.get_by_id(invoice_id)
        
        if not invoice:
            logger.error("Invoice not found", invoice_id=invoice_id)
            return {"status": "error", "error": "invoice_not_found"}
        
        customer_repo = CustomerRepository(session)
        customer = await customer_repo.get_by_id(invoice.customer_id)
        
        if not customer or not customer.email:
            logger.warning("No customer email for invoice", invoice_id=invoice_id)
            return {"status": "skipped", "reason": "no_email"}
        
        email_data = {
            "to": customer.email,
            "subject": f"Invoice {invoice.number or invoice.id}",
            "template": "invoice",
            "data": {
                "invoice_id": invoice.id,
                "invoice_number": invoice.number,
                "amount": invoice.amount_due,
                "currency": invoice.currency,
                "due_date": invoice.due_date,
                "customer_name": customer.name,
            },
        }
        
        invoice.hosted_invoice_url = f"https://invoices.paymentplatform.com/{invoice.id}"
        invoice.invoice_pdf = f"https://invoices.paymentplatform.com/{invoice.id}/pdf"
        
        event_repo = EventRepository(session)
        await event_repo.create_event(
            type="invoice.sent",
            data={"object": _serialize_invoice(invoice)},
            account_id=invoice.account_id,
        )
        
        await session.commit()
        
        logger.info("Invoice email sent", invoice_id=invoice_id, customer_email=customer.email)
        return {"status": "sent", "invoice_id": invoice_id}
        
    except Exception as e:
        logger.error("Error sending invoice email", invoice_id=invoice_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="process_invoice_payment",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
)
def process_invoice_payment(self, invoice_id: str, payment_intent_id: Optional[str] = None):
    return run_async(_process_invoice_payment(self, invoice_id, payment_intent_id))


async def _process_invoice_payment(task, invoice_id: str, payment_intent_id: Optional[str]):
    session = None
    try:
        session = async_session_factory()
        invoice_repo = InvoiceRepository(session)
        invoice = await invoice_repo.get_by_id(invoice_id)
        
        if not invoice:
            logger.error("Invoice not found", invoice_id=invoice_id)
            return {"status": "error", "error": "invoice_not_found"}
        
        if invoice.status == "paid":
            logger.info("Invoice already paid", invoice_id=invoice_id)
            return {"status": "already_paid"}
        
        pi_repo = PaymentIntentRepository(session)
        payment_intent = None
        
        if payment_intent_id:
            payment_intent = await pi_repo.get_by_id(payment_intent_id)
        elif invoice.latest_payment_intent:
            payment_intent = await pi_repo.get_by_id(invoice.latest_payment_intent)
        
        if not payment_intent:
            logger.error("No payment intent for invoice", invoice_id=invoice_id)
            return {"status": "error", "error": "no_payment_intent"}
        
        invoice.latest_payment_intent = payment_intent.id
        
        if payment_intent.status == "succeeded":
            invoice.status = "paid"
            invoice.paid = True
            invoice.amount_paid = payment_intent.amount_received
            invoice.amount_remaining = invoice.amount_due - invoice.amount_paid
            
            charge_repo = ChargeRepository(session)
            if payment_intent.latest_charge:
                charge = await charge_repo.get_by_id(payment_intent.latest_charge)
                if charge:
                    invoice.charge_id = charge.id
            
            event_repo = EventRepository(session)
            event = await event_repo.create_event(
                type="invoice.paid",
                data={"object": _serialize_invoice(invoice)},
                account_id=invoice.account_id,
            )
            
            if invoice.subscription_id:
                sub_repo = SubscriptionRepository(session)
                subscription = await sub_repo.get_by_id(invoice.subscription_id)
                if subscription:
                    period_days = 30
                    now = int(time.time())
                    subscription.current_period_start = now
                    subscription.current_period_end = now + (period_days * 24 * 60 * 60)
                    if subscription.status != "active":
                        subscription.status = "active"
            
            await session.commit()
            
            chain(
                signature(
                    "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
                    args=[event.id],
                    kwargs={},
                    queue="webhooks",
                ),
            ).apply_async()
            
            logger.info("Invoice payment processed", invoice_id=invoice_id, amount=invoice.amount_paid)
            return {"status": "paid", "invoice_id": invoice_id}
        
        elif payment_intent.status == "requires_payment_method":
            invoice.status = "open"
            invoice.attempt_count += 1
            
            await session.commit()
            
            return {"status": "payment_failed", "invoice_status": invoice.status}
        
        else:
            logger.info("Invoice payment pending", invoice_id=invoice_id, pi_status=payment_intent.status)
            return {"status": "pending", "payment_intent_status": payment_intent.status}
        
    except Exception as e:
        logger.error("Error processing invoice payment", invoice_id=invoice_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="handle_invoice_failure",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def handle_invoice_failure(self, invoice_id: str, failure_reason: str):
    return run_async(_handle_invoice_failure(self, invoice_id, failure_reason))


async def _handle_invoice_failure(task, invoice_id: str, failure_reason: str):
    session = None
    try:
        session = async_session_factory()
        invoice_repo = InvoiceRepository(session)
        invoice = await invoice_repo.get_by_id(invoice_id)
        
        if not invoice:
            logger.error("Invoice not found", invoice_id=invoice_id)
            return {"status": "error", "error": "invoice_not_found"}
        
        invoice.attempt_count += 1
        invoice.last_finalization_error = {
            "code": failure_reason,
            "message": _get_failure_message(failure_reason),
        }
        
        if invoice.subscription_id:
            sub_repo = SubscriptionRepository(session)
            subscription = await sub_repo.get_by_id(invoice.subscription_id)
            
            if subscription:
                grace_period_days = settings.subscription.grace_period_days
                max_attempts = 3
                
                if invoice.attempt_count >= max_attempts:
                    subscription.status = "past_due"
                    invoice.status = "uncollectible"
                    
                    event_repo = EventRepository(session)
                    await event_repo.create_event(
                        type="customer.subscription.past_due",
                        data={"object": _serialize_subscription(subscription)},
                        account_id=subscription.account_id,
                    )
                else:
                    next_attempt_delay = _calculate_retry_delay(invoice.attempt_count)
                    invoice.next_payment_attempt = int(time.time()) + next_attempt_delay
                    
                    event_repo = EventRepository(session)
                    await event_repo.create_event(
                        type="invoice.payment_failed",
                        data={
                            "object": _serialize_invoice(invoice),
                            "failure_reason": failure_reason,
                        },
                        account_id=invoice.account_id,
                    )
        else:
            invoice.status = "open"
            
            event_repo = EventRepository(session)
            await event_repo.create_event(
                type="invoice.payment_failed",
                data={
                    "object": _serialize_invoice(invoice),
                    "failure_reason": failure_reason,
                },
                account_id=invoice.account_id,
            )
        
        await session.commit()
        
        logger.info("Invoice failure handled", invoice_id=invoice_id, failure_reason=failure_reason)
        return {"status": "handled", "invoice_id": invoice_id}
        
    except Exception as e:
        logger.error("Error handling invoice failure", invoice_id=invoice_id, error=str(e))
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
    }


def _get_failure_message(failure_reason: str) -> str:
    messages = {
        "card_declined": "Your card was declined.",
        "insufficient_funds": "Your card has insufficient funds.",
        "expired_card": "Your card has expired.",
        "incorrect_cvc": "Your card's security code is incorrect.",
        "processing_error": "An error occurred while processing your card.",
        "incorrect_number": "Your card number is incorrect.",
        "invalid_card": "Your card is invalid.",
        "generic_decline": "Your card was declined for an unknown reason.",
    }
    return messages.get(failure_reason, "Payment failed.")


def _calculate_retry_delay(attempt_count: int) -> int:
    delays = [3600, 86400, 172800, 604800]
    idx = min(attempt_count - 1, len(delays) - 1)
    return delays[idx]
