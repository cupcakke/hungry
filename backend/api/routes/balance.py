from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import BalanceRepository, BalanceTransactionRepository
from payment_platform.shared.models.pagination import PaginatedResponse

router = APIRouter()


class BalanceResponse(BaseModel):
    object: str = "balance"
    available: List[Dict[str, Any]] = []
    connect_reserved: List[Dict[str, Any]] = []
    instant_available: List[Dict[str, Any]] = []
    issuing: Optional[Dict[str, Any]] = None
    livemode: bool = False
    pending: List[Dict[str, Any]] = []


class BalanceTransactionResponse(BaseModel):
    id: str
    object: str = "balance_transaction"
    amount: int
    available_on: int
    created: int
    currency: str
    description: Optional[str] = None
    exchange_rate: Optional[float] = None
    fee: int
    fee_details: List[Dict[str, Any]] = []
    financial_transaction_id: Optional[str] = None
    funding: Optional[str] = None
    livemode: bool = False
    net: int
    reporting_category: Optional[str] = None
    source: Optional[str] = None
    status: str
    type: str


def balance_transaction_to_response(bt: Any) -> BalanceTransactionResponse:
    return BalanceTransactionResponse(
        id=bt.id,
        amount=bt.amount,
        available_on=bt.available_on,
        created=bt.created,
        currency=bt.currency,
        description=bt.description,
        exchange_rate=float(bt.exchange_rate) if bt.exchange_rate else None,
        fee=bt.fee,
        fee_details=bt.fee_details or [],
        financial_transaction_id=bt.financial_transaction_id,
        funding=bt.funding,
        livemode=bt.livemode,
        net=bt.net,
        reporting_category=bt.reporting_category,
        source=bt.source,
        status=bt.status,
        type=bt.type,
    )


@router.get("", response_model=BalanceResponse)
async def get_balance(
    request: Request,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = BalanceRepository(session)
    if account_id:
        balance = await repo.get_or_create_for_account(account_id)
    else:
        balance = None
    if not balance:
        return BalanceResponse()
    return BalanceResponse(
        available=balance.available or [],
        connect_reserved=balance.connect_reserved or [],
        instant_available=balance.instant_available or [],
        issuing=balance.issuing,
        livemode=balance.livemode,
        pending=balance.pending or [],
    )


@router.get("/transactions/{transaction_id}", response_model=BalanceTransactionResponse)
async def get_balance_transaction(
    transaction_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = BalanceTransactionRepository(session)
    bt = await repo.get_by_id(transaction_id)
    if not bt:
        from payment_platform.shared.exceptions import NotFoundError
        raise NotFoundError(f"Balance transaction {transaction_id} not found")
    return balance_transaction_to_response(bt)


@router.get("/transactions", response_model=PaginatedResponse[BalanceTransactionResponse])
async def list_balance_transactions(
    request: Request,
    limit: int = 10,
    currency: Optional[str] = None,
    type: Optional[str] = None,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = BalanceTransactionRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if currency:
        filters["currency"] = currency.lower()
    if type:
        filters["type"] = type
    transactions = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(transactions) > limit
    if has_more:
        transactions = transactions[:limit]
    return PaginatedResponse(
        data=[balance_transaction_to_response(bt) for bt in transactions],
        has_more=has_more,
    )
