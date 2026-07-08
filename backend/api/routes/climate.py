from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from decimal import Decimal

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class ClimateProductResponse(BaseModel):
    id: str
    object: str = "climate.product"
    name: str
    type: str
    description: Optional[str] = None
    metric_tons_available: float
    price_per_ton: int
    currency: str
    verification_standard: str
    project_location: Optional[str] = None
    project_name: Optional[str] = None
    project_id: Optional[str] = None
    vintage_year: Optional[int] = None
    co_benefits: Optional[List[str]] = None
    sdg_impact: Optional[List[str]] = None
    active: bool = True
    created: int
    livemode: bool = False


class ClimateOrderCreateRequest(BaseModel):
    product_id: str = Field(..., description="Climate product ID")
    metric_tons: float = Field(..., gt=0, description="Number of metric tons to purchase")
    currency: str = Field(default="usd", min_length=3, max_length=3, description="Currency code")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ClimateOrderResponse(BaseModel):
    id: str
    object: str = "climate.order"
    account_id: str
    product_id: str
    amount: int
    currency: str
    metric_tons: float
    status: str
    payment_intent_id: Optional[str] = None
    payment_status: Optional[str] = None
    certificate_url: Optional[str] = None
    certificate_generated_at: Optional[int] = None
    cancellation_reason: Optional[str] = None
    canceled_at: Optional[int] = None
    fulfilled_at: Optional[int] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class CarbonCreditResponse(BaseModel):
    id: str
    object: str = "climate.carbon_credit"
    order_id: str
    metric_tons: float
    serial_number: str
    vintage_year: int
    verification_standard: str
    project_id: str
    status: str
    certificate_url: Optional[str] = None
    issued_at: Optional[int] = None
    retired_at: Optional[int] = None
    transferred_at: Optional[int] = None
    transferred_to: Optional[str] = None
    retirement_beneficiary: Optional[str] = None
    retirement_reason: Optional[str] = None
    created: int
    livemode: bool = False


class ClimateImpactResponse(BaseModel):
    id: str
    object: str = "climate.impact"
    account_id: str
    total_metric_tons: float
    total_amount: int
    currency: str
    contributions_count: int
    year: int
    carbon_removal_tons: float
    carbon_avoidance_tons: float
    projects_supported: Optional[List[str]] = None
    co2_equivalent_kg: float


class ClimateReportCreateRequest(BaseModel):
    report_type: str = Field(default="monthly", description="Report type: monthly or annual")
    year: int = Field(..., description="Year for the report")
    month: Optional[int] = Field(default=None, ge=1, le=12, description="Month for monthly reports")


class ClimateReportResponse(BaseModel):
    id: str
    object: str = "climate.report"
    account_id: str
    period_start: int
    period_end: int
    total_offset: float
    total_amount: int
    currency: str
    certificates_count: int
    certificates: Optional[List[Dict[str, Any]]] = None
    projects: Optional[List[Dict[str, Any]]] = None
    report_type: str
    status: str
    report_url: Optional[str] = None
    generated_at: Optional[int] = None
    created: int
    livemode: bool = False


class ImpactSummaryResponse(BaseModel):
    account_id: str
    current_year: int
    current_year_impact: Dict[str, Any]
    lifetime_impact: Dict[str, Any]
    co2_equivalent: Dict[str, Any]
    yearly_breakdown: Optional[List[Dict[str, Any]]] = None


class CertificateResponse(BaseModel):
    certificate_id: str
    serial_number: str
    metric_tons: float
    vintage_year: int
    verification_standard: str
    project_id: str
    status: str
    issued_at: Optional[int] = None
    order_id: Optional[str] = None
    account_id: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    product_name: Optional[str] = None
    product_type: Optional[str] = None
    project_location: Optional[str] = None


class PricingRequest(BaseModel):
    product_id: str = Field(..., description="Climate product ID")
    metric_tons: float = Field(..., gt=0, description="Number of metric tons")
    currency: str = Field(default="usd", description="Currency code")


class PricingResponse(BaseModel):
    metric_tons: float
    unit_price: int
    total_amount: int
    currency: str
    fee: int


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


