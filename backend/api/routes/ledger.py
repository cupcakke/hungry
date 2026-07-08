from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.application.services.ledger_service import (
    CreateAccountService,
    PostEntryService,
    BalanceQueryService,
    ReconciliationService,
)
from payment_platform.backend.domain.ledger import LedgerAccount, LedgerEntry, JournalEntry
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class LedgerAccountCreateRequest(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=50, description="Unique account code")
    name: str = Field(..., min_length=1, max_length=200, description="Account name")
    account_type: str = Field(..., description="Account type: asset, liability, equity, revenue, expense")
    currency: str = Field(..., min_length=3, max_length=3, description="3-letter currency code")
    description: Optional[str] = Field(default=None, max_length=500)
    parent_account_code: Optional[str] = Field(default=None, max_length=50)
    allow_negative: bool = Field(default=False)
    is_system_account: bool = Field(default=False)
    initial_balance: int = Field(default=0)
    metadata: Optional[Dict[str, str]] = Field(default=None)


class LedgerAccountUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = Field(default=None)
    allow_negative: Optional[bool] = Field(default=None)
    metadata: Optional[Dict[str, str]] = Field(default=None)


class JournalEntryCreateRequest(BaseModel):
    debit_account_code: str = Field(..., min_length=1, max_length=50)
    credit_account_code: str = Field(..., min_length=1, max_length=50)
    amount: int = Field(..., gt=0, description="Amount in smallest currency unit")
    currency: str = Field(..., min_length=3, max_length=3)
    reference_type: Optional[str] = Field(default=None, max_length=30)
    reference_id: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, str]] = Field(default=None)


class CompoundEntryLine(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=50)
    entry_type: str = Field(..., pattern="^(debit|credit)$")
    amount: int = Field(..., gt=0)


class CompoundJournalEntryRequest(BaseModel):
    entries: List[CompoundEntryLine] = Field(..., min_length=2)
    currency: str = Field(..., min_length=3, max_length=3)
    description: Optional[str] = Field(default=None, max_length=500)
    reference_type: Optional[str] = Field(default=None, max_length=30)
    reference_id: Optional[str] = Field(default=None, max_length=50)
    metadata: Optional[Dict[str, str]] = Field(default=None)


class BalanceAssertionRequest(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=50)
    expected_balance: int = Field(...)
    notes: Optional[str] = Field(default=None, max_length=500)


class ReversalRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class LedgerAccountResponse(BaseModel):
    id: str
    object: str = "ledger_account"
    account_code: str
    name: str
    account_type: str
    currency: str
    balance: int
    pending_balance: int
    description: Optional[str] = None
    parent_account_id: Optional[str] = None
    is_active: bool
    is_system_account: bool
    allow_negative: bool
    metadata: Dict[str, str] = {}
    created_at: str
    updated_at: str


class LedgerEntryResponse(BaseModel):
    id: str
    object: str = "ledger_entry"
    journal_entry_id: str
    account_id: str
    entry_type: str
    amount: int
    currency: str
    status: str
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    description: Optional[str] = None
    account_balance_before: int
    account_balance_after: int
    created_at: str
    posted_at: Optional[str] = None


class JournalEntryResponse(BaseModel):
    id: str
    object: str = "journal_entry"
    description: Optional[str] = None
    status: str
    reference_type: Optional[str] = None
    reference_id: Optional[str] = None
    posted_at: Optional[str] = None
    entries: List[LedgerEntryResponse] = []
    created_at: str


class TrialBalanceResponse(BaseModel):
    object: str = "trial_balance"
    accounts: List[Dict[str, Any]]
    total_debits: int
    total_credits: int
    is_balanced: bool
    generated_at: str
    as_of_date: Optional[str] = None
    currency: Optional[str] = None


class BalanceSheetResponse(BaseModel):
    object: str = "balance_sheet"
    assets: Dict[str, Any]
    liabilities: Dict[str, Any]
    equity: Dict[str, Any]
    generated_at: str
    as_of_date: Optional[str] = None
    currency: Optional[str] = None


class IncomeStatementResponse(BaseModel):
    object: str = "income_statement"
    revenue: Dict[str, Any]
    expenses: Dict[str, Any]
    net_income: int
    generated_at: str
    period_start: str
    period_end: str
    currency: Optional[str] = None


