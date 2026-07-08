from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import InvoiceRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class InvoiceResponse(BaseModel):
    id: str
    object: str = "invoice"
    account_country: Optional[str] = None
    account_name: Optional[str] = None
    account_tax_ids: Optional[List[str]] = None
    amount_due: int
    amount_paid: int
    amount_remaining: int
    amount_shipping: Optional[int] = None
    application: Optional[str] = None
    application_fee_amount: Optional[int] = None
    attempt_count: int
    attempted: bool
    auto_advance: Optional[bool] = None
    automatic_tax: Optional[Dict[str, Any]] = None
    billing_reason: Optional[str] = None
    charge: Optional[str] = None
    collection_method: str
    created: int
    currency: str
    custom_fields: Optional[List[Dict]] = None
    customer: Optional[str] = None
    customer_address: Optional[Dict] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_shipping: Optional[Dict] = None
    customer_tax_exempt: Optional[str] = None
    customer_tax_ids: Optional[List[Dict]] = None
    default_payment_method: Optional[str] = None
    default_source: Optional[str] = None
    default_tax_rates: Optional[List[Dict]] = None
    description: Optional[str] = None
    discount: Optional[Dict] = None
    discounts: Optional[List[str]] = None
    due_date: Optional[int] = None
    effective_at: Optional[int] = None
    ending_balance: Optional[int] = None
    footer: Optional[str] = None
    from_invoice: Optional[Dict] = None
    hosted_invoice_url: Optional[str] = None
    invoice_pdf: Optional[str] = None
    last_finalization_error: Optional[Dict] = None
    latest_payment_intent: Optional[str] = None
    livemode: bool = False
    lines: Optional[Dict] = None
    metadata: Dict[str, str] = {}
    next_payment_attempt: Optional[int] = None
    number: Optional[str] = None
    on_behalf_of: Optional[str] = None
    paid: bool
    paid_out_of_band: bool
    payment_settings: Optional[Dict] = None
    period_end: int
    period_start: int
    post_payment_credit_notes_amount: int
    pre_payment_credit_notes_amount: int
    prepayment_credit_notes: Optional[List[Dict]] = None
    quote: Optional[str] = None
    receipt_number: Optional[str] = None
    rendering_options: Optional[Dict] = None
    shipping_cost: Optional[Dict] = None
    shipping_details: Optional[Dict] = None
    starting_balance: int
    statement_descriptor: Optional[str] = None
    status: str
    status_transitions: Optional[Dict] = None
    subscription: Optional[str] = None
    subscription_details: Optional[Dict] = None
    subscription_proration_date: Optional[int] = None
    subtotal: int
    subtotal_excluding_tax: Optional[int] = None
    tax: Optional[int] = None
    total: int
    total_discount_amounts: Optional[List[Dict]] = None
    total_excluding_tax: Optional[int] = None
    total_tax_amounts: Optional[List[Dict]] = None
    transfer_data: Optional[Dict] = None
    webhooks_delivered_at: Optional[int] = None


def invoice_to_response(invoice: Any) -> InvoiceResponse:
    return InvoiceResponse(
        id=invoice.id,
        account_country=invoice.account_country,
        account_name=invoice.account_name,
        account_tax_ids=invoice.account_tax_ids,
        amount_due=invoice.amount_due,
        amount_paid=invoice.amount_paid,
        amount_remaining=invoice.amount_remaining,
        amount_shipping=invoice.amount_shipping,
        application=invoice.application,
        application_fee_amount=invoice.application_fee_amount,
        attempt_count=invoice.attempt_count,
        attempted=invoice.attempted,
        auto_advance=invoice.auto_advance,
        automatic_tax=invoice.automatic_tax,
        billing_reason=invoice.billing_reason,
        charge=invoice.charge_id,
        collection_method=invoice.collection_method,
        created=int(invoice.created_at.timestamp()),
        currency=invoice.currency,
        custom_fields=invoice.custom_fields,
        customer=invoice.customer_id,
        customer_address=invoice.customer_address,
        customer_email=invoice.customer_email,
        customer_name=invoice.customer_name,
        customer_phone=invoice.customer_phone,
        customer_shipping=invoice.customer_shipping,
        customer_tax_exempt=invoice.customer_tax_exempt,
        customer_tax_ids=invoice.customer_tax_ids,
        default_payment_method=invoice.default_payment_method,
        default_source=invoice.default_source,
        default_tax_rates=invoice.default_tax_rates,
        description=invoice.description,
        discount=invoice.discount,
        discounts=invoice.discounts,
        due_date=invoice.due_date,
        effective_at=invoice.effective_at,
        ending_balance=invoice.ending_balance,
        footer=invoice.footer,
        from_invoice=invoice.from_invoice,
        hosted_invoice_url=invoice.hosted_invoice_url,
        invoice_pdf=invoice.invoice_pdf,
        last_finalization_error=invoice.last_finalization_error,
        latest_payment_intent=invoice.latest_payment_intent,
        livemode=invoice.livemode,
        lines={"object": "list", "data": invoice.lines or [], "has_more": False},
        metadata=invoice.metadata_ or {},
        next_payment_attempt=invoice.next_payment_attempt,
        number=invoice.number,
        on_behalf_of=invoice.on_behalf_of,
        paid=invoice.paid,
        paid_out_of_band=invoice.paid_out_of_band,
        payment_settings=invoice.payment_settings,
        period_end=invoice.period_end,
        period_start=invoice.period_start,
        post_payment_credit_notes_amount=invoice.post_payment_credit_notes_amount,
        pre_payment_credit_notes_amount=invoice.pre_payment_credit_notes_amount,
        prepayment_credit_notes=invoice.prepayment_credit_notes,
        quote=invoice.quote_id,
        receipt_number=invoice.receipt_number,
        rendering_options=invoice.rendering_options,
        shipping_cost=invoice.shipping_cost,
        shipping_details=invoice.shipping_details,
        starting_balance=invoice.starting_balance,
        statement_descriptor=invoice.statement_descriptor,
        status=invoice.status,
        status_transitions=invoice.status_transitions,
        subscription=invoice.subscription_id,
        subscription_details=invoice.subscription_details,
        subscription_proration_date=invoice.subscription_proration_date,
        subtotal=invoice.subtotal,
        subtotal_excluding_tax=invoice.subtotal_excluding_tax,
        tax=invoice.tax,
        total=invoice.total,
        total_discount_amounts=invoice.total_discount_amounts,
        total_excluding_tax=invoice.total_excluding_tax,
        total_tax_amounts=invoice.total_tax_amounts,
        transfer_data=invoice.transfer_data,
        webhooks_delivered_at=invoice.webhooks_delivered_at,
    )


