from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import PayoutRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class PayoutCreateRequest(BaseModel):
    amount: int = Field(..., ge=1, description="Amount in minor units")
    currency: str = Field(..., min_length=3, max_length=3)
    destination: Optional[str] = Field(default=None, description="Bank account ID")
    method: Optional[str] = Field(default="standard", description="Payout method")
    source_type: Optional[str] = Field(default="card", description="Source type")
    description: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    statement_descriptor: Optional[str] = Field(default=None, max_length=22)


class PayoutResponse(BaseModel):
    id: str
    object: str = "payout"
    amount: int
    arrival_date: int
    automatic: bool
    balance_transaction: Optional[str] = None
    created: int
    currency: str
    debit_from: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    destination: Optional[str] = None
    failure_balance_transaction: Optional[str] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    method: str
    original_payout: Optional[str] = None
    reconciliation_status: Optional[str] = None
    reversed_by: Optional[str] = None
    source_type: str
    statement_descriptor: Optional[str] = None
    status: str
    terminal_refund: Optional[Dict[str, Any]] = None
    type: str


def payout_to_response(payout: Any) -> PayoutResponse:
    return PayoutResponse(
        id=payout.id,
        amount=payout.amount,
        arrival_date=payout.arrival_date,
        automatic=payout.automatic,
        balance_transaction=payout.balance_transaction_id,
        created=int(payout.created_at.timestamp()),
        currency=payout.currency,
        debit_from=payout.debit_from,
        description=payout.description,
        destination=payout.destination,
        failure_balance_transaction=payout.failure_balance_transaction,
        failure_code=payout.failure_code,
        failure_message=payout.failure_message,
        livemode=payout.livemode,
        metadata=payout.metadata_ or {},
        method=payout.method,
        original_payout=payout.original_payout_id,
        reconciliation_status=payout.reconciliation_status,
        reversed_by=payout.reversed_by,
        source_type=payout.source_type,
        statement_descriptor=payout.statement_descriptor,
        status=payout.status,
        terminal_refund=payout.terminal_refund,
        type=payout.type,
    )


@router.post("", response_model=PayoutResponse, status_code=status.HTTP_201_CREATED)
async def create_payout(
    request: Request,
    data: PayoutCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = PayoutRepository(session)
    payout = await repo.create_payout(
        amount=data.amount,
        currency=data.currency.lower(),
        destination=data.destination,
        account_id=account_id,
        description=data.description,
        metadata=data.metadata,
        method=data.method or "standard",
        source_type=data.source_type or "card",
        statement_descriptor=data.statement_descriptor,
    )
    await session.commit()
    return payout_to_response(payout)


@router.get("/{payout_id}", response_model=PayoutResponse)
async def get_payout(
    payout_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = PayoutRepository(session)
    payout = await repo.get_by_id(payout_id)
    if not payout:
        raise NotFoundError(f"Payout {payout_id} not found")
    return payout_to_response(payout)


@router.post("/{payout_id}/cancel", response_model=PayoutResponse)
async def cancel_payout(
    payout_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = PayoutRepository(session)
    payout = await repo.get_by_id(payout_id)
    if not payout:
        raise NotFoundError(f"Payout {payout_id} not found")
    if payout.status != "pending":
        raise ValidationError("Only pending payouts can be canceled")
    payout.status = "canceled"
    await session.commit()
    return payout_to_response(payout)


@router.get("", response_model=PaginatedResponse[PayoutResponse])
async def list_payouts(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    arrival_date: Optional[int] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = PayoutRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if status_filter:
        filters["status"] = status_filter
    payouts = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(payouts) > limit
    if has_more:
        payouts = payouts[:limit]
    return PaginatedResponse(
        data=[payout_to_response(p) for p in payouts],
        has_more=has_more,
    )
