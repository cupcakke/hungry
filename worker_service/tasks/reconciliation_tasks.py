import asyncio
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from celery import shared_task, chain, signature
from celery.exceptions import MaxRetriesExceededError
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment_platform.worker_service.celery_app import celery_app
from payment_platform.shared.logging import get_logger
from payment_platform.shared.observability.metrics import metrics
from payment_platform.shared.config import settings
from payment_platform.backend.infrastructure.database import async_session_factory
from payment_platform.backend.infrastructure.persistence import (
    PaymentIntentRepository,
    ChargeRepository,
    RefundRepository,
    BalanceTransactionRepository,
    PayoutRepository,
    TransferRepository,
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
    name="reconcile_transactions",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def reconcile_transactions(self, account_id: Optional[str] = None, batch_size: int = 1000):
    return run_async(_reconcile_transactions(self, account_id, batch_size))


async def _reconcile_transactions(task, account_id: Optional[str], batch_size: int):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import select, and_, func, case
        from payment_platform.backend.domain.models import (
            Charge as ChargeModel,
            PaymentIntent as PIModel,
            Refund as RefundModel,
            BalanceTransaction as BTModel,
        )
        
        now = int(time.time())
        reconciliation_window = now - (7 * 24 * 60 * 60)
        
        discrepancies = []
        reconciled_count = 0
        
        if account_id:
            charge_query = select(ChargeModel).where(
                and_(
                    ChargeModel.account_id == account_id,
                    ChargeModel.created >= reconciliation_window,
                )
            )
        else:
            charge_query = select(ChargeModel).where(
                ChargeModel.created >= reconciliation_window
            ).limit(batch_size)
        
        charge_result = await session.execute(charge_query)
        charges = list(charge_result.scalars().all())
        
        for charge in charges:
            bt_repo = BalanceTransactionRepository(session)
            bt_query = select(BTModel).where(
                and_(
                    BTModel.source == charge.id,
                    BTModel.type == "payment",
                )
            )
            bt_result = await session.execute(bt_query)
            bt = bt_result.scalar_one_or_none()
            
            if charge.status == "succeeded" and charge.paid:
                if not bt:
                    discrepancies.append({
                        "type": "missing_balance_transaction",
                        "charge_id": charge.id,
                        "amount": charge.amount,
                        "currency": charge.currency,
                    })
                    
                    await bt_repo.create_transaction(
                        amount=charge.amount,
                        currency=charge.currency,
                        type="payment",
                        account_id=charge.account_id,
                        source=charge.id,
                        description=f"Reconciliation: Payment for charge {charge.id}",
                    )
                    reconciled_count += 1
                elif bt.amount != charge.amount_captured:
                    discrepancies.append({
                        "type": "amount_mismatch",
                        "charge_id": charge.id,
                        "bt_amount": bt.amount,
                        "charge_amount": charge.amount_captured,
                    })
            
            refund_query = select(RefundModel).where(RefundModel.charge_id == charge.id)
            refund_result = await session.execute(refund_query)
            refunds = list(refund_result.scalars().all())
            
            for refund in refunds:
                if refund.status == "succeeded":
                    refund_bt_query = select(BTModel).where(
                        and_(
                            BTModel.source == refund.id,
                            BTModel.type == "refund",
                        )
                    )
                    refund_bt_result = await session.execute(refund_bt_query)
                    refund_bt = refund_bt_result.scalar_one_or_none()
                    
                    if not refund_bt:
                        discrepancies.append({
                            "type": "missing_refund_transaction",
                            "refund_id": refund.id,
                            "amount": refund.amount,
                            "currency": refund.currency,
                        })
                        
                        await bt_repo.create_transaction(
                            amount=-refund.amount,
                            currency=refund.currency,
                            type="refund",
                            account_id=refund.account_id,
                            source=refund.id,
                            description=f"Reconciliation: Refund {refund.id}",
                        )
                        reconciled_count += 1
        
        await session.commit()
        
        logger.info("Transaction reconciliation completed", reconciled=reconciled_count, discrepancies=len(discrepancies))
        return {
            "status": "completed",
            "reconciled_count": reconciled_count,
            "discrepancies_found": len(discrepancies),
            "discrepancies": discrepancies[:100],
        }
        
    except Exception as e:
        logger.error("Error reconciling transactions", error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


@celery_app.task(
    name="reconcile_payouts",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def reconcile_payouts(self, account_id: Optional[str] = None):
    return run_async(_reconcile_payouts(self, account_id))


async def _reconcile_payouts(task, account_id: Optional[str]):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import select, and_, func
        from payment_platform.backend.domain.models import (
            Payout as PayoutModel,
            BalanceTransaction as BTModel,
            Balance as BalanceModel,
        )
        
        now = int(time.time())
        reconciliation_window = now - (30 * 24 * 60 * 60)
        
        discrepancies = []
        reconciled_count = 0
        
        if account_id:
            payout_query = select(PayoutModel).where(
                and_(
                    PayoutModel.account_id == account_id,
                    PayoutModel.created >= reconciliation_window,
                )
            )
        else:
            payout_query = select(PayoutModel).where(
                PayoutModel.created >= reconciliation_window
            ).limit(500)
        
        payout_result = await session.execute(payout_query)
        payouts = list(payout_result.scalars().all())
        
        for payout in payouts:
            bt_repo = BalanceTransactionRepository(session)
            bt_query = select(BTModel).where(
                and_(
                    BTModel.source == payout.id,
                    BTModel.type == "payout",
                )
            )
            bt_result = await session.execute(bt_query)
            bt = bt_result.scalar_one_or_none()
            
            if payout.status == "paid":
                if not bt:
                    discrepancies.append({
                        "type": "missing_payout_transaction",
                        "payout_id": payout.id,
                        "amount": payout.amount,
                        "currency": payout.currency,
                    })
                    
                    await bt_repo.create_transaction(
                        amount=-payout.amount,
                        currency=payout.currency,
                        type="payout",
                        account_id=payout.account_id,
                        source=payout.id,
                        description=f"Reconciliation: Payout {payout.id}",
                    )
                    reconciled_count += 1
            
            if payout.status == "pending" or payout.status == "in_transit":
                expected_arrival = payout.arrival_date
                if expected_arrival and expected_arrival < now - (7 * 24 * 60 * 60):
                    discrepancies.append({
                        "type": "stale_payout",
                        "payout_id": payout.id,
                        "status": payout.status,
                        "expected_arrival": expected_arrival,
                    })
        
        balance_query = select(BalanceModel)
        if account_id:
            balance_query = balance_query.where(BalanceModel.account_id == account_id)
        
        balance_result = await session.execute(balance_query.limit(500))
        balances = list(balance_result.scalars().all())
        
        for balance in balances:
            available_list = balance.available or []
            pending_list = balance.pending or []
            
            for avail in available_list:
                currency = avail.get("currency", "").lower()
                reported_available = avail.get("amount", 0)
                
                calculated_available = await _calculate_expected_balance(session, balance.account_id, currency, "available")
                
                if abs(reported_available - calculated_available) > 1:
                    discrepancies.append({
                        "type": "balance_mismatch",
                        "account_id": balance.account_id,
                        "currency": currency,
                        "reported": reported_available,
                        "calculated": calculated_available,
                    })
        
        await session.commit()
        
        logger.info("Payout reconciliation completed", reconciled=reconciled_count, discrepancies=len(discrepancies))
        return {
            "status": "completed",
            "reconciled_count": reconciled_count,
            "discrepancies_found": len(discrepancies),
            "discrepancies": discrepancies[:100],
        }
        
    except Exception as e:
        logger.error("Error reconciling payouts", error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _calculate_expected_balance(session, account_id: str, currency: str, balance_type: str) -> int:
    from sqlalchemy import select, func
    from payment_platform.backend.domain.models import BalanceTransaction as BTModel
    
    now = int(time.time())
    
    if balance_type == "available":
        query = select(func.sum(BTModel.net)).where(
            and_(
                BTModel.account_id == account_id,
                BTModel.currency == currency.lower(),
                BTModel.available_on <= now,
            )
        )
    else:
        query = select(func.sum(BTModel.net)).where(
            and_(
                BTModel.account_id == account_id,
                BTModel.currency == currency.lower(),
                BTModel.available_on > now,
            )
        )
    
    result = await session.execute(query)
    total = result.scalar() or 0
    return total


@celery_app.task(
    name="detect_anomalies",
    bind=True,
    max_retries=1,
)
def detect_anomalies(self, account_id: Optional[str] = None):
    return run_async(_detect_anomalies(self, account_id))


async def _detect_anomalies(task, account_id: Optional[str]):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import select, and_, func
        from payment_platform.backend.domain.models import (
            Charge as ChargeModel,
            PaymentIntent as PIModel,
            Refund as RefundModel,
            Dispute as DisputeModel,
        )
        
        now = int(time.time())
        window_start = now - (24 * 60 * 60)
        week_start = now - (7 * 24 * 60 * 60)
        
        anomalies = []
        
        query_filter = [ChargeModel.created >= week_start]
        if account_id:
            query_filter.append(ChargeModel.account_id == account_id)
        
        charge_query = select(
            ChargeModel.account_id,
            func.count(ChargeModel.id).label("count"),
            func.sum(ChargeModel.amount).label("total_amount"),
            func.avg(ChargeModel.amount).label("avg_amount"),
        ).where(
            and_(*query_filter)
        ).group_by(ChargeModel.account_id)
        
        charge_result = await session.execute(charge_query)
        charge_stats = charge_result.all()
        
        for stat in charge_stats:
            acc_id, count, total_amount, avg_amount = stat
            
            if count > 1000:
                anomalies.append({
                    "type": "high_volume",
                    "account_id": acc_id,
                    "metric": "charge_count",
                    "value": count,
                    "threshold": 1000,
                    "period": "7_days",
                })
            
            if total_amount and total_amount > 10_000_000_00:
                anomalies.append({
                    "type": "high_volume",
                    "account_id": acc_id,
                    "metric": "total_amount",
                    "value": total_amount,
                    "threshold": 10_000_000_00,
                    "period": "7_days",
                })
        
        refund_query = select(
            RefundModel.account_id,
            func.count(RefundModel.id).label("count"),
            func.sum(RefundModel.amount).label("total_amount"),
        ).where(
            and_(
                RefundModel.created >= week_start,
                *(query_filter[1:] if account_id else []),
            )
        ).group_by(RefundModel.account_id)
        
        refund_result = await session.execute(refund_query)
        refund_stats = refund_result.all()
        
        for stat in refund_stats:
            acc_id, refund_count, refund_total = stat
            
            charge_count = 0
            for cs in charge_stats:
                if cs[0] == acc_id:
                    charge_count = cs[1]
                    break
            
            if charge_count > 0:
                refund_rate = refund_count / charge_count
                if refund_rate > 0.20:
                    anomalies.append({
                        "type": "high_refund_rate",
                        "account_id": acc_id,
                        "refund_rate": refund_rate,
                        "refund_count": refund_count,
                        "charge_count": charge_count,
                    })
        
        dispute_query = select(
            DisputeModel.account_id,
            func.count(DisputeModel.id).label("count"),
            func.sum(DisputeModel.amount).label("total_amount"),
        ).where(
            and_(
                DisputeModel.created >= week_start,
                *(query_filter[1:] if account_id else []),
            )
        ).group_by(DisputeModel.account_id)
        
        dispute_result = await session.execute(dispute_query)
        dispute_stats = dispute_result.all()
        
        for stat in dispute_stats:
            acc_id, dispute_count, dispute_total = stat
            
            charge_count = 0
            for cs in charge_stats:
                if cs[0] == acc_id:
                    charge_count = cs[1]
                    break
            
            if charge_count > 0:
                dispute_rate = dispute_count / charge_count
                if dispute_rate > 0.01:
                    anomalies.append({
                        "type": "high_dispute_rate",
                        "account_id": acc_id,
                        "dispute_rate": dispute_rate,
                        "dispute_count": dispute_count,
                        "charge_count": charge_count,
                    })
        
        failed_pi_query = select(
            PIModel.account_id,
            func.count(PIModel.id).label("count"),
        ).where(
            and_(
                PIModel.status == "requires_payment_method",
                PIModel.created >= window_start,
                *(query_filter[1:] if account_id else []),
            )
        ).group_by(PIModel.account_id)
        
        failed_result = await session.execute(failed_pi_query)
        failed_stats = failed_result.all()
        
        for stat in failed_stats:
            acc_id, fail_count = stat
            
            if fail_count > 100:
                anomalies.append({
                    "type": "high_failure_rate",
                    "account_id": acc_id,
                    "failed_payments": fail_count,
                    "period": "24_hours",
                })
        
        event_repo = EventRepository(session)
        for anomaly in anomalies:
            await event_repo.create_event(
                type="platform.anomaly_detected",
                data=anomaly,
                account_id=anomaly.get("account_id"),
            )
        
        await session.commit()
        
        logger.info("Anomaly detection completed", anomalies_found=len(anomalies))
        return {
            "status": "completed",
            "anomalies_found": len(anomalies),
            "anomalies": anomalies[:100],
        }
        
    except Exception as e:
        logger.error("Error detecting anomalies", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()
