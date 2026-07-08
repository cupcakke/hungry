from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class PaymentLinkCreateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200, description="Payment link name")
    payment_intent_data: Optional[Dict[str, Any]] = Field(default=None, description="Payment intent configuration")
    line_items: Optional[List[Dict[str, Any]]] = Field(default=None, description="Line items")
    after_completion: Optional[Dict[str, Any]] = Field(default=None, description="After completion behavior")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class PaymentLinkUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200, description="Payment link name")
    payment_intent_data: Optional[Dict[str, Any]] = Field(default=None, description="Payment intent configuration")
    after_completion: Optional[Dict[str, Any]] = Field(default=None, description="After completion behavior")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class LineItemCreateRequest(BaseModel):
    price_id: str = Field(..., description="Price ID")
    quantity: int = Field(default=1, ge=1, description="Quantity")
    adjustable_quantity: Optional[Dict[str, Any]] = Field(default=None, description="Adjustable quantity settings")


class LineItemUpdateRequest(BaseModel):
    quantity: Optional[int] = Field(default=None, ge=1, description="Quantity")
    adjustable_quantity: Optional[Dict[str, Any]] = Field(default=None, description="Adjustable quantity settings")


class RestrictionsUpdateRequest(BaseModel):
    max_uses: Optional[int] = Field(default=None, ge=1, description="Maximum uses")
    expiry_date: Optional[int] = Field(default=None, description="Expiry timestamp")
    allowed_emails: Optional[List[str]] = Field(default=None, description="Allowed email patterns")
    require_customer: Optional[bool] = Field(default=None, description="Require customer creation")


class CustomizationUpdateRequest(BaseModel):
    brand_color: Optional[str] = Field(default=None, max_length=7, description="Brand color hex")
    logo_url: Optional[str] = Field(default=None, max_length=500, description="Logo URL")
    button_text: Optional[str] = Field(default=None, max_length=50, description="Button text")
    custom_fields: Optional[List[Dict[str, Any]]] = Field(default=None, description="Custom fields")
    terms_url: Optional[str] = Field(default=None, max_length=500, description="Terms URL")
    privacy_url: Optional[str] = Field(default=None, max_length=500, description="Privacy URL")


class PaymentLinkResponse(BaseModel):
    id: str
    object: str = "payment_link"
    account_id: Optional[str] = None
    url: str
    name: Optional[str] = None
    active: bool = True
    payment_intent_data: Optional[Dict[str, Any]] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    after_completion: Optional[Dict[str, Any]] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class LineItemResponse(BaseModel):
    id: str
    object: str = "payment_link.line_item"
    payment_link_id: str
    price_id: str
    quantity: int
    adjustable_quantity: Optional[Dict[str, Any]] = None
    created: int
    metadata: Optional[Dict[str, str]] = None


class PaymentResponse(BaseModel):
    id: str
    object: str = "payment_link.payment"
    payment_link_id: str
    payment_intent_id: Optional[str] = None
    customer_id: Optional[str] = None
    amount: int
    currency: str
    status: str
    paid_at: Optional[int] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class RestrictionsResponse(BaseModel):
    id: str
    object: str = "payment_link.restrictions"
    payment_link_id: str
    max_uses: Optional[int] = None
    current_uses: int = 0
    expiry_date: Optional[int] = None
    allowed_emails: Optional[List[str]] = None
    require_customer: bool = False
    created: int


class CustomizationResponse(BaseModel):
    id: str
    object: str = "payment_link.customization"
    payment_link_id: str
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None
    button_text: Optional[str] = None
    custom_fields: Optional[List[Dict[str, Any]]] = None
    terms_url: Optional[str] = None
    privacy_url: Optional[str] = None
    created: int


class AnalyticsResponse(BaseModel):
    id: str
    object: str = "payment_link.analytics"
    payment_link_id: str
    views: int = 0
    unique_visitors: int = 0
    started_checkouts: int = 0
    completed_payments: int = 0
    total_amount: int = 0
    currency: str = "usd"
    created: int


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


def _generate_unique_url() -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(16))
    return f"https://pay.example.com/link/{random_part}"


