from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
import secrets

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, validator

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import CheckoutSessionRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class CheckoutSessionCreateRequest(BaseModel):
    cancel_url: str = Field(..., description="URL to redirect on cancel")
    success_url: str = Field(..., description="URL to redirect on success")
    mode: str = Field(..., description="Checkout mode: payment, subscription, or setup")
    line_items: Optional[List[Dict[str, Any]]] = Field(default=None, description="Line items")
    allow_promotion_codes: Optional[bool] = Field(default=None)
    automatic_tax: Optional[Dict[str, Any]] = Field(default=None)
    billing_address_collection: Optional[str] = Field(default=None)
    billing_details: Optional[Dict[str, Any]] = Field(default=None)
    can_cancel_subscriptions: Optional[bool] = Field(default=None)
    cancel_subscription_on_failure: Optional[bool] = Field(default=None)
    client_reference_id: Optional[str] = Field(default=None, max_length=255)
    consent_collection: Optional[Dict[str, Any]] = Field(default=None)
    consent: Optional[Dict[str, Any]] = Field(default=None)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    custom_fields: Optional[List[Dict]] = Field(default=None)
    custom_text: Optional[Dict[str, Any]] = Field(default=None)
    customer: Optional[str] = Field(default=None)
    customer_creation: Optional[str] = Field(default="if_required")
    customer_email: Optional[str] = Field(default=None)
    customer_update: Optional[Dict[str, Any]] = Field(default=None)
    customer_tax_ids: Optional[List[Dict]] = Field(default=None)
    discounts: Optional[List[Dict]] = Field(default=None)
    enabled_payment_method_types: Optional[List[str]] = Field(default=None)
    expires_at: Optional[int] = Field(default=None)
    invoice_creation: Optional[Dict[str, Any]] = Field(default=None)
    after_expiration: Optional[Dict[str, Any]] = Field(default=None)
    payment_intent_data: Optional[Dict[str, Any]] = Field(default=None)
    payment_method_collection: Optional[str] = Field(default="if_required")
    payment_method_data: Optional[Dict[str, Any]] = Field(default=None)
    payment_method_options: Optional[Dict[str, Any]] = Field(default=None)
    payment_method_types: Optional[List[str]] = Field(default=["card"])
    payment_type: Optional[str] = Field(default=None)
    phone_number_collection: Optional[Dict[str, Any]] = Field(default=None)
    prefill: Optional[Dict[str, Any]] = Field(default=None)
    recover_cart_url: Optional[str] = Field(default=None)
    return_url: Optional[str] = Field(default=None)
    saved_payment_method_options: Optional[Dict[str, Any]] = Field(default=None)
    setup_intent_data: Optional[Dict[str, Any]] = Field(default=None)
    shipping_address_collection: Optional[Dict[str, Any]] = Field(default=None)
    shipping_options: Optional[List[Dict]] = Field(default=None)
    submit_type: Optional[str] = Field(default=None)
    subscription_data: Optional[Dict[str, Any]] = Field(default=None)
    tax_id_collection: Optional[Dict[str, Any]] = Field(default=None)
    ui_mode: Optional[str] = Field(default="hosted")
    metadata: Optional[Dict[str, str]] = Field(default=None)

    @validator("mode")
    def validate_mode(cls, v):
        if v not in ["payment", "subscription", "setup"]:
            raise ValueError("mode must be 'payment', 'subscription', or 'setup'")
        return v

    @validator("billing_address_collection")
    def validate_billing_address(cls, v):
        if v and v not in ["auto", "required"]:
            raise ValueError("billing_address_collection must be 'auto' or 'required'")
        return v


