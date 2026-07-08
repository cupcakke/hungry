from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, TreasuryError

router = APIRouter()


class FinancialAccountCreateRequest(BaseModel):
    account_type: str = Field(default="checking", description="Account type: checking or savings")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    features: Optional[List[str]] = Field(default=None, description="Features to enable")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class FinancialAccountResponse(BaseModel):
    id: str
    object: str = "treasury.financial_account"
    account_id: Optional[str] = None
    account_type: str
    currency: str
    balance: int
    available_balance: int
    pending_balance: int
    reserved_balance: int
    status: str
    features: Optional[Dict[str, Any]] = None
    active_features: Optional[List[str]] = None
    pending_features: Optional[List[str]] = None
    restricted_features: Optional[List[str]] = None
    routing_numbers: Optional[Dict[str, Any]] = None
    financial_addresses: Optional[List[Dict[str, Any]]] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class FinancialAccountFeaturesResponse(BaseModel):
    financial_account_id: str
    active_features: List[str] = []
    pending_features: List[str] = []
    restricted_features: List[str] = []
    status: Dict[str, Any] = {}


class InboundTransferCreateRequest(BaseModel):
    financial_account_id: str = Field(..., description="Financial account ID")
    amount: int = Field(..., gt=0, description="Amount in cents")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    origin_payment_method: Optional[str] = Field(default=None, description="Origin payment method ID")
    network: str = Field(..., description="Network: ach, wire, or sepa")
    statement_descriptor: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class InboundTransferResponse(BaseModel):
    id: str
    object: str = "treasury.inbound_transfer"
    financial_account_id: str
    amount: int
    currency: str
    status: str
    origin_payment_method: Optional[str] = None
    origin_payment_method_details: Optional[Dict[str, Any]] = None
    network: str
    statement_descriptor: Optional[str] = None
    expected_arrival_date: Optional[int] = None
    arrived_at: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    transaction_id: Optional[str] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class OutboundTransferCreateRequest(BaseModel):
    financial_account_id: str = Field(..., description="Financial account ID")
    amount: int = Field(..., gt=0, description="Amount in cents")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    destination_payment_method: Optional[str] = Field(default=None, description="Destination payment method ID")
    network: str = Field(..., description="Network: ach, wire, or sepa")
    statement_descriptor: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class OutboundTransferResponse(BaseModel):
    id: str
    object: str = "treasury.outbound_transfer"
    financial_account_id: str
    amount: int
    currency: str
    status: str
    destination_payment_method: Optional[str] = None
    destination_payment_method_details: Optional[Dict[str, Any]] = None
    network: str
    statement_descriptor: Optional[str] = None
    expected_arrival_date: Optional[int] = None
    posted_at: Optional[int] = None
    returned_at: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    transaction_id: Optional[str] = None
    returned_details: Optional[Dict[str, Any]] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class OutboundPaymentCreateRequest(BaseModel):
    financial_account_id: str = Field(..., description="Financial account ID")
    amount: int = Field(..., gt=0, description="Amount in cents")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    recipient_payment_method: Optional[str] = Field(default=None, description="Recipient payment method ID")
    statement_descriptor: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class OutboundPaymentResponse(BaseModel):
    id: str
    object: str = "treasury.outbound_payment"
    financial_account_id: str
    amount: int
    currency: str
    status: str
    recipient_payment_method: Optional[str] = None
    recipient_payment_method_details: Optional[Dict[str, Any]] = None
    statement_descriptor: Optional[str] = None
    expected_arrival_date: Optional[int] = None
    posted_at: Optional[int] = None
    returned_at: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    transaction_id: Optional[str] = None
    returned_details: Optional[Dict[str, Any]] = None
    cancelable: bool = True
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class TransactionEntryResponse(BaseModel):
    id: str
    object: str = "treasury.transaction_entry"
    financial_account_id: str
    transaction_id: Optional[str] = None
    flow_type: str
    flow_id: Optional[str] = None
    flow_details: Optional[Dict[str, Any]] = None
    amount: int
    currency: str
    balance_after: int
    available_balance_after: int
    pending_balance_after: int
    effective_at: int
    created: int
    livemode: bool = False


class CreditBalanceResponse(BaseModel):
    id: str
    object: str = "treasury.credit_balance"
    financial_account_id: str
    available: int
    pending: int
    reserved: int
    currency: str
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


