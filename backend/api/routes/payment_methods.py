from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
import secrets

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import PaymentMethodRepository, CustomerRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_payment_method_id
from payment_platform.shared.utils.crypto import encrypt_card_number, generate_card_fingerprint, mask_card_number

router = APIRouter()


class PaymentMethodCreateRequest(BaseModel):
    type: str = Field(..., description="Payment method type")
    card: Optional[Dict[str, Any]] = Field(default=None, description="Card details")
    billing_details: Optional[Dict[str, Any]] = Field(default=None)
    customer: Optional[str] = Field(default=None)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    payment_method: Optional[str] = Field(default=None)
    allow_redisplay: Optional[str] = Field(default="unspecified")


class PaymentMethodResponse(BaseModel):
    id: str
    object: str = "payment_method"
    acss_debit: Optional[Dict[str, Any]] = None
    affirm: Optional[Dict[str, Any]] = None
    afterpay_clearpay: Optional[Dict[str, Any]] = None
    alipay: Optional[Dict[str, Any]] = None
    au_becs_debit: Optional[Dict[str, Any]] = None
    bacs_debit: Optional[Dict[str, Any]] = None
    bancontact: Optional[Dict[str, Any]] = None
    billing_details: Optional[Dict[str, Any]] = None
    blik: Optional[Dict[str, Any]] = None
    card: Optional[Dict[str, Any]] = None
    card_present: Optional[Dict[str, Any]] = None
    cashapp: Optional[Dict[str, Any]] = None
    created: int
    customer: Optional[str] = None
    eps: Optional[Dict[str, Any]] = None
    fpx: Optional[Dict[str, Any]] = None
    giropay: Optional[Dict[str, Any]] = None
    grabpay: Optional[Dict[str, Any]] = None
    ideal: Optional[Dict[str, Any]] = None
    interac_present: Optional[Dict[str, Any]] = None
    klarna: Optional[Dict[str, Any]] = None
    konbini: Optional[Dict[str, Any]] = None
    link: Optional[Dict[str, Any]] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    mobilepay: Optional[Dict[str, Any]] = None
    multibanco: Optional[Dict[str, Any]] = None
    oxxo: Optional[Dict[str, Any]] = None
    p24: Optional[Dict[str, Any]] = None
    paynow: Optional[Dict[str, Any]] = None
    paypal: Optional[Dict[str, Any]] = None
    pix: Optional[Dict[str, Any]] = None
    promptpay: Optional[Dict[str, Any]] = None
    radar_options: Optional[Dict[str, Any]] = None
    reusable: Optional[bool] = None
    sepa_debit: Optional[Dict[str, Any]] = None
    sofort: Optional[Dict[str, Any]] = None
    swish: Optional[Dict[str, Any]] = None
    type: str
    us_bank_account: Optional[Dict[str, Any]] = None
    wechat_pay: Optional[Dict[str, Any]] = None
    zip: Optional[Dict[str, Any]] = None


def payment_method_to_response(pm: Any) -> PaymentMethodResponse:
    return PaymentMethodResponse(
        id=pm.id,
        acss_debit=pm.acss_debit,
        affirm=pm.affirm,
        afterpay_clearpay=pm.afterpay_clearpay,
        alipay=pm.alipay,
        au_becs_debit=pm.au_becs_debit,
        bacs_debit=pm.bacs_debit,
        bancontact=pm.bancontact,
        billing_details=pm.billing_details,
        blik=pm.blik,
        card=pm.card,
        card_present=pm.card_present,
        cashapp=pm.cashapp,
        created=int(pm.created_at.timestamp()),
        customer=pm.customer_id,
        eps=pm.eps,
        fpx=pm.fpx,
        giropay=pm.giropay,
        grabpay=pm.grabpay,
        ideal=pm.ideal,
        interac_present=pm.interac_present,
        klarna=pm.klarna,
        konbini=pm.konbini,
        link=pm.link,
        livemode=pm.livemode,
        metadata=pm.metadata_ or {},
        mobilepay=pm.mobilepay,
        multibanco=pm.multibanco,
        oxxo=pm.oxxo,
        p24=pm.p24,
        paynow=pm.paynow,
        paypal=pm.paypal,
        pix=pm.pix,
        promptpay=pm.promptpay,
        radar_options=pm.radar_options,
        reusable=pm.reusable,
        sepa_debit=pm.sepa_debit,
        sofort=pm.sofort,
        swish=pm.swish,
        type=pm.type,
        us_bank_account=pm.us_bank_account,
        wechat_pay=pm.wechat_pay,
        zip=pm.zip,
    )


