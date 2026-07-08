from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from decimal import Decimal

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, UsageError

router = APIRouter()


class UsageRecordCreateRequest(BaseModel):
    subscription_item_id: str = Field(..., description="Subscription item ID")
    quantity: int = Field(..., description="Usage quantity")
    timestamp: Optional[int] = Field(default=None, description="Unix timestamp (defaults to now)")
    action: str = Field(default="increment", description="Action: increment or set")
    idempotency_key: Optional[str] = Field(default=None, max_length=100, description="Idempotency key")
    period_start: Optional[int] = Field(default=None, description="Period start timestamp")
    period_end: Optional[int] = Field(default=None, description="Period end timestamp")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata")


class UsageRecordResponse(BaseModel):
    id: str
    object: str = "usage_record"
    subscription_item_id: str
    quantity: int
    timestamp: int
    action: str
    idempotency_key: Optional[str] = None
    period_start: int
    period_end: int
    status: str
    invoice_id: Optional[str] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class UsageRecordSummaryResponse(BaseModel):
    id: str
    object: str = "usage_record_summary"
    subscription_item_id: str
    period_start: int
    period_end: int
    total_usage: int
    invoice_usage: int
    period_count: int
    last_usage_record_id: Optional[str] = None
    aggregated_values: Optional[Dict[str, Any]] = None
    created: int
    livemode: bool = False


class MeterCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Meter name")
    display_name: Optional[str] = Field(default=None, max_length=200, description="Display name")
    aggregation_type: str = Field(default="sum", description="Aggregation type: sum, max, or last")
    unit_label: Optional[str] = Field(default=None, max_length=50, description="Unit label")
    reset_period: str = Field(default="monthly", description="Reset period: never, daily, weekly, monthly, yearly")
    default_price_per_unit: Optional[Decimal] = Field(default=None, description="Default price per unit")
    event_name: Optional[str] = Field(default=None, max_length=100, description="Event name filter")
    value_property: Optional[str] = Field(default=None, description="Value property path")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata")


class MeterUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)
    default_price_per_unit: Optional[Decimal] = Field(default=None)
    status: Optional[str] = Field(default=None)


class MeterResponse(BaseModel):
    id: str
    object: str = "meter"
    account_id: str
    name: str
    display_name: Optional[str] = None
    aggregation_type: str
    unit_label: Optional[str] = None
    reset_period: str
    default_price_per_unit: Optional[Decimal] = None
    status: str
    event_name: Optional[str] = None
    customer_mapping: Optional[Dict[str, Any]] = None
    value_property: Optional[str] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class MeterEventCreateRequest(BaseModel):
    customer_id: Optional[str] = Field(default=None, description="Customer ID")
    subscription_id: Optional[str] = Field(default=None, description="Subscription ID")
    value: Decimal = Field(..., description="Event value")
    timestamp: Optional[int] = Field(default=None, description="Event timestamp")
    event_name: Optional[str] = Field(default=None, description="Event name")
    properties: Optional[Dict[str, Any]] = Field(default=None, description="Event properties")
    identifier: Optional[str] = Field(default=None, description="Unique identifier for idempotency")


class MeterEventResponse(BaseModel):
    id: str
    object: str = "meter_event"
    meter_id: str
    customer_id: Optional[str] = None
    subscription_id: Optional[str] = None
    value: Decimal
    timestamp: int
    event_name: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    identifier: Optional[str] = None
    status: str
    processed_at: Optional[int] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class MeterEventAdjustmentCreateRequest(BaseModel):
    adjustment_type: str = Field(..., description="Adjustment type: credit or debit")
    amount: Decimal = Field(..., description="Adjustment amount")
    reason: Optional[str] = Field(default=None, max_length=500, description="Adjustment reason")


class MeterEventAdjustmentResponse(BaseModel):
    id: str
    object: str = "meter_event_adjustment"
    meter_event_id: str
    adjustment_type: str
    amount: Decimal
    reason: Optional[str] = None
    status: str
    created: int
    livemode: bool = False


