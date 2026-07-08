from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, validator

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import (
    SubscriptionRepository, CustomerRepository, PriceRepository, ProductRepository
)
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_subscription_id

router = APIRouter()


class SubscriptionCreateRequest(BaseModel):
    customer: str = Field(..., description="Customer ID")
    items: List[Dict[str, Any]] = Field(..., description="Subscription items")
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    billing_cycle_anchor: Optional[int] = Field(default=None, description="Billing cycle anchor timestamp")
    backdate_start_date: Optional[int] = Field(default=None, description="Backdate start date")
    billing_thresholds: Optional[Dict[str, Any]] = Field(default=None, description="Billing thresholds")
    cancel_at: Optional[int] = Field(default=None, description="Cancel at timestamp")
    cancel_at_period_end: Optional[bool] = Field(default=False, description="Cancel at period end")
    collection_method: Optional[str] = Field(default="charge_automatically")
    coupon: Optional[str] = Field(default=None, description="Coupon ID")
    days_until_due: Optional[int] = Field(default=30, ge=1, le=90)
    default_payment_method: Optional[str] = Field(default=None)
    default_source: Optional[str] = Field(default=None)
    default_tax_rates: Optional[List[str]] = Field(default=None)
    description: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    off_session: Optional[bool] = Field(default=None)
    on_behalf_of: Optional[str] = Field(default=None)
    payment_behavior: Optional[str] = Field(default="default_incomplete")
    payment_settings: Optional[Dict[str, Any]] = Field(default=None)
    pending_invoice_item_interval: Optional[Dict[str, Any]] = Field(default=None)
    promotion_code: Optional[str] = Field(default=None)
    proration_behavior: Optional[str] = Field(default="create_prorations")
    proration_date: Optional[int] = Field(default=None)
    transfer_data: Optional[Dict[str, Any]] = Field(default=None)
    trial_end: Optional[int] = Field(default=None)
    trial_from_plan: Optional[bool] = Field(default=False)
    trial_period_days: Optional[int] = Field(default=None, ge=1, le=730)
    trial_settings: Optional[Dict[str, Any]] = Field(default=None)

    @validator("collection_method")
    def validate_collection_method(cls, v):
        if v not in ["charge_automatically", "send_invoice"]:
            raise ValueError("collection_method must be 'charge_automatically' or 'send_invoice'")
        return v


class SubscriptionUpdateRequest(BaseModel):
    billing_cycle_anchor: Optional[int] = Field(default=None)
    billing_thresholds: Optional[Dict[str, Any]] = Field(default=None)
    cancel_at: Optional[int] = Field(default=None)
    cancel_at_period_end: Optional[bool] = Field(default=None)
    collection_method: Optional[str] = Field(default=None)
    coupon: Optional[str] = Field(default=None)
    days_until_due: Optional[int] = Field(default=None, ge=1, le=90)
    default_payment_method: Optional[str] = Field(default=None)
    default_source: Optional[str] = Field(default=None)
    default_tax_rates: Optional[List[str]] = Field(default=None)
    description: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    on_behalf_of: Optional[str] = Field(default=None)
    payment_behavior: Optional[str] = Field(default="create_prorations")
    payment_settings: Optional[Dict[str, Any]] = Field(default=None)
    pending_invoice_item_interval: Optional[Dict[str, Any]] = Field(default=None)
    promotion_code: Optional[str] = Field(default=None)
    proration_behavior: Optional[str] = Field(default="create_prorations")
    proration_date: Optional[int] = Field(default=None)
    transfer_data: Optional[Dict[str, Any]] = Field(default=None)
    trial_end: Optional[int] = Field(default=None)
    trial_settings: Optional[Dict[str, Any]] = Field(default=None)
    items: Optional[List[Dict[str, Any]]] = Field(default=None)


class SubscriptionResponse(BaseModel):
    id: str
    object: str = "subscription"
    application: Optional[str] = None
    application_fee_percent: Optional[float] = None
    automatic_tax: Optional[Dict[str, Any]] = None
    billing_cycle_anchor: int
    billing_thresholds: Optional[Dict[str, Any]] = None
    cancel_at: Optional[int] = None
    cancel_at_period_end: bool = False
    canceled_at: Optional[int] = None
    cancellation_details: Optional[Dict[str, Any]] = None
    collection_method: str
    created: int
    currency: str
    current_period_end: int
    current_period_start: int
    customer: str
    days_until_due: int
    default_payment_method: Optional[str] = None
    default_source: Optional[str] = None
    default_tax_rates: Optional[List[Dict]] = None
    description: Optional[str] = None
    discount: Optional[Dict[str, Any]] = None
    discounts: Optional[List[Dict]] = None
    ended_at: Optional[int] = None
    invoice_settings: Optional[Dict[str, Any]] = None
    items: List[Dict[str, Any]] = []
    latest_invoice: Optional[str] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    next_pending_invoice_item_invoice: Optional[int] = None
    on_behalf_of: Optional[str] = None
    pause_collection: Optional[Dict[str, Any]] = None
    payment_settings: Optional[Dict[str, Any]] = None
    pending_invoice_item_interval: Optional[Dict[str, Any]] = None
    pending_setup_intent: Optional[str] = None
    pending_update: Optional[Dict[str, Any]] = None
    plan: Optional[Dict[str, Any]] = None
    quantity: int = 1
    schedule: Optional[str] = None
    start_date: int
    status: str
    test_clock: Optional[str] = None
    transfer_data: Optional[Dict[str, Any]] = None
    trial_end: Optional[int] = None
    trial_settings: Optional[Dict[str, Any]] = None
    trial_start: Optional[int] = None

    class Config:
        from_attributes = True


