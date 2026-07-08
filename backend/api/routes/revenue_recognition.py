from typing import Any, Dict, List, Optional
from datetime import date, datetime
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from decimal import Decimal

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class ScheduleCreateRequest(BaseModel):
    transaction_id: str = Field(..., description="Transaction ID")
    total_amount: int = Field(..., gt=0, description="Total amount in cents")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    start_date: str = Field(..., description="Recognition start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Recognition end date (YYYY-MM-DD)")
    recognition_method: str = Field(default="straight_line", description="Recognition method")
    customer_id: Optional[str] = Field(default=None, description="Customer ID")
    contract_id: Optional[str] = Field(default=None, description="Contract ID")
    performance_obligation_id: Optional[str] = Field(default=None, description="Performance obligation ID")
    performance_obligation_description: Optional[str] = Field(default=None, description="Performance obligation description")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata")


class ScheduleAdjustRequest(BaseModel):
    adjustment_amount: int = Field(..., description="Adjustment amount in cents")
    reason: str = Field(..., description="Reason for adjustment")
    new_end_date: Optional[str] = Field(default=None, description="New end date (YYYY-MM-DD)")


class ScheduleRecognizeRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount to recognize")
    period_id: Optional[str] = Field(default=None, description="Period ID")
    journal_entry_id: Optional[str] = Field(default=None, description="Journal entry ID")


class ScheduleResponse(BaseModel):
    id: str
    object: str = "recognition.schedule"
    transaction_id: str
    account_id: Optional[str] = None
    customer_id: Optional[str] = None
    total_amount: int
    currency: str
    recognized_amount: int
    deferred_amount: int
    start_date: str
    end_date: str
    status: str
    recognition_method: str
    contract_id: Optional[str] = None
    performance_obligation_id: Optional[str] = None
    total_periods: int
    recognized_periods: int
    adjustment_count: int
    last_recognition_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str
    metadata: Optional[Dict[str, str]] = None


class PeriodResponse(BaseModel):
    id: str
    object: str = "recognition.period"
    schedule_id: str
    period_number: int
    period_start: str
    period_end: str
    amount_to_recognize: int
    recognized_amount: int
    status: str
    recognized_at: Optional[str] = None
    journal_entry_id: Optional[str] = None


class PeriodRecognizeRequest(BaseModel):
    amount: Optional[int] = Field(default=None, description="Amount to recognize")
    journal_entry_id: Optional[str] = Field(default=None, description="Journal entry ID")


class DeferredRevenueResponse(BaseModel):
    id: str
    object: str = "recognition.deferred_revenue"
    account_id: str
    amount: int
    original_amount: int
    currency: str
    source_type: str
    source_id: str
    schedule_id: Optional[str] = None
    expected_recognition_date: Optional[str] = None
    status: str
    recognized_amount: int
    remaining_amount: int
    created_at: str
    metadata: Optional[Dict[str, str]] = None


class DeferredSummaryResponse(BaseModel):
    account_id: str
    currency: str
    total_deferred: int
    total_recognized: int
    pending_recognition: int
    by_period: List[Dict[str, Any]]
    by_source: List[Dict[str, Any]]


class AllocationCreateRequest(BaseModel):
    transaction_id: str = Field(..., description="Transaction ID")
    total_amount: int = Field(..., gt=0, description="Total amount in cents")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    products: List[Dict[str, Any]] = Field(..., description="Products to allocate")
    bundle_id: Optional[str] = Field(default=None, description="Bundle ID")
    schedule_id: Optional[str] = Field(default=None, description="Schedule ID")
    allocation_method: str = Field(default="standalone_price", description="Allocation method")


class AllocationResponse(BaseModel):
    id: str
    object: str = "recognition.allocation"
    transaction_id: str
    schedule_id: Optional[str] = None
    product_id: str
    performance_obligation_id: Optional[str] = None
    allocated_amount: int
    fair_value: int
    standalone_price: int
    discount_allocation: int
    allocation_percentage: float
    allocation_method: str
    currency: str
    bundle_id: Optional[str] = None
    created_at: str


class RuleCreateRequest(BaseModel):
    product_id: str = Field(..., description="Product ID")
    recognition_trigger: str = Field(default="over_time", description="Recognition trigger")
    recognition_period_days: int = Field(default=30, ge=1, description="Recognition period days")
    milestone_based: bool = Field(default=False, description="Milestone based recognition")
    recognition_method: str = Field(default="straight_line", description="Recognition method")
    revenue_account_code: Optional[str] = Field(default=None, description="Revenue account code")
    deferred_account_code: Optional[str] = Field(default=None, description="Deferred account code")
    auto_recognize: bool = Field(default=False, description="Auto recognize")
    recognition_frequency: str = Field(default="monthly", description="Recognition frequency")