class InvoiceCreateRequest(BaseModel):
    customer: str = Field(..., description="Customer ID")
    account_tax_ids: Optional[List[str]] = None
    auto_advance: Optional[bool] = None
    automatic_tax: Optional[Dict[str, Any]] = None
    collection_method: Optional[str] = Field(default="charge_automatically")
    currency: Optional[str] = None
    custom_fields: Optional[List[Dict]] = None
    days_until_due: Optional[int] = Field(default=30, ge=1, le=90)
    default_payment_method: Optional[str] = None
    default_source: Optional[str] = None
    default_tax_rates: Optional[List[str]] = None
    description: Optional[str] = Field(default=None, max_length=500)
    discounts: Optional[List[str]] = None
    due_date: Optional[int] = None
    effective_at: Optional[int] = None
    footer: Optional[str] = None
    from_invoice: Optional[Dict] = None
    invoice_payer: Optional[Dict] = None
    issuer: Optional[Dict] = None
    metadata: Optional[Dict[str, str]] = None
    on_behalf_of: Optional[str] = None
    payment_settings: Optional[Dict] = None
    pending_invoice_items_behavior: Optional[str] = Field(default="exclude")
    period_end: Optional[int] = None
    period_start: Optional[int] = None
    render_pdf: Optional[bool] = None
    rendering_options: Optional[Dict] = None
    shipping_details: Optional[Dict] = None
    statement_descriptor: Optional[str] = None
    subscription: Optional[str] = None
    subscription_proration_date: Optional[int] = None
    transfer_data: Optional[Dict] = None


@router.post("", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    request: Request,
    data: InvoiceCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = InvoiceRepository(session)
    invoice = await repo.create_invoice(
        customer_id=data.customer,
        currency=data.currency or "usd",
        account_id=account_id,
        collection_method=data.collection_method or "charge_automatically",
        description=data.description,
        metadata=data.metadata,
        days_until_due=data.days_until_due,
    )
    await session.commit()
    return invoice_to_response(invoice)


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    invoice = await repo.get_by_id(invoice_id)
    if not invoice or invoice.is_deleted:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    return invoice_to_response(invoice)


@router.delete("/{invoice_id}", response_model=InvoiceResponse)
async def delete_invoice(
    invoice_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    invoice = await repo.get_by_id(invoice_id)
    if not invoice:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    if invoice.status not in ["draft"]:
        raise ValidationError("Only draft invoices can be deleted")
    invoice.status = "void"
    await repo.soft_delete(invoice_id)
    await session.commit()
    return invoice_to_response(invoice)


@router.post("/{invoice_id}/finalize", response_model=InvoiceResponse)
async def finalize_invoice(
    invoice_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    invoice = await repo.get_by_id(invoice_id)
    if not invoice:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    if invoice.status != "draft":
        raise ValidationError("Only draft invoices can be finalized")
    invoice.status = "open"
    invoice.number = f"INV-{int(time.time())}"
    await session.commit()
    return invoice_to_response(invoice)


@router.post("/{invoice_id}/pay", response_model=InvoiceResponse)
async def pay_invoice(
    invoice_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    invoice = await repo.get_by_id(invoice_id)
    if not invoice:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    if invoice.status != "open":
        raise ValidationError("Only open invoices can be paid")
    invoice.status = "paid"
    invoice.paid = True
    invoice.amount_paid = invoice.amount_due
    invoice.amount_remaining = 0
    await session.commit()
    return invoice_to_response(invoice)


@router.post("/{invoice_id}/void", response_model=InvoiceResponse)
async def void_invoice(
    invoice_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    invoice = await repo.get_by_id(invoice_id)
    if not invoice:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    if invoice.status not in ["draft", "open"]:
        raise ValidationError("Only draft or open invoices can be voided")
    invoice.status = "void"
    await session.commit()
    return invoice_to_response(invoice)


@router.get("", response_model=PaginatedResponse[InvoiceResponse])
async def list_invoices(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    customer: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    subscription: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = InvoiceRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if customer:
        filters["customer_id"] = customer
    if status_filter:
        filters["status"] = status_filter
    if subscription:
        filters["subscription_id"] = subscription
    invoices = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(invoices) > limit
    if has_more:
        invoices = invoices[:limit]
    return PaginatedResponse(
        data=[invoice_to_response(i) for i in invoices],
        has_more=has_more,
    )
