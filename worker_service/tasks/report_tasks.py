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
    ReportRepository,
    AccountRepository,
    ChargeRepository,
    RefundRepository,
    PayoutRepository,
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
    name="generate_scheduled_reports",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def generate_scheduled_reports(self):
    return run_async(_generate_scheduled_reports(self))


async def _generate_scheduled_reports(task):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import select, and_
        from payment_platform.backend.domain.models import Report as ReportModel, Account as AccountModel
        
        now = int(time.time())
        today = datetime.now(timezone.utc).date()
        day_of_week = today.weekday()
        day_of_month = today.day
        
        reports_generated = 0
        
        daily_query = select(ReportModel).where(
            and_(
                ReportModel.schedule == "daily",
                ReportModel.status == "pending",
                ReportModel.next_run_at <= now,
            )
        )
        daily_result = await session.execute(daily_query.limit(100))
        daily_reports = list(daily_result.scalars().all())
        
        for report in daily_reports:
            await _generate_report(session, report)
            reports_generated += 1
        
        weekly_query = select(ReportModel).where(
            and_(
                ReportModel.schedule == "weekly",
                ReportModel.status == "pending",
                ReportModel.next_run_at <= now,
            )
        )
        weekly_result = await session.execute(weekly_query.limit(100))
        weekly_reports = list(weekly_result.scalars().all())
        
        for report in weekly_reports:
            await _generate_report(session, report)
            reports_generated += 1
        
        monthly_query = select(ReportModel).where(
            and_(
                ReportModel.schedule == "monthly",
                ReportModel.status == "pending",
                ReportModel.next_run_at <= now,
            )
        )
        monthly_result = await session.execute(monthly_query.limit(100))
        monthly_reports = list(monthly_result.scalars().all())
        
        for report in monthly_reports:
            await _generate_report(session, report)
            reports_generated += 1
        
        active_accounts_query = select(AccountModel).where(AccountModel.deleted_at.is_(None))
        active_accounts_result = await session.execute(active_accounts_query.limit(500))
        active_accounts = list(active_accounts_result.scalars().all())
        
        for account in active_accounts:
            if account.id:
                existing_today_query = select(ReportModel).where(
                    and_(
                        ReportModel.account_id == account.id,
                        ReportModel.report_type == "daily_summary",
                        ReportModel.created >= int(time.time()) - 86400,
                    )
                )
                existing_today_result = await session.execute(existing_today_query)
                existing_today = existing_today_result.scalar_one_or_none()
                
                if not existing_today:
                    await _create_daily_summary_report(session, account.id)
                    reports_generated += 1
        
        await session.commit()
        
        logger.info("Scheduled reports generated", count=reports_generated)
        return {"status": "completed", "reports_generated": reports_generated}
        
    except Exception as e:
        logger.error("Error generating scheduled reports", error=str(e))
        try:
            task.retry(exc=e)
        except MaxRetriesExceededError:
            return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()


async def _generate_report(session, report):
    report.status = "running"
    await session.flush()
    
    try:
        now = int(time.time())
        account_id = report.account_id
        report_type = report.report_type
        params = report.parameters or {}
        
        data = {}
        
        if report_type == "transaction_summary":
            data = await _generate_transaction_summary(session, account_id, params)
        elif report_type == "payout_summary":
            data = await _generate_payout_summary(session, account_id, params)
        elif report_type == "balance_summary":
            data = await _generate_balance_summary(session, account_id, params)
        elif report_type == "daily_summary":
            data = await _generate_daily_summary(session, account_id, params)
        else:
            data = await _generate_custom_report(session, account_id, report_type, params)
        
        report.result = data
        report.status = "completed"
        report.completed_at = datetime.now(timezone.utc)
        
        if report.schedule == "daily":
            report.next_run_at = now + 86400
        elif report.schedule == "weekly":
            report.next_run_at = now + (7 * 86400)
        elif report.schedule == "monthly":
            next_month = datetime.now(timezone.utc).replace(day=1) + timedelta(days=32)
            report.next_run_at = int(next_month.replace(day=1).timestamp())
        
        event_repo = EventRepository(session)
        await event_repo.create_event(
            type="report.completed",
            data={
                "report_id": report.id,
                "report_type": report_type,
                "account_id": account_id,
            },
            account_id=account_id,
        )
        
        logger.info("Report generated", report_id=report.id, report_type=report_type)
        
    except Exception as e:
        report.status = "failed"
        report.result = {"error": str(e)}
        logger.error("Report generation failed", report_id=report.id, error=str(e))