def account_to_response(account: LedgerAccount) -> LedgerAccountResponse:
    return LedgerAccountResponse(
        id=account.id,
        account_code=account.account_code,
        name=account.name,
        account_type=account.account_type,
        currency=account.currency,
        balance=account.balance,
        pending_balance=account.pending_balance,
        description=account.description,
        parent_account_id=account.parent_account_id,
        is_active=account.is_active,
        is_system_account=account.is_system_account,
        allow_negative=account.allow_negative,
        metadata=account.metadata_ or {},
        created_at=account.created_at.isoformat(),
        updated_at=account.updated_at.isoformat(),
    )


def entry_to_response(entry: LedgerEntry) -> LedgerEntryResponse:
    return LedgerEntryResponse(
        id=entry.id,
        journal_entry_id=entry.journal_entry_id,
        account_id=entry.account_id,
        entry_type=entry.entry_type,
        amount=entry.amount,
        currency=entry.currency,
        status=entry.status,
        reference_type=entry.reference_type,
        reference_id=entry.reference_id,
        description=entry.description,
        account_balance_before=entry.account_balance_before,
        account_balance_after=entry.account_balance_after,
        created_at=entry.created_at.isoformat(),
        posted_at=entry.posted_at.isoformat() if entry.posted_at else None,
    )


