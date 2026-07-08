from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, validator

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import (
    PaymentIntentRepository,
    CustomerRepository,
    PaymentMethodRepository,
    ChargeRepository,
    BalanceTransactionRepository,
    EventRepository,
    WebhookEndpointRepository,
    EventDeliveryRepository,
)
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, PaymentError
from payment_platform.shared.utils.identifiers import generate_charge_id
from payment_platform.shared.config import settings

router = APIRouter()


class PaymentIntentCreateRequest(BaseModel):
    amount: int = Field(..., ge=1, description="Amount in minor units")
    currency: str = Field(..., min_length=3, max_length=3, description="Currency code")
    customer: Optional[str] = Field(default=None, description="Customer ID")
    description: Optional[str] = Field(default=None, max_length=500, description="Description")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")
    payment_method_types: Optional[List[str]] = Field(default=["card"], description="Payment method types")
    receipt_email: Optional[str] = Field(default=None, description="Receipt email")
    setup_future_usage: Optional[str] = Field(default=None, description="Setup future usage")
    shipping: Optional[Dict[str, Any]] = Field(default=None, description="Shipping details")
    statement_descriptor: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor")
    statement_descriptor_suffix: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor suffix")
    transfer_data: Optional[Dict[str, Any]] = Field(default=None, description="Transfer data for platform charges")
    transfer_group: Optional[str] = Field(default=None, description="Transfer group")
    capture_method: Optional[str] = Field(default="automatic", description="Capture method")
    confirmation_method: Optional[str] = Field(default="automatic", description="Confirmation method")
    confirm: Optional[bool] = Field(default=False, description="Confirm immediately")
    payment_method: Optional[str] = Field(default=None, description="Payment method ID")
    payment_method_options: Optional[Dict[str, Any]] = Field(default=None, description="Payment method options")
    off_session: Optional[bool] = Field(default=None, description="Off-session payment")
    error_on_requires_action: Optional[bool] = Field(default=False, description="Error on requires action")
    mandate: Optional[str] = Field(default=None, description="Mandate ID")
    mandate_data: Optional[Dict[str, Any]] = Field(default=None, description="Mandate data")
    on_behalf_of: Optional[str] = Field(default=None, description="On behalf of account")
    application_fee_amount: Optional[int] = Field(default=None, ge=0, description="Application fee amount")
    application_fee_percent: Optional[float] = Field(default=None, ge=0, le=100, description="Application fee percent")

    @validator("currency")
    def validate_currency(cls, v):
        return v.lower()

    @validator("capture_method")
    def validate_capture_method(cls, v):
        if v not in ["automatic", "manual"]:
            raise ValueError("capture_method must be 'automatic' or 'manual'")
        return v

    @validator("confirmation_method")
    def validate_confirmation_method(cls, v):
        if v not in ["automatic", "manual"]:
            raise ValueError("confirmation_method must be 'automatic' or 'manual'")
        return v

    @validator("setup_future_usage")
    def validate_setup_future_usage(cls, v):
        if v and v not in ["off_session", "on_session"]:
            raise ValueError("setup_future_usage must be 'off_session' or 'on_session'")
        return v


class PaymentIntentUpdateRequest(BaseModel):
    amount: Optional[int] = Field(default=None, ge=1, description="Amount in minor units")
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3, description="Currency code")
    customer: Optional[str] = Field(default=None, description="Customer ID")
    description: Optional[str] = Field(default=None, max_length=500, description="Description")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")
    payment_method_types: Optional[List[str]] = Field(default=None, description="Payment method types")
    receipt_email: Optional[str] = Field(default=None, description="Receipt email")
    setup_future_usage: Optional[str] = Field(default=None, description="Setup future usage")
    shipping: Optional[Dict[str, Any]] = Field(default=None, description="Shipping details")
    statement_descriptor: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor")
    statement_descriptor_suffix: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor suffix")
    transfer_data: Optional[Dict[str, Any]] = Field(default=None, description="Transfer data")
    transfer_group: Optional[str] = Field(default=None, description="Transfer group")
    application_fee_amount: Optional[int] = Field(default=None, ge=0, description="Application fee amount")


