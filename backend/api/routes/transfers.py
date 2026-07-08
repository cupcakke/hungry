from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import TransferRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError

router = APIRouter()


class TransferCreateRequest(BaseModel):
    amount: int = Field(..., ge=1, description="Amount in minor units")
    currency: str = Field(..., min_length=3, max_length=3)
    destination: str = Field(..., description="Account ID to transfer to")
    description: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    source_transaction: Optional[str] = Field(default=None, description="Source charge ID")
    source_type: Optional[str] = Field(default="card", description="Source type")
    transfer_group: Optional[str] = Field(default=None)


class TransferResponse(BaseModel):
    id: str
    object: str = "transfer"
    amount: int
    amount_reversed: int
    balance_transaction: Optional[str] = None
    created: int
    currency: str
    description: Optional[str] = None
    destination: str
    destination_payment: Optional[str] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    reversed: bool
    source_transaction: Optional[str] = None
    source_type: Optional[str] = None
    transfer_group: Optional[str] = None


def transfer_to_response(transfer: Any) -> TransferResponse:
    return TransferResponse(
        id=transfer.id,
        amount=transfer.amount,
        amount_reversed=transfer.amount_reversed,
        balance_transaction=transfer.balance_transaction_id,
        created=int(transfer.created_at.timestamp()),
        currency=transfer.currency,
        description=transfer.description,
        destination=transfer.destination,
        destination_payment=transfer.destination_payment,
        livemode=transfer.livemode,
        metadata=transfer.metadata_ or {},
        reversed=transfer.reversed,
        source_transaction=transfer.source_transaction,
        source_type=transfer.source_type,
        transfer_group=transfer.transfer_group,
    )


@router.post("", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    request: Request,
    data: TransferCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = TransferRepository(session)
    transfer = await repo.create_transfer(
        amount=data.amount,
        currency=data.currency.lower(),
        destination=data.destination,
        account_id=account_id,
        description=data.description,
        metadata=data.metadata,
        source_transaction=data.source_transaction,
        source_type=data.source_type or "card",
        transfer_group=data.transfer_group,
    )
    await session.commit()
    return transfer_to_response(transfer)


@router.get("/{transfer_id}", response_model=TransferResponse)
async def get_transfer(
    transfer_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = TransferRepository(session)
    transfer = await repo.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(f"Transfer {transfer_id} not found")
    return transfer_to_response(transfer)


@router.post("/{transfer_id}/reversals", response_model=TransferResponse)
async def reverse_transfer(
    transfer_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    amount = data.get("amount")
    repo = TransferRepository(session)
    transfer = await repo.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(f"Transfer {transfer_id} not found")
    if transfer.reversed:
        raise ValueError("Transfer already reversed")
    reversal_amount = amount or transfer.amount
    transfer.amount_reversed += reversal_amount
    transfer.reversed = transfer.amount_reversed >= transfer.amount
    await session.commit()
    return transfer_to_response(transfer)


@router.get("", response_model=PaginatedResponse[TransferResponse])
async def list_transfers(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    destination: Optional[str] = Query(default=None),
    transfer_group: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = TransferRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if destination:
        filters["destination"] = destination
    if transfer_group:
        filters["transfer_group"] = transfer_group
    transfers = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(transfers) > limit
    if has_more:
        transfers = transfers[:limit]
    return PaginatedResponse(
        data=[transfer_to_response(t) for t in transfers],
        has_more=has_more,
    )
