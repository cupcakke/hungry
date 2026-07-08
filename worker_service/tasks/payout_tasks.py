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
    PayoutRepository,
    BalanceRepository,
    BalanceTransactionRepository,
    AccountRepository,
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
    name="process_payout",
    bind=True,
    max_retries=5,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def process_payout(self, payout_id: str):
    return run_async(_process_payout(self, payout_id))


async def _process_payout(task, payout_id: str):
    session = None
    try:
        session = async_session_factory()
        payout_repo = PayoutRepository(session)
        payout = await payout_repo.get_by_id(payout_id)
        
        if not payout:
            logger.error("Payout not found", payout_id=payout_id)
            return {"status": "error", "error": "payout_not_found"}
        
        if payout.status != "pending":
            logger.info("Payout not in pending state", payout_id=payout_id, status=payout.status)
            return {"status": "invalid_status", "current_status": payout.status}
        
        account_repo = AccountRepository(session)
        account = await account_repo.get_by_id(payout.account_id) if payout.account_id else None
        
        balance_repo = BalanceRepository(session)
        balance = await balance_repo.get_or_create_for_account(payout.account_id) if payout.account_id else None
        
        if balance:
            available_balance = _get_available_balance_for_currency(balance, payout.currency)
            
            if available_balance < payout.amount:
                logger.warning("Insufficient balance for payout", payout_id=payout_id, required=payout.amount, available=available_balance)
                payout.status = "failed"
                payout.failure_code = "insufficient_funds"
                payout.failure_message = "Insufficient available balance"
                
                await session.commit()
                return {"status": "failed", "error": "insufficient_funds"}
        
        payout.status = "in_transit"
        
        await _reserve_payout_balance(session, payout)
        
        arrival_date = _calculate_arrival_date(payout.currency)
        payout.arrival_date = arrival_date
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type="payout.created",
            data={"object": _serialize_payout(payout)},
            account_id=payout.account_id,
        )
        
        await session.commit()
        
        signature(
            "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
            args=[event.id],
            kwargs={},
            queue="webhooks",
        ).apply_async()
        
        delay = (arrival_date - int(time.time())) * 1000
        if delay > 0:
            signature(
                "payment_platform.worker_service.tasks.payout_tasks.finalize_payout",
                args=[payout_id],
                kwargs={},
                queue="payouts",
            ).apply_async(countdown=min(delay, 300))
        
        metrics.track_payout("initiated", payout.amount, payout.currency)
        logger.info("Payout processing initiated", payout_id=payout_id, amount=payout.amount, currency=payout.currency)
        return {"status": "in_transit", "payout_id": payout_id, "arrival_date": arrival_date}
        
    except Exception as e:
        logger.error("Error processing payout", payout_id=payout_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


def _get_available_balance_for_currency(balance, currency: str) -> int:
    available_list = balance.available or []
    for item in available_list:
        if item.get("currency", "").lower() == currency.lower():
            return item.get("amount", 0)
    return 0


async def _reserve_payout_balance(session, payout):
    balance_repo = BalanceRepository(session)
    balance = await balance_repo.get_or_create_for_account(payout.account_id)
    
    available_list = balance.available or []
    pending_list = balance.pending or []
    
    for item in available_list:
        if item.get("currency", "").lower() == payout.currency.lower():
            item["amount"] = item.get("amount", 0) - payout.amount
            break
    
    pending_entry = {
        "currency": payout.currency.lower(),
        "amount": payout.amount,
        "source_types": {"payout": payout.amount},
    }
    pending_list.append(pending_entry)
    
    balance.available = available_list
    balance.pending = pending_list


def _calculate_arrival_date(currency: str) -> int:
    now = int(time.time())
    standard_currencies = {"usd", "eur", "gbp", "cad", "aud"}
    
    if currency.lower() in standard_currencies:
        arrival_days = 2
    else:
        arrival_days = 4
    
    return now + (arrival_days * 24 * 60 * 60)


def _serialize_payout(payout) -> Dict[str, Any]:
    return {
        "id": payout.id,
        "object": "payout",
        "amount": payout.amount,
        "currency": payout.currency,
        "status": payout.status,
        "arrival_date": payout.arrival_date,
        "destination": payout.destination,
        "created": payout.created if hasattr(payout, 'created') else int(time.time()),
    }


@celery_app.task(
    name="finalize_payout",
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
)
def finalize_payout(self, payout_id: str):
    return run_async(_finalize_payout(self, payout_id))


async def _finalize_payout(task, payout_id: str):
    session = None
    try:
        session = async_session_factory()
        payout_repo = PayoutRepository(session)
        payout = await payout_repo.get_by_id(payout_id)
        
        if not payout:
            logger.error("Payout not found for finalization", payout_id=payout_id)
            return {"status": "error", "error": "payout_not_found"}
        
        if payout.status == "paid":
            logger.info("Payout already finalized", payout_id=payout_id)
            return {"status": "already_paid"}
        
        if payout.status != "in_transit":
            logger.warning("Payout not in transit", payout_id=payout_id, status=payout.status)
            return {"status": "invalid_status", "current_status": payout.status}
        
        payout.status = "paid"
        
        await _deduct_payout_balance(session, payout)
        
        bt_repo = BalanceTransactionRepository(session)
        await bt_repo.create_transaction(
            amount=-payout.amount,
            currency=payout.currency,
            type="payout",
            account_id=payout.account_id,
            source=payout.id,
            description=f"Payout {payout.id}",
        )
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type="payout.paid",
            data={"object": _serialize_payout(payout)},
            account_id=payout.account_id,
        )
        
        await session.commit()
        
        signature(
            "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
            args=[event.id],
            kwargs={},
            queue="webhooks",
        ).apply_async()
        
        metrics.track_payout("completed", payout.amount, payout.currency)
        logger.info("Payout finalized", payout_id=payout_id, amount=payout.amount)
        return {"status": "paid", "payout_id": payout_id}
        
    except Exception as e:
        logger.error("Error finalizing payout", payout_id=payout_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _deduct_payout_balance(session, payout):
    balance_repo = BalanceRepository(session)
    balance = await balance_repo.get_or_create_for_account(payout.account_id)
    
    pending_list = balance.pending or []
    new_pending = []
    
    for item in pending_list:
        if item.get("currency", "").lower() == payout.currency.lower():
            pending_amount = item.get("amount", 0) - payout.amount
            if pending_amount > 0:
                item["amount"] = pending_amount
                new_pending.append(item)
        else:
            new_pending.append(item)
    
    balance.pending = new_pending


@celery_app.task(
    name="calculate_available_balance",
    bind=True,
    max_retries=1,
)
def calculate_available_balance(self, account_id: Optional[str] = None):
    return run_async(_calculate_available_balance(self, account_id))


async def _calculate_available_balance(task, account_id: Optional[str]):
    session = None
    try:
        session = async_session_factory()
        
        now = int(time.time())
        
        from sqlalchemy import select, and_
        from payment_platform.backend.domain.models import BalanceTransaction as BTModel
        
        if account_id:
            query = select(BTModel).where(
                and_(
                    BTModel.account_id == account_id,
                    BTModel.available_on <= now,
                )
            )
        else:
            query = select(BTModel).where(BTModel.available_on <= now).limit(10000)
        
        result = await session.execute(query)
        transactions = list(result.scalars().all())
        
        balance_changes = {}
        
        for txn in transactions:
            currency = txn.currency.lower()
            if currency not in balance_changes:
                balance_changes[currency] = {
                    "available": 0,
                    "pending": 0,
                }
            
            balance_changes[currency]["available"] += txn.net or txn.amount
        
        balance_repo = BalanceRepository(session)
        
        accounts_updated = set()
        for txn in transactions:
            if txn.account_id:
                accounts_updated.add(txn.account_id)
        
        for acc_id in accounts_updated:
            balance = await balance_repo.get_or_create_for_account(acc_id)
            
            acc_transactions = [t for t in transactions if t.account_id == acc_id]
            
            currency_balances = {}
            for t in acc_transactions:
                curr = t.currency.lower()
                if curr not in currency_balances:
                    currency_balances[curr] = {"available": 0}
                currency_balances[curr]["available"] += t.net or t.amount
            
            available_list = [{"currency": curr, "amount": data["available"]} for curr, data in currency_balances.items()]
            balance.available = available_list
        
        await session.commit()
        
        logger.info("Available balance calculated", accounts_updated=len(accounts_updated))
        return {"status": "completed", "accounts_updated": len(accounts_updated)}
        
    except Exception as e:
        logger.error("Error calculating available balance", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="handle_payout_failure",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def handle_payout_failure(self, payout_id: str, failure_code: str, failure_message: str):
    return run_async(_handle_payout_failure(self, payout_id, failure_code, failure_message))


async def _handle_payout_failure(task, payout_id: str, failure_code: str, failure_message: str):
    session = None
    try:
        session = async_session_factory()
        payout_repo = PayoutRepository(session)
        payout = await payout_repo.get_by_id(payout_id)
        
        if not payout:
            logger.error("Payout not found", payout_id=payout_id)
            return {"status": "error", "error": "payout_not_found"}
        
        payout.status = "failed"
        payout.failure_code = failure_code
        payout.failure_message = failure_message
        
        await _refund_payout_balance(session, payout)
        
        bt_repo = BalanceTransactionRepository(session)
        await bt_repo.create_transaction(
            amount=payout.amount,
            currency=payout.currency,
            type="payout_failure",
            account_id=payout.account_id,
            source=payout.id,
            description=f"Payout failure refund for {payout.id}",
        )
        
        event_repo = EventRepository(session)
        event = await event_repo.create_event(
            type="payout.failed",
            data={
                "object": _serialize_payout(payout),
                "failure_code": failure_code,
                "failure_message": failure_message,
            },
            account_id=payout.account_id,
        )
        
        await session.commit()
        
        signature(
            "payment_platform.worker_service.tasks.webhook_tasks.deliver_webhook",
            args=[event.id],
            kwargs={},
            queue="webhooks",
        ).apply_async()
        
        metrics.track_payout("failed", payout.amount, payout.currency)
        logger.info("Payout failure handled", payout_id=payout_id, failure_code=failure_code)
        return {"status": "handled", "payout_id": payout_id}
        
    except Exception as e:
        logger.error("Error handling payout failure", payout_id=payout_id, error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _refund_payout_balance(session, payout):
    balance_repo = BalanceRepository(session)
    balance = await balance_repo.get_or_create_for_account(payout.account_id)
    
    available_list = balance.available or []
    currency_found = False
    
    for item in available_list:
        if item.get("currency", "").lower() == payout.currency.lower():
            item["amount"] = item.get("amount", 0) + payout.amount
            currency_found = True
            break
    
    if not currency_found:
        available_list.append({
            "currency": payout.currency.lower(),
            "amount": payout.amount,
        })
    
    pending_list = balance.pending or []
    new_pending = []
    
    for item in pending_list:
        if item.get("currency", "").lower() == payout.currency.lower():
            pending_amount = item.get("amount", 0) - payout.amount
            if pending_amount > 0:
                item["amount"] = pending_amount
                new_pending.append(item)
        else:
            new_pending.append(item)
    
    balance.available = available_list
    balance.pending = new_pending
