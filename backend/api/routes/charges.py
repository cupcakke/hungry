from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import ChargeRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError

router = APIRouter()


class ChargeResponse(BaseModel):
    id: str
    object: str = "charge"
    amount: int
    amount_captured: int = 0
    amount_refunded: int = 0
    application: Optional[str] = None
    application_fee: Optional[str] = None
    application_fee_amount: Optional[int] = None
    balance_transaction: Optional[str] = None
    billing_details: Optional[Dict[str, Any]] = None
    calculated_statement_descriptor: Optional[str] = None
    captured: bool = False
    created: int
    currency: str
    customer: Optional[str] = None
    description: Optional[str] = None
    destination: Optional[str] = None
    dispute: Optional[str] = None
    disputed: bool = False
    failure_balance_transaction: Optional[str] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    fraud_details: Optional[Dict[str, Any]] = None
    invoice: Optional[str] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    on_behalf_of: Optional[str] = None
    order: Optional[str] = None
    outcome: Optional[Dict[str, Any]] = None
    paid: bool = False
    payment_intent: Optional[str] = None
    payment_method: Optional[str] = None
    payment_method_details: Optional[Dict[str, Any]] = None
    radar_options: Optional[Dict[str, Any]] = None
    receipt_email: Optional[str] = None
    receipt_number: Optional[str] = None
    receipt_url: Optional[str] = None
    refunded: bool = False
    refunds: Optional[Dict[str, Any]] = None
    review: Optional[str] = None
    shipping: Optional[Dict[str, Any]] = None
    source: Optional[Dict[str, Any]] = None
    source_transfer: Optional[str] = None
    statement_descriptor: Optional[str] = None
    statement_descriptor_suffix: Optional[str] = None
    status: str
    transfer: Optional[str] = None
    transfer_data: Optional[Dict[str, Any]] = None
    transfer_group: Optional[str] = None


def charge_to_response(charge: Any) -> ChargeResponse:
    return ChargeResponse(
        id=charge.id,
        amount=charge.amount,
        amount_captured=charge.amount_captured,
        amount_refunded=charge.amount_refunded,
        application=charge.application,
        application_fee=charge.application_fee,
        application_fee_amount=charge.application_fee_amount,
        balance_transaction=charge.balance_transaction,
        billing_details=charge.billing_details,
        calculated_statement_descriptor=charge.calculated_statement_descriptor,
        captured=charge.captured,
        created=charge.created,
        currency=charge.currency,
        customer=charge.customer_id,
        description=charge.description,
        destination=charge.destination,
        dispute=charge.dispute,
        disputed=charge.disputed,
        failure_balance_transaction=charge.failure_balance_transaction,
        failure_code=charge.failure_code,
        failure_message=charge.failure_message,
        fraud_details=charge.fraud_details,
        invoice=charge.invoice_id,
        livemode=charge.livemode,
        metadata=charge.metadata_ or {},
        on_behalf_of=charge.on_behalf_of,
        order=charge.order,
        outcome=charge.outcome,
        paid=charge.paid,
        payment_intent=charge.payment_intent_id,
        payment_method=charge.payment_method,
        payment_method_details=charge.payment_method_details,
        radar_options=charge.radar_options,
        receipt_email=charge.receipt_email,
        receipt_number=charge.receipt_number,
        receipt_url=charge.receipt_url,
        refunded=charge.refunded,
        refunds={"object": "list", "data": charge.refunds or [], "has_more": False},
        review=charge.review,
        shipping=charge.shipping_details,
        source=charge.source,
        source_transfer=charge.source_transfer,
        statement_descriptor=charge.statement_descriptor,
        statement_descriptor_suffix=charge.statement_descriptor_suffix,
        status=charge.status,
        transfer=charge.transfer,
        transfer_data=charge.transfer_data,
        transfer_group=charge.transfer_group,
    )


@router.get("/{charge_id}", response_model=ChargeResponse)
async def get_charge(
    charge_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = ChargeRepository(session)
    charge = await repo.get_by_id(charge_id)
    if not charge:
        raise NotFoundError(f"Charge {charge_id} not found")
    return charge_to_response(charge)


@router.get("", response_model=PaginatedResponse[ChargeResponse])
async def list_charges(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    customer: Optional[str] = Query(default=None),
    payment_intent: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = ChargeRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if customer:
        filters["customer_id"] = customer
    if payment_intent:
        filters["payment_intent_id"] = payment_intent
    charges = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(charges) > limit
    if has_more:
        charges = charges[:limit]
    return PaginatedResponse(
        data=[charge_to_response(c) for c in charges],
        has_more=has_more,
    )


@router.post("/{charge_id}/capture", response_model=ChargeResponse)
async def capture_charge(
    charge_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = ChargeRepository(session)
    charge = await repo.get_by_id(charge_id)
    if not charge:
        raise NotFoundError(f"Charge {charge_id} not found")
    if charge.captured:
        raise ValueError("Charge already captured")
    charge.captured = True
    charge.amount_captured = charge.amount
    charge.status = "succeeded"
    await session.commit()
    return charge_to_response(charge)