class RuleResponse(BaseModel):
    id: str
    object: str = "recognition.rule"
    product_id: str
    recognition_trigger: str
    recognition_period_days: int
    milestone_based: bool
    recognition_method: str
    revenue_account_code: Optional[str] = None
    deferred_account_code: Optional[str] = None
    auto_recognize: bool
    recognition_frequency: str
    is_active: bool
    created_at: str


class MilestoneCreateRequest(BaseModel):
    schedule_id: str = Field(..., description="Schedule ID")
    name: str = Field(..., description="Milestone name")
    amount: int = Field(..., gt=0, description="Milestone amount")
    due_date: Optional[str] = Field(default=None, description="Due date (YYYY-MM-DD)")
    description: Optional[str] = Field(default=None, description="Milestone description")
    sequence: int = Field(default=0, description="Milestone sequence")


class MilestoneResponse(BaseModel):
    id: str
    object: str = "recognition.milestone"
    schedule_id: str
    name: str
    description: Optional[str] = None
    amount: int
    percentage: Optional[float] = None
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    status: str
    sequence: int
    journal_entry_id: Optional[str] = None
    created_at: str


class RecognitionResultResponse(BaseModel):
    schedule_id: str
    amount_recognized: int
    total_recognized: int
    remaining_deferred: int
    period_id: Optional[str] = None
    journal_entry_id: Optional[str] = None


def _get_account_id(request: Request) -> Optional[str]:
    return getattr(request.state, "account_id", None)


def _generate_id(prefix: str) -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{prefix}_{random_part}"


def _parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


