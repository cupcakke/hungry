from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from decimal import Decimal
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import TaxRateRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError

router = APIRouter()


class TaxRateCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=50)
    inclusive: bool = Field(default=False)
    percentage: Decimal = Field(..., ge=0, le=100, decimal_places=4)
    active: Optional[bool] = True
    country: Optional[str] = Field(default=None, min_length=2, max_length=2)
    description: Optional[str] = Field(default=None, max_length=500)
    jurisdiction: Optional[str] = Field(default=None, max_length=50)
    jurisdiction_level: Optional[str] = Field(default=None)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    state: Optional[str] = Field(default=None, max_length=50)
    tax_type: Optional[str] = Field(default=None)


class TaxRateResponse(BaseModel):
    id: str
    object: str = "tax_rate"
    active: bool
    country: Optional[str] = None
    created: int
    description: Optional[str] = None
    display_name: str
    inclusive: bool
    jurisdiction: Optional[str] = None
    jurisdiction_level: Optional[str] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    percentage: float
    state: Optional[str] = None
    tax_type: Optional[str] = None


def tax_rate_to_response(tr: Any) -> TaxRateResponse:
    return TaxRateResponse(
        id=tr.id,
        active=tr.active,
        country=tr.country,
        created=int(tr.created_at.timestamp()),
        description=tr.description,
        display_name=tr.display_name,
        inclusive=tr.inclusive,
        jurisdiction=tr.jurisdiction,
        jurisdiction_level=tr.jurisdiction_level,
        livemode=tr.livemode,
        metadata=tr.metadata_ or {},
        percentage=float(tr.percentage),
        state=tr.state,
        tax_type=tr.tax_type,
    )


@router.post("", response_model=TaxRateResponse, status_code=status.HTTP_201_CREATED)
async def create_tax_rate(
    request: Request,
    data: TaxRateCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = TaxRateRepository(session)
    tax_rate = await repo.create(
        account_id=account_id,
        display_name=data.display_name,
        inclusive=data.inclusive,
        percentage=data.percentage,
        active=data.active,
        country=data.country,
        description=data.description,
        jurisdiction=data.jurisdiction,
        jurisdiction_level=data.jurisdiction_level,
        metadata=data.metadata,
        state=data.state,
        tax_type=data.tax_type,
    )
    await session.commit()
    return tax_rate_to_response(tax_rate)


@router.get("/{tax_rate_id}", response_model=TaxRateResponse)
async def get_tax_rate(
    tax_rate_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = TaxRateRepository(session)
    tax_rate = await repo.get_by_id(tax_rate_id)
    if not tax_rate:
        raise NotFoundError(f"Tax rate {tax_rate_id} not found")
    return tax_rate_to_response(tax_rate)


@router.post("/{tax_rate_id}", response_model=TaxRateResponse)
async def update_tax_rate(
    tax_rate_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = TaxRateRepository(session)
    tax_rate = await repo.get_by_id(tax_rate_id)
    if not tax_rate:
        raise NotFoundError(f"Tax rate {tax_rate_id} not found")
    update_data = {}
    for key in ["active", "country", "description", "display_name", "jurisdiction", "metadata", "state"]:
        if key in data:
            if key == "metadata":
                update_data["metadata_"] = data[key]
            else:
                update_data[key] = data[key]
    if update_data:
        await repo.update(tax_rate_id, **update_data)
        await session.commit()
    return tax_rate_to_response(tax_rate)


@router.get("", response_model=PaginatedResponse[TaxRateResponse])
async def list_tax_rates(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    active: Optional[bool] = Query(default=None),
    country: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = TaxRateRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if active is not None:
        filters["active"] = active
    if country:
        filters["country"] = country.upper()
    tax_rates = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(tax_rates) > limit
    if has_more:
        tax_rates = tax_rates[:limit]
    return PaginatedResponse(
        data=[tax_rate_to_response(tr) for tr in tax_rates],
        has_more=has_more,
    )