class PaymentIntentConfirmRequest(BaseModel):
    payment_method: Optional[str] = Field(default=None, description="Payment method ID")
    payment_method_options: Optional[Dict[str, Any]] = Field(default=None, description="Payment method options")
    receipt_email: Optional[str] = Field(default=None, description="Receipt email")
    setup_future_usage: Optional[str] = Field(default=None, description="Setup future usage")
    shipping: Optional[Dict[str, Any]] = Field(default=None, description="Shipping details")
    mandate: Optional[str] = Field(default=None, description="Mandate ID")
    mandate_data: Optional[Dict[str, Any]] = Field(default=None, description="Mandate data")
    off_session: Optional[bool] = Field(default=None, description="Off-session payment")
    error_on_requires_action: Optional[bool] = Field(default=False, description="Error on requires action")
    return_url: Optional[str] = Field(default=None, description="Return URL for redirects")


class PaymentIntentCaptureRequest(BaseModel):
    amount_to_capture: Optional[int] = Field(default=None, ge=1, description="Amount to capture")
    statement_descriptor: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor")
    statement_descriptor_suffix: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor suffix")
    receipt_email: Optional[str] = Field(default=None, description="Receipt email")
    transfer_data: Optional[Dict[str, Any]] = Field(default=None, description="Transfer data")
    application_fee_amount: Optional[int] = Field(default=None, ge=0, description="Application fee amount")


class PaymentIntentCancelRequest(BaseModel):
    cancellation_reason: Optional[str] = Field(default=None, description="Cancellation reason")


class PaymentIntentResponse(BaseModel):
    id: str
    object: str = "payment_intent"
    amount: int
    amount_capturable: int = 0
    amount_received: int = 0
    amount_details: Optional[Dict[str, Any]] = None
    application: Optional[str] = None
    application_fee_amount: Optional[int] = None
    automatic_payment_methods: Optional[Dict[str, Any]] = None
    canceled_at: Optional[int] = None
    cancellation_reason: Optional[str] = None
    capture_method: str
    charges: Optional[Dict[str, Any]] = None
    client_secret: Optional[str] = None
    confirmation_method: str
    created: int
    currency: str
    customer: Optional[str] = None
    description: Optional[str] = None
    invoice: Optional[str] = None
    last_payment_error: Optional[Dict[str, Any]] = None
    latest_charge: Optional[str] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    next_action: Optional[Dict[str, Any]] = None
    on_behalf_of: Optional[str] = None
    payment_method: Optional[str] = None
    payment_method_configuration_details: Optional[Dict[str, Any]] = None
    payment_method_options: Optional[Dict[str, Any]] = None
    payment_method_types: List[str] = ["card"]
    processing: Optional[Dict[str, Any]] = None
    receipt_email: Optional[str] = None
    review: Optional[str] = None
    setup_future_usage: Optional[str] = None
    shipping: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    statement_descriptor: Optional[str] = None
    statement_descriptor_suffix: Optional[str] = None
    status: str
    transfer_data: Optional[Dict[str, Any]] = None
    transfer_group: Optional[str] = None

    class Config:
        from_attributes = True