@router.post("/accounts", response_model=LedgerAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_ledger_account(
    request: Request,
    data: LedgerAccountCreateRequest,
    session = Depends(get_session),
):
    service = CreateAccountService(session)
    account = await service.create_account(
        account_code=data.account_code,
        name=data.name,
        account_type=data.account_type,
        currency=data.currency.upper(),
        description=data.description,
        parent_account_code=data.parent_account_code,
        allow_negative=data.allow_negative,
        is_system_account=data.is_system_account,
        initial_balance=data.initial_balance,
        account_id=getattr(request.state, "account_id", None),
        livemode=getattr(request.state, "livemode", False),
        metadata=data.metadata,
    )
    await session.commit()
    return account_to_response(account)


@router.get("/accounts", response_model=PaginatedResponse[LedgerAccountResponse])
async def list_ledger_accounts(
    request: Request,
    account_type: Optional[str] = Query(default=None, description="Filter by account type"),
    is_active: Optional[bool] = Query(default=None, description="Filter by active status"),
    currency: Optional[str] = Query(default=None, description="Filter by currency"),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    accounts = await service.get_chart_of_accounts(
        account_type=account_type,
        is_active=is_active,
        currency=currency.upper() if currency else None,
        account_id=getattr(request.state, "account_id", None),
    )
    has_more = len(accounts) > offset + limit
    paginated_accounts = accounts[offset:offset + limit]
    return PaginatedResponse(
        data=[LedgerAccountResponse(**a) for a in paginated_accounts],
        has_more=has_more,
    )


@router.get("/accounts/{account_code}", response_model=LedgerAccountResponse)
async def get_ledger_account(
    account_code: str,
    request: Request,
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    balance_info = await service.get_balance(account_code)
    return LedgerAccountResponse(
        id=balance_info["account_id"],
        account_code=balance_info["account_code"],
        name=balance_info["account_name"],
        account_type=balance_info["account_type"],
        currency=balance_info["currency"],
        balance=balance_info["balance"],
        pending_balance=balance_info["pending_balance"],
        is_active=balance_info["is_active"],
        metadata={},
        created_at="",
        updated_at="",
    )


@router.post("/accounts/{account_code}", response_model=LedgerAccountResponse)
async def update_ledger_account(
    account_code: str,
    request: Request,
    data: LedgerAccountUpdateRequest,
    session = Depends(get_session),
):
    service = CreateAccountService(session)
    account = await service.update_account(
        account_code=account_code,
        name=data.name,
        description=data.description,
        is_active=data.is_active,
        allow_negative=data.allow_negative,
        metadata=data.metadata,
    )
    await session.commit()
    return account_to_response(account)


@router.delete("/accounts/{account_code}", response_model=LedgerAccountResponse)
async def deactivate_ledger_account(
    account_code: str,
    request: Request,
    session = Depends(get_session),
):
    service = CreateAccountService(session)
    account = await service.deactivate_account(account_code)
    await session.commit()
    return account_to_response(account)


@router.get("/accounts/{account_code}/balance")
async def get_account_balance(
    account_code: str,
    request: Request,
    include_pending: bool = Query(default=False),
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    return await service.get_balance(account_code, include_pending)


@router.get("/accounts/{account_code}/history")
async def get_account_history(
    account_code: str,
    request: Request,
    start_date: Optional[datetime] = Query(default=None),
    end_date: Optional[datetime] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    return await service.get_account_history(
        account_code=account_code,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@router.post("/entries", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def post_journal_entry(
    request: Request,
    data: JournalEntryCreateRequest,
    session = Depends(get_session),
):
    service = PostEntryService(session)
    journal_entry = await service.post_entry(
        debit_account_code=data.debit_account_code,
        credit_account_code=data.credit_account_code,
        amount=data.amount,
        currency=data.currency.upper(),
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        description=data.description,
        metadata=data.metadata,
        account_id=getattr(request.state, "account_id", None),
        livemode=getattr(request.state, "livemode", False),
        created_by=getattr(request.state, "api_key", None),
    )
    await session.commit()
    
    return JournalEntryResponse(
        id=journal_entry.id,
        description=journal_entry.description,
        status=journal_entry.status,
        reference_type=journal_entry.reference_type,
        reference_id=journal_entry.reference_id,
        posted_at=journal_entry.posted_at.isoformat() if journal_entry.posted_at else None,
        created_at=journal_entry.created_at.isoformat(),
        entries=[],
    )


@router.post("/entries/compound", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
async def post_compound_journal_entry(
    request: Request,
    data: CompoundJournalEntryRequest,
    session = Depends(get_session),
):
    service = PostEntryService(session)
    entries = [e.model_dump() for e in data.entries]
    journal_entry = await service.post_compound_entry(
        entries=entries,
        currency=data.currency.upper(),
        description=data.description,
        reference_type=data.reference_type,
        reference_id=data.reference_id,
        account_id=getattr(request.state, "account_id", None),
        livemode=getattr(request.state, "livemode", False),
        created_by=getattr(request.state, "api_key", None),
    )
    await session.commit()
    
    return JournalEntryResponse(
        id=journal_entry.id,
        description=journal_entry.description,
        status=journal_entry.status,
        reference_type=journal_entry.reference_type,
        reference_id=journal_entry.reference_id,
        posted_at=journal_entry.posted_at.isoformat() if journal_entry.posted_at else None,
        created_at=journal_entry.created_at.isoformat(),
        entries=[],
    )


@router.get("/entries", response_model=PaginatedResponse[JournalEntryResponse])
async def list_journal_entries(
    request: Request,
    reference_type: Optional[str] = Query(default=None),
    reference_id: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.ledger import JournalEntry
    
    query = select(JournalEntry).order_by(JournalEntry.created_at.desc())
    
    if reference_type:
        query = query.where(JournalEntry.reference_type == reference_type)
    if reference_id:
        query = query.where(JournalEntry.reference_id == reference_id)
    
    account_id = getattr(request.state, "account_id", None)
    if account_id:
        query = query.where(JournalEntry.account_id == account_id)
    
    query = query.limit(limit + 1).offset(offset)
    result = await session.execute(query)
    entries = result.scalars().all()
    
    has_more = len(entries) > limit
    if has_more:
        entries = entries[:limit]
    
    return PaginatedResponse(
        data=[
            JournalEntryResponse(
                id=e.id,
                description=e.description,
                status=e.status,
                reference_type=e.reference_type,
                reference_id=e.reference_id,
                posted_at=e.posted_at.isoformat() if e.posted_at else None,
                created_at=e.created_at.isoformat(),
                entries=[],
            )
            for e in entries
        ],
        has_more=has_more,
    )


@router.get("/entries/{journal_entry_id}", response_model=JournalEntryResponse)
async def get_journal_entry(
    journal_entry_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.ledger import JournalEntry, LedgerEntry
    
    result = await session.execute(
        select(JournalEntry).where(JournalEntry.id == journal_entry_id)
    )
    journal = result.scalar_one_or_none()
    if not journal:
        raise NotFoundError(f"Journal entry {journal_entry_id} not found")
    
    entries_result = await session.execute(
        select(LedgerEntry).where(LedgerEntry.journal_entry_id == journal_entry_id)
    )
    entries = entries_result.scalars().all()
    
    return JournalEntryResponse(
        id=journal.id,
        description=journal.description,
        status=journal.status,
        reference_type=journal.reference_type,
        reference_id=journal.reference_id,
        posted_at=journal.posted_at.isoformat() if journal.posted_at else None,
        created_at=journal.created_at.isoformat(),
        entries=[entry_to_response(e) for e in entries],
    )


@router.post("/entries/{journal_entry_id}/reverse", response_model=JournalEntryResponse)
async def reverse_journal_entry(
    journal_entry_id: str,
    request: Request,
    data: ReversalRequest,
    session = Depends(get_session),
):
    service = PostEntryService(session)
    reversal = await service.reverse_entry(
        journal_entry_id=journal_entry_id,
        reason=data.reason,
        reversed_by=getattr(request.state, "api_key", None),
    )
    await session.commit()
    
    return JournalEntryResponse(
        id=reversal.id,
        description=reversal.description,
        status=reversal.status,
        reference_type=reversal.reference_type,
        reference_id=reversal.reference_id,
        posted_at=reversal.posted_at.isoformat() if reversal.posted_at else None,
        created_at=reversal.created_at.isoformat(),
        entries=[],
    )


@router.get("/trial_balance", response_model=TrialBalanceResponse)
async def get_trial_balance(
    request: Request,
    as_of_date: Optional[datetime] = Query(default=None),
    currency: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    result = await service.get_trial_balance(
        as_of_date=as_of_date,
        currency=currency.upper() if currency else None,
        account_id=getattr(request.state, "account_id", None),
    )
    return TrialBalanceResponse(**result)


@router.get("/balance_sheet", response_model=BalanceSheetResponse)
async def get_balance_sheet(
    request: Request,
    as_of_date: Optional[datetime] = Query(default=None),
    currency: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    result = await service.get_balance_sheet(
        as_of_date=as_of_date,
        currency=currency.upper() if currency else None,
        account_id=getattr(request.state, "account_id", None),
    )
    return BalanceSheetResponse(**result)


@router.get("/income_statement", response_model=IncomeStatementResponse)
async def get_income_statement(
    request: Request,
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    currency: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    result = await service.get_income_statement(
        start_date=start_date,
        end_date=end_date,
        currency=currency.upper() if currency else None,
        account_id=getattr(request.state, "account_id", None),
    )
    return IncomeStatementResponse(**result)


@router.post("/assertions", status_code=status.HTTP_201_CREATED)
async def create_balance_assertion(
    request: Request,
    data: BalanceAssertionRequest,
    session = Depends(get_session),
):
    service = ReconciliationService(session)
    assertion = await service.create_assertion(
        account_code=data.account_code,
        expected_balance=data.expected_balance,
        notes=data.notes,
        created_by=getattr(request.state, "api_key", None),
    )
    await session.commit()
    return {
        "id": assertion.id,
        "object": "balance_assertion",
        "account_id": assertion.account_id,
        "expected_balance": assertion.expected_balance,
        "actual_balance": assertion.actual_balance,
        "currency": assertion.currency,
        "assertion_date": assertion.assertion_date.isoformat(),
        "is_valid": assertion.is_valid,
        "discrepancy": assertion.discrepancy,
        "notes": assertion.notes,
    }


@router.get("/assertions")
async def list_balance_assertions(
    request: Request,
    account_code: Optional[str] = Query(default=None),
    is_valid: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    session = Depends(get_session),
):
    service = ReconciliationService(session)
    assertions = await service.get_assertions(
        account_code=account_code,
        is_valid=is_valid,
        limit=limit,
    )
    return {"data": assertions, "has_more": False}


@router.post("/reconcile")
async def reconcile_account(
    request: Request,
    data: BalanceAssertionRequest,
    session = Depends(get_session),
):
    service = ReconciliationService(session)
    result = await service.reconcile_account(
        account_code=data.account_code,
        expected_balance=data.expected_balance,
        notes=data.notes,
        created_by=getattr(request.state, "api_key", None),
    )
    await session.commit()
    return result


@router.get("/audit_trail")
async def get_audit_trail(
    request: Request,
    reference_type: Optional[str] = Query(default=None),
    reference_id: Optional[str] = Query(default=None),
    account_code: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    session = Depends(get_session),
):
    service = ReconciliationService(session)
    trail = await service.get_audit_trail(
        reference_type=reference_type,
        reference_id=reference_id,
        account_code=account_code,
        limit=limit,
    )
    return {"data": trail, "has_more": False}


@router.post("/validate/{journal_entry_id}")
async def validate_journal_entry(
    journal_entry_id: str,
    request: Request,
    session = Depends(get_session),
):
    service = ReconciliationService(session)
    result = await service.validate_journal_entry(journal_entry_id)
    return result


@router.get("/chart_of_accounts")
async def get_chart_of_accounts(
    request: Request,
    account_type: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    currency: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    service = BalanceQueryService(session)
    chart = await service.get_chart_of_accounts(
        account_type=account_type,
        is_active=is_active,
        currency=currency.upper() if currency else None,
        account_id=getattr(request.state, "account_id", None),
    )
    return {"data": chart, "has_more": False}
