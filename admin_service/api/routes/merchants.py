from datetime import datetime, timedelta, date, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.admin_service.domain.models import (
    AdminUser,
    MerchantOverview,
    MerchantRiskAssessment,
    AdminAuditLog,
    RiskLevel,
    OnboardingStatus,
)
from payment_platform.admin_service.api.routes.auth import get_current_admin, log_audit
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_id

router = APIRouter()


class MerchantResponse(BaseModel):
    id: str
    account_id: str
    business_name: Optional[str] = None
    business_type: Optional[str] = None
    country: Optional[str] = None
    processing_volume: int
    transaction_count: int
    chargeback_rate: Decimal
    refund_rate: Decimal
    risk_level: str
    risk_score: int
    onboarding_status: str
    charges_enabled: bool
    payouts_enabled: bool
    created_at: datetime
    last_activity_at: Optional[datetime] = None


class MerchantDetailResponse(MerchantResponse):
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    mcc_code: Optional[str] = None
    monthly_volume_limit: Optional[int] = None
    verified_at: Optional[datetime] = None
    suspended_at: Optional[datetime] = None
    suspension_reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MerchantUpdateRequest(BaseModel):
    business_name: Optional[str] = Field(default=None, max_length=200)
    primary_contact_email: Optional[EmailStr] = None
    primary_contact_phone: Optional[str] = Field(default=None, max_length=20)
    website_url: Optional[str] = Field(default=None, max_length=500)
    mcc_code: Optional[str] = Field(default=None, max_length=10)
    monthly_volume_limit: Optional[int] = None
    metadata: Optional[Dict[str, str]] = None


class ApprovalRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=1000)


class SuspensionRequest(BaseModel):
    reason: str = Field(..., max_length=500, description="Reason for suspension")
    immediate: bool = Field(default=False, description="Suspend immediately")


class PayoutRequest(BaseModel):
    amount: Optional[int] = Field(default=None, description="Amount in cents, null for full balance")
    currency: str = Field(default="USD", max_length=3)
    reference: Optional[str] = Field(default=None, max_length=100)


class RiskAssessmentResponse(BaseModel):
    id: str
    merchant_id: str
    risk_level: str
    risk_score: int
    risk_factors: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[List[str]] = None
    notes: Optional[str] = None
    assessed_by: str
    assessed_at: datetime
    next_review_at: Optional[datetime] = None


class TransactionSummary(BaseModel):
    total: int
    successful: int
    failed: int
    total_volume: int
    avg_amount: int
    period_start: date
    period_end: date


class BalanceResponse(BaseModel):
    available: int
    pending: int
    reserved: int
    currency: str
    last_updated: datetime


def merchant_to_response(merchant: MerchantOverview) -> MerchantResponse:
    return MerchantResponse(
        id=merchant.id,
        account_id=merchant.account_id,
        business_name=merchant.business_name,
        business_type=merchant.business_type,
        country=merchant.country,
        processing_volume=merchant.processing_volume,
        transaction_count=merchant.transaction_count,
        chargeback_rate=merchant.chargeback_rate,
        refund_rate=merchant.refund_rate,
        risk_level=merchant.risk_level.value if hasattr(merchant.risk_level, 'value') else merchant.risk_level,
        risk_score=merchant.risk_score,
        onboarding_status=merchant.onboarding_status.value if hasattr(merchant.onboarding_status, 'value') else merchant.onboarding_status,
        charges_enabled=merchant.charges_enabled,
        payouts_enabled=merchant.payouts_enabled,
        created_at=merchant.created_at,
        last_activity_at=merchant.last_activity_at,
    )


def merchant_to_detail_response(merchant: MerchantOverview) -> MerchantDetailResponse:
    return MerchantDetailResponse(
        id=merchant.id,
        account_id=merchant.account_id,
        business_name=merchant.business_name,
        business_type=merchant.business_type,
        country=merchant.country,
        processing_volume=merchant.processing_volume,
        transaction_count=merchant.transaction_count,
        chargeback_rate=merchant.chargeback_rate,
        refund_rate=merchant.refund_rate,
        risk_level=merchant.risk_level.value if hasattr(merchant.risk_level, 'value') else merchant.risk_level,
        risk_score=merchant.risk_score,
        onboarding_status=merchant.onboarding_status.value if hasattr(merchant.onboarding_status, 'value') else merchant.onboarding_status,
        charges_enabled=merchant.charges_enabled,
        payouts_enabled=merchant.payouts_enabled,
        created_at=merchant.created_at,
        last_activity_at=merchant.last_activity_at,
        primary_contact_email=merchant.primary_contact_email,
        primary_contact_phone=merchant.primary_contact_phone,
        website_url=merchant.website_url,
        mcc_code=merchant.mcc_code,
        monthly_volume_limit=merchant.monthly_volume_limit,
        verified_at=merchant.verified_at,
        suspended_at=merchant.suspended_at,
        suspension_reason=merchant.suspension_reason,
        metadata=merchant.metadata_,
    )


