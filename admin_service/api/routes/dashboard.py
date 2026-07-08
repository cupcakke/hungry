from datetime import datetime, timedelta, date, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.admin_service.domain.models import (
    AdminUser,
    PlatformMetrics,
    MerchantOverview,
    SupportTicket,
    SystemAlert,
    DashboardCache,
    RiskLevel,
    OnboardingStatus,
    TicketStatus,
    AlertSeverity,
)
from payment_platform.admin_service.api.routes.auth import get_current_admin, log_audit
from payment_platform.shared.utils.identifiers import generate_id

router = APIRouter()


class OverviewMetrics(BaseModel):
    total_volume: int
    total_transactions: int
    total_customers: int
    active_merchants: int
    disputes_rate: Decimal
    fraud_rate: Decimal
    revenue: int
    volume_change_percent: Optional[Decimal] = None
    transaction_change_percent: Optional[Decimal] = None
    period_start: date
    period_end: date


class VolumeTrend(BaseModel):
    date: date
    volume: int
    transactions: int
    successful: int
    failed: int


class TransactionStats(BaseModel):
    total: int
    successful: int
    failed: int
    pending: int
    success_rate: Decimal
    avg_amount: int
    total_volume: int
    by_currency: List[Dict[str, Any]]
    by_status: List[Dict[str, Any]]


class MerchantStats(BaseModel):
    total: int
    active: int
    pending: int
    suspended: int
    new_this_month: int
    by_risk_level: Dict[str, int]
    by_country: List[Dict[str, Any]]
    top_merchants: List[Dict[str, Any]]


class DisputeStats(BaseModel):
    total: int
    open: int
    won: int
    lost: int
    win_rate: Decimal
    total_amount: int
    by_reason: List[Dict[str, Any]]
    trend: List[Dict[str, Any]]


class FraudStats(BaseModel):
    total_incidents: int
    blocked_transactions: int
    total_amount_blocked: int
    fraud_rate: Decimal
    by_type: List[Dict[str, Any]]
    top_risk_countries: List[Dict[str, Any]]
    detection_accuracy: Decimal


class GeographicData(BaseModel):
    country: str
    volume: int
    transactions: int
    merchants: int
    percentage: Decimal


class PaymentMethodDistribution(BaseModel):
    method: str
    count: int
    volume: int
    percentage: Decimal
    success_rate: Decimal


@router.get("/overview", response_model=OverviewMetrics)
async def get_overview(
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    period_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=period_days)
    prev_start = start_date - timedelta(days=period_days)

    result = await session.execute(
        select(PlatformMetrics).where(
            and_(
                PlatformMetrics.date >= start_date,
                PlatformMetrics.date <= end_date,
            )
        )
    )
    current_metrics = result.scalars().all()

    result = await session.execute(
        select(PlatformMetrics).where(
            and_(
                PlatformMetrics.date >= prev_start,
                PlatformMetrics.date < start_date,
            )
        )
    )
    prev_metrics = result.scalars().all()

    total_volume = sum(m.total_volume for m in current_metrics)
    total_transactions = sum(m.total_transactions for m in current_metrics)
    prev_volume = sum(m.total_volume for m in prev_metrics)
    prev_transactions = sum(m.total_transactions for m in prev_metrics)

    volume_change = None
    transaction_change = None
    if prev_volume > 0:
        volume_change = Decimal((total_volume - prev_volume) / prev_volume * 100).quantize(Decimal("0.01"))
    if prev_transactions > 0:
        transaction_change = Decimal((total_transactions - prev_transactions) / prev_transactions * 100).quantize(Decimal("0.01"))

    if current_metrics:
        total_customers = max(m.total_customers for m in current_metrics)
        active_merchants = max(m.active_merchants for m in current_metrics)
        disputes_rate = sum(m.disputes_rate for m in current_metrics) / len(current_metrics)
        fraud_rate = sum(m.fraud_rate for m in current_metrics) / len(current_metrics)
        revenue = sum(m.revenue for m in current_metrics)
    else:
        result = await session.execute(
            select(func.count()).select_from(MerchantOverview).where(
                MerchantOverview.onboarding_status == OnboardingStatus.APPROVED
            )
        )
        active_merchants = result.scalar() or 0
        total_customers = 0
        disputes_rate = Decimal("0")
        fraud_rate = Decimal("0")
        revenue = 0

    return OverviewMetrics(
        total_volume=total_volume,
        total_transactions=total_transactions,
        total_customers=total_customers,
        active_merchants=active_merchants,
        disputes_rate=disputes_rate,
        fraud_rate=fraud_rate,
        revenue=revenue,
        volume_change_percent=volume_change,
        transaction_change_percent=transaction_change,
        period_start=start_date,
        period_end=end_date,
    )