@router.post("", response_model=PaymentLinkResponse, status_code=201)
async def create_payment_link(
    request: Request,
    data: PaymentLinkCreateRequest,
    session = Depends(get_session),
):
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    from payment_platform.backend.domain.payment_links import PaymentLink
    
    pl_id = _generate_id("pl")
    timestamp = _get_timestamp()
    url = _generate_unique_url()
    
    payment_link = PaymentLink(
        id=pl_id,
        account_id=account_id,
        url=url,
        name=data.name,
        active=True,
        payment_intent_data=data.payment_intent_data,
        line_items=data.line_items,
        after_completion=data.after_completion,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(payment_link)
    await session.flush()
    
    return PaymentLinkResponse(
        id=payment_link.id,
        account_id=payment_link.account_id,
        url=payment_link.url,
        name=payment_link.name,
        active=payment_link.active,
        payment_intent_data=payment_link.payment_intent_data,
        line_items=payment_link.line_items,
        after_completion=payment_link.after_completion,
        created=payment_link.created,
        metadata=payment_link.metadata_,
    )


@router.get("", response_model=PaginatedResponse[PaymentLinkResponse])
async def list_payment_links(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    active: Optional[bool] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLink
    
    account_id = _get_account_id(request)
    
    query = select(PaymentLink)
    if account_id:
        query = query.where(PaymentLink.account_id == account_id)
    if active is not None:
        query = query.where(PaymentLink.active == active)
    if starting_after:
        query = query.where(PaymentLink.id > starting_after)
    
    query = query.order_by(PaymentLink.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    links = list(result.scalars().all())
    
    has_more = len(links) > limit
    if has_more:
        links = links[:limit]
    
    data = [
        PaymentLinkResponse(
            id=pl.id,
            account_id=pl.account_id,
            url=pl.url,
            name=pl.name,
            active=pl.active,
            payment_intent_data=pl.payment_intent_data,
            line_items=pl.line_items,
            after_completion=pl.after_completion,
            created=pl.created,
            metadata=pl.metadata_,
        )
        for pl in links
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/{payment_link_id}", response_model=PaymentLinkResponse)
async def get_payment_link(
    payment_link_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLink
    
    query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    result = await session.execute(query)
    pl = result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    return PaymentLinkResponse(
        id=pl.id,
        account_id=pl.account_id,
        url=pl.url,
        name=pl.name,
        active=pl.active,
        payment_intent_data=pl.payment_intent_data,
        line_items=pl.line_items,
        after_completion=pl.after_completion,
        created=pl.created,
        metadata=pl.metadata_,
    )


@router.post("/{payment_link_id}/update", response_model=PaymentLinkResponse)
async def update_payment_link(
    payment_link_id: str,
    request: Request,
    data: PaymentLinkUpdateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLink
    
    query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    result = await session.execute(query)
    pl = result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    if data.name is not None:
        pl.name = data.name
    if data.payment_intent_data is not None:
        pl.payment_intent_data = data.payment_intent_data
    if data.after_completion is not None:
        pl.after_completion = data.after_completion
    if data.metadata is not None:
        pl.metadata_ = data.metadata
    
    await session.flush()
    
    return PaymentLinkResponse(
        id=pl.id,
        account_id=pl.account_id,
        url=pl.url,
        name=pl.name,
        active=pl.active,
        payment_intent_data=pl.payment_intent_data,
        line_items=pl.line_items,
        after_completion=pl.after_completion,
        created=pl.created,
        metadata=pl.metadata_,
    )


@router.post("/{payment_link_id}/deactivate", response_model=PaymentLinkResponse)
async def deactivate_payment_link(
    payment_link_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLink
    
    query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    result = await session.execute(query)
    pl = result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    pl.active = False
    await session.flush()
    
    return PaymentLinkResponse(
        id=pl.id,
        account_id=pl.account_id,
        url=pl.url,
        name=pl.name,
        active=pl.active,
        payment_intent_data=pl.payment_intent_data,
        line_items=pl.line_items,
        after_completion=pl.after_completion,
        created=pl.created,
        metadata=pl.metadata_,
    )


@router.post("/{payment_link_id}/activate", response_model=PaymentLinkResponse)
async def activate_payment_link(
    payment_link_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLink
    
    query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    result = await session.execute(query)
    pl = result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    pl.active = True
    await session.flush()
    
    return PaymentLinkResponse(
        id=pl.id,
        account_id=pl.account_id,
        url=pl.url,
        name=pl.name,
        active=pl.active,
        payment_intent_data=pl.payment_intent_data,
        line_items=pl.line_items,
        after_completion=pl.after_completion,
        created=pl.created,
        metadata=pl.metadata_,
    )


@router.get("/{payment_link_id}/line_items", response_model=PaginatedResponse[LineItemResponse])
async def get_line_items(
    payment_link_id: str,
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkLineItem, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    query = select(PaymentLinkLineItem).where(PaymentLinkLineItem.payment_link_id == payment_link_id)
    if starting_after:
        query = query.where(PaymentLinkLineItem.id > starting_after)
    
    query = query.order_by(PaymentLinkLineItem.created_at.asc()).limit(limit + 1)
    
    result = await session.execute(query)
    items = list(result.scalars().all())
    
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    
    data = [
        LineItemResponse(
            id=item.id,
            payment_link_id=item.payment_link_id,
            price_id=item.price_id,
            quantity=item.quantity,
            adjustable_quantity=item.adjustable_quantity,
            created=item.created,
            metadata=item.metadata_,
        )
        for item in items
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/{payment_link_id}/line_items", response_model=LineItemResponse, status_code=201)
async def add_line_item(
    payment_link_id: str,
    request: Request,
    data: LineItemCreateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkLineItem, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    item_id = _generate_id("pli")
    timestamp = _get_timestamp()
    
    line_item = PaymentLinkLineItem(
        id=item_id,
        payment_link_id=payment_link_id,
        price_id=data.price_id,
        quantity=data.quantity,
        adjustable_quantity=data.adjustable_quantity,
        created=timestamp,
    )
    
    session.add(line_item)
    await session.flush()
    
    return LineItemResponse(
        id=line_item.id,
        payment_link_id=line_item.payment_link_id,
        price_id=line_item.price_id,
        quantity=line_item.quantity,
        adjustable_quantity=line_item.adjustable_quantity,
        created=line_item.created,
    )


@router.get("/{payment_link_id}/payments", response_model=PaginatedResponse[PaymentResponse])
async def list_payments(
    payment_link_id: str,
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkPayment, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    query = select(PaymentLinkPayment).where(PaymentLinkPayment.payment_link_id == payment_link_id)
    if status:
        query = query.where(PaymentLinkPayment.status == status)
    if starting_after:
        query = query.where(PaymentLinkPayment.id > starting_after)
    
    query = query.order_by(PaymentLinkPayment.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    payments = list(result.scalars().all())
    
    has_more = len(payments) > limit
    if has_more:
        payments = payments[:limit]
    
    data = [
        PaymentResponse(
            id=p.id,
            payment_link_id=p.payment_link_id,
            payment_intent_id=p.payment_intent_id,
            customer_id=p.customer_id,
            amount=p.amount,
            currency=p.currency,
            status=p.status.value,
            paid_at=p.paid_at,
            created=p.created,
            livemode=p.livemode,
            metadata=p.metadata_,
        )
        for p in payments
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/{payment_link_id}/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    payment_link_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkAnalytics, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    query = select(PaymentLinkAnalytics).where(PaymentLinkAnalytics.payment_link_id == payment_link_id)
    result = await session.execute(query)
    analytics = result.scalar_one_or_none()
    
    if not analytics:
        analytics = PaymentLinkAnalytics(
            id=_generate_id("pla"),
            payment_link_id=payment_link_id,
            views=0,
            unique_visitors=0,
            started_checkouts=0,
            completed_payments=0,
            total_amount=0,
            currency="usd",
            created=_get_timestamp(),
        )
        session.add(analytics)
        await session.flush()
    
    return AnalyticsResponse(
        id=analytics.id,
        payment_link_id=analytics.payment_link_id,
        views=analytics.views,
        unique_visitors=analytics.unique_visitors,
        started_checkouts=analytics.started_checkouts,
        completed_payments=analytics.completed_payments,
        total_amount=analytics.total_amount,
        currency=analytics.currency,
        created=analytics.created,
    )


@router.get("/{payment_link_id}/restrictions", response_model=RestrictionsResponse)
async def get_restrictions(
    payment_link_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkRestrictions, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    query = select(PaymentLinkRestrictions).where(PaymentLinkRestrictions.payment_link_id == payment_link_id)
    result = await session.execute(query)
    restrictions = result.scalar_one_or_none()
    
    if not restrictions:
        restrictions = PaymentLinkRestrictions(
            id=_generate_id("plr"),
            payment_link_id=payment_link_id,
            max_uses=None,
            current_uses=0,
            expiry_date=None,
            allowed_emails=None,
            require_customer=False,
            created=_get_timestamp(),
        )
        session.add(restrictions)
        await session.flush()
    
    return RestrictionsResponse(
        id=restrictions.id,
        payment_link_id=restrictions.payment_link_id,
        max_uses=restrictions.max_uses,
        current_uses=restrictions.current_uses,
        expiry_date=restrictions.expiry_date,
        allowed_emails=restrictions.allowed_emails,
        require_customer=restrictions.require_customer,
        created=restrictions.created,
    )


@router.put("/{payment_link_id}/restrictions", response_model=RestrictionsResponse)
async def update_restrictions(
    payment_link_id: str,
    request: Request,
    data: RestrictionsUpdateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkRestrictions, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    query = select(PaymentLinkRestrictions).where(PaymentLinkRestrictions.payment_link_id == payment_link_id)
    result = await session.execute(query)
    restrictions = result.scalar_one_or_none()
    
    if not restrictions:
        restrictions = PaymentLinkRestrictions(
            id=_generate_id("plr"),
            payment_link_id=payment_link_id,
            max_uses=data.max_uses,
            current_uses=0,
            expiry_date=data.expiry_date,
            allowed_emails=data.allowed_emails,
            require_customer=data.require_customer if data.require_customer is not None else False,
            created=_get_timestamp(),
        )
        session.add(restrictions)
    else:
        if data.max_uses is not None:
            restrictions.max_uses = data.max_uses
        if data.expiry_date is not None:
            restrictions.expiry_date = data.expiry_date
        if data.allowed_emails is not None:
            restrictions.allowed_emails = data.allowed_emails
        if data.require_customer is not None:
            restrictions.require_customer = data.require_customer
    
    await session.flush()
    
    return RestrictionsResponse(
        id=restrictions.id,
        payment_link_id=restrictions.payment_link_id,
        max_uses=restrictions.max_uses,
        current_uses=restrictions.current_uses,
        expiry_date=restrictions.expiry_date,
        allowed_emails=restrictions.allowed_emails,
        require_customer=restrictions.require_customer,
        created=restrictions.created,
    )


@router.get("/{payment_link_id}/customization", response_model=CustomizationResponse)
async def get_customization(
    payment_link_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkCustomization, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    query = select(PaymentLinkCustomization).where(PaymentLinkCustomization.payment_link_id == payment_link_id)
    result = await session.execute(query)
    customization = result.scalar_one_or_none()
    
    if not customization:
        customization = PaymentLinkCustomization(
            id=_generate_id("plc"),
            payment_link_id=payment_link_id,
            brand_color=None,
            logo_url=None,
            button_text=None,
            custom_fields=None,
            terms_url=None,
            privacy_url=None,
            created=_get_timestamp(),
        )
        session.add(customization)
        await session.flush()
    
    return CustomizationResponse(
        id=customization.id,
        payment_link_id=customization.payment_link_id,
        brand_color=customization.brand_color,
        logo_url=customization.logo_url,
        button_text=customization.button_text,
        custom_fields=customization.custom_fields,
        terms_url=customization.terms_url,
        privacy_url=customization.privacy_url,
        created=customization.created,
    )


@router.put("/{payment_link_id}/customization", response_model=CustomizationResponse)
async def update_customization(
    payment_link_id: str,
    request: Request,
    data: CustomizationUpdateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.payment_links import PaymentLinkCustomization, PaymentLink
    
    pl_query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
    pl_result = await session.execute(pl_query)
    pl = pl_result.scalar_one_or_none()
    
    if not pl:
        raise NotFoundError(f"Payment link {payment_link_id} not found")
    
    query = select(PaymentLinkCustomization).where(PaymentLinkCustomization.payment_link_id == payment_link_id)
    result = await session.execute(query)
    customization = result.scalar_one_or_none()
    
    if not customization:
        customization = PaymentLinkCustomization(
            id=_generate_id("plc"),
            payment_link_id=payment_link_id,
            brand_color=data.brand_color,
            logo_url=data.logo_url,
            button_text=data.button_text,
            custom_fields=data.custom_fields,
            terms_url=data.terms_url,
            privacy_url=data.privacy_url,
            created=_get_timestamp(),
        )
        session.add(customization)
    else:
        if data.brand_color is not None:
            customization.brand_color = data.brand_color
        if data.logo_url is not None:
            customization.logo_url = data.logo_url
        if data.button_text is not None:
            customization.button_text = data.button_text
        if data.custom_fields is not None:
            customization.custom_fields = data.custom_fields
        if data.terms_url is not None:
            customization.terms_url = data.terms_url
        if data.privacy_url is not None:
            customization.privacy_url = data.privacy_url
    
    await session.flush()
    
    return CustomizationResponse(
        id=customization.id,
        payment_link_id=customization.payment_link_id,
        brand_color=customization.brand_color,
        logo_url=customization.logo_url,
        button_text=customization.button_text,
        custom_fields=customization.custom_fields,
        terms_url=customization.terms_url,
        privacy_url=customization.privacy_url,
        created=customization.created,
    )
