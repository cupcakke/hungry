from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class LinkSessionCreateRequest(BaseModel):
    connection_type: str = Field(..., description="Connection type: plaid, mx, yodlee, finicity, teller")
    products: List[str] = Field(default=["transactions", "balance"], description="Products to enable")
    institution_id: Optional[str] = Field(default=None, description="Pre-selected institution ID")
    client_name: Optional[str] = Field(default=None, description="Client display name")
    webhook: Optional[str] = Field(default=None, description="Webhook URL for events")
    redirect_uri: Optional[str] = Field(default=None, description="OAuth redirect URI")
    country_codes: List[str] = Field(default=["US"], description="Country codes")
    language: str = Field(default="en", description="Language code")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata")


class LinkSessionResponse(BaseModel):
    id: str
    object: str = "link_session"
    account_id: str
    connection_type: str
    products: List[str]
    institution_id: Optional[str] = None
    client_name: Optional[str] = None
    country_codes: List[str]
    language: str
    webhook: Optional[str] = None
    redirect_uri: Optional[str] = None
    oauth_url: Optional[str] = None
    link_token: Optional[str] = None
    status: str
    expires_at: int
    created: int
    metadata: Optional[Dict[str, str]] = None


class FinancialConnectionResponse(BaseModel):
    id: str
    object: str = "financial_connection"
    account_id: str
    institution_id: str
    institution_name: str
    status: str
    connection_type: str
    last_synced_at: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    external_connection_id: Optional[str] = None
    products: Optional[List[str]] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class LinkedAccountResponse(BaseModel):
    id: str
    object: str = "linked_account"
    connection_id: str
    external_account_id: str
    account_type: str
    account_subtype: Optional[str] = None
    account_name: str
    mask: Optional[str] = None
    official_name: Optional[str] = None
    balance_available: Optional[int] = None
    balance_current: Optional[int] = None
    balance_limit: Optional[int] = None
    currency: str
    status: str
    owner_name: Optional[str] = None
    last_balance_update: Optional[int] = None
    last_transaction_update: Optional[int] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class AccountBalanceResponse(BaseModel):
    id: str
    object: str = "account_balance"
    linked_account_id: str
    available: Optional[int] = None
    current: Optional[int] = None
    limit: Optional[int] = None
    currency: str
    as_of: int
    source: Optional[str] = None
    livemode: bool = False


class AccountTransactionResponse(BaseModel):
    id: str
    object: str = "account_transaction"
    linked_account_id: str
    external_transaction_id: str
    amount: int
    currency: str
    description: Optional[str] = None
    merchant_name: Optional[str] = None
    merchant_category_code: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    date: str
    authorized_date: Optional[str] = None
    pending: bool
    transaction_type: str
    payment_channel: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class SyncStatusResponse(BaseModel):
    id: str
    object: str = "sync_status"
    connection_id: str
    status: str
    sync_type: Optional[str] = None
    items_synced: int
    items_failed: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: int
    completed_at: Optional[int] = None
    has_more: bool
    cursor: Optional[str] = None
    created: int
    livemode: bool = False


class InstitutionResponse(BaseModel):
    id: str
    object: str = "institution"
    name: str
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    countries_supported: List[str]
    credentials_type: str
    oauth_enabled: bool
    products: Optional[List[str]] = None
    status: Optional[str] = None
    health_status: Optional[str] = None
    url: Optional[str] = None


class SubscriptionCreateRequest(BaseModel):
    webhook_url: str = Field(..., description="Webhook URL for notifications")
    event_types: List[str] = Field(..., description="Event types to subscribe to")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata")


class SubscriptionResponse(BaseModel):
    id: str
    object: str = "connection_subscription"
    connection_id: str
    account_id: str
    webhook_url: str
    event_types: List[str]
    status: str
    last_triggered_at: Optional[int] = None
    failure_count: int
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class RefreshRequest(BaseModel):
    products: Optional[List[str]] = Field(default=None, description="Products to refresh")


class SyncRequest(BaseModel):
    cursor: Optional[str] = Field(default=None, description="Pagination cursor")
    count: Optional[int] = Field(default=100, description="Number of items to sync")


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


