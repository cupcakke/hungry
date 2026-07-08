from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
import secrets

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import AccountRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_account_id

router = APIRouter()


class AccountCreateRequest(BaseModel):
    country: str = Field(..., min_length=2, max_length=2, description="Country code")
    account_type: str = Field(default="standard", description="Account type")
    business_type: Optional[str] = Field(default=None, description="Business type")
    business_profile: Optional[Dict[str, Any]] = Field(default=None)
    company: Optional[Dict[str, Any]] = Field(default=None)
    individual: Optional[Dict[str, Any]] = Field(default=None)
    email: Optional[str] = Field(default=None)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    capabilities: Optional[Dict[str, Any]] = Field(default=None)
    settings: Optional[Dict[str, Any]] = Field(default=None)
    tos_acceptance: Optional[Dict[str, Any]] = Field(default=None)

    class Config:
        extra = "allow"


class AccountResponse(BaseModel):
    id: str
    object: str = "account"
    account_type: Optional[str] = None
    business_profile: Optional[Dict[str, Any]] = None
    business_type: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    charges_enabled: bool = False
    company: Optional[Dict[str, Any]] = None
    controller: Optional[Dict[str, Any]] = None
    country: str
    created: int
    default_currency: str
    details_submitted: bool = False
    email: Optional[str] = None
    external_accounts: Optional[Dict[str, Any]] = None
    future_requirements: Optional[Dict[str, Any]] = None
    individual: Optional[Dict[str, Any]] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    payouts_enabled: bool = False
    requirements: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    tos_acceptance: Optional[Dict[str, Any]] = None


def account_to_response(account: Any) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        account_type=account.account_type,
        business_profile=account.business_profile,
        business_type=account.business_type,
        capabilities=account.capabilities,
        charges_enabled=account.charges_enabled,
        company=account.company,
        controller=account.controller,
        country=account.country,
        created=int(account.created_at.timestamp()),
        default_currency=account.default_currency,
        details_submitted=account.details_submitted,
        email=account.email,
        external_accounts=account.external_accounts,
        future_requirements=account.future_requirements,
        individual=account.individual,
        livemode=account.livemode,
        metadata=account.metadata_ or {},
        payouts_enabled=account.payouts_enabled,
        requirements=account.requirements,
        settings=account.settings,
        tos_acceptance=account.tos_acceptance,
    )


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    request: Request,
    data: AccountCreateRequest,
    session = Depends(get_session),
):
    repo = AccountRepository(session)
    account = await repo.create_account(
        country=data.country.upper(),
        account_type=data.account_type or "standard",
        email=data.email,
        business_type=data.business_type,
        business_profile=data.business_profile,
        company=data.company,
        individual=data.individual,
        metadata=data.metadata,
        capabilities=data.capabilities,
        settings=data.settings,
        tos_acceptance=data.tos_acceptance,
    )
    await session.commit()
    return account_to_response(account)


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = AccountRepository(session)
    account = await repo.get_by_id(account_id)
    if not account or account.is_deleted:
        raise NotFoundError(f"Account {account_id} not found")
    return account_to_response(account)


@router.post("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = AccountRepository(session)
    account = await repo.get_by_id(account_id)
    if not account:
        raise NotFoundError(f"Account {account_id} not found")
    update_data = {}
    for key in ["business_profile", "business_type", "company", "individual", "email", "metadata", "capabilities", "settings", "tos_acceptance"]:
        if key in data:
            update_data[key] = data[key]
    if update_data:
        await repo.update(account_id, **update_data)
        await session.commit()
    return account_to_response(account)


@router.delete("/{account_id}", response_model=AccountResponse)
async def delete_account(
    account_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = AccountRepository(session)
    account = await repo.get_by_id(account_id)
    if not account:
        raise NotFoundError(f"Account {account_id} not found")
    await repo.soft_delete(account_id)
    await session.commit()
    return account_to_response(account)


@router.get("", response_model=PaginatedResponse[AccountResponse])
async def list_accounts(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    session = Depends(get_session),
):
    repo = AccountRepository(session)
    accounts = await repo.list(
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(accounts) > limit
    if has_more:
        accounts = accounts[:limit]
    return PaginatedResponse(
        data=[account_to_response(a) for a in accounts],
        has_more=has_more,
    )


@router.post("/{account_id}/accept_tos", response_model=AccountResponse)
async def accept_tos(
    account_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    repo = AccountRepository(session)
    account = await repo.get_by_id(account_id)
    if not account:
        raise NotFoundError(f"Account {account_id} not found")
    account.tos_acceptance = {
        "date": int(time.time()),
        "ip": ip,
        "user_agent": user_agent,
    }
    account.details_submitted = True
    await session.commit()
    return account_to_response(account)


@router.post("/{account_id}/reject", response_model=AccountResponse)
async def reject_account(
    account_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    reason = data.get("reason", "fraud")
    repo = AccountRepository(session)
    account = await repo.get_by_id(account_id)
    if not account:
        raise NotFoundError(f"Account {account_id} not found")
    account.charges_enabled = False
    account.payouts_enabled = False
    await session.commit()
    return account_to_response(account)
