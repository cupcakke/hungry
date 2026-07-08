from datetime import datetime, date
from typing import Any, Dict, List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, status, Header
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, AuthorizationError
from payment_platform.backend.application.services.capital_service import (
    OfferService, FinancingService, RepaymentService,
    RiskAssessmentService, CollectionService, FinancingTransactionService,
)

router = APIRouter()


class CreateOfferRequest(BaseModel):
    account_id: str = Field(..., description="Account ID for the offer")
    amount: int = Field(..., gt=0, description="Offer amount in minor units")
    currency: str = Field(default="usd", min_length=3, max_length=3, description="Currency code")
    interest_rate: float = Field(..., ge=0, le=100, description="Annual interest rate percentage")
    term_months: int = Field(..., gt=0, le=60, description="Loan term in months")
    repayment_method: str = Field(..., description="fixed or revenue_share")
    interest_type: str = Field(default="simple", description="simple or compound")
    revenue_share_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    metadata: Optional[Dict[str, str]] = None


class FinancingOfferResponse(BaseModel):
    id: str
    object: str = "financing_offer"
    account_id: str
    amount: int
    currency: str
    interest_rate: float
    interest_type: str
    term_months: int
    repayment_method: str
    revenue_share_percentage: Optional[float] = None
    total_repayment_amount: int
    status: str
    expires_at: str
    accepted_at: Optional[str] = None
    declined_at: Optional[str] = None
    risk_score: Optional[float] = None
    risk_tier: Optional[str] = None
    created: int
    metadata: Dict[str, str] = {}


class FinancingResponse(BaseModel):
    id: str
    object: str = "financing"
    account_id: str
    offer_id: Optional[str] = None
    amount: int
    currency: str
    interest_rate: float
    interest_type: str
    term_months: int
    repayment_method: str
    revenue_share_percentage: Optional[float] = None
    disbursed_at: Optional[str] = None
    status: str
    outstanding_principal: int
    outstanding_interest: int
    outstanding_balance: int
    total_principal_paid: int
    total_interest_paid: int
    total_fees_paid: int
    next_payment_date: Optional[str] = None
    next_payment_amount: Optional[int] = None
    delinquency_status: str
    created: int
    metadata: Dict[str, str] = {}


class FinancingSummaryResponse(BaseModel):
    id: str
    object: str = "financing_summary"
    account_id: str
    amount: int
    currency: str
    status: str
    disbursed_at: Optional[str] = None
    outstanding_balance: int
    outstanding_principal: int
    outstanding_interest: int
    total_principal_paid: int
    total_interest_paid: int
    total_fees_paid: int
    next_payment_date: Optional[str] = None
    next_payment_amount: Optional[int] = None
    delinquency_status: str
    payoff_amount: int
    progress_percentage: float
    installments_completed: int
    installments_total: int


class RepaymentScheduleResponse(BaseModel):
    id: str
    object: str = "repayment_schedule"
    financing_id: str
    total_installments: int
    completed_installments: int
    next_payment_date: Optional[str] = None
    next_payment_amount: Optional[int] = None
    total_remaining: int
    total_paid: int
    installments: List[Dict[str, Any]]


class RepaymentResponse(BaseModel):
    id: str
    object: str = "repayment"
    financing_id: str
    account_id: str
    amount: int
    applied_to_principal: int
    applied_to_interest: int
    applied_to_fees: int
    paid_at: str
    status: str
    source: Optional[str] = None
    source_type: Optional[str] = None
    installment_number: Optional[int] = None


class FinancingTransactionResponse(BaseModel):
    id: str
    object: str = "financing_transaction"
    financing_id: str
    account_id: str
    type: str
    amount: int
    balance_before: int
    balance_after: int
    timestamp: str
    description: Optional[str] = None
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None


class OfferEligibilityResponse(BaseModel):
    id: str
    object: str = "offer_eligibility"
    account_id: str
    eligible: bool
    max_amount: Optional[int] = None
    currency: str
    reason_codes: Optional[List[str]] = None
    risk_score: Optional[float] = None
    risk_tier: Optional[str] = None
    evaluated_at: str


class MakeRepaymentRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Repayment amount in minor units")
    source: Optional[str] = Field(default=None, description="Payment source ID")
    source_type: Optional[str] = Field(default=None, description="Source type")
    metadata: Optional[Dict[str, str]] = None


class AcceptOfferRequest(BaseModel):
    pass