async def _generate_transaction_summary(session, account_id: str, params: Dict) -> Dict:
    from sqlalchemy import select, func, and_
    from payment_platform.backend.domain.models import Charge as ChargeModel, Refund as RefundModel
    
    start_date = params.get("start_date", int(time.time()) - (30 * 86400))
    end_date = params.get("end_date", int(time.time()))
    
    charge_query = select(
        func.count(ChargeModel.id).label("count"),
        func.sum(ChargeModel.amount).label("total"),
        func.avg(ChargeModel.amount).label("average"),
    ).where(
        and_(
            ChargeModel.account_id == account_id,
            ChargeModel.created >= start_date,
            ChargeModel.created <= end_date,
            ChargeModel.status == "succeeded",
        )
    )
    charge_result = await session.execute(charge_query)
    charge_stats = charge_result.first()
    
    refund_query = select(
        func.count(RefundModel.id).label("count"),
        func.sum(RefundModel.amount).label("total"),
    ).where(
        and_(
            RefundModel.account_id == account_id,
            RefundModel.created >= start_date,
            RefundModel.created <= end_date,
            RefundModel.status == "succeeded",
        )
    )
    refund_result = await session.execute(refund_query)
    refund_stats = refund_result.first()
    
    return {
        "period": {
            "start": start_date,
            "end": end_date,
        },
        "charges": {
            "count": charge_stats.count or 0,
            "total": charge_stats.total or 0,
            "average": float(charge_stats.average or 0),
        },
        "refunds": {
            "count": refund_stats.count or 0,
            "total": refund_stats.total or 0,
        },
        "net": (charge_stats.total or 0) - (refund_stats.total or 0),
    }


async def _generate_payout_summary(session, account_id: str, params: Dict) -> Dict:
    from sqlalchemy import select, func, and_
    from payment_platform.backend.domain.models import Payout as PayoutModel
    
    start_date = params.get("start_date", int(time.time()) - (30 * 86400))
    end_date = params.get("end_date", int(time.time()))
    
    payout_query = select(
        PayoutModel.status,
        func.count(PayoutModel.id).label("count"),
        func.sum(PayoutModel.amount).label("total"),
    ).where(
        and_(
            PayoutModel.account_id == account_id,
            PayoutModel.created >= start_date,
            PayoutModel.created <= end_date,
        )
    ).group_by(PayoutModel.status)
    
    payout_result = await session.execute(payout_query)
    payout_stats = payout_result.all()
    
    by_status = {}
    for stat in payout_stats:
        by_status[stat.status] = {
            "count": stat.count,
            "total": stat.total or 0,
        }
    
    return {
        "period": {
            "start": start_date,
            "end": end_date,
        },
        "by_status": by_status,
        "total_payouts": sum(s.get("total", 0) for s in by_status.values()),
    }


async def _generate_balance_summary(session, account_id: str, params: Dict) -> Dict:
    from sqlalchemy import select, func, and_
    from payment_platform.backend.domain.models import Balance as BalanceModel, BalanceTransaction as BTModel
    
    balance_repo = BalanceRepository(session)
    balance = await balance_repo.get_or_create_for_account(account_id)
    
    now = int(time.time())
    
    bt_query = select(
        BTModel.type,
        func.count(BTModel.id).label("count"),
        func.sum(BTModel.amount).label("total"),
    ).where(
        and_(
            BTModel.account_id == account_id,
            BTModel.created >= now - (30 * 86400),
        )
    ).group_by(BTModel.type)
    
    bt_result = await session.execute(bt_query)
    bt_stats = bt_result.all()
    
    by_type = {}
    for stat in bt_stats:
        by_type[stat.type] = {
            "count": stat.count,
            "total": stat.total or 0,
        }
    
    return {
        "available": balance.available or [],
        "pending": balance.pending or [],
        "transactions_by_type": by_type,
    }


