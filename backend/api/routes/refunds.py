from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import RefundRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class RefundCreateRequest(BaseModel):
    charge: str = Field(..., description="Charge ID to refund")
    amount: Optional[int] = Field(default=None, ge=1, description="Amount to refund in minor units")
    reason: Optional[str] = Field(default=None, description="Reason for refund")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")
    instructions_email: Optional[str] = Field(default=None, description="Email for refund instructions")
    origin: Optional[str] = Field(default="customer_balance", description="Refund origin")


class RefundResponse(BaseModel):
    id: str
    object: str = "refund"
    amount: int
    balance_transaction: Optional[str] = None
    charge: str
    created: int
    currency: str
    description: Optional[str] = None
    failure_balance_transaction: Optional[str] = None
    failure_reason: Optional[str] = None
    instructions_email: Optional[str] = None
    instructions_payer_email: Optional[str] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    next_action: Optional[Dict[str, Any]] = None
    origin: str = "customer_balance"
    payment_intent: Optional[str] = None
    reason: Optional[str] = None
    receipt_number: Optional[str] = None
    source: Optional[str] = None
    status: str
    status_details: Optional[Dict[str, Any]] = None


def refund_to_response(refund: Any) -> RefundResponse:
    return RefundResponse(
        id=refund.id,
        amount=refund.amount,
        balance_transaction=refund.balance_transaction,
        charge=refund.charge_id,
        created=refund.created,
        currency=refund.currency,
        description=refund.description,
        failure_balance_transaction=refund.failure_balance_transaction,
        failure_reason=refund.failure_reason,
        instructions_email=refund.instructions_email,
        instructions_payer_email=refund.instructions_payer_email,
        livemode=refund.livemode,
        metadata=refund.metadata_ or {},
        next_action=refund.next_action,
        origin=refund.origin,
        payment_intent=refund.payment_intent_id,
        reason=refund.reason,
        receipt_number=refund.receipt_number,
        source=refund.source,
        status=refund.status,
        status_details=refund.status_details,
    )


@router.post("", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
async def create_refund(
    request: Request,
    data: RefundCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import ChargeRepository
    account_id = getattr(request.state, "account_id", None)
    charge_repo = ChargeRepository(session)
    charge = await charge_repo.get_by_id(data.charge)
    if not charge:
        raise NotFoundError(f"Charge {data.charge} not found")
    if not charge.paid:
        raise ValidationError("Cannot refund an unpaid charge")
    refund_amount = data.amount or (charge.amount - charge.amount_refunded)
    if charge.amount_refunded + refund_amount > charge.amount:
        raise ValidationError("Refund amount exceeds charge amount")
    repo = RefundRepository(session)
    refund = await repo.create_refund(
        charge_id=data.charge,
        amount=refund_amount,
        currency=charge.currency,
        reason=data.reason,
        account_id=account_id,
        metadata=data.metadata,
    )
    refund.payment_intent_id = charge.payment_intent_id
    charge.amount_refunded += refund_amount
    charge.refunded = charge.amount_refunded >= charge.amount
    await session.commit()
    return refund_to_response(refund)


@router.get("/{refund_id}", response_model=RefundResponse)
async def get_refund(
    refund_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = RefundRepository(session)
    refund = await repo.get_by_id(refund_id)
    if not refund:
        raise NotFoundError(f"Refund {refund_id} not found")
    return refund_to_response(refund)


@router.post("/{refund_id}", response_model=RefundResponse)
async def update_refund(
    refund_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = RefundRepository(session)
    refund = await repo.get_by_id(refund_id)
    if not refund:
        raise NotFoundError(f"Refund {refund_id} not found")
    if "metadata" in data:
        refund.metadata_ = data["metadata"]
    await session.commit()
    return refund_to_response(refund)


@router.get("", response_model=PaginatedResponse[RefundResponse])
async def list_refunds(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    charge: Optional[str] = Query(default=None),
    payment_intent: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = RefundRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if charge:
        filters["charge_id"] = charge
    refunds = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(refunds) > limit
    if has_more:
        refunds = refunds[:limit]
    return PaginatedResponse(
        data=[refund_to_response(r) for r in refunds],
        has_more=has_more,
    )


@router.post("/{refund_id}/cancel", response_model=RefundResponse)
async def cancel_refund(
    refund_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = RefundRepository(session)
    refund = await repo.get_by_id(refund_id)
    if not refund:
        raise NotFoundError(f"Refund {refund_id} not found")
    if refund.status != "pending":
        raise ValidationError("Only pending refunds can be canceled")
    refund.status = "canceled"
    await session.commit()
    return refund_to_response(refund)