def offer_to_response(offer) -> FinancingOfferResponse:
    return FinancingOfferResponse(
        id=offer.id,
        account_id=offer.account_id,
        amount=offer.amount,
        currency=offer.currency,
        interest_rate=float(offer.interest_rate),
        interest_type=offer.interest_type,
        term_months=offer.term_months,
        repayment_method=offer.repayment_method,
        revenue_share_percentage=float(offer.revenue_share_percentage) if offer.revenue_share_percentage else None,
        total_repayment_amount=offer.total_repayment_amount,
        status=offer.status,
        expires_at=offer.expires_at.isoformat(),
        accepted_at=offer.accepted_at.isoformat() if offer.accepted_at else None,
        declined_at=offer.declined_at.isoformat() if offer.declined_at else None,
        risk_score=float(offer.risk_score) if offer.risk_score else None,
        risk_tier=offer.risk_tier,
        created=int(offer.created_at.timestamp()),
        metadata=offer.metadata_ or {},
    )


def financing_to_response(financing) -> FinancingResponse:
    return FinancingResponse(
        id=financing.id,
        account_id=financing.account_id,
        offer_id=financing.offer_id,
        amount=financing.amount,
        currency=financing.currency,
        interest_rate=float(financing.interest_rate),
        interest_type=financing.interest_type,
        term_months=financing.term_months,
        repayment_method=financing.repayment_method,
        revenue_share_percentage=float(financing.revenue_share_percentage) if financing.revenue_share_percentage else None,
        disbursed_at=financing.disbursed_at.isoformat() if financing.disbursed_at else None,
        status=financing.status,
        outstanding_principal=financing.outstanding_principal,
        outstanding_interest=financing.outstanding_interest,
        outstanding_balance=financing.outstanding_balance,
        total_principal_paid=financing.total_principal_paid,
        total_interest_paid=financing.total_interest_paid,
        total_fees_paid=financing.total_fees_paid,
        next_payment_date=financing.next_payment_date.isoformat() if financing.next_payment_date else None,
        next_payment_amount=financing.next_payment_amount,
        delinquency_status=financing.delinquency_status,
        created=int(financing.created_at.timestamp()),
        metadata=financing.terms.get("metadata", {}) if financing.terms else {},
    )


def repayment_to_response(repayment) -> RepaymentResponse:
    return RepaymentResponse(
        id=repayment.id,
        financing_id=repayment.financing_id,
        account_id=repayment.account_id,
        amount=repayment.amount,
        applied_to_principal=repayment.applied_to_principal,
        applied_to_interest=repayment.applied_to_interest,
        applied_to_fees=repayment.applied_to_fees,
        paid_at=repayment.paid_at.isoformat(),
        status=repayment.status,
        source=repayment.source,
        source_type=repayment.source_type,
        installment_number=repayment.installment_number,
    )


def transaction_to_response(transaction) -> FinancingTransactionResponse:
    return FinancingTransactionResponse(
        id=transaction.id,
        financing_id=transaction.financing_id,
        account_id=transaction.account_id,
        type=transaction.type,
        amount=transaction.amount,
        balance_before=transaction.balance_before,
        balance_after=transaction.balance_after,
        timestamp=transaction.timestamp.isoformat(),
        description=transaction.description,
        reference_id=transaction.reference_id,
        reference_type=transaction.reference_type,
    )


def eligibility_to_response(eligibility) -> OfferEligibilityResponse:
    return OfferEligibilityResponse(
        id=eligibility.id,
        account_id=eligibility.account_id,
        eligible=eligibility.eligible,
        max_amount=eligibility.max_amount,
        currency=eligibility.currency,
        reason_codes=eligibility.reason_codes,
        risk_score=float(eligibility.risk_score) if eligibility.risk_score else None,
        risk_tier=eligibility.risk_tier,
        evaluated_at=eligibility.evaluated_at.isoformat(),
    )


@router.get("/offers", response_model=PaginatedResponse[FinancingOfferResponse])
async def list_offers(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Filter by account ID"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=10, ge=1, le=100),
    session=Depends(get_session),
):
    service = OfferService(session)
    if account_id:
        offers = await service.get_by_account(account_id, status=status)
    else:
        offers = []
    has_more = len(offers) > limit
    if has_more:
        offers = offers[:limit]
    return PaginatedResponse(
        data=[offer_to_response(o) for o in offers],
        has_more=has_more,
    )