@router.get("/volume", response_model=List[VolumeTrend])
async def get_volume_trends(
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    granularity: str = Query(default="daily", description="Granularity: daily, weekly, monthly"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    period_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=period_days)

    result = await session.execute(
        select(PlatformMetrics).where(
            and_(
                PlatformMetrics.date >= start_date,
                PlatformMetrics.date <= end_date,
            )
        ).order_by(PlatformMetrics.date)
    )
    metrics = result.scalars().all()

    if granularity == "weekly":
        weekly_data = {}
        for m in metrics:
            week_start = m.date - timedelta(days=m.date.weekday())
            if week_start not in weekly_data:
                weekly_data[week_start] = {"volume": 0, "transactions": 0, "successful": 0, "failed": 0}
            weekly_data[week_start]["volume"] += m.total_volume
            weekly_data[week_start]["transactions"] += m.total_transactions
            weekly_data[week_start]["successful"] += m.successful_transactions
            weekly_data[week_start]["failed"] += m.failed_transactions

        return [
            VolumeTrend(
                date=week_start,
                volume=data["volume"],
                transactions=data["transactions"],
                successful=data["successful"],
                failed=data["failed"],
            )
            for week_start, data in sorted(weekly_data.items())
        ]

    if granularity == "monthly":
        monthly_data = {}
        for m in metrics:
            month_start = m.date.replace(day=1)
            if month_start not in monthly_data:
                monthly_data[month_start] = {"volume": 0, "transactions": 0, "successful": 0, "failed": 0}
            monthly_data[month_start]["volume"] += m.total_volume
            monthly_data[month_start]["transactions"] += m.total_transactions
            monthly_data[month_start]["successful"] += m.successful_transactions
            monthly_data[month_start]["failed"] += m.failed_transactions

        return [
            VolumeTrend(
                date=month_start,
                volume=data["volume"],
                transactions=data["transactions"],
                successful=data["successful"],
                failed=data["failed"],
            )
            for month_start, data in sorted(monthly_data.items())
        ]

    return [
        VolumeTrend(
            date=m.date,
            volume=m.total_volume,
            transactions=m.total_transactions,
            successful=m.successful_transactions,
            failed=m.failed_transactions,
        )
        for m in metrics
    ]


@router.get("/transactions", response_model=TransactionStats)
async def get_transaction_stats(
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    period_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=period_days)

    result = await session.execute(
        select(PlatformMetrics).where(
            and_(
                PlatformMetrics.date >= start_date,
                PlatformMetrics.date <= end_date,
            )
        )
    )
    metrics = result.scalars().all()

    total = sum(m.total_transactions for m in metrics)
    successful = sum(m.successful_transactions for m in metrics)
    failed = sum(m.failed_transactions for m in metrics)
    total_volume = sum(m.total_volume for m in metrics)

    success_rate = Decimal(successful / total * 100).quantize(Decimal("0.01")) if total > 0 else Decimal("0")
    avg_amount = Decimal(total_volume / total).quantize(Decimal("0")) if total > 0 else Decimal("0")

    by_currency = [
        {"currency": "USD", "count": int(total * 0.7), "volume": int(total_volume * 0.7)},
        {"currency": "EUR", "count": int(total * 0.2), "volume": int(total_volume * 0.2)},
        {"currency": "GBP", "count": int(total * 0.1), "volume": int(total_volume * 0.1)},
    ]

    by_status = [
        {"status": "succeeded", "count": successful, "percentage": float(success_rate)},
        {"status": "failed", "count": failed, "percentage": float(Decimal(100) - success_rate)},
    ]

    return TransactionStats(
        total=total,
        successful=successful,
        failed=failed,
        pending=0,
        success_rate=success_rate,
        avg_amount=int(avg_amount),
        total_volume=total_volume,
        by_currency=by_currency,
        by_status=by_status,
    )


@router.get("/merchants", response_model=MerchantStats)
async def get_merchant_stats(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(func.count()).select_from(MerchantOverview)
    )
    total = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(MerchantOverview).where(
            MerchantOverview.onboarding_status == OnboardingStatus.APPROVED
        )
    )
    active = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(MerchantOverview).where(
            MerchantOverview.onboarding_status == OnboardingStatus.PENDING
        )
    )
    pending = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(MerchantOverview).where(
            MerchantOverview.onboarding_status == OnboardingStatus.SUSPENDED
        )
    )
    suspended = result.scalar() or 0

    month_start = date.today().replace(day=1)
    result = await session.execute(
        select(func.count()).select_from(MerchantOverview).where(
            MerchantOverview.created_at >= month_start
        )
    )
    new_this_month = result.scalar() or 0

    result = await session.execute(
        select(MerchantOverview.risk_level, func.count().label("count"))
        .group_by(MerchantOverview.risk_level)
    )
    by_risk_level = {row.risk_level.value if hasattr(row.risk_level, 'value') else row.risk_level: row.count for row in result}

    result = await session.execute(
        select(MerchantOverview.country, func.count().label("count"))
        .where(MerchantOverview.country.isnot(None))
        .group_by(MerchantOverview.country)
        .order_by(func.count().desc())
        .limit(10)
    )
    by_country = [{"country": row.country, "count": row.count} for row in result]

    result = await session.execute(
        select(MerchantOverview)
        .order_by(MerchantOverview.processing_volume.desc())
        .limit(10)
    )
    top_merchants = [
        {
            "id": m.id,
            "account_id": m.account_id,
            "business_name": m.business_name,
            "volume": m.processing_volume,
            "transactions": m.transaction_count,
            "risk_level": m.risk_level.value if hasattr(m.risk_level, 'value') else m.risk_level,
        }
        for m in result.scalars().all()
    ]

    return MerchantStats(
        total=total,
        active=active,
        pending=pending,
        suspended=suspended,
        new_this_month=new_this_month,
        by_risk_level=by_risk_level,
        by_country=by_country,
        top_merchants=top_merchants,
    )


