import asyncio
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
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
    IdempotencyKeyRepository,
    CustomerRepository,
    ChargeRepository,
    PaymentIntentRepository,
    SubscriptionRepository,
    InvoiceRepository,
    BalanceTransactionRepository,
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
    name="cleanup_expired_sessions",
    bind=True,
    max_retries=1,
)
def cleanup_expired_sessions(self):
    return run_async(_cleanup_expired_sessions(self))


async def _cleanup_expired_sessions(task):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import delete, and_
        from payment_platform.backend.domain.models import (
            IdempotencyKey,
            CheckoutSession as CheckoutSessionModel,
            SetupIntent as SetupIntentModel,
            VerificationSession as VerificationSessionModel,
        )
        
        now = datetime.now(timezone.utc)
        results = {}
        
        idempotency_repo = IdempotencyKeyRepository(session)
        deleted_keys = await idempotency_repo.cleanup_expired()
        results["idempotency_keys"] = deleted_keys
        
        checkout_cutoff = int(time.time()) - 86400
        checkout_stmt = delete(CheckoutSessionModel).where(
            and_(
                CheckoutSessionModel.status == "expired",
                CheckoutSessionModel.expires_at < checkout_cutoff,
            )
        )
        checkout_result = await session.execute(checkout_stmt)
        results["checkout_sessions"] = checkout_result.rowcount
        
        setup_cutoff = now - timedelta(hours=24)
        setup_stmt = delete(SetupIntentModel).where(
            and_(
                SetupIntentModel.status.in_(["canceled", "succeeded"]),
                SetupIntentModel.updated_at < setup_cutoff,
            )
        )
        setup_result = await session.execute(setup_stmt)
        results["setup_intents"] = setup_result.rowcount
        
        verification_cutoff = now - timedelta(days=7)
        verification_stmt = delete(VerificationSessionModel).where(
            and_(
                VerificationSessionModel.status.in_(["verified", "failed", "canceled", "expired"]),
                VerificationSessionModel.expires_at < verification_cutoff,
            )
        )
        verification_result = await session.execute(verification_stmt)
        results["verification_sessions"] = verification_result.rowcount
        
        await session.commit()
        
        total_cleaned = sum(results.values())
        logger.info("Expired sessions cleaned up", **results, total=total_cleaned)
        return {"status": "completed", "results": results, "total_cleaned": total_cleaned}
        
    except Exception as e:
        logger.error("Error cleaning up expired sessions", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="archive_old_records",
    bind=True,
    max_retries=1,
)
def archive_old_records(self, days_to_archive: int = 365):
    return run_async(_archive_old_records(self, days_to_archive))