class MeterPriceTierCreateRequest(BaseModel):
    up_to: Optional[int] = Field(default=None, description="Upper limit for this tier")
    unit_amount: Decimal = Field(..., description="Price per unit")
    flat_amount: Optional[int] = Field(default=None, description="Flat fee amount")
    tier_type: str = Field(default="volume", description="Tier type: volume or graduated")


class MeterPriceTierResponse(BaseModel):
    id: str
    object: str = "meter_price_tier"
    meter_id: str
    price_id: Optional[str] = None
    up_to: Optional[int] = None
    unit_amount: Decimal
    flat_amount: Optional[int] = None
    tier_type: str
    created: int
    livemode: bool = False


class MeterUsageResponse(BaseModel):
    meter_id: str
    customer_id: Optional[str] = None
    period_start: int
    period_end: int
    total_value: Decimal
    event_count: int
    aggregated_value: Decimal
    aggregation_type: str


class UsageAlertCreateRequest(BaseModel):
    subscription_item_id: str = Field(..., description="Subscription item ID")
    threshold: int = Field(..., description="Usage threshold")
    notification_emails: Optional[List[str]] = Field(default=None, description="Notification emails")
    webhook_url: Optional[str] = Field(default=None, max_length=500, description="Webhook URL")


class UsageAlertResponse(BaseModel):
    id: str
    object: str = "usage_alert"
    subscription_item_id: str
    threshold: int
    notification_emails: Optional[List[str]] = None
    triggered_at: Optional[int] = None
    current_usage: int
    status: str
    webhook_url: Optional[str] = None
    created: int
    livemode: bool = False


class UsageSummaryRequest(BaseModel):
    subscription_item_id: str
    period_start: int
    period_end: int
    aggregation_type: Optional[str] = Field(default="sum")


class UsageSummaryResponse(BaseModel):
    subscription_item_id: str
    period_start: int
    period_end: int
    total_usage: int
    period_count: int
    aggregation_type: str
    breakdown: Optional[List[Dict[str, Any]]] = None


class UsageReportResponse(BaseModel):
    id: str
    object: str = "usage_report"
    subscription_id: str
    period_start: int
    period_end: int
    usage_summary: Optional[Dict[str, Any]] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    total_usage: int
    total_amount: int
    currency: str
    status: str
    generated_at: Optional[int] = None
    created: int
    livemode: bool = False


def _get_account_id(request: Request) -> Optional[str]:
    return getattr(request.state, "account_id", None)


def _generate_id(prefix: str) -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{prefix}_{random_part}"


def _get_timestamp() -> int:
    import time
    return int(time.time())