class CheckoutSessionResponse(BaseModel):
    id: str
    object: str = "checkout.session"
    after_expiration: Optional[Dict[str, Any]] = None
    allow_promotion_codes: Optional[bool] = None
    amount_subtotal: Optional[int] = None
    amount_total: Optional[int] = None
    automatic_tax: Optional[Dict[str, Any]] = None
    billing_address_collection: Optional[str] = None
    billing_details: Optional[Dict[str, Any]] = None
    cancel_url: Optional[str] = None
    client_reference_id: Optional[str] = None
    client_secret: Optional[str] = None
    consent: Optional[Dict[str, Any]] = None
    consent_collection: Optional[Dict[str, Any]] = None
    created: int
    currency: Optional[str] = None
    currency_conversion: Optional[Dict[str, Any]] = None
    custom_fields: Optional[List[Dict]] = None
    custom_text: Optional[Dict[str, Any]] = None
    customer: Optional[str] = None
    customer_creation: Optional[str] = None
    customer_details: Optional[Dict[str, Any]] = None
    customer_email: Optional[str] = None
    customer_tax_ids: Optional[List[Dict]] = None
    discounts: Optional[List[Dict]] = None
    expires_at: Optional[int] = None
    idempotency_key: Optional[str] = None
    invoice: Optional[str] = None
    invoice_creation: Optional[Dict[str, Any]] = None
    line_items: Optional[List[Dict]] = None
    livemode: bool = False
    locale: Optional[str] = None
    metadata: Dict[str, str] = {}
    mode: str
    payment_intent: Optional[str] = None
    payment_link: Optional[str] = None
    payment_method_collection: Optional[str] = None
    payment_method_configuration_details: Optional[Dict[str, Any]] = None
    payment_method_options: Optional[Dict[str, Any]] = None
    payment_method_types: List[str] = ["card"]
    payment_method_usage: Optional[str] = None
    payment_status: Optional[str] = None
    phone_number_collection: Optional[Dict[str, Any]] = None
    recovered_from: Optional[str] = None
    redirect_on_completion: Optional[str] = None
    return_url: Optional[str] = None
    setup_intent: Optional[str] = None
    shipping_address_collection: Optional[Dict[str, Any]] = None
    shipping_cost: Optional[Dict[str, Any]] = None
    shipping_details: Optional[Dict[str, Any]] = None
    shipping_options: Optional[List[Dict]] = None
    status: str
    submit_type: Optional[str] = None
    subscription: Optional[str] = None
    success_url: Optional[str] = None
    tax_id_collection: Optional[Dict[str, Any]] = None
    total_details: Optional[Dict[str, Any]] = None
    ui_mode: Optional[str] = None
    url: Optional[str] = None


def checkout_session_to_response(cs: Any) -> CheckoutSessionResponse:
    return CheckoutSessionResponse(
        id=cs.id,
        after_expiration=cs.after_expiration,
        allow_promotion_codes=cs.allow_promotion_codes,
        amount_subtotal=cs.amount_subtotal,
        amount_total=cs.amount_total,
        automatic_tax=cs.automatic_tax,
        billing_address_collection=cs.billing_address_collection,
        billing_details=cs.billing_details,
        cancel_url=cs.cancel_url,
        client_reference_id=cs.client_reference_id,
        client_secret=cs.client_secret,
        consent=cs.consent,
        consent_collection=cs.consent_collection,
        created=int(cs.created_at.timestamp()),
        currency=cs.currency,
        currency_conversion=cs.currency_conversion,
        custom_fields=cs.custom_fields,
        custom_text=cs.custom_text,
        customer=cs.customer_id,
        customer_creation=cs.customer_creation,
        customer_details=cs.customer_details,
        customer_email=cs.customer_email,
        customer_tax_ids=cs.customer_tax_ids,
        discounts=cs.discounts,
        expires_at=cs.expires_at,
        invoice=cs.invoice_id,
        invoice_creation=cs.invoice_creation,
        line_items=cs.line_items,
        livemode=cs.livemode,
        locale=cs.locale,
        metadata=cs.metadata_ or {},
        mode=cs.mode,
        payment_intent=cs.payment_intent_id,
        payment_link=cs.payment_link,
        payment_method_collection=cs.payment_method_collection,
        payment_method_configuration_details=cs.payment_method_configuration_details,
        payment_method_options=cs.payment_method_options,
        payment_method_types=cs.payment_method_types or ["card"],
        payment_method_usage=cs.payment_method_usage,
        payment_status=cs.payment_status,
        phone_number_collection=cs.phone_number_collection,
        recovered_from=cs.recovered_from,
        redirect_on_completion=cs.redirect_on_completion,
        return_url=cs.return_url,
        setup_intent=cs.setup_intent_id,
        shipping_address_collection=cs.shipping_address_collection,
        shipping_cost=cs.shipping_cost,
        shipping_details=cs.shipping_details,
        shipping_options=cs.shipping_options,
        status=cs.status,
        submit_type=cs.submit_type,
        subscription=cs.subscription_id,
        success_url=cs.success_url,
        tax_id_collection=cs.tax_id_collection,
        total_details=cs.total_details,
        ui_mode=cs.ui_mode,
        url=cs.url,
    )