async def _archive_old_records(task, days_to_archive: int):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import select, insert, delete, and_
        from payment_platform.backend.domain.models import (
            Charge as ChargeModel,
            PaymentIntent as PIModel,
            Refund as RefundModel,
            Event as EventModel,
            EventDelivery as EventDeliveryModel,
        )
        
        cutoff_timestamp = int(time.time()) - (days_to_archive * 86400)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_archive)
        
        results = {}
        batch_size = 1000
        
        charge_query = select(ChargeModel).where(
            and_(
                ChargeModel.created < cutoff_timestamp,
                ChargeModel.status.in_(["succeeded", "failed", "canceled"]),
            )
        ).limit(batch_size)
        charge_result = await session.execute(charge_query)
        charges_to_archive = list(charge_result.scalars().all())
        
        if charges_to_archive:
            for charge in charges_to_archive:
                await _archive_charge(session, charge)
            
            charge_ids = [c.id for c in charges_to_archive]
            await session.execute(
                delete(ChargeModel).where(ChargeModel.id.in_(charge_ids))
            )
        results["charges_archived"] = len(charges_to_archive)
        
        pi_query = select(PIModel).where(
            and_(
                PIModel.created < cutoff_timestamp,
                PIModel.status.in_(["succeeded", "canceled", "failed"]),
            )
        ).limit(batch_size)
        pi_result = await session.execute(pi_query)
        pis_to_archive = list(pi_result.scalars().all())
        
        if pis_to_archive:
            for pi in pis_to_archive:
                await _archive_payment_intent(session, pi)
            
            pi_ids = [p.id for p in pis_to_archive]
            await session.execute(
                delete(PIModel).where(PIModel.id.in_(pi_ids))
            )
        results["payment_intents_archived"] = len(pis_to_archive)
        
        event_query = select(EventModel).where(
            EventModel.created < cutoff_timestamp
        ).limit(batch_size * 10)
        event_result = await session.execute(event_query)
        events_to_archive = list(event_result.scalars().all())
        
        if events_to_archive:
            for event in events_to_archive:
                await _archive_event(session, event)
            
            event_ids = [e.id for e in events_to_archive]
            await session.execute(
                delete(EventDeliveryModel).where(EventDeliveryModel.event_id.in_(event_ids))
            )
            await session.execute(
                delete(EventModel).where(EventModel.id.in_(event_ids))
            )
        results["events_archived"] = len(events_to_archive)
        
        await session.commit()
        
        total_archived = sum(results.values())
        logger.info("Old records archived", **results, total=total_archived)
        return {"status": "completed", "results": results, "total_archived": total_archived}
        
    except Exception as e:
        logger.error("Error archiving old records", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _archive_charge(session, charge):
    from sqlalchemy import text
    
    await session.execute(
        text("""
            INSERT INTO archived_charges 
            (id, account_id, amount, currency, status, customer_id, payment_intent_id, created, archived_at)
            VALUES (:id, :account_id, :amount, :currency, :status, :customer_id, :payment_intent_id, :created, NOW())
        """),
        {
            "id": charge.id,
            "account_id": charge.account_id,
            "amount": charge.amount,
            "currency": charge.currency,
            "status": charge.status,
            "customer_id": charge.customer_id,
            "payment_intent_id": charge.payment_intent_id,
            "created": charge.created,
        }
    )


async def _archive_payment_intent(session, payment_intent):
    from sqlalchemy import text
    
    await session.execute(
        text("""
            INSERT INTO archived_payment_intents 
            (id, account_id, amount, currency, status, customer_id, created, archived_at)
            VALUES (:id, :account_id, :amount, :currency, :status, :customer_id, :created, NOW())
        """),
        {
            "id": payment_intent.id,
            "account_id": payment_intent.account_id,
            "amount": payment_intent.amount,
            "currency": payment_intent.currency,
            "status": payment_intent.status,
            "customer_id": payment_intent.customer_id,
            "created": payment_intent.created,
        }
    )


async def _archive_event(session, event):
    from sqlalchemy import text
    
    await session.execute(
        text("""
            INSERT INTO archived_events 
            (id, type, account_id, data, created, archived_at)
            VALUES (:id, :type, :account_id, :data, :created, NOW())
        """),
        {
            "id": event.id,
            "type": event.type,
            "account_id": event.account_id,
            "data": json.dumps(event.data),
            "created": event.created,
        }
    )


@celery_app.task(
    name="update_aggregations",
    bind=True,
    max_retries=1,
)
def update_aggregations(self):
    return run_async(_update_aggregations(self))


async def _update_aggregations(task):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import select, func, and_
        from payment_platform.backend.domain.models import (
            Account as AccountModel,
            Charge as ChargeModel,
            Customer as CustomerModel,
            Subscription as SubscriptionModel,
            Invoice as InvoiceModel,
        )
        
        now = int(time.time())
        hour_start = now - (now % 3600)
        hour_end = hour_start + 3600
        
        results = {}
        
        accounts_query = select(AccountModel).where(AccountModel.deleted_at.is_(None)).limit(500)
        accounts_result = await session.execute(accounts_query)
        accounts = list(accounts_result.scalars().all())
        
        for account in accounts:
            if not account.id:
                continue
            
            charge_count_query = select(func.count(ChargeModel.id)).where(
                and_(
                    ChargeModel.account_id == account.id,
                    ChargeModel.created >= hour_start,
                    ChargeModel.created < hour_end,
                    ChargeModel.status == "succeeded",
                )
            )
            charge_count_result = await session.execute(charge_count_query)
            charge_count = charge_count_result.scalar() or 0
            
            charge_total_query = select(func.sum(ChargeModel.amount)).where(
                and_(
                    ChargeModel.account_id == account.id,
                    ChargeModel.created >= hour_start,
                    ChargeModel.created < hour_end,
                    ChargeModel.status == "succeeded",
                )
            )
            charge_total_result = await session.execute(charge_total_query)
            charge_total = charge_total_result.scalar() or 0
            
            customer_count_query = select(func.count(CustomerModel.id)).where(
                and_(
                    CustomerModel.account_id == account.id,
                    CustomerModel.created_at >= datetime.fromtimestamp(hour_start, tz=timezone.utc),
                    CustomerModel.created_at < datetime.fromtimestamp(hour_end, tz=timezone.utc),
                )
            )
            customer_count_result = await session.execute(customer_count_query)
            customer_count = customer_count_result.scalar() or 0
            
            sub_count_query = select(func.count(SubscriptionModel.id)).where(
                and_(
                    SubscriptionModel.account_id == account.id,
                    SubscriptionModel.status == "active",
                )
            )
            sub_count_result = await session.execute(sub_count_query)
            active_subscriptions = sub_count_result.scalar() or 0
            
            await _update_account_hourly_stats(
                session, account.id, hour_start, charge_count, charge_total, customer_count
            )
            
            await _update_account_summary(session, account.id, active_subscriptions)
        
        await session.commit()
        
        results["accounts_updated"] = len(accounts)
        
        await _update_global_metrics(session, hour_start)
        
        logger.info("Aggregations updated", **results)
        return {"status": "completed", "results": results}
        
    except Exception as e:
        logger.error("Error updating aggregations", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _update_account_hourly_stats(session, account_id: str, hour: int, charge_count: int, charge_total: int, customer_count: int):
    from sqlalchemy import text
    
    await session.execute(
        text("""
            INSERT INTO account_hourly_stats 
            (account_id, hour, charge_count, charge_total, customer_count, updated_at)
            VALUES (:account_id, :hour, :charge_count, :charge_total, :customer_count, NOW())
            ON CONFLICT (account_id, hour) 
            DO UPDATE SET 
                charge_count = EXCLUDED.charge_count,
                charge_total = EXCLUDED.charge_total,
                customer_count = EXCLUDED.customer_count,
                updated_at = NOW()
        """),
        {
            "account_id": account_id,
            "hour": hour,
            "charge_count": charge_count,
            "charge_total": charge_total,
            "customer_count": customer_count,
        }
    )


async def _update_account_summary(session, account_id: str, active_subscriptions: int):
    from sqlalchemy import text
    
    await session.execute(
        text("""
            INSERT INTO account_summary 
            (account_id, active_subscriptions, updated_at)
            VALUES (:account_id, :active_subscriptions, NOW())
            ON CONFLICT (account_id) 
            DO UPDATE SET 
                active_subscriptions = EXCLUDED.active_subscriptions,
                updated_at = NOW()
        """),
        {
            "account_id": account_id,
            "active_subscriptions": active_subscriptions,
        }
    )


async def _update_global_metrics(session, hour: int):
    from sqlalchemy import text, func
    from payment_platform.backend.domain.models import Charge as ChargeModel, Customer as CustomerModel
    
    total_charges_query = select(func.sum(ChargeModel.amount)).where(
        and_(
            ChargeModel.created >= hour,
            ChargeModel.created < hour + 3600,
            ChargeModel.status == "succeeded",
        )
    )
    total_charges_result = await session.execute(total_charges_query)
    total_charges = total_charges_result.scalar() or 0
    
    charge_count_query = select(func.count(ChargeModel.id)).where(
        and_(
            ChargeModel.created >= hour,
            ChargeModel.created < hour + 3600,
            ChargeModel.status == "succeeded",
        )
    )
    charge_count_result = await session.execute(charge_count_query)
    charge_count = charge_count_result.scalar() or 0
    
    customer_count_query = select(func.count(CustomerModel.id)).where(
        and_(
            CustomerModel.created_at >= datetime.fromtimestamp(hour, tz=timezone.utc),
            CustomerModel.created_at < datetime.fromtimestamp(hour + 3600, tz=timezone.utc),
        )
    )
    customer_count_result = await session.execute(customer_count_query)
    customer_count = customer_count_result.scalar() or 0
    
    await session.execute(
        text("""
            INSERT INTO global_hourly_metrics 
            (hour, total_volume, transaction_count, new_customers, updated_at)
            VALUES (:hour, :total_volume, :transaction_count, :new_customers, NOW())
            ON CONFLICT (hour) 
            DO UPDATE SET 
                total_volume = EXCLUDED.total_volume,
                transaction_count = EXCLUDED.transaction_count,
                new_customers = EXCLUDED.new_customers,
                updated_at = NOW()
        """),
        {
            "hour": hour,
            "total_volume": total_charges,
            "transaction_count": charge_count,
            "new_customers": customer_count,
        }
    )
    
    await session.commit()