@router.post("", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_method(
    request: Request,
    data: PaymentMethodCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = PaymentMethodRepository(session)
    card_data = None
    if data.type == "card" and data.card:
        card_number = data.card.get("number", "").replace(" ", "")
        exp_month = data.card.get("exp_month")
        exp_year = data.card.get("exp_year")
        cvc = data.card.get("cvc")
        encrypted_number = encrypt_card_number(card_number)
        fingerprint = generate_card_fingerprint(card_number)
        card_data = {
            "brand": "visa" if card_number.startswith("4") else "mastercard",
            "last4": card_number[-4:],
            "exp_month": exp_month,
            "exp_year": exp_year,
            "fingerprint": fingerprint,
            "funding": "credit",
            "country": "US",
            "checks": {
                "address_line1_check": "unchecked",
                "address_postal_code_check": "unchecked",
                "cvc_check": "pass",
            },
            "wallet": None,
            "generated_from": None,
            "three_d_secure_usage": {"supported": True},
            "capture_before": None,
            "network_token": {"status": "unavailable"},
        }
    pm = await repo.create_payment_method(
        type=data.type,
        account_id=account_id,
        customer_id=data.customer,
        card=card_data,
        billing_details=data.billing_details,
        metadata=data.metadata,
    )
    await session.commit()
    return payment_method_to_response(pm)


@router.get("/{payment_method_id}", response_model=PaymentMethodResponse)
async def get_payment_method(
    payment_method_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = PaymentMethodRepository(session)
    pm = await repo.get_by_id(payment_method_id)
    if not pm:
        raise NotFoundError(f"Payment method {payment_method_id} not found")
    return payment_method_to_response(pm)


@router.post("/{payment_method_id}", response_model=PaymentMethodResponse)
async def update_payment_method(
    payment_method_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = PaymentMethodRepository(session)
    pm = await repo.get_by_id(payment_method_id)
    if not pm:
        raise NotFoundError(f"Payment method {payment_method_id} not found")
    if "billing_details" in data:
        pm.billing_details = data["billing_details"]
    if "metadata" in data:
        pm.metadata_ = data["metadata"]
    await session.commit()
    return payment_method_to_response(pm)


@router.post("/{payment_method_id}/attach", response_model=PaymentMethodResponse)
async def attach_payment_method(
    payment_method_id: str,
    request: Request,
    data: Dict[str, str],
    session = Depends(get_session),
):
    customer_id = data.get("customer")
    if not customer_id:
        raise ValidationError("customer is required")
    repo = PaymentMethodRepository(session)
    customer_repo = CustomerRepository(session)
    pm = await repo.get_by_id(payment_method_id)
    if not pm:
        raise NotFoundError(f"Payment method {payment_method_id} not found")
    customer = await customer_repo.get_by_id(customer_id)
    if not customer:
        raise NotFoundError(f"Customer {customer_id} not found")
    pm.customer_id = customer_id
    await session.commit()
    return payment_method_to_response(pm)


@router.post("/{payment_method_id}/detach", response_model=PaymentMethodResponse)
async def detach_payment_method(
    payment_method_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = PaymentMethodRepository(session)
    pm = await repo.get_by_id(payment_method_id)
    if not pm:
        raise NotFoundError(f"Payment method {payment_method_id} not found")
    pm.customer_id = None
    await session.commit()
    return payment_method_to_response(pm)


@router.get("", response_model=PaginatedResponse[PaymentMethodResponse])
async def list_payment_methods(
    request: Request,
    customer: str,
    type: str = "card",
    limit: int = Query(default=10, ge=1, le=100),
    session = Depends(get_session),
):
    repo = PaymentMethodRepository(session)
    payment_methods = await repo.get_by_customer(customer)
    filtered = [pm for pm in payment_methods if pm.type == type]
    return PaginatedResponse(
        data=[payment_method_to_response(pm) for pm in filtered[:limit]],
        has_more=len(filtered) > limit,
    )