@router.post("/offers", response_model=FinancingOfferResponse, status_code=status.HTTP_201_CREATED)
async def create_offer(
    request: Request,
    data: CreateOfferRequest,
    session=Depends(get_session),
    internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
):
    if not internal_api_key:
        raise AuthorizationError("Internal API key required for offer creation")
    service = OfferService(session)
    offer = await service.create(
        account_id=data.account_id,
        amount=data.amount,
        currency=data.currency,
        interest_rate=Decimal(str(data.interest_rate)),
        term_months=data.term_months,
        repayment_method=data.repayment_method,
        interest_type=data.interest_type,
        revenue_share_percentage=Decimal(str(data.revenue_share_percentage)) if data.revenue_share_percentage else None,
        metadata=data.metadata,
    )
    await session.commit()
    return offer_to_response(offer)


@router.get("/offers/{offer_id}", response_model=FinancingOfferResponse)
async def get_offer(
    offer_id: str,
    request: Request,
    session=Depends(get_session),
):
    service = OfferService(session)
    offer = await service.get_by_id(offer_id)
    if not offer:
        raise NotFoundError(f"Offer {offer_id} not found")
    return offer_to_response(offer)


@router.post("/offers/{offer_id}/accept", response_model=FinancingResponse, status_code=status.HTTP_201_CREATED)
async def accept_offer(
    offer_id: str,
    request: Request,
    data: AcceptOfferRequest,
    session=Depends(get_session),
):
    offer_service = OfferService(session)
    offer = await offer_service.accept(offer_id)
    financing_service = FinancingService(session)
    financing = await financing_service.disburse(offer_id)
    await session.commit()
    return financing_to_response(financing)


@router.post("/offers/{offer_id}/decline", response_model=FinancingOfferResponse)
async def decline_offer(
    offer_id: str,
    request: Request,
    session=Depends(get_session),
):
    service = OfferService(session)
    offer = await service.decline(offer_id)
    await session.commit()
    return offer_to_response(offer)


@router.get("/financings", response_model=PaginatedResponse[FinancingResponse])
async def list_financings(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Filter by account ID"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=10, ge=1, le=100),
    session=Depends(get_session),
):
    service = FinancingService(session)
    if account_id:
        financings = await service.get_by_account(account_id, status=status)
    else:
        financings = []
    has_more = len(financings) > limit
    if has_more:
        financings = financings[:limit]
    return PaginatedResponse(
        data=[financing_to_response(f) for f in financings],
        has_more=has_more,
    )


@router.get("/financings/{financing_id}", response_model=FinancingResponse)
async def get_financing(
    financing_id: str,
    request: Request,
    session=Depends(get_session),
):
    service = FinancingService(session)
    financing = await service.get_by_id(financing_id)
    if not financing:
        raise NotFoundError(f"Financing {financing_id} not found")
    return financing_to_response(financing)


@router.get("/financings/{financing_id}/summary", response_model=FinancingSummaryResponse)
async def get_financing_summary(
    financing_id: str,
    request: Request,
    session=Depends(get_session),
):
    service = FinancingService(session)
    summary = await service.get_summary(financing_id)
    if not summary:
        raise NotFoundError(f"Financing {financing_id} not found")
    return FinancingSummaryResponse(**summary)


@router.get("/financings/{financing_id}/repayment_schedule", response_model=RepaymentScheduleResponse)
async def get_repayment_schedule(
    financing_id: str,
    request: Request,
    session=Depends(get_session),
):
    service = FinancingService(session)
    financing = await service.get_by_id(financing_id)
    if not financing:
        raise NotFoundError(f"Financing {financing_id} not found")
    schedule = await service.get_repayment_schedule(financing_id)
    if not schedule:
        raise NotFoundError(f"Repayment schedule for financing {financing_id} not found")
    return RepaymentScheduleResponse(
        id=schedule.id,
        financing_id=schedule.financing_id,
        total_installments=schedule.total_installments,
        completed_installments=schedule.completed_installments,
        next_payment_date=schedule.next_payment_date.isoformat() if schedule.next_payment_date else None,
        next_payment_amount=schedule.next_payment_amount,
        total_remaining=schedule.total_remaining,
        total_paid=schedule.total_paid,
        installments=schedule.installments,
    )


@router.post("/financings/{financing_id}/repay", response_model=RepaymentResponse)
async def make_repayment(
    financing_id: str,
    request: Request,
    data: MakeRepaymentRequest,
    session=Depends(get_session),
):
    service = RepaymentService(session)
    repayment = await service.process_repayment(
        financing_id=financing_id,
        amount=data.amount,
        source=data.source,
        source_type=data.source_type,
        metadata=data.metadata,
    )
    await session.commit()
    return repayment_to_response(repayment)


