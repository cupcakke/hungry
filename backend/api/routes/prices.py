from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from decimal import Decimal
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import PriceRepository, ProductRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class PriceCreateRequest(BaseModel):
    currency: str = Field(..., min_length=3, max_length=3)
    product: str = Field(..., description="Product ID")
    active: Optional[bool] = True
    billing_scheme: Optional[str] = "per_unit"
    currency_options: Optional[Dict[str, Any]] = None
    custom_unit_amount: Optional[Dict[str, Any]] = None
    lookup_key: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    nickname: Optional[str] = None
    recurring: Optional[Dict[str, Any]] = None
    tax_behavior: Optional[str] = "unspecified"
    tiers: Optional[List[Dict[str, Any]]] = None
    tiers_mode: Optional[str] = None
    transform_quantity: Optional[Dict[str, Any]] = None
    type: Optional[str] = "recurring"
    unit_amount: Optional[int] = None
    unit_amount_decimal: Optional[str] = None


class PriceResponse(BaseModel):
    id: str
    object: str = "price"
    active: bool
    billing_scheme: str
    created: int
    currency: str
    currency_options: Optional[Dict[str, Any]] = None
    custom_unit_amount: Optional[Dict[str, Any]] = None
    livemode: bool = False
    lookup_key: Optional[str] = None
    metadata: Dict[str, str] = {}
    nickname: Optional[str] = None
    product: str
    recurring: Optional[Dict[str, Any]] = None
    tax_behavior: str
    tiers: Optional[List[Dict[str, Any]]] = None
    tiers_mode: Optional[str] = None
    transform_quantity: Optional[Dict[str, Any]] = None
    type: str
    unit_amount: Optional[int] = None
    unit_amount_decimal: Optional[str] = None


def price_to_response(price: Any) -> PriceResponse:
    return PriceResponse(
        id=price.id,
        active=price.active,
        billing_scheme=price.billing_scheme,
        created=int(price.created_at.timestamp()),
        currency=price.currency,
        currency_options=price.currency_options,
        custom_unit_amount=price.custom_unit_amount,
        livemode=price.livemode,
        lookup_key=price.lookup_key,
        metadata=price.metadata_ or {},
        nickname=price.nickname,
        product=price.product_id,
        recurring={
            "interval": price.recurring_interval,
            "interval_count": price.recurring_interval_count,
            "aggregate_usage": price.recurring_aggregate_usage,
            "usage_type": price.recurring_usage_type,
        } if price.recurring_interval else None,
        tax_behavior=price.tax_behavior,
        tiers=price.tiers,
        tiers_mode=price.tiers_mode,
        transform_quantity=price.transform_quantity,
        type=price.type,
        unit_amount=price.unit_amount,
        unit_amount_decimal=str(price.unit_amount_decimal) if price.unit_amount_decimal else None,
    )


@router.post("", response_model=PriceResponse, status_code=status.HTTP_201_CREATED)
async def create_price(
    request: Request,
    data: PriceCreateRequest,
    session = Depends(get_session),
):
    product_repo = ProductRepository(session)
    product = await product_repo.get_by_id(data.product)
    if not product or product.is_deleted:
        raise NotFoundError(f"Product {data.product} not found")
    account_id = getattr(request.state, "account_id", None)
    repo = PriceRepository(session)
    recurring_interval = None
    recurring_interval_count = 1
    recurring_aggregate_usage = None
    recurring_usage_type = None
    if data.recurring:
        recurring_interval = data.recurring.get("interval")
        recurring_interval_count = data.recurring.get("interval_count", 1)
        recurring_aggregate_usage = data.recurring.get("aggregate_usage")
        recurring_usage_type = data.recurring.get("usage_type")
    price = await repo.create_price(
        id=f"price_{time.time_ns()}",
        product_id=data.product,
        account_id=account_id,
        currency=data.currency.lower(),
        unit_amount=data.unit_amount,
        active=data.active,
        billing_scheme=data.billing_scheme or "per_unit",
        recurring_interval=recurring_interval,
        recurring_interval_count=recurring_interval_count,
        recurring_aggregate_usage=recurring_aggregate_usage,
        recurring_usage_type=recurring_usage_type,
        nickname=data.nickname,
        lookup_key=data.lookup_key,
        metadata=data.metadata,
        tax_behavior=data.tax_behavior,
        tiers=data.tiers,
        tiers_mode=data.tiers_mode,
        type=data.type or "recurring",
    )
    await session.commit()
    return price_to_response(price)


@router.get("/{price_id}", response_model=PriceResponse)
async def get_price(
    price_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = PriceRepository(session)
    price = await repo.get_by_id(price_id)
    if not price or price.is_deleted:
        raise NotFoundError(f"Price {price_id} not found")
    return price_to_response(price)


@router.post("/{price_id}", response_model=PriceResponse)
async def update_price(
    price_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = PriceRepository(session)
    price = await repo.get_by_id(price_id)
    if not price or price.is_deleted:
        raise NotFoundError(f"Price {price_id} not found")
    update_data = {}
    for key in ["active", "lookup_key", "nickname", "metadata", "tax_behavior"]:
        if key in data:
            if key == "metadata":
                update_data["metadata_"] = data[key]
            else:
                update_data[key] = data[key]
    if update_data:
        await repo.update(price_id, **update_data)
        await session.commit()
    return price_to_response(price)


@router.get("", response_model=PaginatedResponse[PriceResponse])
async def list_prices(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    product: Optional[str] = Query(default=None),
    active: Optional[bool] = Query(default=None),
    currency: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = PriceRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if product:
        filters["product_id"] = product
    if active is not None:
        filters["active"] = active
    if currency:
        filters["currency"] = currency.lower()
    if type:
        filters["type"] = type
    prices = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(prices) > limit
    if has_more:
        prices = prices[:limit]
    return PaginatedResponse(
        data=[price_to_response(p) for p in prices],
        has_more=has_more,
    )