def _dt_to_ts(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    return int(dt.timestamp())


@router.post("/sessions", response_model=LinkSessionResponse, status_code=201)
async def create_link_session(
    request: Request,
    data: LinkSessionCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.financial_connections import (
        LinkSession, ConnectionType, ConnectionStatus
    )
    from sqlalchemy import select
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    connection_type = ConnectionType.PLAID
    if data.connection_type == "mx":
        connection_type = ConnectionType.MX
    elif data.connection_type == "yodlee":
        connection_type = ConnectionType.YODLEE
    elif data.connection_type == "finicity":
        connection_type = ConnectionType.FINICITY
    elif data.connection_type == "teller":
        connection_type = ConnectionType.TELLER
    
    session_id = _generate_id("ls")
    timestamp = _get_timestamp()
    expires_at = datetime.utcnow() + timedelta(hours=24)
    
    link_session = LinkSession(
        id=session_id,
        account_id=account_id,
        connection_type=connection_type,
        products=data.products,
        institution_id=data.institution_id,
        client_name=data.client_name,
        country_codes=data.country_codes,
        language=data.language,
        webhook=data.webhook,
        redirect_uri=data.redirect_uri,
        status="pending",
        expires_at=expires_at,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(link_session)
    await session.flush()
    
    oauth_url = None
    link_token = None
    if connection_type == ConnectionType.PLAID:
        link_token = f"link-sandbox-{session_id}"
        oauth_url = f"https://cdn.plaid.com/link/v2/stable/link.html?token={link_token}"
    elif connection_type == ConnectionType.MX:
        link_token = f"mx-link-{session_id}"
        oauth_url = f"https://int-widgets.moneydesktop.com/md/connect/{session_id}"
    elif connection_type == ConnectionType.TELLER:
        link_token = f"teller-token-{session_id}"
        oauth_url = f"https://teller.io/connect/{session_id}"
    
    return LinkSessionResponse(
        id=link_session.id,
        account_id=link_session.account_id,
        connection_type=link_session.connection_type.value,
        products=link_session.products,
        institution_id=link_session.institution_id,
        client_name=link_session.client_name,
        country_codes=link_session.country_codes,
        language=link_session.language,
        webhook=link_session.webhook,
        redirect_uri=link_session.redirect_uri,
        oauth_url=oauth_url,
        link_token=link_token,
        status=link_session.status,
        expires_at=_dt_to_ts(link_session.expires_at),
        created=link_session.created_at,
        metadata=link_session.metadata_,
    )


@router.get("", response_model=PaginatedResponse[FinancialConnectionResponse])
async def list_connections(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    connection_type: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import FinancialConnection
    
    account_id = _get_account_id(request)
    
    query = select(FinancialConnection)
    if account_id:
        query = query.where(FinancialConnection.account_id == account_id)
    if status:
        query = query.where(FinancialConnection.status == status)
    if connection_type:
        query = query.where(FinancialConnection.connection_type == connection_type)
    if starting_after:
        query = query.where(FinancialConnection.id > starting_after)
    
    query = query.order_by(FinancialConnection.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    connections = list(result.scalars().all())
    
    has_more = len(connections) > limit
    if has_more:
        connections = connections[:limit]
    
    data = [
        FinancialConnectionResponse(
            id=c.id,
            account_id=c.account_id,
            institution_id=c.institution_id,
            institution_name=c.institution_name,
            status=c.status.value,
            connection_type=c.connection_type.value,
            last_synced_at=_dt_to_ts(c.last_synced_at),
            error_code=c.error_code,
            error_message=c.error_message,
            external_connection_id=c.external_connection_id,
            products=c.products,
            created=_dt_to_ts(c.created_at),
            livemode=c.livemode,
            metadata=c.metadata_,
        )
        for c in connections
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/{connection_id}", response_model=FinancialConnectionResponse)
async def get_connection(
    connection_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import FinancialConnection
    
    query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
    result = await session.execute(query)
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise NotFoundError(f"Financial connection {connection_id} not found")
    
    return FinancialConnectionResponse(
        id=connection.id,
        account_id=connection.account_id,
        institution_id=connection.institution_id,
        institution_name=connection.institution_name,
        status=connection.status.value,
        connection_type=connection.connection_type.value,
        last_synced_at=_dt_to_ts(connection.last_synced_at),
        error_code=connection.error_code,
        error_message=connection.error_message,
        external_connection_id=connection.external_connection_id,
        products=connection.products,
        created=_dt_to_ts(connection.created_at),
        livemode=connection.livemode,
        metadata=connection.metadata_,
    )


@router.delete("/{connection_id}")
async def disconnect_connection(
    connection_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import (
        FinancialConnection, ConnectionStatus
    )
    
    query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
    result = await session.execute(query)
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise NotFoundError(f"Financial connection {connection_id} not found")
    
    connection.status = ConnectionStatus.DISCONNECTED
    await session.flush()
    
    return {"id": connection_id, "object": "financial_connection", "deleted": True}


@router.post("/{connection_id}/refresh", response_model=FinancialConnectionResponse)
async def refresh_connection(
    connection_id: str,
    data: RefreshRequest,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import (
        FinancialConnection, ConnectionStatus, SyncStatus, SyncStatusType
    )
    
    query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
    result = await session.execute(query)
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise NotFoundError(f"Financial connection {connection_id} not found")
    
    if connection.status == ConnectionStatus.DISCONNECTED:
        raise ValidationError("Cannot refresh a disconnected connection")
    
    sync_id = _generate_id("sync")
    sync_status = SyncStatus(
        id=sync_id,
        connection_id=connection_id,
        status=SyncStatusType.SYNCING,
        sync_type="refresh",
        started_at=datetime.utcnow(),
    )
    session.add(sync_status)
    
    await session.flush()
    
    return FinancialConnectionResponse(
        id=connection.id,
        account_id=connection.account_id,
        institution_id=connection.institution_id,
        institution_name=connection.institution_name,
        status=connection.status.value,
        connection_type=connection.connection_type.value,
        last_synced_at=_dt_to_ts(connection.last_synced_at),
        error_code=connection.error_code,
        error_message=connection.error_message,
        external_connection_id=connection.external_connection_id,
        products=connection.products,
        created=_dt_to_ts(connection.created_at),
        livemode=connection.livemode,
        metadata=connection.metadata_,
    )


@router.get("/{connection_id}/accounts", response_model=PaginatedResponse[LinkedAccountResponse])
async def list_linked_accounts(
    connection_id: str,
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    account_type: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import LinkedAccount
    
    query = select(LinkedAccount).where(LinkedAccount.connection_id == connection_id)
    if account_type:
        query = query.where(LinkedAccount.account_type == account_type)
    if starting_after:
        query = query.where(LinkedAccount.id > starting_after)
    
    query = query.order_by(LinkedAccount.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    accounts = list(result.scalars().all())
    
    has_more = len(accounts) > limit
    if has_more:
        accounts = accounts[:limit]
    
    data = [
        LinkedAccountResponse(
            id=a.id,
            connection_id=a.connection_id,
            external_account_id=a.external_account_id,
            account_type=a.account_type.value,
            account_subtype=a.account_subtype,
            account_name=a.account_name,
            mask=a.mask,
            official_name=a.official_name,
            balance_available=a.balance_available,
            balance_current=a.balance_current,
            balance_limit=a.balance_limit,
            currency=a.currency,
            status=a.status.value,
            owner_name=a.owner_name,
            last_balance_update=_dt_to_ts(a.last_balance_update),
            last_transaction_update=_dt_to_ts(a.last_transaction_update),
            created=_dt_to_ts(a.created_at),
            livemode=a.livemode,
            metadata=a.metadata_,
        )
        for a in accounts
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/{connection_id}/accounts/{account_id}", response_model=LinkedAccountResponse)
async def get_linked_account(
    connection_id: str,
    account_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import LinkedAccount
    
    query = select(LinkedAccount).where(
        LinkedAccount.id == account_id,
        LinkedAccount.connection_id == connection_id,
    )
    result = await session.execute(query)
    account = result.scalar_one_or_none()
    
    if not account:
        raise NotFoundError(f"Linked account {account_id} not found")
    
    return LinkedAccountResponse(
        id=account.id,
        connection_id=account.connection_id,
        external_account_id=account.external_account_id,
        account_type=account.account_type.value,
        account_subtype=account.account_subtype,
        account_name=account.account_name,
        mask=account.mask,
        official_name=account.official_name,
        balance_available=account.balance_available,
        balance_current=account.balance_current,
        balance_limit=account.balance_limit,
        currency=account.currency,
        status=account.status.value,
        owner_name=account.owner_name,
        last_balance_update=_dt_to_ts(account.last_balance_update),
        last_transaction_update=_dt_to_ts(account.last_transaction_update),
        created=_dt_to_ts(account.created_at),
        livemode=account.livemode,
        metadata=account.metadata_,
    )


@router.get("/{connection_id}/accounts/{account_id}/balance", response_model=AccountBalanceResponse)
async def get_account_balance(
    connection_id: str,
    account_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import LinkedAccount, AccountBalance
    
    query = select(LinkedAccount).where(
        LinkedAccount.id == account_id,
        LinkedAccount.connection_id == connection_id,
    )
    result = await session.execute(query)
    account = result.scalar_one_or_none()
    
    if not account:
        raise NotFoundError(f"Linked account {account_id} not found")
    
    balance_query = select(AccountBalance).where(
        AccountBalance.linked_account_id == account_id
    ).order_by(AccountBalance.as_of.desc())
    balance_result = await session.execute(balance_query)
    balance = balance_result.scalar_one_or_none()
    
    if not balance:
        balance = AccountBalance(
            id=_generate_id("bal"),
            linked_account_id=account_id,
            available=account.balance_available,
            current=account.balance_current,
            limit=account.balance_limit,
            currency=account.currency,
            as_of=datetime.utcnow(),
        )
        session.add(balance)
        await session.flush()
    
    return AccountBalanceResponse(
        id=balance.id,
        linked_account_id=balance.linked_account_id,
        available=balance.available,
        current=balance.current,
        limit=balance.limit,
        currency=balance.currency,
        as_of=_dt_to_ts(balance.as_of),
        source=balance.source,
        livemode=balance.livemode,
    )


@router.get("/{connection_id}/accounts/{account_id}/transactions", response_model=PaginatedResponse[AccountTransactionResponse])
async def list_account_transactions(
    connection_id: str,
    account_id: str,
    request: Request,
    limit: int = 50,
    starting_after: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    pending: Optional[bool] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import AccountTransaction
    from datetime import datetime as dt
    
    query = select(AccountTransaction).where(
        AccountTransaction.linked_account_id == account_id
    )
    
    if start_date:
        query = query.where(AccountTransaction.date >= dt.strptime(start_date, "%Y-%m-%d").date())
    if end_date:
        query = query.where(AccountTransaction.date <= dt.strptime(end_date, "%Y-%m-%d").date())
    if category:
        query = query.where(AccountTransaction.category == category)
    if pending is not None:
        query = query.where(AccountTransaction.pending == pending)
    if starting_after:
        query = query.where(AccountTransaction.id > starting_after)
    
    query = query.order_by(AccountTransaction.date.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    transactions = list(result.scalars().all())
    
    has_more = len(transactions) > limit
    if has_more:
        transactions = transactions[:limit]
    
    data = [
        AccountTransactionResponse(
            id=t.id,
            linked_account_id=t.linked_account_id,
            external_transaction_id=t.external_transaction_id,
            amount=t.amount,
            currency=t.currency,
            description=t.description,
            merchant_name=t.merchant_name,
            merchant_category_code=t.merchant_category_code,
            category=t.category,
            subcategory=t.subcategory,
            date=t.date.isoformat(),
            authorized_date=t.authorized_date.isoformat() if t.authorized_date else None,
            pending=t.pending,
            transaction_type=t.transaction_type.value,
            payment_channel=t.payment_channel,
            location=t.location,
            created=_dt_to_ts(t.created_at),
            livemode=t.livemode,
            metadata=t.metadata_,
        )
        for t in transactions
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/{connection_id}/sync", response_model=SyncStatusResponse, status_code=201)
async def trigger_sync(
    connection_id: str,
    data: SyncRequest,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import (
        FinancialConnection, SyncStatus, SyncStatusType, ConnectionStatus
    )
    
    query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
    result = await session.execute(query)
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise NotFoundError(f"Financial connection {connection_id} not found")
    
    if connection.status != ConnectionStatus.ACTIVE:
        raise ValidationError("Connection must be active to sync")
    
    sync_id = _generate_id("sync")
    sync_status = SyncStatus(
        id=sync_id,
        connection_id=connection_id,
        status=SyncStatusType.SYNCING,
        sync_type="full",
        started_at=datetime.utcnow(),
        cursor=data.cursor,
    )
    session.add(sync_status)
    await session.flush()
    
    return SyncStatusResponse(
        id=sync_status.id,
        connection_id=sync_status.connection_id,
        status=sync_status.status.value,
        sync_type=sync_status.sync_type,
        items_synced=sync_status.items_synced,
        items_failed=sync_status.items_failed,
        error_code=sync_status.error_code,
        error_message=sync_status.error_message,
        started_at=_dt_to_ts(sync_status.started_at),
        completed_at=_dt_to_ts(sync_status.completed_at),
        has_more=sync_status.has_more,
        cursor=sync_status.cursor,
        created=_dt_to_ts(sync_status.created_at),
        livemode=sync_status.livemode,
    )


@router.get("/{connection_id}/sync_status", response_model=SyncStatusResponse)
async def get_sync_status(
    connection_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import SyncStatus
    
    query = select(SyncStatus).where(
        SyncStatus.connection_id == connection_id
    ).order_by(SyncStatus.created_at.desc())
    result = await session.execute(query)
    sync_status = result.scalar_one_or_none()
    
    if not sync_status:
        raise NotFoundError(f"No sync status found for connection {connection_id}")
    
    return SyncStatusResponse(
        id=sync_status.id,
        connection_id=sync_status.connection_id,
        status=sync_status.status.value,
        sync_type=sync_status.sync_type,
        items_synced=sync_status.items_synced,
        items_failed=sync_status.items_failed,
        error_code=sync_status.error_code,
        error_message=sync_status.error_message,
        started_at=_dt_to_ts(sync_status.started_at),
        completed_at=_dt_to_ts(sync_status.completed_at),
        has_more=sync_status.has_more,
        cursor=sync_status.cursor,
        created=_dt_to_ts(sync_status.created_at),
        livemode=sync_status.livemode,
    )


@router.get("/institutions", response_model=PaginatedResponse[InstitutionResponse])
async def list_institutions(
    request: Request,
    limit: int = 50,
    starting_after: Optional[str] = None,
    country: Optional[str] = None,
    products: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import Institution
    
    query = select(Institution)
    if country:
        query = query.where(Institution.countries_supported.contains([country]))
    if starting_after:
        query = query.where(Institution.id > starting_after)
    
    query = query.order_by(Institution.name).limit(limit + 1)
    
    result = await session.execute(query)
    institutions = list(result.scalars().all())
    
    has_more = len(institutions) > limit
    if has_more:
        institutions = institutions[:limit]
    
    data = [
        InstitutionResponse(
            id=i.id,
            name=i.name,
            logo_url=i.logo_url,
            primary_color=i.primary_color,
            countries_supported=i.countries_supported,
            credentials_type=i.credentials_type.value,
            oauth_enabled=i.oauth_enabled,
            products=i.products,
            status=i.status,
            health_status=i.health_status,
            url=i.url,
        )
        for i in institutions
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/institutions/{institution_id}", response_model=InstitutionResponse)
async def get_institution(
    institution_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import Institution
    
    query = select(Institution).where(Institution.id == institution_id)
    result = await session.execute(query)
    institution = result.scalar_one_or_none()
    
    if not institution:
        raise NotFoundError(f"Institution {institution_id} not found")
    
    return InstitutionResponse(
        id=institution.id,
        name=institution.name,
        logo_url=institution.logo_url,
        primary_color=institution.primary_color,
        countries_supported=institution.countries_supported,
        credentials_type=institution.credentials_type.value,
        oauth_enabled=institution.oauth_enabled,
        products=institution.products,
        status=institution.status,
        health_status=institution.health_status,
        url=institution.url,
    )


@router.post("/{connection_id}/subscribe", response_model=SubscriptionResponse, status_code=201)
async def subscribe_to_updates(
    connection_id: str,
    data: SubscriptionCreateRequest,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.financial_connections import (
        FinancialConnection, ConnectionSubscription
    )
    import secrets
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
    result = await session.execute(query)
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise NotFoundError(f"Financial connection {connection_id} not found")
    
    subscription_id = _generate_id("sub")
    timestamp = _get_timestamp()
    secret = secrets.token_hex(32)
    
    subscription = ConnectionSubscription(
        id=subscription_id,
        connection_id=connection_id,
        account_id=account_id,
        webhook_url=data.webhook_url,
        event_types=data.event_types,
        secret=secret,
        status="active",
        metadata_=data.metadata,
    )
    
    session.add(subscription)
    await session.flush()
    
    return SubscriptionResponse(
        id=subscription.id,
        connection_id=subscription.connection_id,
        account_id=subscription.account_id,
        webhook_url=subscription.webhook_url,
        event_types=subscription.event_types,
        status=subscription.status,
        last_triggered_at=_dt_to_ts(subscription.last_triggered_at),
        failure_count=subscription.failure_count,
        created=_dt_to_ts(subscription.created_at),
        livemode=subscription.livemode,
        metadata=subscription.metadata_,
    )


@router.delete("/{connection_id}/subscribe")
async def unsubscribe_from_updates(
    connection_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select, delete
    from payment_platform.backend.domain.financial_connections import ConnectionSubscription
    
    account_id = _get_account_id(request)
    
    stmt = delete(ConnectionSubscription).where(
        ConnectionSubscription.connection_id == connection_id,
    )
    if account_id:
        stmt = stmt.where(ConnectionSubscription.account_id == account_id)
    
    result = await session.execute(stmt)
    await session.flush()
    
    return {"id": connection_id, "object": "connection_subscription", "deleted": True}