@router.post("/usage_records", response_model=UsageRecordResponse, status_code=201)
async def create_usage_record(
    request: Request,
    data: UsageRecordCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.usage import (
        UsageRecord, UsageRecordAction, UsageRecordStatus
    )
    from sqlalchemy import select
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    if data.idempotency_key:
        existing_query = select(UsageRecord).where(
            UsageRecord.idempotency_key == data.idempotency_key
        )
        existing_result = await session.execute(existing_query)
        existing_record = existing_result.scalar_one_or_none()
        if existing_record:
            return UsageRecordResponse(
                id=existing_record.id,
                subscription_item_id=existing_record.subscription_item_id,
                quantity=existing_record.quantity,
                timestamp=existing_record.timestamp,
                action=existing_record.action.value,
                idempotency_key=existing_record.idempotency_key,
                period_start=existing_record.period_start,
                period_end=existing_record.period_end,
                status=existing_record.status.value,
                invoice_id=existing_record.invoice_id,
                created=existing_record.created,
                metadata=existing_record.metadata_,
            )
    
    action = UsageRecordAction.INCREMENT
    if data.action == "set":
        action = UsageRecordAction.SET
    
    timestamp = data.timestamp or _get_timestamp()
    period_start = data.period_start or timestamp
    period_end = data.period_end or (timestamp + 2592000)
    
    record_id = _generate_id("ur")
    created_ts = _get_timestamp()
    
    usage_record = UsageRecord(
        id=record_id,
        subscription_item_id=data.subscription_item_id,
        quantity=data.quantity,
        timestamp=timestamp,
        action=action,
        idempotency_key=data.idempotency_key,
        period_start=period_start,
        period_end=period_end,
        status=UsageRecordStatus.PENDING,
        created=created_ts,
        metadata_=data.metadata,
    )
    
    session.add(usage_record)
    await session.flush()
    
    return UsageRecordResponse(
        id=usage_record.id,
        subscription_item_id=usage_record.subscription_item_id,
        quantity=usage_record.quantity,
        timestamp=usage_record.timestamp,
        action=usage_record.action.value,
        idempotency_key=usage_record.idempotency_key,
        period_start=usage_record.period_start,
        period_end=usage_record.period_end,
        status=usage_record.status.value,
        invoice_id=usage_record.invoice_id,
        created=usage_record.created,
        metadata=usage_record.metadata_,
    )


@router.get("/usage_records", response_model=PaginatedResponse[UsageRecordResponse])
async def list_usage_records(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    subscription_item_id: Optional[str] = None,
    status: Optional[str] = None,
    period_start: Optional[int] = None,
    period_end: Optional[int] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import UsageRecord
    
    query = select(UsageRecord)
    
    if subscription_item_id:
        query = query.where(UsageRecord.subscription_item_id == subscription_item_id)
    if status:
        query = query.where(UsageRecord.status == status)
    if period_start:
        query = query.where(UsageRecord.period_start >= period_start)
    if period_end:
        query = query.where(UsageRecord.period_end <= period_end)
    if starting_after:
        query = query.where(UsageRecord.id > starting_after)
    
    query = query.order_by(UsageRecord.timestamp.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    records = list(result.scalars().all())
    
    has_more = len(records) > limit
    if has_more:
        records = records[:limit]
    
    data = [
        UsageRecordResponse(
            id=r.id,
            subscription_item_id=r.subscription_item_id,
            quantity=r.quantity,
            timestamp=r.timestamp,
            action=r.action.value,
            idempotency_key=r.idempotency_key,
            period_start=r.period_start,
            period_end=r.period_end,
            status=r.status.value,
            invoice_id=r.invoice_id,
            created=r.created,
            metadata=r.metadata_,
        )
        for r in records
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/usage_records/{usage_record_id}", response_model=UsageRecordResponse)
async def get_usage_record(
    usage_record_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import UsageRecord
    
    query = select(UsageRecord).where(UsageRecord.id == usage_record_id)
    result = await session.execute(query)
    record = result.scalar_one_or_none()
    
    if not record:
        raise NotFoundError(f"Usage record {usage_record_id} not found")
    
    return UsageRecordResponse(
        id=record.id,
        subscription_item_id=record.subscription_item_id,
        quantity=record.quantity,
        timestamp=record.timestamp,
        action=record.action.value,
        idempotency_key=record.idempotency_key,
        period_start=record.period_start,
        period_end=record.period_end,
        status=record.status.value,
        invoice_id=record.invoice_id,
        created=record.created,
        metadata=record.metadata_,
    )


@router.delete("/usage_records/{usage_record_id}")
async def delete_usage_record(
    usage_record_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import UsageRecord, UsageRecordStatus
    
    query = select(UsageRecord).where(UsageRecord.id == usage_record_id)
    result = await session.execute(query)
    record = result.scalar_one_or_none()
    
    if not record:
        raise NotFoundError(f"Usage record {usage_record_id} not found")
    
    if record.status == UsageRecordStatus.INVOICED:
        raise UsageError(
            "Cannot delete usage record that has been invoiced",
            usage_record_id=usage_record_id,
        )
    
    record.status = UsageRecordStatus.CANCELED
    await session.flush()
    
    return {"id": record.id, "deleted": True}


@router.post("/usage_records/summary", response_model=UsageSummaryResponse)
async def get_usage_summary(
    request: Request,
    data: UsageSummaryRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select, func
    from payment_platform.backend.domain.usage import UsageRecord, UsageRecordStatus
    
    query = select(
        func.sum(UsageRecord.quantity).label("total_usage"),
        func.count(UsageRecord.id).label("period_count"),
    ).where(
        UsageRecord.subscription_item_id == data.subscription_item_id,
        UsageRecord.period_start >= data.period_start,
        UsageRecord.period_end <= data.period_end,
        UsageRecord.status != UsageRecordStatus.CANCELED,
    )
    
    result = await session.execute(query)
    row = result.one()
    
    total_usage = row.total_usage or 0
    period_count = row.period_count or 0
    
    breakdown_query = select(
        UsageRecord.timestamp,
        UsageRecord.quantity,
        UsageRecord.action,
    ).where(
        UsageRecord.subscription_item_id == data.subscription_item_id,
        UsageRecord.period_start >= data.period_start,
        UsageRecord.period_end <= data.period_end,
        UsageRecord.status != UsageRecordStatus.CANCELED,
    ).order_by(UsageRecord.timestamp)
    
    breakdown_result = await session.execute(breakdown_query)
    breakdown = [
        {
            "timestamp": r.timestamp,
            "quantity": r.quantity,
            "action": r.action.value,
        }
        for r in breakdown_result
    ]
    
    return UsageSummaryResponse(
        subscription_item_id=data.subscription_item_id,
        period_start=data.period_start,
        period_end=data.period_end,
        total_usage=total_usage,
        period_count=period_count,
        aggregation_type=data.aggregation_type,
        breakdown=breakdown,
    )


@router.post("/meters", response_model=MeterResponse, status_code=201)
async def create_meter(
    request: Request,
    data: MeterCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.usage import Meter, AggregationType, ResetPeriod
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    aggregation_type = AggregationType.SUM
    if data.aggregation_type == "max":
        aggregation_type = AggregationType.MAX
    elif data.aggregation_type == "last":
        aggregation_type = AggregationType.LAST
    
    reset_period = ResetPeriod.MONTHLY
    if data.reset_period == "never":
        reset_period = ResetPeriod.NEVER
    elif data.reset_period == "daily":
        reset_period = ResetPeriod.DAILY
    elif data.reset_period == "weekly":
        reset_period = ResetPeriod.WEEKLY
    elif data.reset_period == "yearly":
        reset_period = ResetPeriod.YEARLY
    
    meter_id = _generate_id("meter")
    timestamp = _get_timestamp()
    
    meter = Meter(
        id=meter_id,
        account_id=account_id,
        name=data.name,
        display_name=data.display_name,
        aggregation_type=aggregation_type,
        unit_label=data.unit_label,
        reset_period=reset_period,
        default_price_per_unit=data.default_price_per_unit,
        event_name=data.event_name,
        value_property=data.value_property,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(meter)
    await session.flush()
    
    return MeterResponse(
        id=meter.id,
        account_id=meter.account_id,
        name=meter.name,
        display_name=meter.display_name,
        aggregation_type=meter.aggregation_type.value,
        unit_label=meter.unit_label,
        reset_period=meter.reset_period.value,
        default_price_per_unit=meter.default_price_per_unit,
        status=meter.status,
        event_name=meter.event_name,
        customer_mapping=meter.customer_mapping,
        value_property=meter.value_property,
        created=meter.created,
        metadata=meter.metadata_,
    )


@router.get("/meters", response_model=PaginatedResponse[MeterResponse])
async def list_meters(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    name: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import Meter
    
    account_id = _get_account_id(request)
    
    query = select(Meter)
    
    if account_id:
        query = query.where(Meter.account_id == account_id)
    if status:
        query = query.where(Meter.status == status)
    if name:
        query = query.where(Meter.name.ilike(f"%{name}%"))
    if starting_after:
        query = query.where(Meter.id > starting_after)
    
    query = query.order_by(Meter.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    meters = list(result.scalars().all())
    
    has_more = len(meters) > limit
    if has_more:
        meters = meters[:limit]
    
    data = [
        MeterResponse(
            id=m.id,
            account_id=m.account_id,
            name=m.name,
            display_name=m.display_name,
            aggregation_type=m.aggregation_type.value,
            unit_label=m.unit_label,
            reset_period=m.reset_period.value,
            default_price_per_unit=m.default_price_per_unit,
            status=m.status,
            event_name=m.event_name,
            customer_mapping=m.customer_mapping,
            value_property=m.value_property,
            created=m.created,
            metadata=m.metadata_,
        )
        for m in meters
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/meters/{meter_id}", response_model=MeterResponse)
async def get_meter(
    meter_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import Meter
    
    query = select(Meter).where(Meter.id == meter_id)
    result = await session.execute(query)
    meter = result.scalar_one_or_none()
    
    if not meter:
        raise NotFoundError(f"Meter {meter_id} not found")
    
    return MeterResponse(
        id=meter.id,
        account_id=meter.account_id,
        name=meter.name,
        display_name=meter.display_name,
        aggregation_type=meter.aggregation_type.value,
        unit_label=meter.unit_label,
        reset_period=meter.reset_period.value,
        default_price_per_unit=meter.default_price_per_unit,
        status=meter.status,
        event_name=meter.event_name,
        customer_mapping=meter.customer_mapping,
        value_property=meter.value_property,
        created=meter.created,
        metadata=meter.metadata_,
    )


@router.put("/meters/{meter_id}", response_model=MeterResponse)
async def update_meter(
    meter_id: str,
    request: Request,
    data: MeterUpdateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import Meter
    
    query = select(Meter).where(Meter.id == meter_id)
    result = await session.execute(query)
    meter = result.scalar_one_or_none()
    
    if not meter:
        raise NotFoundError(f"Meter {meter_id} not found")
    
    if data.display_name is not None:
        meter.display_name = data.display_name
    if data.default_price_per_unit is not None:
        meter.default_price_per_unit = data.default_price_per_unit
    if data.status is not None:
        meter.status = data.status
    
    await session.flush()
    
    return MeterResponse(
        id=meter.id,
        account_id=meter.account_id,
        name=meter.name,
        display_name=meter.display_name,
        aggregation_type=meter.aggregation_type.value,
        unit_label=meter.unit_label,
        reset_period=meter.reset_period.value,
        default_price_per_unit=meter.default_price_per_unit,
        status=meter.status,
        event_name=meter.event_name,
        customer_mapping=meter.customer_mapping,
        value_property=meter.value_property,
        created=meter.created,
        metadata=meter.metadata_,
    )


@router.post("/meters/{meter_id}/events", response_model=MeterEventResponse, status_code=201)
async def create_meter_event(
    meter_id: str,
    request: Request,
    data: MeterEventCreateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import Meter, MeterEvent
    
    meter_query = select(Meter).where(Meter.id == meter_id)
    meter_result = await session.execute(meter_query)
    meter = meter_result.scalar_one_or_none()
    
    if not meter:
        raise NotFoundError(f"Meter {meter_id} not found")
    
    if data.identifier:
        existing_query = select(MeterEvent).where(
            MeterEvent.identifier == data.identifier
        )
        existing_result = await session.execute(existing_query)
        existing_event = existing_result.scalar_one_or_none()
        if existing_event:
            return MeterEventResponse(
                id=existing_event.id,
                meter_id=existing_event.meter_id,
                customer_id=existing_event.customer_id,
                subscription_id=existing_event.subscription_id,
                value=existing_event.value,
                timestamp=existing_event.timestamp,
                event_name=existing_event.event_name,
                properties=existing_event.properties,
                identifier=existing_event.identifier,
                status=existing_event.status,
                processed_at=existing_event.processed_at,
                created=existing_event.created,
                metadata=existing_event.metadata_,
            )
    
    timestamp = data.timestamp or _get_timestamp()
    event_id = _generate_id("me")
    created_ts = _get_timestamp()
    
    meter_event = MeterEvent(
        id=event_id,
        meter_id=meter_id,
        customer_id=data.customer_id,
        subscription_id=data.subscription_id,
        value=data.value,
        timestamp=timestamp,
        event_name=data.event_name or meter.event_name,
        properties=data.properties,
        identifier=data.identifier,
        processed_at=created_ts,
        created=created_ts,
    )
    
    session.add(meter_event)
    await session.flush()
    
    return MeterEventResponse(
        id=meter_event.id,
        meter_id=meter_event.meter_id,
        customer_id=meter_event.customer_id,
        subscription_id=meter_event.subscription_id,
        value=meter_event.value,
        timestamp=meter_event.timestamp,
        event_name=meter_event.event_name,
        properties=meter_event.properties,
        identifier=meter_event.identifier,
        status=meter_event.status,
        processed_at=meter_event.processed_at,
        created=meter_event.created,
        metadata=meter_event.metadata_,
    )


@router.get("/meters/{meter_id}/events", response_model=PaginatedResponse[MeterEventResponse])
async def list_meter_events(
    meter_id: str,
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    customer_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import MeterEvent, Meter
    
    meter_query = select(Meter).where(Meter.id == meter_id)
    meter_result = await session.execute(meter_query)
    meter = meter_result.scalar_one_or_none()
    
    if not meter:
        raise NotFoundError(f"Meter {meter_id} not found")
    
    query = select(MeterEvent).where(MeterEvent.meter_id == meter_id)
    
    if customer_id:
        query = query.where(MeterEvent.customer_id == customer_id)
    if subscription_id:
        query = query.where(MeterEvent.subscription_id == subscription_id)
    if start_time:
        query = query.where(MeterEvent.timestamp >= start_time)
    if end_time:
        query = query.where(MeterEvent.timestamp <= end_time)
    if starting_after:
        query = query.where(MeterEvent.id > starting_after)
    
    query = query.order_by(MeterEvent.timestamp.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    events = list(result.scalars().all())
    
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]
    
    data = [
        MeterEventResponse(
            id=e.id,
            meter_id=e.meter_id,
            customer_id=e.customer_id,
            subscription_id=e.subscription_id,
            value=e.value,
            timestamp=e.timestamp,
            event_name=e.event_name,
            properties=e.properties,
            identifier=e.identifier,
            status=e.status,
            processed_at=e.processed_at,
            created=e.created,
            metadata=e.metadata_,
        )
        for e in events
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/meters/{meter_id}/usage", response_model=MeterUsageResponse)
async def get_meter_usage(
    meter_id: str,
    request: Request,
    period_start: int,
    period_end: int,
    customer_id: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select, func
    from payment_platform.backend.domain.usage import Meter, MeterEvent, AggregationType
    
    meter_query = select(Meter).where(Meter.id == meter_id)
    meter_result = await session.execute(meter_query)
    meter = meter_result.scalar_one_or_none()
    
    if not meter:
        raise NotFoundError(f"Meter {meter_id} not found")
    
    query = select(
        func.sum(MeterEvent.value).label("total_value"),
        func.count(MeterEvent.id).label("event_count"),
    ).where(
        MeterEvent.meter_id == meter_id,
        MeterEvent.timestamp >= period_start,
        MeterEvent.timestamp <= period_end,
    )
    
    if customer_id:
        query = query.where(MeterEvent.customer_id == customer_id)
    
    result = await session.execute(query)
    row = result.one()
    
    total_value = row.total_value or Decimal("0")
    event_count = row.event_count or 0
    
    aggregated_value = total_value
    if meter.aggregation_type == AggregationType.MAX:
        max_query = select(func.max(MeterEvent.value)).where(
            MeterEvent.meter_id == meter_id,
            MeterEvent.timestamp >= period_start,
            MeterEvent.timestamp <= period_end,
        )
        if customer_id:
            max_query = max_query.where(MeterEvent.customer_id == customer_id)
        max_result = await session.execute(max_query)
        aggregated_value = max_result.scalar() or Decimal("0")
    elif meter.aggregation_type == AggregationType.LAST:
        last_query = select(MeterEvent.value).where(
            MeterEvent.meter_id == meter_id,
            MeterEvent.timestamp >= period_start,
            MeterEvent.timestamp <= period_end,
        )
        if customer_id:
            last_query = last_query.where(MeterEvent.customer_id == customer_id)
        last_query = last_query.order_by(MeterEvent.timestamp.desc()).limit(1)
        last_result = await session.execute(last_query)
        last_value = last_result.scalar_one_or_none()
        aggregated_value = last_value or Decimal("0")
    
    return MeterUsageResponse(
        meter_id=meter_id,
        customer_id=customer_id,
        period_start=period_start,
        period_end=period_end,
        total_value=total_value,
        event_count=event_count,
        aggregated_value=aggregated_value,
        aggregation_type=meter.aggregation_type.value,
    )


@router.post("/usage_alerts", response_model=UsageAlertResponse, status_code=201)
async def create_usage_alert(
    request: Request,
    data: UsageAlertCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.usage import UsageAlert, UsageAlertStatus
    
    alert_id = _generate_id("ual")
    timestamp = _get_timestamp()
    
    alert = UsageAlert(
        id=alert_id,
        subscription_item_id=data.subscription_item_id,
        threshold=data.threshold,
        notification_emails=data.notification_emails,
        status=UsageAlertStatus.ACTIVE,
        webhook_url=data.webhook_url,
        created=timestamp,
    )
    
    session.add(alert)
    await session.flush()
    
    return UsageAlertResponse(
        id=alert.id,
        subscription_item_id=alert.subscription_item_id,
        threshold=alert.threshold,
        notification_emails=alert.notification_emails,
        triggered_at=alert.triggered_at,
        current_usage=alert.current_usage,
        status=alert.status.value,
        webhook_url=alert.webhook_url,
        created=alert.created,
    )


@router.get("/usage_alerts", response_model=PaginatedResponse[UsageAlertResponse])
async def list_usage_alerts(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    subscription_item_id: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import UsageAlert
    
    query = select(UsageAlert)
    
    if subscription_item_id:
        query = query.where(UsageAlert.subscription_item_id == subscription_item_id)
    if status:
        query = query.where(UsageAlert.status == status)
    if starting_after:
        query = query.where(UsageAlert.id > starting_after)
    
    query = query.order_by(UsageAlert.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    alerts = list(result.scalars().all())
    
    has_more = len(alerts) > limit
    if has_more:
        alerts = alerts[:limit]
    
    data = [
        UsageAlertResponse(
            id=a.id,
            subscription_item_id=a.subscription_item_id,
            threshold=a.threshold,
            notification_emails=a.notification_emails,
            triggered_at=a.triggered_at,
            current_usage=a.current_usage,
            status=a.status.value,
            webhook_url=a.webhook_url,
            created=a.created,
        )
        for a in alerts
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.delete("/usage_alerts/{alert_id}")
async def delete_usage_alert(
    alert_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import UsageAlert
    
    query = select(UsageAlert).where(UsageAlert.id == alert_id)
    result = await session.execute(query)
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise NotFoundError(f"Usage alert {alert_id} not found")
    
    await session.delete(alert)
    await session.flush()
    
    return {"id": alert_id, "deleted": True}


@router.get("/subscription_items/{subscription_item_id}/usage_record_summaries", response_model=PaginatedResponse[UsageRecordSummaryResponse])
async def get_usage_record_summaries(
    subscription_item_id: str,
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    period_start: Optional[int] = None,
    period_end: Optional[int] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import UsageRecordSummary
    
    query = select(UsageRecordSummary).where(
        UsageRecordSummary.subscription_item_id == subscription_item_id
    )
    
    if period_start:
        query = query.where(UsageRecordSummary.period_start >= period_start)
    if period_end:
        query = query.where(UsageRecordSummary.period_end <= period_end)
    if starting_after:
        query = query.where(UsageRecordSummary.id > starting_after)
    
    query = query.order_by(UsageRecordSummary.period_start.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    summaries = list(result.scalars().all())
    
    has_more = len(summaries) > limit
    if has_more:
        summaries = summaries[:limit]
    
    data = [
        UsageRecordSummaryResponse(
            id=s.id,
            subscription_item_id=s.subscription_item_id,
            period_start=s.period_start,
            period_end=s.period_end,
            total_usage=s.total_usage,
            invoice_usage=s.invoice_usage,
            period_count=s.period_count,
            last_usage_record_id=s.last_usage_record_id,
            aggregated_values=s.aggregated_values,
            created=s.created,
        )
        for s in summaries
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/meter_events/{event_id}/adjustments", response_model=MeterEventAdjustmentResponse, status_code=201)
async def create_meter_event_adjustment(
    event_id: str,
    request: Request,
    data: MeterEventAdjustmentCreateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import MeterEvent, MeterEventAdjustment, MeterEventAdjustmentType
    
    event_query = select(MeterEvent).where(MeterEvent.id == event_id)
    event_result = await session.execute(event_query)
    event = event_result.scalar_one_or_none()
    
    if not event:
        raise NotFoundError(f"Meter event {event_id} not found")
    
    adjustment_type = MeterEventAdjustmentType.CREDIT
    if data.adjustment_type == "debit":
        adjustment_type = MeterEventAdjustmentType.DEBIT
    
    adjustment_id = _generate_id("mea")
    timestamp = _get_timestamp()
    
    adjustment = MeterEventAdjustment(
        id=adjustment_id,
        meter_event_id=event_id,
        adjustment_type=adjustment_type,
        amount=data.amount,
        reason=data.reason,
        created=timestamp,
    )
    
    session.add(adjustment)
    await session.flush()
    
    return MeterEventAdjustmentResponse(
        id=adjustment.id,
        meter_event_id=adjustment.meter_event_id,
        adjustment_type=adjustment.adjustment_type.value,
        amount=adjustment.amount,
        reason=adjustment.reason,
        status=adjustment.status,
        created=adjustment.created,
    )


@router.post("/meter_price_tiers", response_model=MeterPriceTierResponse, status_code=201)
async def create_meter_price_tier(
    request: Request,
    meter_id: str,
    data: MeterPriceTierCreateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import Meter, MeterPriceTier
    
    meter_query = select(Meter).where(Meter.id == meter_id)
    meter_result = await session.execute(meter_query)
    meter = meter_result.scalar_one_or_none()
    
    if not meter:
        raise NotFoundError(f"Meter {meter_id} not found")
    
    tier_id = _generate_id("mpt")
    timestamp = _get_timestamp()
    
    tier = MeterPriceTier(
        id=tier_id,
        meter_id=meter_id,
        up_to=data.up_to,
        unit_amount=data.unit_amount,
        flat_amount=data.flat_amount,
        tier_type=data.tier_type,
        created=timestamp,
    )
    
    session.add(tier)
    await session.flush()
    
    return MeterPriceTierResponse(
        id=tier.id,
        meter_id=tier.meter_id,
        price_id=tier.price_id,
        up_to=tier.up_to,
        unit_amount=tier.unit_amount,
        flat_amount=tier.flat_amount,
        tier_type=tier.tier_type,
        created=tier.created,
    )


@router.get("/meters/{meter_id}/price_tiers", response_model=PaginatedResponse[MeterPriceTierResponse])
async def list_meter_price_tiers(
    meter_id: str,
    request: Request,
    limit: int = 10,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.usage import MeterPriceTier, Meter
    
    meter_query = select(Meter).where(Meter.id == meter_id)
    meter_result = await session.execute(meter_query)
    meter = meter_result.scalar_one_or_none()
    
    if not meter:
        raise NotFoundError(f"Meter {meter_id} not found")
    
    query = select(MeterPriceTier).where(
        MeterPriceTier.meter_id == meter_id
    ).order_by(MeterPriceTier.up_to.nulls_last()).limit(limit + 1)
    
    result = await session.execute(query)
    tiers = list(result.scalars().all())
    
    has_more = len(tiers) > limit
    if has_more:
        tiers = tiers[:limit]
    
    data = [
        MeterPriceTierResponse(
            id=t.id,
            meter_id=t.meter_id,
            price_id=t.price_id,
            up_to=t.up_to,
            unit_amount=t.unit_amount,
            flat_amount=t.flat_amount,
            tier_type=t.tier_type,
            created=t.created,
        )
        for t in tiers
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)