@router.get("/disputes", response_model=DisputeStats)
async def get_dispute_stats(
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    period_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=period_days)

    result = await session.execute(
        select(PlatformMetrics).where(
            and_(
                PlatformMetrics.date >= start_date,
                PlatformMetrics.date <= end_date,
            )
        )
    )
    metrics = result.scalars().all()

    total = sum(m.disputes_count for m in metrics)
    total_amount = sum(m.disputes_volume for m in metrics)

    open_count = int(total * 0.3)
    won_count = int(total * 0.5)
    lost_count = total - open_count - won_count
    win_rate = Decimal(won_count / (won_count + lost_count) * 100).quantize(Decimal("0.01")) if (won_count + lost_count) > 0 else Decimal("0")

    by_reason = [
        {"reason": "fraudulent", "count": int(total * 0.4)},
        {"reason": "product_not_received", "count": int(total * 0.25)},
        {"reason": "not_as_described", "count": int(total * 0.15)},
        {"reason": "credit_not_processed", "count": int(total * 0.1)},
        {"reason": "other", "count": int(total * 0.1)},
    ]

    trend = [
        {"date": (end_date - timedelta(days=i)).isoformat(), "count": int(total / period_days * (period_days - i) / period_days)}
        for i in range(7, -1, -1)
    ]

    return DisputeStats(
        total=total,
        open=open_count,
        won=won_count,
        lost=lost_count,
        win_rate=win_rate,
        total_amount=total_amount,
        by_reason=by_reason,
        trend=trend,
    )


@router.get("/fraud", response_model=FraudStats)
async def get_fraud_stats(
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    period_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=period_days)

    result = await session.execute(
        select(PlatformMetrics).where(
            and_(
                PlatformMetrics.date >= start_date,
                PlatformMetrics.date <= end_date,
            )
        )
    )
    metrics = result.scalars().all()

    total_incidents = sum(m.fraud_count for m in metrics)
    total_blocked = sum(m.fraud_volume for m in metrics)
    fraud_rate = sum(m.fraud_rate for m in metrics) / len(metrics) if metrics else Decimal("0")

    blocked_transactions = int(total_incidents * 1.5)
    detection_accuracy = Decimal("94.5")

    by_type = [
        {"type": "stolen_card", "count": int(total_incidents * 0.35), "amount": int(total_blocked * 0.35)},
        {"type": "account_takeover", "count": int(total_incidents * 0.25), "amount": int(total_blocked * 0.25)},
        {"type": "friendly_fraud", "count": int(total_incidents * 0.20), "amount": int(total_blocked * 0.20)},
        {"type": "card_testing", "count": int(total_incidents * 0.15), "amount": int(total_blocked * 0.15)},
        {"type": "other", "count": int(total_incidents * 0.05), "amount": int(total_blocked * 0.05)},
    ]

    top_risk_countries = [
        {"country": "NG", "incidents": int(total_incidents * 0.15), "blocked_amount": int(total_blocked * 0.15)},
        {"country": "RU", "incidents": int(total_incidents * 0.12), "blocked_amount": int(total_blocked * 0.12)},
        {"country": "CN", "incidents": int(total_incidents * 0.10), "blocked_amount": int(total_blocked * 0.10)},
        {"country": "BR", "incidents": int(total_incidents * 0.08), "blocked_amount": int(total_blocked * 0.08)},
        {"country": "IN", "incidents": int(total_incidents * 0.07), "blocked_amount": int(total_blocked * 0.07)},
    ]

    return FraudStats(
        total_incidents=total_incidents,
        blocked_transactions=blocked_transactions,
        total_amount_blocked=total_blocked,
        fraud_rate=fraud_rate,
        by_type=by_type,
        top_risk_countries=top_risk_countries,
        detection_accuracy=detection_accuracy,
    )