@router.post("", response_model=CheckoutSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_checkout_session(
    request: Request,
    data: CheckoutSessionCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = CheckoutSessionRepository(session)
    checkout_session = await repo.create(
        id=f"cs_{secrets.token_urlsafe(24)}",
        mode=data.mode,
        success_url=data.success_url,
        cancel_url=data.cancel_url,
        account_id=account_id,
        customer_id=data.customer,
        customer_email=data.customer_email,
        line_items=data.line_items,
        payment_method_types=data.payment_method_types or ["card"],
        metadata=data.metadata,
        allow_promotion_codes=data.allow_promotion_codes,
        billing_address_collection=data.billing_address_collection,
        currency=data.currency,
        custom_fields=data.custom_fields,
        custom_text=data.custom_text,
        client_reference_id=data.client_reference_id,
        shipping_address_collection=data.shipping_address_collection,
        shipping_options=data.shipping_options,
        submit_type=data.submit_type,
        phone_number_collection=data.phone_number_collection,
        tax_id_collection=data.tax_id_collection,
        consent_collection=data.consent_collection,
        after_expiration=data.after_expiration,
        expires_at=data.expires_at or int(time.time()) + 86400,
        customer_creation=data.customer_creation or "if_required",
        ui_mode=data.ui_mode or "hosted",
        payment_method_collection=data.payment_method_collection or "if_required",
    )
    checkout_session.url = f"https://checkout.paymentplatform.com/pay/{checkout_session.id}"
    checkout_session.client_secret = f"{checkout_session.id}_secret_{secrets.token_urlsafe(24)}"
    await session.commit()
    return checkout_session_to_response(checkout_session)


@router.get("/{session_id}", response_model=CheckoutSessionResponse)
async def get_checkout_session(
    session_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = CheckoutSessionRepository(session)
    cs = await repo.get_by_id(session_id)
    if not cs:
        raise NotFoundError(f"Checkout session {session_id} not found")
    return checkout_session_to_response(cs)


@router.get("/{session_id}/line_items")
async def get_checkout_session_line_items(
    session_id: str,
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    session = Depends(get_session),
):
    repo = CheckoutSessionRepository(session)
    cs = await repo.get_by_id(session_id)
    if not cs:
        raise NotFoundError(f"Checkout session {session_id} not found")
    line_items = cs.line_items or []
    return {
        "object": "list",
        "data": line_items,
        "has_more": False,
        "url": f"/v1/checkout/sessions/{session_id}/line_items",
    }


@router.post("/{session_id}/expire", response_model=CheckoutSessionResponse)
async def expire_checkout_session(
    session_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = CheckoutSessionRepository(session)
    cs = await repo.get_by_id(session_id)
    if not cs:
        raise NotFoundError(f"Checkout session {session_id} not found")
    if cs.status != "open":
        raise ValidationError("Only open checkout sessions can be expired")
    cs.status = "expired"
    await session.commit()
    return checkout_session_to_response(cs)


@router.get("", response_model=PaginatedResponse[CheckoutSessionResponse])
async def list_checkout_sessions(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    customer: Optional[str] = Query(default=None),
    payment_intent: Optional[str] = Query(default=None),
    subscription: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = CheckoutSessionRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if customer:
        filters["customer_id"] = customer
    if payment_intent:
        filters["payment_intent_id"] = payment_intent
    if subscription:
        filters["subscription_id"] = subscription
    if status_filter:
        filters["status"] = status_filter
    sessions = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(sessions) > limit
    if has_more:
        sessions = sessions[:limit]
    return PaginatedResponse(
        data=[checkout_session_to_response(s) for s in sessions],
        has_more=has_more,
    )