def payment_intent_to_response(pi: Any, charges: Optional[List] = None) -> PaymentIntentResponse:
    return PaymentIntentResponse(
        id=pi.id,
        amount=pi.amount,
        amount_capturable=pi.amount_capturable,
        amount_received=pi.amount_received,
        amount_details=pi.amount_details,
        application=pi.application,
        application_fee_amount=pi.application_fee_amount,
        automatic_payment_methods=pi.automatic_payment_methods,
        canceled_at=int(pi.canceled_at.timestamp()) if pi.canceled_at else None,
        cancellation_reason=pi.cancellation_reason,
        capture_method=pi.capture_method,
        charges={"object": "list", "data": charges or [], "has_more": False},
        client_secret=pi.client_secret,
        confirmation_method=pi.confirmation_method,
        created=int(pi.created_at.timestamp()),
        currency=pi.currency,
        customer=pi.customer_id,
        description=pi.description,
        invoice=pi.invoice_id,
        last_payment_error=pi.last_payment_error,
        latest_charge=pi.latest_charge,
        livemode=pi.livemode,
        metadata=pi.metadata_ or {},
        next_action=pi.next_action,
        on_behalf_of=pi.on_behalf_of,
        payment_method=pi.payment_method,
        payment_method_configuration_details=pi.payment_method_configuration_details,
        payment_method_options=pi.payment_method_options,
        payment_method_types=pi.payment_method_types or ["card"],
        processing=pi.processing,
        receipt_email=pi.receipt_email,
        review=pi.review,
        setup_future_usage=pi.setup_future_usage,
        shipping=pi.shipping_details,
        statement_descriptor=pi.statement_descriptor,
        statement_descriptor_suffix=pi.statement_descriptor_suffix,
        status=pi.status,
        transfer_data=pi.transfer_data,
        transfer_group=pi.transfer_group,
    )


def validate_amount(amount: int, currency: str) -> None:
    min_amount = settings.payment.min_payment_amount.get(currency, 50)
    max_amount = settings.payment.max_payment_amount.get(currency, 9999999999)
    if amount < min_amount:
        raise ValidationError(f"Amount must be at least {min_amount} in minor units")
    if amount > max_amount:
        raise ValidationError(f"Amount exceeds maximum of {max_amount} in minor units")


async def create_charge_for_payment_intent(
    session,
    payment_intent,
    payment_method_id: Optional[str] = None,
) -> Any:
    charge_repo = ChargeRepository(session)
    charge_id = generate_charge_id()
    import time
    import secrets
    charge = await charge_repo.create(
        id=charge_id,
        amount=payment_intent.amount,
        currency=payment_intent.currency,
        payment_intent_id=payment_intent.id,
        customer_id=payment_intent.customer_id,
        account_id=payment_intent.account_id,
        description=payment_intent.description,
        metadata_=payment_intent.metadata_,
        created=int(time.time()),
        paid=False,
        status="pending",
        receipt_email=payment_intent.receipt_email,
        statement_descriptor=payment_intent.statement_descriptor,
    )
    return charge