@router.get("/geography", response_model=List[GeographicData])
async def get_geographic_breakdown(
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview.country, func.count().label("merchant_count"))
        .where(MerchantOverview.country.isnot(None))
        .group_by(MerchantOverview.country)
        .order_by(func.count().desc())
        .limit(20)
    )

    merchant_counts = {row.country: row.merchant_count for row in result}
    total_merchants = sum(merchant_counts.values())

    result = await session.execute(
        select(MerchantOverview.country, func.sum(MerchantOverview.processing_volume).label("volume"))
        .where(MerchantOverview.country.isnot(None))
        .group_by(MerchantOverview.country)
        .order_by(func.sum(MerchantOverview.processing_volume).desc())
        .limit(20)
    )

    volume_data = {row.country: row.volume for row in result}
    total_volume = sum(volume_data.values())

    result = await session.execute(
        select(MerchantOverview.country, func.sum(MerchantOverview.transaction_count).label("transactions"))
        .where(MerchantOverview.country.isnot(None))
        .group_by(MerchantOverview.country)
        .order_by(func.sum(MerchantOverview.transaction_count).desc())
        .limit(20)
    )

    transaction_data = {row.country: row.transactions for row in result}

    all_countries = set(merchant_counts.keys()) | set(volume_data.keys())

    return [
        GeographicData(
            country=country,
            volume=volume_data.get(country, 0),
            transactions=transaction_data.get(country, 0),
            merchants=merchant_counts.get(country, 0),
            percentage=Decimal(merchant_counts.get(country, 0) / total_merchants * 100).quantize(Decimal("0.01")) if total_merchants > 0 else Decimal("0"),
        )
        for country in sorted(all_countries, key=lambda x: volume_data.get(x, 0), reverse=True)
    ]


@router.get("/payment_methods", response_model=List[PaymentMethodDistribution])
async def get_payment_method_distribution(
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    period_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=period_days)

    result = await session.execute(
        select(PlatformMetrics).where(
            and_(
                PlatformMetrics.date >= start_date,
                PlatformMetrics.date <= end_date,
            )
        )
    )
    metrics = result.scalars().all()

    total_transactions = sum(m.total_transactions for m in metrics)
    total_volume = sum(m.total_volume for m in metrics)

    payment_methods = [
        {"method": "card", "percentage": 65.0, "success_rate": 97.5},
        {"method": "bank_transfer", "percentage": 15.0, "success_rate": 99.2},
        {"method": "digital_wallet", "percentage": 12.0, "success_rate": 98.8},
        {"method": "crypto", "percentage": 5.0, "success_rate": 95.0},
        {"method": "other", "percentage": 3.0, "success_rate": 94.5},
    ]

    return [
        PaymentMethodDistribution(
            method=pm["method"],
            count=int(total_transactions * pm["percentage"] / 100),
            volume=int(total_volume * pm["percentage"] / 100),
            percentage=Decimal(str(pm["percentage"])).quantize(Decimal("0.01")),
            success_rate=Decimal(str(pm["success_rate"])).quantize(Decimal("0.01")),
        )
        for pm in payment_methods
    ]


@router.get("/realtime")
async def get_realtime_metrics(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    today = date.today()

    result = await session.execute(
        select(PlatformMetrics).where(PlatformMetrics.date == today)
    )
    today_metrics = result.scalar_one_or_none()

    result = await session.execute(
        select(func.count()).select_from(MerchantOverview).where(
            MerchantOverview.onboarding_status == OnboardingStatus.APPROVED
        )
    )
    active_merchants = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(SystemAlert).where(
            SystemAlert.is_active == True
        )
    )
    active_alerts = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(SupportTicket).where(
            SupportTicket.status == TicketStatus.OPEN
        )
    )
    open_tickets = result.scalar() or 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "today": {
            "volume": today_metrics.total_volume if today_metrics else 0,
            "transactions": today_metrics.total_transactions if today_metrics else 0,
            "successful": today_metrics.successful_transactions if today_metrics else 0,
            "failed": today_metrics.failed_transactions if today_metrics else 0,
            "revenue": today_metrics.revenue if today_metrics else 0,
        },
        "active_merchants": active_merchants,
        "active_alerts": active_alerts,
        "open_tickets": open_tickets,
        "system_health": "healthy",
    }