@router.post("/financial_accounts", response_model=FinancialAccountResponse, status_code=201)
async def create_financial_account(
    request: Request,
    data: FinancialAccountCreateRequest,
    session = Depends(get_session),
):
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    from payment_platform.backend.domain.treasury import (
        TreasuryFinancialAccount, FinancialAccountType, FinancialAccountStatus
    )
    
    account_type = FinancialAccountType.CHECKING
    if data.account_type == "savings":
        account_type = FinancialAccountType.SAVINGS
    
    fa_id = _generate_id("fa")
    timestamp = _get_timestamp()
    
    financial_account = TreasuryFinancialAccount(
        id=fa_id,
        account_id=account_id,
        account_type=account_type,
        currency=data.currency.lower(),
        balance=0,
        available_balance=0,
        pending_balance=0,
        reserved_balance=0,
        status=FinancialAccountStatus.OPEN,
        features={"inbound_transfers": True, "outbound_transfers": True},
        active_features=data.features or ["inbound_transfers", "outbound_transfers"],
        routing_numbers={"ach": {"routing_number": "021000021", "account_number": f"****{fa_id[-4:]}"}},
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(financial_account)
    await session.flush()
    
    return FinancialAccountResponse(
        id=financial_account.id,
        account_id=financial_account.account_id,
        account_type=financial_account.account_type.value,
        currency=financial_account.currency,
        balance=financial_account.balance,
        available_balance=financial_account.available_balance,
        pending_balance=financial_account.pending_balance,
        reserved_balance=financial_account.reserved_balance,
        status=financial_account.status.value,
        features=financial_account.features,
        active_features=financial_account.active_features,
        pending_features=financial_account.pending_features,
        restricted_features=financial_account.restricted_features,
        routing_numbers=financial_account.routing_numbers,
        financial_addresses=financial_account.financial_addresses,
        created=financial_account.created,
        metadata=financial_account.metadata_,
    )


@router.get("/financial_accounts", response_model=PaginatedResponse[FinancialAccountResponse])
async def list_financial_accounts(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    currency: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import TreasuryFinancialAccount
    
    account_id = _get_account_id(request)
    
    query = select(TreasuryFinancialAccount)
    if account_id:
        query = query.where(TreasuryFinancialAccount.account_id == account_id)
    if status:
        query = query.where(TreasuryFinancialAccount.status == status)
    if currency:
        query = query.where(TreasuryFinancialAccount.currency == currency.lower())
    if starting_after:
        query = query.where(TreasuryFinancialAccount.id > starting_after)
    
    query = query.order_by(TreasuryFinancialAccount.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    accounts = list(result.scalars().all())
    
    has_more = len(accounts) > limit
    if has_more:
        accounts = accounts[:limit]
    
    data = [
        FinancialAccountResponse(
            id=fa.id,
            account_id=fa.account_id,
            account_type=fa.account_type.value,
            currency=fa.currency,
            balance=fa.balance,
            available_balance=fa.available_balance,
            pending_balance=fa.pending_balance,
            reserved_balance=fa.reserved_balance,
            status=fa.status.value,
            features=fa.features,
            active_features=fa.active_features,
            pending_features=fa.pending_features,
            restricted_features=fa.restricted_features,
            routing_numbers=fa.routing_numbers,
            financial_addresses=fa.financial_addresses,
            created=fa.created,
            metadata=fa.metadata_,
        )
        for fa in accounts
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/financial_accounts/{financial_account_id}", response_model=FinancialAccountResponse)
async def get_financial_account(
    financial_account_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import TreasuryFinancialAccount
    
    query = select(TreasuryFinancialAccount).where(TreasuryFinancialAccount.id == financial_account_id)
    result = await session.execute(query)
    fa = result.scalar_one_or_none()
    
    if not fa:
        raise NotFoundError(f"Financial account {financial_account_id} not found")
    
    return FinancialAccountResponse(
        id=fa.id,
        account_id=fa.account_id,
        account_type=fa.account_type.value,
        currency=fa.currency,
        balance=fa.balance,
        available_balance=fa.available_balance,
        pending_balance=fa.pending_balance,
        reserved_balance=fa.reserved_balance,
        status=fa.status.value,
        features=fa.features,
        active_features=fa.active_features,
        pending_features=fa.pending_features,
        restricted_features=fa.restricted_features,
        routing_numbers=fa.routing_numbers,
        financial_addresses=fa.financial_addresses,
        created=fa.created,
        metadata=fa.metadata_,
    )


@router.get("/financial_accounts/{financial_account_id}/features", response_model=FinancialAccountFeaturesResponse)
async def get_financial_account_features(
    financial_account_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import TreasuryFinancialAccount
    
    query = select(TreasuryFinancialAccount).where(TreasuryFinancialAccount.id == financial_account_id)
    result = await session.execute(query)
    fa = result.scalar_one_or_none()
    
    if not fa:
        raise NotFoundError(f"Financial account {financial_account_id} not found")
    
    return FinancialAccountFeaturesResponse(
        financial_account_id=fa.id,
        active_features=fa.active_features or [],
        pending_features=fa.pending_features or [],
        restricted_features=fa.restricted_features or [],
        status={"inbound_transfers": "active", "outbound_transfers": "active"},
    )


@router.post("/inbound_transfers", response_model=InboundTransferResponse, status_code=201)
async def create_inbound_transfer(
    request: Request,
    data: InboundTransferCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.treasury import (
        InboundTransfer, InboundTransferStatus, TransferNetwork, TreasuryFinancialAccount
    )
    from sqlalchemy import select
    
    query = select(TreasuryFinancialAccount).where(TreasuryFinancialAccount.id == data.financial_account_id)
    result = await session.execute(query)
    fa = result.scalar_one_or_none()
    
    if not fa:
        raise NotFoundError(f"Financial account {data.financial_account_id} not found")
    
    if data.currency.lower() != fa.currency:
        raise ValidationError(f"Currency mismatch. Expected {fa.currency}, got {data.currency}")
    
    network = TransferNetwork.ACH
    if data.network == "wire":
        network = TransferNetwork.WIRE
    elif data.network == "sepa":
        network = TransferNetwork.SEPA
    
    transfer_id = _generate_id("ibt")
    timestamp = _get_timestamp()
    expected_arrival = timestamp + 86400 * 2
    
    inbound_transfer = InboundTransfer(
        id=transfer_id,
        financial_account_id=data.financial_account_id,
        amount=data.amount,
        currency=data.currency.lower(),
        status=InboundTransferStatus.PENDING,
        origin_payment_method=data.origin_payment_method,
        network=network,
        statement_descriptor=data.statement_descriptor,
        expected_arrival_date=expected_arrival,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(inbound_transfer)
    
    fa.pending_balance += data.amount
    
    await session.flush()
    
    return InboundTransferResponse(
        id=inbound_transfer.id,
        financial_account_id=inbound_transfer.financial_account_id,
        amount=inbound_transfer.amount,
        currency=inbound_transfer.currency,
        status=inbound_transfer.status.value,
        origin_payment_method=inbound_transfer.origin_payment_method,
        network=inbound_transfer.network.value,
        statement_descriptor=inbound_transfer.statement_descriptor,
        expected_arrival_date=inbound_transfer.expected_arrival_date,
        created=inbound_transfer.created,
        metadata=inbound_transfer.metadata_,
    )


@router.get("/inbound_transfers", response_model=PaginatedResponse[InboundTransferResponse])
async def list_inbound_transfers(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    financial_account_id: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import InboundTransfer
    
    query = select(InboundTransfer)
    if financial_account_id:
        query = query.where(InboundTransfer.financial_account_id == financial_account_id)
    if status:
        query = query.where(InboundTransfer.status == status)
    if starting_after:
        query = query.where(InboundTransfer.id > starting_after)
    
    query = query.order_by(InboundTransfer.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    transfers = list(result.scalars().all())
    
    has_more = len(transfers) > limit
    if has_more:
        transfers = transfers[:limit]
    
    data = [
        InboundTransferResponse(
            id=t.id,
            financial_account_id=t.financial_account_id,
            amount=t.amount,
            currency=t.currency,
            status=t.status.value,
            origin_payment_method=t.origin_payment_method,
            origin_payment_method_details=t.origin_payment_method_details,
            network=t.network.value,
            statement_descriptor=t.statement_descriptor,
            expected_arrival_date=t.expected_arrival_date,
            arrived_at=t.arrived_at,
            failure_code=t.failure_code,
            failure_message=t.failure_message,
            transaction_id=t.transaction_id,
            created=t.created,
            metadata=t.metadata_,
        )
        for t in transfers
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/inbound_transfers/{transfer_id}", response_model=InboundTransferResponse)
async def get_inbound_transfer(
    transfer_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import InboundTransfer
    
    query = select(InboundTransfer).where(InboundTransfer.id == transfer_id)
    result = await session.execute(query)
    transfer = result.scalar_one_or_none()
    
    if not transfer:
        raise NotFoundError(f"Inbound transfer {transfer_id} not found")
    
    return InboundTransferResponse(
        id=transfer.id,
        financial_account_id=transfer.financial_account_id,
        amount=transfer.amount,
        currency=transfer.currency,
        status=transfer.status.value,
        origin_payment_method=transfer.origin_payment_method,
        origin_payment_method_details=transfer.origin_payment_method_details,
        network=transfer.network.value,
        statement_descriptor=transfer.statement_descriptor,
        expected_arrival_date=transfer.expected_arrival_date,
        arrived_at=transfer.arrived_at,
        failure_code=transfer.failure_code,
        failure_message=transfer.failure_message,
        transaction_id=transfer.transaction_id,
        created=transfer.created,
        metadata=transfer.metadata_,
    )


@router.post("/outbound_transfers", response_model=OutboundTransferResponse, status_code=201)
async def create_outbound_transfer(
    request: Request,
    data: OutboundTransferCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.treasury import (
        OutboundTransfer, OutboundTransferStatus, TransferNetwork, TreasuryFinancialAccount
    )
    from sqlalchemy import select
    
    query = select(TreasuryFinancialAccount).where(TreasuryFinancialAccount.id == data.financial_account_id)
    result = await session.execute(query)
    fa = result.scalar_one_or_none()
    
    if not fa:
        raise NotFoundError(f"Financial account {data.financial_account_id} not found")
    
    if data.currency.lower() != fa.currency:
        raise ValidationError(f"Currency mismatch. Expected {fa.currency}, got {data.currency}")
    
    if fa.available_balance < data.amount:
        from payment_platform.shared.exceptions import InsufficientBalanceError
        raise InsufficientBalanceError(
            available_amount=fa.available_balance,
            requested_amount=data.amount,
            currency=fa.currency,
        )
    
    network = TransferNetwork.ACH
    if data.network == "wire":
        network = TransferNetwork.WIRE
    elif data.network == "sepa":
        network = TransferNetwork.SEPA
    
    transfer_id = _generate_id("obt")
    timestamp = _get_timestamp()
    expected_arrival = timestamp + 86400 * 2
    
    outbound_transfer = OutboundTransfer(
        id=transfer_id,
        financial_account_id=data.financial_account_id,
        amount=data.amount,
        currency=data.currency.lower(),
        status=OutboundTransferStatus.PENDING,
        destination_payment_method=data.destination_payment_method,
        network=network,
        statement_descriptor=data.statement_descriptor,
        expected_arrival_date=expected_arrival,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(outbound_transfer)
    
    fa.available_balance -= data.amount
    fa.pending_balance += data.amount
    
    await session.flush()
    
    return OutboundTransferResponse(
        id=outbound_transfer.id,
        financial_account_id=outbound_transfer.financial_account_id,
        amount=outbound_transfer.amount,
        currency=outbound_transfer.currency,
        status=outbound_transfer.status.value,
        destination_payment_method=outbound_transfer.destination_payment_method,
        network=outbound_transfer.network.value,
        statement_descriptor=outbound_transfer.statement_descriptor,
        expected_arrival_date=outbound_transfer.expected_arrival_date,
        created=outbound_transfer.created,
        metadata=outbound_transfer.metadata_,
    )


@router.get("/outbound_transfers", response_model=PaginatedResponse[OutboundTransferResponse])
async def list_outbound_transfers(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    financial_account_id: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import OutboundTransfer
    
    query = select(OutboundTransfer)
    if financial_account_id:
        query = query.where(OutboundTransfer.financial_account_id == financial_account_id)
    if status:
        query = query.where(OutboundTransfer.status == status)
    if starting_after:
        query = query.where(OutboundTransfer.id > starting_after)
    
    query = query.order_by(OutboundTransfer.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    transfers = list(result.scalars().all())
    
    has_more = len(transfers) > limit
    if has_more:
        transfers = transfers[:limit]
    
    data = [
        OutboundTransferResponse(
            id=t.id,
            financial_account_id=t.financial_account_id,
            amount=t.amount,
            currency=t.currency,
            status=t.status.value,
            destination_payment_method=t.destination_payment_method,
            destination_payment_method_details=t.destination_payment_method_details,
            network=t.network.value,
            statement_descriptor=t.statement_descriptor,
            expected_arrival_date=t.expected_arrival_date,
            posted_at=t.posted_at,
            returned_at=t.returned_at,
            failure_code=t.failure_code,
            failure_message=t.failure_message,
            transaction_id=t.transaction_id,
            returned_details=t.returned_details,
            created=t.created,
            metadata=t.metadata_,
        )
        for t in transfers
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/outbound_transfers/{transfer_id}", response_model=OutboundTransferResponse)
async def get_outbound_transfer(
    transfer_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import OutboundTransfer
    
    query = select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
    result = await session.execute(query)
    transfer = result.scalar_one_or_none()
    
    if not transfer:
        raise NotFoundError(f"Outbound transfer {transfer_id} not found")
    
    return OutboundTransferResponse(
        id=transfer.id,
        financial_account_id=transfer.financial_account_id,
        amount=transfer.amount,
        currency=transfer.currency,
        status=transfer.status.value,
        destination_payment_method=transfer.destination_payment_method,
        destination_payment_method_details=transfer.destination_payment_method_details,
        network=transfer.network.value,
        statement_descriptor=transfer.statement_descriptor,
        expected_arrival_date=transfer.expected_arrival_date,
        posted_at=transfer.posted_at,
        returned_at=transfer.returned_at,
        failure_code=transfer.failure_code,
        failure_message=transfer.failure_message,
        transaction_id=transfer.transaction_id,
        returned_details=transfer.returned_details,
        created=transfer.created,
        metadata=transfer.metadata_,
    )


@router.post("/outbound_payments", response_model=OutboundPaymentResponse, status_code=201)
async def create_outbound_payment(
    request: Request,
    data: OutboundPaymentCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.treasury import (
        OutboundPayment, OutboundPaymentStatus, TreasuryFinancialAccount
    )
    from sqlalchemy import select
    
    query = select(TreasuryFinancialAccount).where(TreasuryFinancialAccount.id == data.financial_account_id)
    result = await session.execute(query)
    fa = result.scalar_one_or_none()
    
    if not fa:
        raise NotFoundError(f"Financial account {data.financial_account_id} not found")
    
    if data.currency.lower() != fa.currency:
        raise ValidationError(f"Currency mismatch. Expected {fa.currency}, got {data.currency}")
    
    if fa.available_balance < data.amount:
        from payment_platform.shared.exceptions import InsufficientBalanceError
        raise InsufficientBalanceError(
            available_amount=fa.available_balance,
            requested_amount=data.amount,
            currency=fa.currency,
        )
    
    payment_id = _generate_id("obp")
    timestamp = _get_timestamp()
    expected_arrival = timestamp + 86400 * 3
    
    outbound_payment = OutboundPayment(
        id=payment_id,
        financial_account_id=data.financial_account_id,
        amount=data.amount,
        currency=data.currency.lower(),
        status=OutboundPaymentStatus.PENDING,
        recipient_payment_method=data.recipient_payment_method,
        statement_descriptor=data.statement_descriptor,
        expected_arrival_date=expected_arrival,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(outbound_payment)
    
    fa.available_balance -= data.amount
    fa.pending_balance += data.amount
    
    await session.flush()
    
    return OutboundPaymentResponse(
        id=outbound_payment.id,
        financial_account_id=outbound_payment.financial_account_id,
        amount=outbound_payment.amount,
        currency=outbound_payment.currency,
        status=outbound_payment.status.value,
        recipient_payment_method=outbound_payment.recipient_payment_method,
        statement_descriptor=outbound_payment.statement_descriptor,
        expected_arrival_date=outbound_payment.expected_arrival_date,
        created=outbound_payment.created,
        metadata=outbound_payment.metadata_,
    )


@router.get("/outbound_payments", response_model=PaginatedResponse[OutboundPaymentResponse])
async def list_outbound_payments(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    financial_account_id: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import OutboundPayment
    
    query = select(OutboundPayment)
    if financial_account_id:
        query = query.where(OutboundPayment.financial_account_id == financial_account_id)
    if status:
        query = query.where(OutboundPayment.status == status)
    if starting_after:
        query = query.where(OutboundPayment.id > starting_after)
    
    query = query.order_by(OutboundPayment.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    payments = list(result.scalars().all())
    
    has_more = len(payments) > limit
    if has_more:
        payments = payments[:limit]
    
    data = [
        OutboundPaymentResponse(
            id=p.id,
            financial_account_id=p.financial_account_id,
            amount=p.amount,
            currency=p.currency,
            status=p.status.value,
            recipient_payment_method=p.recipient_payment_method,
            recipient_payment_method_details=p.recipient_payment_method_details,
            statement_descriptor=p.statement_descriptor,
            expected_arrival_date=p.expected_arrival_date,
            posted_at=p.posted_at,
            returned_at=p.returned_at,
            failure_code=p.failure_code,
            failure_message=p.failure_message,
            transaction_id=p.transaction_id,
            returned_details=p.returned_details,
            cancelable=p.cancelable,
            created=p.created,
            metadata=p.metadata_,
        )
        for p in payments
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/transactions", response_model=PaginatedResponse[TransactionEntryResponse])
async def list_transactions(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    financial_account_id: Optional[str] = None,
    flow_type: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import TransactionEntry
    
    query = select(TransactionEntry)
    if financial_account_id:
        query = query.where(TransactionEntry.financial_account_id == financial_account_id)
    if flow_type:
        query = query.where(TransactionEntry.flow_type == flow_type)
    if starting_after:
        query = query.where(TransactionEntry.id > starting_after)
    
    query = query.order_by(TransactionEntry.effective_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    entries = list(result.scalars().all())
    
    has_more = len(entries) > limit
    if has_more:
        entries = entries[:limit]
    
    data = [
        TransactionEntryResponse(
            id=e.id,
            financial_account_id=e.financial_account_id,
            transaction_id=e.transaction_id,
            flow_type=e.flow_type.value,
            flow_id=e.flow_id,
            flow_details=e.flow_details,
            amount=e.amount,
            currency=e.currency,
            balance_after=e.balance_after,
            available_balance_after=e.available_balance_after,
            pending_balance_after=e.pending_balance_after,
            effective_at=e.effective_at,
            created=e.created,
        )
        for e in entries
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/entries", response_model=PaginatedResponse[TransactionEntryResponse])
async def list_entries(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    financial_account_id: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import TransactionEntry
    
    query = select(TransactionEntry)
    if financial_account_id:
        query = query.where(TransactionEntry.financial_account_id == financial_account_id)
    if starting_after:
        query = query.where(TransactionEntry.id > starting_after)
    
    query = query.order_by(TransactionEntry.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    entries = list(result.scalars().all())
    
    has_more = len(entries) > limit
    if has_more:
        entries = entries[:limit]
    
    data = [
        TransactionEntryResponse(
            id=e.id,
            financial_account_id=e.financial_account_id,
            transaction_id=e.transaction_id,
            flow_type=e.flow_type.value,
            flow_id=e.flow_id,
            flow_details=e.flow_details,
            amount=e.amount,
            currency=e.currency,
            balance_after=e.balance_after,
            available_balance_after=e.available_balance_after,
            pending_balance_after=e.pending_balance_after,
            effective_at=e.effective_at,
            created=e.created,
        )
        for e in entries
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/credit_balance", response_model=CreditBalanceResponse)
async def get_credit_balance(
    request: Request,
    financial_account_id: str,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.treasury import CreditBalance, TreasuryFinancialAccount
    
    fa_query = select(TreasuryFinancialAccount).where(TreasuryFinancialAccount.id == financial_account_id)
    fa_result = await session.execute(fa_query)
    fa = fa_result.scalar_one_or_none()
    
    if not fa:
        raise NotFoundError(f"Financial account {financial_account_id} not found")
    
    query = select(CreditBalance).where(CreditBalance.financial_account_id == financial_account_id)
    result = await session.execute(query)
    balance = result.scalar_one_or_none()
    
    if not balance:
        balance = CreditBalance(
            id=_generate_id("cb"),
            financial_account_id=financial_account_id,
            available=fa.available_balance,
            pending=fa.pending_balance,
            reserved=fa.reserved_balance,
            currency=fa.currency,
        )
        session.add(balance)
        await session.flush()
    
    return CreditBalanceResponse(
        id=balance.id,
        financial_account_id=balance.financial_account_id,
        available=balance.available,
        pending=balance.pending,
        reserved=balance.reserved,
        currency=balance.currency,
    )