def subscription_to_response(sub: Any) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        application=sub.application,
        application_fee_percent=float(sub.application_fee_percent) if sub.application_fee_percent else None,
        automatic_tax=sub.automatic_tax,
        billing_cycle_anchor=sub.billing_cycle_anchor,
        billing_thresholds=sub.billing_thresholds,
        cancel_at=sub.cancel_at,
        cancel_at_period_end=sub.cancel_at_period_end,
        canceled_at=sub.canceled_at,
        cancellation_details=sub.cancellation_details,
        collection_method=sub.collection_method,
        created=int(sub.created_at.timestamp()),
        currency=sub.currency,
        current_period_end=sub.current_period_end,
        current_period_start=sub.current_period_start,
        customer=sub.customer_id,
        days_until_due=sub.days_until_due,
        default_payment_method=sub.default_payment_method,
        default_source=sub.default_source,
        default_tax_rates=sub.default_tax_rates,
        description=sub.description,
        discount=sub.discount,
        discounts=sub.discounts,
        ended_at=sub.ended_at,
        invoice_settings=sub.invoice_settings,
        items=sub.items or [],
        latest_invoice=sub.latest_invoice_id,
        livemode=sub.livemode,
        metadata=sub.metadata_ or {},
        next_pending_invoice_item_invoice=sub.next_pending_invoice_item_invoice,
        on_behalf_of=sub.on_behalf_of,
        pause_collection=sub.pause_collection,
        payment_settings=sub.payment_settings,
        pending_invoice_item_interval=sub.pending_invoice_item_interval,
        pending_setup_intent=sub.pending_setup_intent,
        pending_update=sub.pending_update,
        plan=sub.plan,
        quantity=sub.quantity,
        schedule=sub.schedule,
        start_date=sub.start_date,
        status=sub.status,
        test_clock=sub.test_clock,
        transfer_data=sub.transfer_data,
        trial_end=sub.trial_end,
        trial_settings=sub.trial_settings,
        trial_start=sub.trial_start,
    )


@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    request: Request,
    data: SubscriptionCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_by_id(data.customer)
    if not customer or customer.is_deleted:
        raise NotFoundError(f"Customer {data.customer} not found")
    currency = data.currency or customer.currency or "usd"
    billing_anchor = data.billing_cycle_anchor or int(time.time())
    repo = SubscriptionRepository(session)
    subscription = await repo.create_subscription(
        customer_id=data.customer,
        currency=currency,
        billing_cycle_anchor=billing_anchor,
        account_id=account_id,
        items=data.items,
        metadata=data.metadata,
        collection_method=data.collection_method or "charge_automatically",
        days_until_due=data.days_until_due or 30,
    )
    if data.cancel_at_period_end:
        subscription.cancel_at_period_end = True
    if data.default_payment_method:
        subscription.default_payment_method = data.default_payment_method
    if data.trial_period_days:
        import time
        subscription.status = "trialing"
        subscription.trial_start = int(time.time())
        subscription.trial_end = int(time.time()) + (data.trial_period_days * 86400)
    await session.commit()
    return subscription_to_response(subscription)


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = SubscriptionRepository(session)
    subscription = await repo.get_by_id(subscription_id)
    if not subscription or subscription.is_deleted:
        raise NotFoundError(f"Subscription {subscription_id} not found")
    return subscription_to_response(subscription)


@router.post("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: str,
    request: Request,
    data: SubscriptionUpdateRequest,
    session = Depends(get_session),
):
    repo = SubscriptionRepository(session)
    subscription = await repo.get_by_id(subscription_id)
    if not subscription or subscription.is_deleted:
        raise NotFoundError(f"Subscription {subscription_id} not found")
    update_data = data.dict(exclude_unset=True)
    if "items" in update_data:
        subscription.items = update_data.pop("items")
    await repo.update(subscription_id, **update_data)
    await session.commit()
    return subscription_to_response(subscription)


@router.delete("/{subscription_id}", response_model=SubscriptionResponse)
async def cancel_subscription(
    subscription_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = SubscriptionRepository(session)
    subscription = await repo.get_by_id(subscription_id)
    if not subscription or subscription.is_deleted:
        raise NotFoundError(f"Subscription {subscription_id} not found")
    now = int(time.time())
    subscription.status = "canceled"
    subscription.canceled_at = now
    subscription.ended_at = now
    await repo.soft_delete(subscription_id)
    await session.commit()
    return subscription_to_response(subscription)


@router.get("", response_model=PaginatedResponse[SubscriptionResponse])
async def list_subscriptions(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    customer: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = SubscriptionRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if customer:
        filters["customer_id"] = customer
    if status_filter:
        filters["status"] = status_filter
    subscriptions = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(subscriptions) > limit
    if has_more:
        subscriptions = subscriptions[:limit]
    return PaginatedResponse(
        data=[subscription_to_response(s) for s in subscriptions],
        has_more=has_more,
    )