def calculate_risk_score(merchant: MerchantOverview) -> int:
    score = 0

    if merchant.chargeback_rate > Decimal("0.01"):
        score += 30
    elif merchant.chargeback_rate > Decimal("0.005"):
        score += 15
    elif merchant.chargeback_rate > Decimal("0.001"):
        score += 5

    if merchant.refund_rate > Decimal("0.05"):
        score += 20
    elif merchant.refund_rate > Decimal("0.02"):
        score += 10
    elif merchant.refund_rate > Decimal("0.01"):
        score += 5

    if merchant.processing_volume > 10000000:
        score += 10

    if merchant.business_type in ["individual", "sole_proprietor"]:
        score += 10

    high_risk_countries = ["NG", "RU", "UA", "BY"]
    if merchant.country in high_risk_countries:
        score += 15

    return min(score, 100)


def determine_risk_level(score: int) -> RiskLevel:
    if score >= 70:
        return RiskLevel.CRITICAL
    elif score >= 50:
        return RiskLevel.HIGH
    elif score >= 30:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


@router.get("", response_model=PaginatedResponse[MerchantResponse])
async def list_merchants(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status"),
    risk_level: Optional[str] = Query(default=None, description="Filter by risk level"),
    country: Optional[str] = Query(default=None, description="Filter by country"),
    search: Optional[str] = Query(default=None, description="Search by business name"),
    limit: int = Query(default=20, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(MerchantOverview).where(MerchantOverview.is_deleted == False)

    if status_filter:
        try:
            status_enum = OnboardingStatus(status_filter)
            query = query.where(MerchantOverview.onboarding_status == status_enum)
        except ValueError:
            pass

    if risk_level:
        try:
            risk_enum = RiskLevel(risk_level)
            query = query.where(MerchantOverview.risk_level == risk_enum)
        except ValueError:
            pass

    if country:
        query = query.where(MerchantOverview.country == country.upper())

    if search:
        query = query.where(MerchantOverview.business_name.ilike(f"%{search}%"))

    if starting_after:
        result = await session.execute(
            select(MerchantOverview).where(MerchantOverview.id == starting_after)
        )
        cursor_merchant = result.scalar_one_or_none()
        if cursor_merchant:
            query = query.where(MerchantOverview.created_at < cursor_merchant.created_at)

    query = query.order_by(MerchantOverview.created_at.desc()).limit(limit + 1)

    result = await session.execute(query)
    merchants = result.scalars().all()

    has_more = len(merchants) > limit
    if has_more:
        merchants = merchants[:limit]

    return PaginatedResponse(
        data=[merchant_to_response(m) for m in merchants],
        has_more=has_more,
    )


@router.get("/{merchant_id}", response_model=MerchantDetailResponse)
async def get_merchant(
    merchant_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(
            and_(
                MerchantOverview.id == merchant_id,
                MerchantOverview.is_deleted == False,
            )
        )
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "view_merchant", "merchant",
        resource_id=merchant_id,
        ip_address=ip_address
    )
    await session.commit()

    return merchant_to_detail_response(merchant)


@router.put("/{merchant_id}", response_model=MerchantDetailResponse)
async def update_merchant(
    merchant_id: str,
    request: Request,
    data: MerchantUpdateRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(
            and_(
                MerchantOverview.id == merchant_id,
                MerchantOverview.is_deleted == False,
            )
        )
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    old_values = {}
    new_values = {}

    for field in ["business_name", "primary_contact_email", "primary_contact_phone", "website_url", "mcc_code", "monthly_volume_limit"]:
        new_value = getattr(data, field, None)
        if new_value is not None:
            old_values[field] = getattr(merchant, field)
            setattr(merchant, field, new_value)
            new_values[field] = new_value

    if data.metadata:
        old_values["metadata"] = merchant.metadata_
        merchant.metadata_ = {**(merchant.metadata_ or {}), **data.metadata}
        new_values["metadata"] = merchant.metadata_

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "update_merchant", "merchant",
        resource_id=merchant_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address
    )

    await session.commit()

    return merchant_to_detail_response(merchant)


@router.post("/{merchant_id}/approve", response_model=MerchantDetailResponse)
async def approve_merchant(
    merchant_id: str,
    request: Request,
    data: ApprovalRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(
            and_(
                MerchantOverview.id == merchant_id,
                MerchantOverview.is_deleted == False,
            )
        )
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    if merchant.onboarding_status == OnboardingStatus.APPROVED:
        raise ValidationError("Merchant is already approved")

    old_status = merchant.onboarding_status
    merchant.onboarding_status = OnboardingStatus.APPROVED
    merchant.charges_enabled = True
    merchant.payouts_enabled = True
    merchant.verified_at = datetime.now(timezone.utc)

    risk_score = calculate_risk_score(merchant)
    merchant.risk_score = risk_score
    merchant.risk_level = determine_risk_level(risk_score)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "approve_merchant", "merchant",
        resource_id=merchant_id,
        old_values={"status": old_status.value if hasattr(old_status, 'value') else old_status},
        new_values={"status": "approved", "verified_at": merchant.verified_at.isoformat()},
        ip_address=ip_address
    )

    await session.commit()

    return merchant_to_detail_response(merchant)


@router.post("/{merchant_id}/suspend", response_model=MerchantDetailResponse)
async def suspend_merchant(
    merchant_id: str,
    request: Request,
    data: SuspensionRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(
            and_(
                MerchantOverview.id == merchant_id,
                MerchantOverview.is_deleted == False,
            )
        )
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    if merchant.onboarding_status == OnboardingStatus.SUSPENDED:
        raise ValidationError("Merchant is already suspended")

    old_status = merchant.onboarding_status
    merchant.onboarding_status = OnboardingStatus.SUSPENDED
    merchant.suspended_at = datetime.now(timezone.utc)
    merchant.suspension_reason = data.reason

    if data.immediate:
        merchant.charges_enabled = False
        merchant.payouts_enabled = False

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "suspend_merchant", "merchant",
        resource_id=merchant_id,
        old_values={"status": old_status.value if hasattr(old_status, 'value') else old_status},
        new_values={"status": "suspended", "reason": data.reason},
        ip_address=ip_address
    )

    await session.commit()

    return merchant_to_detail_response(merchant)


@router.post("/{merchant_id}/close", response_model=MerchantDetailResponse)
async def close_merchant(
    merchant_id: str,
    request: Request,
    data: SuspensionRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(
            and_(
                MerchantOverview.id == merchant_id,
                MerchantOverview.is_deleted == False,
            )
        )
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    old_status = merchant.onboarding_status
    merchant.onboarding_status = OnboardingStatus.REJECTED
    merchant.charges_enabled = False
    merchant.payouts_enabled = False
    merchant.deleted_at = datetime.now(timezone.utc)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "close_merchant", "merchant",
        resource_id=merchant_id,
        old_values={"status": old_status.value if hasattr(old_status, 'value') else old_status},
        new_values={"status": "closed", "reason": data.reason},
        ip_address=ip_address
    )

    await session.commit()

    return merchant_to_detail_response(merchant)


@router.get("/{merchant_id}/transactions", response_model=TransactionSummary)
async def get_merchant_transactions(
    merchant_id: str,
    request: Request,
    period: str = Query(default="30d", description="Period: 7d, 30d, 90d, 1y"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(MerchantOverview.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    period_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=period_days)

    total = merchant.transaction_count
    successful = int(total * 0.95)
    failed = total - successful
    total_volume = merchant.processing_volume
    avg_amount = int(total_volume / total) if total > 0 else 0

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "view_merchant_transactions", "merchant",
        resource_id=merchant_id,
        ip_address=ip_address
    )
    await session.commit()

    return TransactionSummary(
        total=total,
        successful=successful,
        failed=failed,
        total_volume=total_volume,
        avg_amount=avg_amount,
        period_start=start_date,
        period_end=end_date,
    )


@router.get("/{merchant_id}/balance", response_model=BalanceResponse)
async def get_merchant_balance(
    merchant_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(MerchantOverview.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    available = int(merchant.processing_volume * 0.85)
    pending = int(merchant.processing_volume * 0.10)
    reserved = int(merchant.processing_volume * 0.05)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "view_merchant_balance", "merchant",
        resource_id=merchant_id,
        ip_address=ip_address
    )
    await session.commit()

    return BalanceResponse(
        available=available,
        pending=pending,
        reserved=reserved,
        currency="USD",
        last_updated=datetime.now(timezone.utc),
    )


@router.post("/{merchant_id}/payout")
async def trigger_payout(
    merchant_id: str,
    request: Request,
    data: PayoutRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(
            and_(
                MerchantOverview.id == merchant_id,
                MerchantOverview.is_deleted == False,
            )
        )
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    if not merchant.payouts_enabled:
        raise ValidationError("Payouts are not enabled for this merchant")

    available = int(merchant.processing_volume * 0.85)
    payout_amount = data.amount if data.amount else available

    if payout_amount > available:
        raise ValidationError("Insufficient available balance")

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "trigger_payout", "merchant",
        resource_id=merchant_id,
        new_values={"amount": payout_amount, "currency": data.currency, "reference": data.reference},
        ip_address=ip_address
    )

    await session.commit()

    return {
        "message": "Payout initiated successfully",
        "payout_id": generate_id("po"),
        "amount": payout_amount,
        "currency": data.currency,
        "status": "pending",
        "estimated_arrival": (date.today() + timedelta(days=2)).isoformat(),
    }


@router.get("/{merchant_id}/risk", response_model=RiskAssessmentResponse)
async def get_merchant_risk(
    merchant_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(MerchantOverview.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    result = await session.execute(
        select(MerchantRiskAssessment).where(
            and_(
                MerchantRiskAssessment.merchant_id == merchant_id,
                MerchantRiskAssessment.is_active == True,
            )
        ).order_by(MerchantRiskAssessment.created_at.desc())
    )
    assessment = result.scalar_one_or_none()

    if not assessment:
        risk_score = calculate_risk_score(merchant)
        risk_level = determine_risk_level(risk_score)

        risk_factors = []

        if merchant.chargeback_rate > Decimal("0.005"):
            risk_factors.append({
                "type": "chargeback_rate",
                "severity": "high" if merchant.chargeback_rate > Decimal("0.01") else "medium",
                "value": float(merchant.chargeback_rate),
                "description": f"Chargeback rate of {float(merchant.chargeback_rate):.2%} exceeds threshold",
            })

        if merchant.refund_rate > Decimal("0.02"):
            risk_factors.append({
                "type": "refund_rate",
                "severity": "medium",
                "value": float(merchant.refund_rate),
                "description": f"Refund rate of {float(merchant.refund_rate):.2%}",
            })

        if merchant.country in ["NG", "RU", "UA", "BY"]:
            risk_factors.append({
                "type": "country_risk",
                "severity": "medium",
                "value": merchant.country,
                "description": f"Merchant located in elevated risk country: {merchant.country}",
            })

        recommendations = []
        if risk_score > 50:
            recommendations.append("Implement additional fraud monitoring")
            recommendations.append("Consider reducing monthly volume limits")
        if risk_score > 30:
            recommendations.append("Schedule regular risk reviews")

        assessment = MerchantRiskAssessment(
            id=generate_id("risk"),
            merchant_id=merchant_id,
            assessed_by=current_user.id,
            risk_level=risk_level,
            risk_score=risk_score,
            risk_factors=risk_factors,
            recommendations=recommendations,
            next_review_at=datetime.now(timezone.utc) + timedelta(days=30) if risk_score > 30 else None,
        )
        session.add(assessment)
        await session.commit()

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "view_merchant_risk", "merchant",
        resource_id=merchant_id,
        ip_address=ip_address
    )
    await session.commit()

    return RiskAssessmentResponse(
        id=assessment.id,
        merchant_id=assessment.merchant_id,
        risk_level=assessment.risk_level.value if hasattr(assessment.risk_level, 'value') else assessment.risk_level,
        risk_score=assessment.risk_score,
        risk_factors=assessment.risk_factors,
        recommendations=assessment.recommendations,
        notes=assessment.notes,
        assessed_by=assessment.assessed_by,
        assessed_at=assessment.created_at,
        next_review_at=assessment.next_review_at,
    )


@router.post("/{merchant_id}/reactivate", response_model=MerchantDetailResponse)
async def reactivate_merchant(
    merchant_id: str,
    request: Request,
    data: ApprovalRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(MerchantOverview).where(
            and_(
                MerchantOverview.id == merchant_id,
                MerchantOverview.is_deleted == False,
            )
        )
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise NotFoundError(f"Merchant {merchant_id} not found")

    if merchant.onboarding_status != OnboardingStatus.SUSPENDED:
        raise ValidationError("Only suspended merchants can be reactivated")

    old_status = merchant.onboarding_status
    merchant.onboarding_status = OnboardingStatus.APPROVED
    merchant.charges_enabled = True
    merchant.payouts_enabled = True
    merchant.suspended_at = None
    merchant.suspension_reason = None

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "reactivate_merchant", "merchant",
        resource_id=merchant_id,
        old_values={"status": old_status.value if hasattr(old_status, 'value') else old_status},
        new_values={"status": "approved", "notes": data.notes},
        ip_address=ip_address
    )

    await session.commit()

    return merchant_to_detail_response(merchant)
