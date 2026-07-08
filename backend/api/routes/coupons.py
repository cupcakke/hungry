from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from decimal import Decimal
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, validator

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import CouponRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError

router = APIRouter()


class CouponCreateRequest(BaseModel):
    duration: str = Field(..., description="forever, once, or repeating")
    id: Optional[str] = Field(default=None, max_length=50)
    amount_off: Optional[int] = Field(default=None, ge=1)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    currency_options: Optional[Dict[str, Any]] = None
    duration_in_months: Optional[int] = Field(default=None, ge=1, le=36)
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    name: Optional[str] = Field(default=None, max_length=100)
    percent_off: Optional[Decimal] = Field(default=None, ge=0, le=100)
    redeem_by: Optional[int] = Field(default=None)
    applies_to: Optional[Dict[str, Any]] = None

    @validator("duration")
    def validate_duration(cls, v):
        if v not in ["forever", "once", "repeating"]:
            raise ValueError("duration must be 'forever', 'once', or 'repeating'")
        return v


class CouponResponse(BaseModel):
    id: str
    object: str = "coupon"
    amount_off: Optional[int] = None
    applies_to: Optional[Dict[str, Any]] = None
    created: int
    currency: Optional[str] = None
    currency_options: Optional[Dict[str, Any]] = None
    deleted: bool = False
    duration: str
    duration_in_months: Optional[int] = None
    livemode: bool = False
    max_redemptions: Optional[int] = None
    metadata: Dict[str, str] = {}
    name: Optional[str] = None
    percent_off: Optional[float] = None
    redeem_by: Optional[int] = None
    times_redeemed: int = 0
    valid: bool = True


def coupon_to_response(coupon: Any) -> CouponResponse:
    return CouponResponse(
        id=coupon.id,
        amount_off=coupon.amount_off,
        applies_to=coupon.applies_to,
        created=int(coupon.created_at.timestamp()),
        currency=coupon.currency,
        currency_options=coupon.currency_options,
        deleted=coupon.is_deleted if hasattr(coupon, "is_deleted") else False,
        duration=coupon.duration,
        duration_in_months=coupon.duration_in_months,
        livemode=coupon.livemode,
        max_redemptions=coupon.max_redemptions,
        metadata=coupon.metadata_ or {},
        name=coupon.name,
        percent_off=float(coupon.percent_off) if coupon.percent_off else None,
        redeem_by=coupon.redeem_by,
        times_redeemed=coupon.times_redeemed or 0,
        valid=coupon.valid,
    )


@router.post("", response_model=CouponResponse, status_code=status.HTTP_201_CREATED)
async def create_coupon(
    request: Request,
    data: CouponCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = CouponRepository(session)
    coupon_id = data.id or f"coupon_{int(time.time() * 1000)}"
    coupon = await repo.create(
        id=coupon_id,
        account_id=account_id,
        duration=data.duration,
        amount_off=data.amount_off,
        currency=data.currency.lower() if data.currency else None,
        currency_options=data.currency_options,
        duration_in_months=data.duration_in_months,
        max_redemptions=data.max_redemptions,
        metadata=data.metadata,
        name=data.name,
        percent_off=data.percent_off,
        redeem_by=data.redeem_by,
        applies_to=data.applies_to,
    )
    await session.commit()
    return coupon_to_response(coupon)


@router.get("/{coupon_id}", response_model=CouponResponse)
async def get_coupon(
    coupon_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if not coupon or coupon.is_deleted:
        raise NotFoundError(f"Coupon {coupon_id} not found")
    return coupon_to_response(coupon)


@router.post("/{coupon_id}", response_model=CouponResponse)
async def update_coupon(
    coupon_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if not coupon or coupon.is_deleted:
        raise NotFoundError(f"Coupon {coupon_id} not found")
    update_data = {}
    for key in ["metadata", "name"]:
        if key in data:
            if key == "metadata":
                update_data["metadata_"] = data[key]
            else:
                update_data[key] = data[key]
    if update_data:
        await repo.update(coupon_id, **update_data)
        await session.commit()
    return coupon_to_response(coupon)


@router.delete("/{coupon_id}", response_model=CouponResponse)
async def delete_coupon(
    coupon_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if not coupon:
        raise NotFoundError(f"Coupon {coupon_id} not found")
    await repo.soft_delete(coupon_id)
    await session.commit()
    return coupon_to_response(coupon)


@router.get("", response_model=PaginatedResponse[CouponResponse])
async def list_coupons(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = CouponRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    coupons = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(coupons) > limit
    if has_more:
        coupons = coupons[:limit]
    return PaginatedResponse(
        data=[coupon_to_response(c) for c in coupons],
        has_more=has_more,
    )