@router.get("/eligibility", response_model=OfferEligibilityResponse)
async def check_eligibility(
    request: Request,
    account_id: str = Query(..., description="Account ID to check"),
    session=Depends(get_session),
):
    service = RiskAssessmentService(session)
    eligibility = await service.get_eligibility(account_id)
    if not eligibility:
        offer_service = OfferService(session)
        eligibility = await offer_service.evaluate_eligibility(account_id)
    await session.commit()
    return eligibility_to_response(eligibility)


@router.get("/transactions", response_model=PaginatedResponse[FinancingTransactionResponse])
async def list_transactions(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Filter by account ID"),
    financing_id: Optional[str] = Query(default=None, description="Filter by financing ID"),
    transaction_type: Optional[str] = Query(default=None, description="Filter by type"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session=Depends(get_session),
):
    service = FinancingTransactionService(session)
    if financing_id:
        transactions = await service.get_by_financing(financing_id, limit=limit + 1, offset=offset)
    elif account_id:
        transactions = await service.get_by_account(
            account_id,
            transaction_type=transaction_type,
            limit=limit + 1,
            offset=offset,
        )
    else:
        raise ValidationError("Either account_id or financing_id must be provided")
    has_more = len(transactions) > limit
    if has_more:
        transactions = transactions[:limit]
    return PaginatedResponse(
        data=[transaction_to_response(t) for t in transactions],
        has_more=has_more,
    )


@router.get("/financings/{financing_id}/payoff")
async def calculate_payoff(
    financing_id: str,
    request: Request,
    payoff_date: Optional[str] = Query(default=None, description="Target payoff date (YYYY-MM-DD)"),
    session=Depends(get_session),
):
    service = FinancingService(session)
    target_date = None
    if payoff_date:
        try:
            target_date = date.fromisoformat(payoff_date)
        except ValueError:
            raise ValidationError("Invalid date format. Use YYYY-MM-DD")
    payoff = await service.calculate_payoff(financing_id, target_date)
    return payoff


@router.post("/financings/{financing_id}/check_delinquency", response_model=FinancingResponse)
async def check_delinquency(
    financing_id: str,
    request: Request,
    session=Depends(get_session),
    internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
):
    if not internal_api_key:
        raise AuthorizationError("Internal API key required")
    service = CollectionService(session)
    financing = await service.handle_delinquency(financing_id)
    await session.commit()
    return financing_to_response(financing)


@router.post("/financings/{financing_id}/collection_plan", response_model=Dict[str, Any])
async def create_collection_plan(
    financing_id: str,
    request: Request,
    data: Dict[str, Any],
    session=Depends(get_session),
    internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
):
    if not internal_api_key:
        raise AuthorizationError("Internal API key required")
    service = CollectionService(session)
    plan = await service.set_up_plan(
        financing_id=financing_id,
        plan_type=data.get("plan_type", "modified_payment"),
        modified_payment_amount=data.get("modified_payment_amount"),
        payment_frequency=data.get("payment_frequency", "monthly"),
        duration_months=data.get("duration_months"),
        waive_late_fees=data.get("waive_late_fees", False),
        freeze_interest=data.get("freeze_interest", False),
        notes=data.get("notes"),
        created_by=data.get("created_by"),
    )
    await session.commit()
    return {
        "id": plan.id,
        "object": "collection_plan",
        "financing_id": plan.financing_id,
        "account_id": plan.account_id,
        "status": plan.status,
        "plan_type": plan.plan_type,
        "original_payment_amount": plan.original_payment_amount,
        "modified_payment_amount": plan.modified_payment_amount,
        "payment_frequency": plan.payment_frequency,
        "start_date": plan.start_date.isoformat(),
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
        "interest_frozen": plan.interest_frozen,
    }


@router.get("/delinquent_financings")
async def list_delinquent_financings(
    request: Request,
    min_days_past_due: int = Query(default=30, ge=1, description="Minimum days past due"),
    limit: int = Query(default=100, ge=1, le=500),
    session=Depends(get_session),
    internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
):
    if not internal_api_key:
        raise AuthorizationError("Internal API key required")
    service = CollectionService(session)
    financings = await service.get_delinquent_financings(
        min_days_past_due=min_days_past_due,
        limit=limit,
    )
    return {
        "object": "list",
        "data": [
            {
                "id": f.id,
                "account_id": f.account_id,
                "outstanding_balance": f.outstanding_balance,
                "next_payment_date": f.next_payment_date.isoformat() if f.next_payment_date else None,
                "delinquency_status": f.delinquency_status,
            }
            for f in financings
        ],
        "count": len(financings),
    }