@router.get("/products", response_model=PaginatedResponse[ClimateProductResponse])
async def list_climate_products(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    product_type: Optional[str] = None,
    verification_standard: Optional[str] = None,
    min_metric_tons: Optional[float] = None,
    max_price_per_ton: Optional[int] = None,
    project_location: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.climate import ClimateProduct, ClimateProductType

    query = select(ClimateProduct).where(ClimateProduct.active == True)

    if product_type:
        if product_type == "carbon_removal":
            query = query.where(ClimateProduct.type == ClimateProductType.CARBON_REMOVAL)
        elif product_type == "carbon_avoidance":
            query = query.where(ClimateProduct.type == ClimateProductType.CARBON_AVOIDANCE)

    if verification_standard:
        query = query.where(ClimateProduct.verification_standard == verification_standard)

    if min_metric_tons is not None:
        query = query.where(ClimateProduct.metric_tons_available >= min_metric_tons)

    if max_price_per_ton is not None:
        query = query.where(ClimateProduct.price_per_ton <= max_price_per_ton)

    if project_location:
        query = query.where(ClimateProduct.project_location.ilike(f"%{project_location}%"))

    if starting_after:
        query = query.where(ClimateProduct.id > starting_after)

    query = query.order_by(ClimateProduct.created_at.desc()).limit(limit + 1)

    result = await session.execute(query)
    products = list(result.scalars().all())

    has_more = len(products) > limit
    if has_more:
        products = products[:limit]

    data = [
        ClimateProductResponse(
            id=p.id,
            name=p.name,
            type=p.type.value,
            description=p.description,
            metric_tons_available=float(p.metric_tons_available),
            price_per_ton=p.price_per_ton,
            currency=p.currency,
            verification_standard=p.verification_standard.value,
            project_location=p.project_location,
            project_name=p.project_name,
            project_id=p.project_id,
            vintage_year=p.vintage_year,
            co_benefits=p.co_benefits,
            sdg_impact=p.sdg_impact,
            active=p.active,
            created=p.created,
        )
        for p in products
    ]

    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/products/{product_id}", response_model=ClimateProductResponse)
async def get_climate_product(
    product_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.climate import ClimateProduct

    query = select(ClimateProduct).where(ClimateProduct.id == product_id)
    result = await session.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise NotFoundError(f"Climate product {product_id} not found")

    return ClimateProductResponse(
        id=product.id,
        name=product.name,
        type=product.type.value,
        description=product.description,
        metric_tons_available=float(product.metric_tons_available),
        price_per_ton=product.price_per_ton,
        currency=product.currency,
        verification_standard=product.verification_standard.value,
        project_location=product.project_location,
        project_name=product.project_name,
        project_id=product.project_id,
        vintage_year=product.vintage_year,
        co_benefits=product.co_benefits,
        sdg_impact=product.sdg_impact,
        active=product.active,
        created=product.created,
    )


@router.post("/products/{product_id}/pricing", response_model=PricingResponse)
async def calculate_product_pricing(
    product_id: str,
    data: PricingRequest,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import ProductService

    product_service = ProductService(session)
    pricing = await product_service.calculate_pricing(
        product_id=product_id,
        metric_tons=Decimal(str(data.metric_tons)),
        currency=data.currency,
    )

    return PricingResponse(
        metric_tons=float(pricing.metric_tons),
        unit_price=pricing.unit_price,
        total_amount=pricing.total_amount,
        currency=pricing.currency,
        fee=pricing.fee,
    )


@router.post("/orders", response_model=ClimateOrderResponse, status_code=201)
async def create_climate_order(
    request: Request,
    data: ClimateOrderCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import OrderService

    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")

    order_service = OrderService(session)
    order = await order_service.create(
        account_id=account_id,
        product_id=data.product_id,
        metric_tons=Decimal(str(data.metric_tons)),
        currency=data.currency,
        metadata=data.metadata,
    )

    return ClimateOrderResponse(
        id=order.id,
        account_id=order.account_id,
        product_id=order.product_id,
        amount=order.amount,
        currency=order.currency,
        metric_tons=float(order.metric_tons),
        status=order.status.value,
        payment_intent_id=order.payment_intent_id,
        payment_status=order.payment_status,
        certificate_url=order.certificate_url,
        certificate_generated_at=order.certificate_generated_at,
        cancellation_reason=order.cancellation_reason,
        canceled_at=order.canceled_at,
        fulfilled_at=order.fulfilled_at,
        created=order.created,
        metadata=order.metadata_,
    )


@router.get("/orders", response_model=PaginatedResponse[ClimateOrderResponse])
async def list_climate_orders(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.climate import ClimateOrder

    account_id = _get_account_id(request)

    query = select(ClimateOrder)
    if account_id:
        query = query.where(ClimateOrder.account_id == account_id)
    if status:
        query = query.where(ClimateOrder.status == status)
    if product_id:
        query = query.where(ClimateOrder.product_id == product_id)
    if starting_after:
        query = query.where(ClimateOrder.id > starting_after)

    query = query.order_by(ClimateOrder.created_at.desc()).limit(limit + 1)

    result = await session.execute(query)
    orders = list(result.scalars().all())

    has_more = len(orders) > limit
    if has_more:
        orders = orders[:limit]

    data = [
        ClimateOrderResponse(
            id=o.id,
            account_id=o.account_id,
            product_id=o.product_id,
            amount=o.amount,
            currency=o.currency,
            metric_tons=float(o.metric_tons),
            status=o.status.value,
            payment_intent_id=o.payment_intent_id,
            payment_status=o.payment_status,
            certificate_url=o.certificate_url,
            certificate_generated_at=o.certificate_generated_at,
            cancellation_reason=o.cancellation_reason,
            canceled_at=o.canceled_at,
            fulfilled_at=o.fulfilled_at,
            created=o.created,
            metadata=o.metadata_,
        )
        for o in orders
    ]

    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/orders/{order_id}", response_model=ClimateOrderResponse)
async def get_climate_order(
    order_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.climate import ClimateOrder

    query = select(ClimateOrder).where(ClimateOrder.id == order_id)
    result = await session.execute(query)
    order = result.scalar_one_or_none()

    if not order:
        raise NotFoundError(f"Climate order {order_id} not found")

    return ClimateOrderResponse(
        id=order.id,
        account_id=order.account_id,
        product_id=order.product_id,
        amount=order.amount,
        currency=order.currency,
        metric_tons=float(order.metric_tons),
        status=order.status.value,
        payment_intent_id=order.payment_intent_id,
        payment_status=order.payment_status,
        certificate_url=order.certificate_url,
        certificate_generated_at=order.certificate_generated_at,
        cancellation_reason=order.cancellation_reason,
        canceled_at=order.canceled_at,
        fulfilled_at=order.fulfilled_at,
        created=order.created,
        metadata=order.metadata_,
    )


@router.post("/orders/{order_id}/cancel", response_model=ClimateOrderResponse)
async def cancel_climate_order(
    order_id: str,
    request: Request,
    reason: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import OrderService

    order_service = OrderService(session)
    order = await order_service.cancel(order_id, reason=reason)

    return ClimateOrderResponse(
        id=order.id,
        account_id=order.account_id,
        product_id=order.product_id,
        amount=order.amount,
        currency=order.currency,
        metric_tons=float(order.metric_tons),
        status=order.status.value,
        payment_intent_id=order.payment_intent_id,
        payment_status=order.payment_status,
        certificate_url=order.certificate_url,
        certificate_generated_at=order.certificate_generated_at,
        cancellation_reason=order.cancellation_reason,
        canceled_at=order.canceled_at,
        fulfilled_at=order.fulfilled_at,
        created=order.created,
        metadata=order.metadata_,
    )


@router.get("/credits", response_model=PaginatedResponse[CarbonCreditResponse])
async def list_carbon_credits(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    verification_standard: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import CreditService

    account_id = _get_account_id(request)

    credit_service = CreditService(session)
    credits = await credit_service.list_credits(
        account_id=account_id,
        status=status,
        verification_standard=verification_standard,
        limit=limit + 1,
    )

    has_more = len(credits) > limit
    if has_more:
        credits = credits[:limit]

    data = [
        CarbonCreditResponse(
            id=c.id,
            order_id=c.order_id,
            metric_tons=float(c.metric_tons),
            serial_number=c.serial_number,
            vintage_year=c.vintage_year,
            verification_standard=c.verification_standard.value,
            project_id=c.project_id,
            status=c.status.value,
            certificate_url=c.certificate_url,
            issued_at=c.issued_at,
            retired_at=c.retired_at,
            transferred_at=c.transferred_at,
            transferred_to=c.transferred_to,
            retirement_beneficiary=c.retirement_beneficiary,
            retirement_reason=c.retirement_reason,
            created=c.created,
        )
        for c in credits
    ]

    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/credits/{credit_id}", response_model=CarbonCreditResponse)
async def get_carbon_credit(
    credit_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.climate import CarbonCredit

    query = select(CarbonCredit).where(CarbonCredit.id == credit_id)
    result = await session.execute(query)
    credit = result.scalar_one_or_none()

    if not credit:
        raise NotFoundError(f"Carbon credit {credit_id} not found")

    return CarbonCreditResponse(
        id=credit.id,
        order_id=credit.order_id,
        metric_tons=float(credit.metric_tons),
        serial_number=credit.serial_number,
        vintage_year=credit.vintage_year,
        verification_standard=credit.verification_standard.value,
        project_id=credit.project_id,
        status=credit.status.value,
        certificate_url=credit.certificate_url,
        issued_at=credit.issued_at,
        retired_at=credit.retired_at,
        transferred_at=credit.transferred_at,
        transferred_to=credit.transferred_to,
        retirement_beneficiary=credit.retirement_beneficiary,
        retirement_reason=credit.retirement_reason,
        created=credit.created,
    )


@router.get("/credits/{credit_id}/certificate", response_model=CertificateResponse)
async def get_credit_certificate(
    credit_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import CreditService

    credit_service = CreditService(session)
    certificate = await credit_service.generate_certificate(credit_id)

    return CertificateResponse(**certificate)


@router.post("/credits/{credit_id}/retire", response_model=CarbonCreditResponse)
async def retire_carbon_credit(
    credit_id: str,
    request: Request,
    beneficiary: Optional[str] = None,
    reason: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import CreditService

    credit_service = CreditService(session)
    credit = await credit_service.retire(
        credit_id=credit_id,
        beneficiary=beneficiary,
        reason=reason,
    )

    return CarbonCreditResponse(
        id=credit.id,
        order_id=credit.order_id,
        metric_tons=float(credit.metric_tons),
        serial_number=credit.serial_number,
        vintage_year=credit.vintage_year,
        verification_standard=credit.verification_standard.value,
        project_id=credit.project_id,
        status=credit.status.value,
        certificate_url=credit.certificate_url,
        issued_at=credit.issued_at,
        retired_at=credit.retired_at,
        transferred_at=credit.transferred_at,
        transferred_to=credit.transferred_to,
        retirement_beneficiary=credit.retirement_beneficiary,
        retirement_reason=credit.retirement_reason,
        created=credit.created,
    )


@router.get("/impact", response_model=ImpactSummaryResponse)
async def get_climate_impact(
    request: Request,
    year: Optional[int] = None,
    include_yearly_breakdown: bool = True,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import ImpactService

    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")

    impact_service = ImpactService(session)
    summary = await impact_service.generate_summary(
        account_id=account_id,
        include_yearly_breakdown=include_yearly_breakdown,
    )

    return ImpactSummaryResponse(**summary)


@router.get("/impact/{year}", response_model=ClimateImpactResponse)
async def get_climate_impact_by_year(
    year: int,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.climate import ClimateImpact

    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")

    query = select(ClimateImpact).where(
        ClimateImpact.account_id == account_id,
        ClimateImpact.year == year,
    )
    result = await session.execute(query)
    impact = result.scalar_one_or_none()

    if not impact:
        return ClimateImpactResponse(
            id="",
            account_id=account_id,
            total_metric_tons=0.0,
            total_amount=0,
            currency="usd",
            contributions_count=0,
            year=year,
            carbon_removal_tons=0.0,
            carbon_avoidance_tons=0.0,
            projects_supported=[],
            co2_equivalent_kg=0.0,
        )

    return ClimateImpactResponse(
        id=impact.id,
        account_id=impact.account_id,
        total_metric_tons=float(impact.total_metric_tons),
        total_amount=impact.total_amount,
        currency=impact.currency,
        contributions_count=impact.contributions_count,
        year=impact.year,
        carbon_removal_tons=float(impact.carbon_removal_tons),
        carbon_avoidance_tons=float(impact.carbon_avoidance_tons),
        projects_supported=impact.projects_supported,
        co2_equivalent_kg=float(impact.co2_equivalent_kg),
    )


@router.get("/reports", response_model=PaginatedResponse[ClimateReportResponse])
async def list_climate_reports(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    report_type: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import ReportService

    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")

    report_service = ReportService(session)
    reports = await report_service.list_reports(
        account_id=account_id,
        report_type=report_type,
        limit=limit + 1,
    )

    has_more = len(reports) > limit
    if has_more:
        reports = reports[:limit]

    data = [
        ClimateReportResponse(
            id=r.id,
            account_id=r.account_id,
            period_start=r.period_start,
            period_end=r.period_end,
            total_offset=float(r.total_offset),
            total_amount=r.total_amount,
            currency=r.currency,
            certificates_count=r.certificates_count,
            certificates=r.certificates,
            projects=r.projects,
            report_type=r.report_type,
            status=r.status.value,
            report_url=r.report_url,
            generated_at=r.generated_at,
            created=r.created,
        )
        for r in reports
    ]

    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/reports", response_model=ClimateReportResponse, status_code=201)
async def generate_climate_report(
    request: Request,
    data: ClimateReportCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import ReportService

    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")

    report_service = ReportService(session)

    if data.report_type == "annual":
        report = await report_service.generate_annual(
            account_id=account_id,
            year=data.year,
        )
    else:
        if not data.month:
            raise ValidationError("Month is required for monthly reports", param="month")
        report = await report_service.generate_monthly(
            account_id=account_id,
            year=data.year,
            month=data.month,
        )

    return ClimateReportResponse(
        id=report.id,
        account_id=report.account_id,
        period_start=report.period_start,
        period_end=report.period_end,
        total_offset=float(report.total_offset),
        total_amount=report.total_amount,
        currency=report.currency,
        certificates_count=report.certificates_count,
        certificates=report.certificates,
        projects=report.projects,
        report_type=report.report_type,
        status=report.status.value,
        report_url=report.report_url,
        generated_at=report.generated_at,
        created=report.created,
    )


@router.get("/reports/{report_id}", response_model=ClimateReportResponse)
async def get_climate_report(
    report_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.climate import ClimateReport

    query = select(ClimateReport).where(ClimateReport.id == report_id)
    result = await session.execute(query)
    report = result.scalar_one_or_none()

    if not report:
        raise NotFoundError(f"Climate report {report_id} not found")

    return ClimateReportResponse(
        id=report.id,
        account_id=report.account_id,
        period_start=report.period_start,
        period_end=report.period_end,
        total_offset=float(report.total_offset),
        total_amount=report.total_amount,
        currency=report.currency,
        certificates_count=report.certificates_count,
        certificates=report.certificates,
        projects=report.projects,
        report_type=report.report_type,
        status=report.status.value,
        report_url=report.report_url,
        generated_at=report.generated_at,
        created=report.created,
    )


@router.get("/verifications")
async def list_verifications(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    project_id: Optional[str] = None,
    standard: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import VerificationService

    verification_service = VerificationService(session)
    verifications = await verification_service.list_verifications(
        project_id=project_id,
        standard=standard,
        limit=limit + 1,
    )

    has_more = len(verifications) > limit
    if has_more:
        verifications = verifications[:limit]

    data = [
        {
            "id": v.id,
            "object": "climate.project_verification",
            "project_id": v.project_id,
            "standard": v.standard.value,
            "verification_date": v.verification_date,
            "certifier": v.certifier,
            "certificate_number": v.certificate_number,
            "verification_body": v.verification_body,
            "valid_from": v.valid_from,
            "valid_until": v.valid_until,
            "verification_url": v.verification_url,
            "status": v.status,
            "created": v.created,
        }
        for v in verifications
    ]

    return {"data": data, "has_more": has_more}


@router.get("/verifications/{verification_id}")
async def get_verification(
    verification_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import VerificationService

    verification_service = VerificationService(session)
    verification = await verification_service.get_verification(verification_id)

    if not verification:
        raise NotFoundError(f"Project verification {verification_id} not found")

    return {
        "id": verification.id,
        "object": "climate.project_verification",
        "project_id": verification.project_id,
        "standard": verification.standard.value,
        "verification_date": verification.verification_date,
        "certifier": verification.certifier,
        "certificate_number": verification.certificate_number,
        "verification_body": verification.verification_body,
        "valid_from": verification.valid_from,
        "valid_until": verification.valid_until,
        "verification_url": verification.verification_url,
        "status": verification.status,
        "created": verification.created,
    }


@router.post("/verifications/{verification_id}/validate")
async def validate_verification(
    verification_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.climate_service import VerificationService

    verification_service = VerificationService(session)
    verification = await verification_service.get_verification(verification_id)

    if not verification:
        raise NotFoundError(f"Project verification {verification_id} not found")

    validation_result = await verification_service.validate_credits([verification.project_id])

    return {
        "verification_id": verification_id,
        "is_valid": len(validation_result["valid"]) > 0,
        "validation_result": validation_result,
    }
