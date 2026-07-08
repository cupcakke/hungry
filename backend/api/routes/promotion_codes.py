from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
import secrets

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import PromotionCodeRepository, CouponRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class PromotionCodeCreateRequest(BaseModel):
    coupon: str = Field(..., description="Coupon ID")
    active: Optional[bool] = True
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    customer: Optional[str] = None
    expires_at: Optional[int] = None
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    restrictions: Optional[Dict[str, Any]] = None
    first_order_transaction: Optional[Dict[str, Any]] = None


class PromotionCodeResponse(BaseModel):
    id: str
    object: str = "promotion_code"
    active: bool
    code: str
    coupon: Dict[str, Any]
    created: int
    customer: Optional[str] = None
    expires_at: Optional[int] = None
    livemode: bool = False
    max_redemptions: Optional[int] = None
    metadata: Dict[str, str] = {}
    restrictions: Optional[Dict[str, Any]] = None
    times_redeemed: int = 0


def promotion_code_to_response(pc: Any, coupon: Any) -> PromotionCodeResponse:
    return PromotionCodeResponse(
        id=pc.id,
        active=pc.active,
        code=pc.code,
        coupon={
            "id": coupon.id,
            "object": "coupon",
            "duration": coupon.duration,
            "percent_off": float(coupon.percent_off) if coupon.percent_off else None,
            "amount_off": coupon.amount_off,
            "currency": coupon.currency,
        },
        created=int(pc.created_at.timestamp()),
        customer=pc.customer_id,
        expires_at=pc.expires_at,
        livemode=pc.livemode,
        max_redemptions=pc.max_redemptions,
        metadata=pc.metadata_ or {},
        restrictions=pc.restrictions,
        times_redeemed=pc.times_redeemed or 0,
    )


@router.post("", response_model=PromotionCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion_code(
    request: Request,
    data: PromotionCodeCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    coupon_repo = CouponRepository(session)
    coupon = await coupon_repo.get_by_id(data.coupon)
    if not coupon or coupon.is_deleted:
        raise NotFoundError(f"Coupon {data.coupon} not found")
    repo = PromotionCodeRepository(session)
    code = data.code or secrets.token_urlsafe(8).upper()
    pc = await repo.create(
        account_id=account_id,
        coupon_id=data.coupon,
        code=code,
        active=data.active,
        customer_id=data.customer,
        expires_at=data.expires_at,
        max_redemptions=data.max_redemptions,
        metadata=data.metadata,
        restrictions=data.restrictions,
    )
    await session.commit()
    return promotion_code_to_response(pc, coupon)


@router.get("/{promotion_code_id}", response_model=PromotionCodeResponse)
async def get_promotion_code(
    promotion_code_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = PromotionCodeRepository(session)
    pc = await repo.get_by_id(promotion_code_id)
    if not pc:
        raise NotFoundError(f"Promotion code {promotion_code_id} not found")
    coupon_repo = CouponRepository(session)
    coupon = await coupon_repo.get_by_id(pc.coupon_id)
    return promotion_code_to_response(pc, coupon)


@router.post("/{promotion_code_id}", response_model=PromotionCodeResponse)
async def update_promotion_code(
    promotion_code_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = PromotionCodeRepository(session)
    pc = await repo.get_by_id(promotion_code_id)
    if not pc:
        raise NotFoundError(f"Promotion code {promotion_code_id} not found")
    update_data = {}
    for key in ["active", "metadata", "restrictions"]:
        if key in data:
            if key == "metadata":
                update_data["metadata_"] = data[key]
            else:
                update_data[key] = data[key]
    if update_data:
        await repo.update(promotion_code_id, **update_data)
        await session.commit()
    coupon_repo = CouponRepository(session)
    coupon = await coupon_repo.get_by_id(pc.coupon_id)
    return promotion_code_to_response(pc, coupon)


@router.get("", response_model=PaginatedResponse[PromotionCodeResponse])
async def list_promotion_codes(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    coupon: Optional[str] = Query(default=None),
    active: Optional[bool] = Query(default=None),
    code: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = PromotionCodeRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if coupon:
        filters["coupon_id"] = coupon
    if active is not None:
        filters["active"] = active
    if code:
        filters["code"] = code
    promotion_codes = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(promotion_codes) > limit
    if has_more:
        promotion_codes = promotion_codes[:limit]
    coupon_repo = CouponRepository(session)
    results = []
    for pc in promotion_codes:
        coupon = await coupon_repo.get_by_id(pc.coupon_id)
        results.append(promotion_code_to_response(pc, coupon))
    return PaginatedResponse(
        data=results,
        has_more=has_more,
    )