async def _generate_daily_summary(session, account_id: str, params: Dict) -> Dict:
    from sqlalchemy import select, func, and_
    from payment_platform.backend.domain.models import Charge as ChargeModel, Refund as RefundModel, Payout as PayoutModel
    
    now = int(time.time())
    day_start = now - (24 * 60 * 60)
    
    charge_query = select(
        func.count(ChargeModel.id).label("count"),
        func.sum(ChargeModel.amount).label("total"),
    ).where(
        and_(
            ChargeModel.account_id == account_id,
            ChargeModel.created >= day_start,
            ChargeModel.status == "succeeded",
        )
    )
    charge_result = await session.execute(charge_query)
    charge_stats = charge_result.first()
    
    refund_query = select(
        func.count(RefundModel.id).label("count"),
        func.sum(RefundModel.amount).label("total"),
    ).where(
        and_(
            RefundModel.account_id == account_id,
            RefundModel.created >= day_start,
            RefundModel.status == "succeeded",
        )
    )
    refund_result = await session.execute(refund_query)
    refund_stats = refund_result.first()
    
    payout_query = select(
        func.count(PayoutModel.id).label("count"),
        func.sum(PayoutModel.amount).label("total"),
    ).where(
        and_(
            PayoutModel.account_id == account_id,
            PayoutModel.created >= day_start,
            PayoutModel.status.in_(["paid", "pending", "in_transit"]),
        )
    )
    payout_result = await session.execute(payout_query)
    payout_stats = payout_result.first()
    
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "charges": {
            "count": charge_stats.count or 0,
            "total": charge_stats.total or 0,
        },
        "refunds": {
            "count": refund_stats.count or 0,
            "total": refund_stats.total or 0,
        },
        "payouts": {
            "count": payout_stats.count or 0,
            "total": payout_stats.total or 0,
        },
        "net_revenue": (charge_stats.total or 0) - (refund_stats.total or 0),
    }


async def _create_daily_summary_report(session, account_id: str):
    from payment_platform.backend.domain.models import Report as ReportModel
    import uuid
    
    now = int(time.time())
    report_id = f"re_{uuid.uuid4().hex[:24]}"
    
    report = ReportModel(
        id=report_id,
        account_id=account_id,
        report_type="daily_summary",
        status="pending",
        schedule="daily",
        parameters={},
        created=now,
        next_run_at=now + 86400,
    )
    session.add(report)
    await session.flush()
    
    await _generate_report(session, report)
    return report


async def _generate_custom_report(session, account_id: str, report_type: str, params: Dict) -> Dict:
    return {
        "report_type": report_type,
        "account_id": account_id,
        "parameters": params,
        "generated_at": int(time.time()),
    }


@celery_app.task(
    name="cleanup_old_reports",
    bind=True,
    max_retries=1,
)
def cleanup_old_reports(self, days_to_keep: int = 90):
    return run_async(_cleanup_old_reports(self, days_to_keep))


async def _cleanup_old_reports(task, days_to_keep: int):
    session = None
    try:
        session = async_session_factory()
        
        from sqlalchemy import delete, and_
        from payment_platform.backend.domain.models import Report as ReportModel
        
        cutoff_date = int(time.time()) - (days_to_keep * 86400)
        
        stmt = delete(ReportModel).where(
            and_(
                ReportModel.status.in_(["completed", "failed"]),
                ReportModel.completed_at != None,
                ReportModel.completed_at < datetime.fromtimestamp(cutoff_date, tz=timezone.utc),
            )
        )
        
        result = await session.execute(stmt)
        deleted_count = result.rowcount
        
        await session.commit()
        
        logger.info("Old reports cleaned up", deleted_count=deleted_count, days_kept=days_to_keep)
        return {"status": "completed", "reports_deleted": deleted_count}
        
    except Exception as e:
        logger.error("Error cleaning up old reports", error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        if session:
            await session.close()