@router.post("", response_model=PaymentIntentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_intent(
    request: Request,
    data: PaymentIntentCreateRequest,
    session = Depends(get_session),
):
    validate_amount(data.amount, data.currency)
    account_id = getattr(request.state, "account_id", None)
    repo = PaymentIntentRepository(session)
    customer_repo = CustomerRepository(session)
    if data.customer:
        customer = await customer_repo.get_by_id(data.customer)
        if not customer or customer.is_deleted:
            raise NotFoundError(f"Customer {data.customer} not found")
    payment_intent = await repo.create_payment_intent(
        amount=data.amount,
        currency=data.currency,
        account_id=account_id,
        customer_id=data.customer,
        payment_method_types=data.payment_method_types or ["card"],
        capture_method=data.capture_method or "automatic",
        confirmation_method=data.confirmation_method or "automatic",
        metadata=data.metadata,
        description=data.description,
        receipt_email=data.receipt_email,
        setup_future_usage=data.setup_future_usage,
        statement_descriptor=data.statement_descriptor,
        statement_descriptor_suffix=data.statement_descriptor_suffix,
        transfer_data=data.transfer_data,
        transfer_group=data.transfer_group,
        application_fee_amount=data.application_fee_amount,
    )
    if data.shipping:
        payment_intent.shipping_details = data.shipping
    if data.confirm and data.payment_method:
        payment_intent = await confirm_payment_intent_internal(
            session, payment_intent, data.payment_method
        )
    await session.commit()
    return payment_intent_to_response(payment_intent)


@router.get("/{payment_intent_id}", response_model=PaymentIntentResponse)
async def get_payment_intent(
    payment_intent_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = PaymentIntentRepository(session)
    payment_intent = await repo.get_by_id(payment_intent_id)
    if not payment_intent:
        raise NotFoundError(f"Payment intent {payment_intent_id} not found")
    charge_repo = ChargeRepository(session)
    charges = await charge_repo.get_by_payment_intent(payment_intent_id)
    charges_data = [
        {
            "id": c.id,
            "object": "charge",
            "amount": c.amount,
            "currency": c.currency,
            "status": c.status,
            "paid": c.paid,
        }
        for c in charges
    ]
    return payment_intent_to_response(payment_intent, charges_data)


@router.post("/{payment_intent_id}", response_model=PaymentIntentResponse)
async def update_payment_intent(
    payment_intent_id: str,
    request: Request,
    data: PaymentIntentUpdateRequest,
    session = Depends(get_session),
):
    repo = PaymentIntentRepository(session)
    payment_intent = await repo.get_by_id(payment_intent_id)
    if not payment_intent:
        raise NotFoundError(f"Payment intent {payment_intent_id} not found")
    if payment_intent.status not in ["requires_payment_method", "requires_confirmation", "requires_action"]:
        raise ValidationError("Payment intent cannot be updated in its current state")
    update_data = data.dict(exclude_unset=True)
    if "amount" in update_data:
        validate_amount(update_data["amount"], payment_intent.currency)
    if "currency" in update_data:
        update_data["currency"] = update_data["currency"].lower()
    if "shipping" in update_data:
        update_data["shipping_details"] = update_data.pop("shipping")
    if "customer" in update_data:
        update_data["customer_id"] = update_data.pop("customer")
    await repo.update(payment_intent_id, **update_data)
    await session.commit()
    return payment_intent_to_response(payment_intent)


@router.post("/{payment_intent_id}/confirm", response_model=PaymentIntentResponse)
async def confirm_payment_intent(
    payment_intent_id: str,
    request: Request,
    data: PaymentIntentConfirmRequest,
    session = Depends(get_session),
):
    repo = PaymentIntentRepository(session)
    payment_intent = await repo.get_by_id(payment_intent_id)
    if not payment_intent:
        raise NotFoundError(f"Payment intent {payment_intent_id} not found")
    if payment_intent.status not in ["requires_payment_method", "requires_confirmation"]:
        raise ValidationError(f"Payment intent cannot be confirmed in state: {payment_intent.status}")
    payment_method_id = data.payment_method or payment_intent.payment_method
    if not payment_method_id:
        raise ValidationError("A payment method is required to confirm this payment intent")
    payment_intent = await confirm_payment_intent_internal(
        session, payment_intent, payment_method_id, data.dict(exclude_unset=True)
    )
    await session.commit()
    return payment_intent_to_response(payment_intent)


async def confirm_payment_intent_internal(
    session,
    payment_intent,
    payment_method_id: str,
    confirm_data: Optional[Dict] = None,
) -> Any:
    repo = PaymentIntentRepository(session)
    pm_repo = PaymentMethodRepository(session)
    payment_method = await pm_repo.get_by_id(payment_method_id)
    if not payment_method:
        raise NotFoundError(f"Payment method {payment_method_id} not found")
    payment_intent.payment_method = payment_method_id
    payment_intent.status = "processing"
    payment_intent.confirmed_on = datetime.now(timezone.utc)
    import time
    charge = await create_charge_for_payment_intent(session, payment_intent, payment_method_id)
    charge.payment_method = payment_method_id
    charge.payment_method_details = {
        "type": payment_method.type,
        payment_method.type: payment_method.card if payment_method.type == "card" else {},
    }
    charge.status = "succeeded"
    charge.paid = True
    charge.captured = True
    charge.amount_captured = payment_intent.amount
    await session.flush()
    payment_intent.status = "succeeded"
    payment_intent.amount_received = payment_intent.amount
    payment_intent.latest_charge = charge.id
    payment_intent.charges = [charge.id]
    bt_repo = BalanceTransactionRepository(session)
    await bt_repo.create_transaction(
        amount=payment_intent.amount,
        currency=payment_intent.currency,
        type="payment",
        source=charge.id,
        account_id=payment_intent.account_id,
        description=f"Payment for {payment_intent.id}",
    )
    event_repo = EventRepository(session)
    await event_repo.create_event(
        type="payment_intent.succeeded",
        data={
            "object": {"id": payment_intent.id, "status": "succeeded"},
        },
        account_id=payment_intent.account_id,
    )
    webhook_repo = WebhookEndpointRepository(session)
    endpoints = await webhook_repo.get_enabled_for_account(payment_intent.account_id)
    for endpoint in endpoints:
        if "*" in endpoint.enabled_events or "payment_intent.succeeded" in endpoint.enabled_events:
            ed_repo = EventDeliveryRepository(session)
            await ed_repo.create_delivery(
                event_id=payment_intent.id,
                webhook_endpoint_id=endpoint.id,
                webhook_url=endpoint.url,
                account_id=payment_intent.account_id,
            )
    return payment_intent


@router.post("/{payment_intent_id}/capture", response_model=PaymentIntentResponse)
async def capture_payment_intent(
    payment_intent_id: str,
    request: Request,
    data: PaymentIntentCaptureRequest,
    session = Depends(get_session),
):
    repo = PaymentIntentRepository(session)
    payment_intent = await repo.get_by_id(payment_intent_id)
    if not payment_intent:
        raise NotFoundError(f"Payment intent {payment_intent_id} not found")
    if payment_intent.status != "requires_capture":
        raise ValidationError("Payment intent cannot be captured in its current state")
    capture_amount = data.amount_to_capture or payment_intent.amount
    if capture_amount > payment_intent.amount:
        raise ValidationError("Amount to capture cannot exceed payment intent amount")
    payment_intent.status = "succeeded"
    payment_intent.amount_received = capture_amount
    payment_intent.amount_capturable = 0
    await session.commit()
    return payment_intent_to_response(payment_intent)


@router.post("/{payment_intent_id}/cancel", response_model=PaymentIntentResponse)
async def cancel_payment_intent(
    payment_intent_id: str,
    request: Request,
    data: PaymentIntentCancelRequest,
    session = Depends(get_session),
):
    repo = PaymentIntentRepository(session)
    payment_intent = await repo.get_by_id(payment_intent_id)
    if not payment_intent:
        raise NotFoundError(f"Payment intent {payment_intent_id} not found")
    if payment_intent.status not in ["requires_payment_method", "requires_capture", "requires_confirmation"]:
        raise ValidationError("Payment intent cannot be canceled in its current state")
    payment_intent.status = "canceled"
    payment_intent.canceled_at = datetime.now(timezone.utc)
    payment_intent.cancellation_reason = data.cancellation_reason
    await session.commit()
    return payment_intent_to_response(payment_intent)


@router.get("", response_model=PaginatedResponse[PaymentIntentResponse])
async def list_payment_intents(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    customer: Optional[str] = Query(default=None),
    created: Optional[Dict[str, int]] = None,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = PaymentIntentRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if customer:
        filters["customer_id"] = customer
    payment_intents = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(payment_intents) > limit
    if has_more:
        payment_intents = payment_intents[:limit]
    return PaginatedResponse(
        data=[payment_intent_to_response(pi) for pi in payment_intents],
        has_more=has_more,
    )