@router.post("/schedules", response_model=ScheduleResponse, status_code=201)
async def create_schedule(
    request: Request,
    data: ScheduleCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import ScheduleService
    
    account_id = _get_account_id(request)
    service = ScheduleService(session)
    
    schedule = await service.create(
        transaction_id=data.transaction_id,
        total_amount=data.total_amount,
        currency=data.currency,
        start_date=_parse_date(data.start_date),
        end_date=_parse_date(data.end_date),
        recognition_method=data.recognition_method,
        account_id=account_id,
        customer_id=data.customer_id,
        contract_id=data.contract_id,
        performance_obligation_id=data.performance_obligation_id,
        performance_obligation_description=data.performance_obligation_description,
        metadata=data.metadata,
    )
    
    return ScheduleResponse(
        id=schedule.id,
        transaction_id=schedule.transaction_id,
        account_id=schedule.account_id,
        customer_id=schedule.customer_id,
        total_amount=schedule.total_amount,
        currency=schedule.currency,
        recognized_amount=schedule.recognized_amount,
        deferred_amount=schedule.deferred_amount,
        start_date=schedule.start_date.isoformat(),
        end_date=schedule.end_date.isoformat(),
        status=schedule.status.value,
        recognition_method=schedule.recognition_method.value,
        contract_id=schedule.contract_id,
        performance_obligation_id=schedule.performance_obligation_id,
        total_periods=schedule.total_periods,
        recognized_periods=schedule.recognized_periods,
        adjustment_count=schedule.adjustment_count,
        last_recognition_at=schedule.last_recognition_at.isoformat() if schedule.last_recognition_at else None,
        completed_at=schedule.completed_at.isoformat() if schedule.completed_at else None,
        created_at=schedule.created_at.isoformat(),
        metadata=schedule.metadata_,
    )


@router.get("/schedules", response_model=PaginatedResponse[ScheduleResponse])
async def list_schedules(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    transaction_id: Optional[str] = None,
    contract_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import ScheduleService
    
    account_id = _get_account_id(request)
    service = ScheduleService(session)
    
    schedules = await service.list(
        account_id=account_id,
        transaction_id=transaction_id,
        contract_id=contract_id,
        status=status,
        start_date=_parse_date(start_date) if start_date else None,
        end_date=_parse_date(end_date) if end_date else None,
        limit=limit + 1,
    )
    
    has_more = len(schedules) > limit
    if has_more:
        schedules = schedules[:limit]
    
    data = [
        ScheduleResponse(
            id=s.id,
            transaction_id=s.transaction_id,
            account_id=s.account_id,
            customer_id=s.customer_id,
            total_amount=s.total_amount,
            currency=s.currency,
            recognized_amount=s.recognized_amount,
            deferred_amount=s.deferred_amount,
            start_date=s.start_date.isoformat(),
            end_date=s.end_date.isoformat(),
            status=s.status.value,
            recognition_method=s.recognition_method.value,
            contract_id=s.contract_id,
            performance_obligation_id=s.performance_obligation_id,
            total_periods=s.total_periods,
            recognized_periods=s.recognized_periods,
            adjustment_count=s.adjustment_count,
            last_recognition_at=s.last_recognition_at.isoformat() if s.last_recognition_at else None,
            completed_at=s.completed_at.isoformat() if s.completed_at else None,
            created_at=s.created_at.isoformat(),
            metadata=s.metadata_,
        )
        for s in schedules
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import ScheduleService
    
    service = ScheduleService(session)
    schedule = await service.get(schedule_id)
    
    if not schedule:
        raise NotFoundError(f"Schedule {schedule_id} not found")
    
    return ScheduleResponse(
        id=schedule.id,
        transaction_id=schedule.transaction_id,
        account_id=schedule.account_id,
        customer_id=schedule.customer_id,
        total_amount=schedule.total_amount,
        currency=schedule.currency,
        recognized_amount=schedule.recognized_amount,
        deferred_amount=schedule.deferred_amount,
        start_date=schedule.start_date.isoformat(),
        end_date=schedule.end_date.isoformat(),
        status=schedule.status.value,
        recognition_method=schedule.recognition_method.value,
        contract_id=schedule.contract_id,
        performance_obligation_id=schedule.performance_obligation_id,
        total_periods=schedule.total_periods,
        recognized_periods=schedule.recognized_periods,
        adjustment_count=schedule.adjustment_count,
        last_recognition_at=schedule.last_recognition_at.isoformat() if schedule.last_recognition_at else None,
        completed_at=schedule.completed_at.isoformat() if schedule.completed_at else None,
        created_at=schedule.created_at.isoformat(),
        metadata=schedule.metadata_,
    )


@router.post("/schedules/{schedule_id}/adjust", response_model=ScheduleResponse)
async def adjust_schedule(
    schedule_id: str,
    data: ScheduleAdjustRequest,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import ScheduleService
    
    service = ScheduleService(session)
    
    new_end_date = None
    if data.new_end_date:
        new_end_date = _parse_date(data.new_end_date)
    
    schedule = await service.adjust(
        schedule_id=schedule_id,
        adjustment_amount=data.adjustment_amount,
        reason=data.reason,
        new_end_date=new_end_date,
    )
    
    return ScheduleResponse(
        id=schedule.id,
        transaction_id=schedule.transaction_id,
        account_id=schedule.account_id,
        customer_id=schedule.customer_id,
        total_amount=schedule.total_amount,
        currency=schedule.currency,
        recognized_amount=schedule.recognized_amount,
        deferred_amount=schedule.deferred_amount,
        start_date=schedule.start_date.isoformat(),
        end_date=schedule.end_date.isoformat(),
        status=schedule.status.value,
        recognition_method=schedule.recognition_method.value,
        contract_id=schedule.contract_id,
        performance_obligation_id=schedule.performance_obligation_id,
        total_periods=schedule.total_periods,
        recognized_periods=schedule.recognized_periods,
        adjustment_count=schedule.adjustment_count,
        last_recognition_at=schedule.last_recognition_at.isoformat() if schedule.last_recognition_at else None,
        completed_at=schedule.completed_at.isoformat() if schedule.completed_at else None,
        created_at=schedule.created_at.isoformat(),
        metadata=schedule.metadata_,
    )


@router.post("/schedules/{schedule_id}/recognize", response_model=RecognitionResultResponse)
async def recognize_schedule(
    schedule_id: str,
    data: ScheduleRecognizeRequest,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import ScheduleService
    
    service = ScheduleService(session)
    
    result = await service.recognize(
        schedule_id=schedule_id,
        amount=data.amount,
        period_id=data.period_id,
        journal_entry_id=data.journal_entry_id,
    )
    
    return RecognitionResultResponse(
        schedule_id=result.schedule_id,
        amount_recognized=result.amount_recognized,
        total_recognized=result.total_recognized,
        remaining_deferred=result.remaining_deferred,
        period_id=result.period_id,
        journal_entry_id=result.journal_entry_id,
    )


@router.get("/periods", response_model=PaginatedResponse[PeriodResponse])
async def list_periods(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    schedule_id: Optional[str] = None,
    status: Optional[str] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import PeriodService
    
    service = PeriodService(session)
    
    periods = await service.list(
        schedule_id=schedule_id,
        status=status,
        period_start=_parse_date(period_start) if period_start else None,
        period_end=_parse_date(period_end) if period_end else None,
        limit=limit + 1,
    )
    
    has_more = len(periods) > limit
    if has_more:
        periods = periods[:limit]
    
    data = [
        PeriodResponse(
            id=p.id,
            schedule_id=p.schedule_id,
            period_number=p.period_number,
            period_start=p.period_start.isoformat(),
            period_end=p.period_end.isoformat(),
            amount_to_recognize=p.amount_to_recognize,
            recognized_amount=p.recognized_amount,
            status=p.status.value,
            recognized_at=p.recognized_at.isoformat() if p.recognized_at else None,
            journal_entry_id=p.journal_entry_id,
        )
        for p in periods
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/periods/{period_id}/recognize", response_model=PeriodResponse)
async def recognize_period(
    period_id: str,
    data: PeriodRecognizeRequest,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import PeriodService
    
    service = PeriodService(session)
    
    period = await service.recognize_period(
        period_id=period_id,
        amount=data.amount,
        journal_entry_id=data.journal_entry_id,
    )
    
    return PeriodResponse(
        id=period.id,
        schedule_id=period.schedule_id,
        period_number=period.period_number,
        period_start=period.period_start.isoformat(),
        period_end=period.period_end.isoformat(),
        amount_to_recognize=period.amount_to_recognize,
        recognized_amount=period.recognized_amount,
        status=period.status.value,
        recognized_at=period.recognized_at.isoformat() if period.recognized_at else None,
        journal_entry_id=period.journal_entry_id,
    )


@router.get("/deferred", response_model=PaginatedResponse[DeferredRevenueResponse])
async def list_deferred(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    source_type: Optional[str] = None,
    expected_before: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import DeferredRevenueService
    
    account_id = _get_account_id(request)
    service = DeferredRevenueService(session)
    
    deferred_items = await service.list(
        account_id=account_id,
        status=status,
        source_type=source_type,
        expected_before=_parse_date(expected_before) if expected_before else None,
        limit=limit + 1,
    )
    
    has_more = len(deferred_items) > limit
    if has_more:
        deferred_items = deferred_items[:limit]
    
    data = [
        DeferredRevenueResponse(
            id=d.id,
            account_id=d.account_id,
            amount=d.amount,
            original_amount=d.original_amount,
            currency=d.currency,
            source_type=d.source_type,
            source_id=d.source_id,
            schedule_id=d.schedule_id,
            expected_recognition_date=d.expected_recognition_date.isoformat() if d.expected_recognition_date else None,
            status=d.status.value,
            recognized_amount=d.recognized_amount,
            remaining_amount=d.remaining_amount,
            created_at=d.created_at.isoformat(),
            metadata=d.metadata_,
        )
        for d in deferred_items
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/deferred_summary", response_model=DeferredSummaryResponse)
async def get_deferred_summary(
    request: Request,
    currency: Optional[str] = None,
    as_of_date: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import DeferredRevenueService
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    service = DeferredRevenueService(session)
    
    report = await service.report(
        account_id=account_id,
        currency=currency,
        as_of_date=_parse_date(as_of_date) if as_of_date else None,
    )
    
    return DeferredSummaryResponse(
        account_id=report.account_id,
        currency=report.currency,
        total_deferred=report.total_deferred,
        total_recognized=report.total_recognized,
        pending_recognition=report.pending_recognition,
        by_period=report.by_period,
        by_source=report.by_source,
    )


@router.post("/allocations", response_model=Dict[str, Any], status_code=201)
async def create_allocation(
    request: Request,
    data: AllocationCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import AllocationService
    
    service = AllocationService(session)
    
    result = await service.allocate_transaction(
        transaction_id=data.transaction_id,
        total_amount=data.total_amount,
        currency=data.currency,
        products=data.products,
        bundle_id=data.bundle_id,
        schedule_id=data.schedule_id,
        allocation_method=data.allocation_method,
    )
    
    return {
        "transaction_id": result.transaction_id,
        "total_amount": result.total_amount,
        "allocations": result.allocations,
    }


@router.get("/allocations", response_model=PaginatedResponse[AllocationResponse])
async def list_allocations(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    transaction_id: Optional[str] = None,
    product_id: Optional[str] = None,
    schedule_id: Optional[str] = None,
    bundle_id: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import AllocationService
    
    service = AllocationService(session)
    
    allocations = await service.list(
        transaction_id=transaction_id,
        product_id=product_id,
        schedule_id=schedule_id,
        bundle_id=bundle_id,
        limit=limit + 1,
    )
    
    has_more = len(allocations) > limit
    if has_more:
        allocations = allocations[:limit]
    
    data = [
        AllocationResponse(
            id=a.id,
            transaction_id=a.transaction_id,
            schedule_id=a.schedule_id,
            product_id=a.product_id,
            performance_obligation_id=a.performance_obligation_id,
            allocated_amount=a.allocated_amount,
            fair_value=a.fair_value,
            standalone_price=a.standalone_price,
            discount_allocation=a.discount_allocation,
            allocation_percentage=float(a.allocation_percentage),
            allocation_method=a.allocation_method,
            currency=a.currency,
            bundle_id=a.bundle_id,
            created_at=a.created_at.isoformat(),
        )
        for a in allocations
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/rules", response_model=PaginatedResponse[RuleResponse])
async def list_rules(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    is_active: Optional[bool] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.revenue_recognition import RecognitionRule
    
    query = select(RecognitionRule)
    
    if is_active is not None:
        query = query.where(RecognitionRule.is_active == is_active)
    
    if starting_after:
        query = query.where(RecognitionRule.id > starting_after)
    
    query = query.order_by(RecognitionRule.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    rules = list(result.scalars().all())
    
    has_more = len(rules) > limit
    if has_more:
        rules = rules[:limit]
    
    data = [
        RuleResponse(
            id=r.id,
            product_id=r.product_id,
            recognition_trigger=r.recognition_trigger.value,
            recognition_period_days=r.recognition_period_days,
            milestone_based=r.milestone_based,
            recognition_method=r.recognition_method.value,
            revenue_account_code=r.revenue_account_code,
            deferred_account_code=r.deferred_account_code,
            auto_recognize=r.auto_recognize,
            recognition_frequency=r.recognition_frequency,
            is_active=r.is_active,
            created_at=r.created_at.isoformat(),
        )
        for r in rules
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/rules", response_model=RuleResponse, status_code=201)
async def create_rule(
    request: Request,
    data: RuleCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.revenue_recognition import (
        RecognitionRule, RecognitionTrigger, RecognitionMethod
    )
    
    trigger = RecognitionTrigger.OVER_TIME
    if data.recognition_trigger == "at_sale":
        trigger = RecognitionTrigger.AT_SALE
    elif data.recognition_trigger == "upon_delivery":
        trigger = RecognitionTrigger.UPON_DELIVERY
    
    method = RecognitionMethod.STRAIGHT_LINE
    if data.recognition_method == "performance":
        method = RecognitionMethod.PERFORMANCE
    elif data.recognition_method == "usage":
        method = RecognitionMethod.USAGE
    
    rule = RecognitionRule(
        id=_generate_id("rr"),
        product_id=data.product_id,
        recognition_trigger=trigger,
        recognition_period_days=data.recognition_period_days,
        milestone_based=data.milestone_based,
        recognition_method=method,
        revenue_account_code=data.revenue_account_code,
        deferred_account_code=data.deferred_account_code,
        auto_recognize=data.auto_recognize,
        recognition_frequency=data.recognition_frequency,
    )
    
    session.add(rule)
    await session.flush()
    
    return RuleResponse(
        id=rule.id,
        product_id=rule.product_id,
        recognition_trigger=rule.recognition_trigger.value,
        recognition_period_days=rule.recognition_period_days,
        milestone_based=rule.milestone_based,
        recognition_method=rule.recognition_method.value,
        revenue_account_code=rule.revenue_account_code,
        deferred_account_code=rule.deferred_account_code,
        auto_recognize=rule.auto_recognize,
        recognition_frequency=rule.recognition_frequency,
        is_active=rule.is_active,
        created_at=rule.created_at.isoformat(),
    )


@router.post("/milestones/{milestone_id}/complete", response_model=MilestoneResponse)
async def complete_milestone(
    milestone_id: str,
    request: Request,
    journal_entry_id: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.revenue_recognition_service import MilestoneService
    
    service = MilestoneService(session)
    
    milestone = await service.complete(
        milestone_id=milestone_id,
        journal_entry_id=journal_entry_id,
    )
    
    return MilestoneResponse(
        id=milestone.id,
        schedule_id=milestone.schedule_id,
        name=milestone.name,
        description=milestone.description,
        amount=milestone.amount,
        percentage=float(milestone.percentage) if milestone.percentage else None,
        due_date=milestone.due_date.isoformat() if milestone.due_date else None,
        completed_at=milestone.completed_at.isoformat() if milestone.completed_at else None,
        status=milestone.status.value,
        sequence=milestone.sequence,
        journal_entry_id=milestone.journal_entry_id,
        created_at=milestone.created_at.isoformat(),
    )
