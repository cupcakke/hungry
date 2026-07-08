from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, validator

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import CustomerRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.models.address import Address
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class CustomerCreateRequest(BaseModel):
    email: Optional[EmailStr] = Field(default=None, description="Customer email address")
    name: Optional[str] = Field(default=None, max_length=100, description="Customer name")
    phone: Optional[str] = Field(default=None, max_length=20, description="Customer phone number")
    description: Optional[str] = Field(default=None, max_length=500, description="Description")
    address: Optional[Address] = Field(default=None, description="Customer address")
    balance: Optional[int] = Field(default=0, description="Customer balance in minor units")
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3, description="Default currency")
    invoice_prefix: Optional[str] = Field(default=None, max_length=20, description="Invoice prefix")
    invoice_settings: Optional[Dict[str, Any]] = Field(default=None, description="Invoice settings")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")
    payment_method: Optional[str] = Field(default=None, description="Payment method to attach")
    preferred_locales: Optional[List[str]] = Field(default=None, description="Preferred locales")
    shipping: Optional[Dict[str, Any]] = Field(default=None, description="Shipping address")
    source: Optional[str] = Field(default=None, description="Payment source to attach")
    tax: Optional[Dict[str, Any]] = Field(default=None, description="Tax settings")
    tax_exempt: Optional[str] = Field(default="none", description="Tax exempt status")
    tax_id_data: Optional[List[Dict[str, str]]] = Field(default=None, description="Tax IDs")
    test_clock: Optional[str] = Field(default=None, description="Test clock")

    @validator("tax_exempt")
    def validate_tax_exempt(cls, v):
        if v not in ["none", "exempt", "reverse"]:
            raise ValueError("tax_exempt must be one of: none, exempt, reverse")
        return v


class CustomerUpdateRequest(BaseModel):
    email: Optional[EmailStr] = Field(default=None, description="Customer email address")
    name: Optional[str] = Field(default=None, max_length=100, description="Customer name")
    phone: Optional[str] = Field(default=None, max_length=20, description="Customer phone number")
    description: Optional[str] = Field(default=None, max_length=500, description="Description")
    address: Optional[Address] = Field(default=None, description="Customer address")
    balance: Optional[int] = Field(default=None, description="Customer balance in minor units")
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3, description="Default currency")
    default_source: Optional[str] = Field(default=None, description="Default payment source")
    default_payment_method: Optional[str] = Field(default=None, description="Default payment method")
    invoice_prefix: Optional[str] = Field(default=None, max_length=20, description="Invoice prefix")
    invoice_settings: Optional[Dict[str, Any]] = Field(default=None, description="Invoice settings")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")
    preferred_locales: Optional[List[str]] = Field(default=None, description="Preferred locales")
    shipping: Optional[Dict[str, Any]] = Field(default=None, description="Shipping address")
    tax_exempt: Optional[str] = Field(default=None, description="Tax exempt status")


class CustomerResponse(BaseModel):
    id: str
    object: str = "customer"
    email: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    description: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    balance: int = 0
    currency: Optional[str] = None
    default_source: Optional[str] = None
    default_payment_method: Optional[str] = None
    invoice_prefix: Optional[str] = None
    invoice_settings: Optional[Dict[str, Any]] = None
    livemode: bool = False
    metadata: Dict[str, str] = {}
    preferred_locales: Optional[List[str]] = None
    shipping: Optional[Dict[str, Any]] = None
    tax_exempt: str = "none"
    tax_ids: Optional[List[Dict[str, Any]]] = None
    created: int
    deleted: bool = False

    class Config:
        from_attributes = True


def customer_to_response(customer: Any) -> CustomerResponse:
    return CustomerResponse(
        id=customer.id,
        email=customer.email,
        name=customer.name,
        phone=customer.phone,
        description=customer.description,
        address={
            "line1": customer.address_line1,
            "line2": customer.address_line2,
            "city": customer.address_city,
            "state": customer.address_state,
            "postal_code": customer.address_postal_code,
            "country": customer.address_country,
        } if customer.address_line1 else None,
        balance=customer.balance,
        currency=customer.currency,
        default_source=customer.default_source,
        default_payment_method=customer.default_payment_method,
        invoice_prefix=customer.invoice_prefix,
        invoice_settings={
            "default_payment_method": customer.invoice_settings_default_payment_method,
            "custom_fields": customer.invoice_settings_custom_fields,
            "footer": customer.invoice_settings_footer,
        },
        livemode=customer.livemode,
        metadata=customer.metadata_ or {},
        preferred_locales=customer.preferred_locales,
        shipping={
            "name": customer.shipping_name,
            "phone": customer.shipping_phone,
            "address": {
                "line1": customer.shipping_line1,
                "line2": customer.shipping_line2,
                "city": customer.shipping_city,
                "state": customer.shipping_state,
                "postal_code": customer.shipping_postal_code,
                "country": customer.shipping_country,
            },
        } if customer.shipping_name else None,
        tax_exempt=customer.tax_exempt,
        tax_ids=customer.tax_ids,
        created=int(customer.created_at.timestamp()),
        deleted=customer.is_deleted if hasattr(customer, "is_deleted") else False,
    )


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    request: Request,
    data: CustomerCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = CustomerRepository(session)
    customer = await repo.create_customer(
        account_id=account_id,
        email=data.email.lower() if data.email else None,
        name=data.name,
        phone=data.phone,
        description=data.description,
        metadata=data.metadata,
        currency=data.currency,
        invoice_prefix=data.invoice_prefix,
        tax_exempt=data.tax_exempt or "none",
    )
    if data.address:
        customer.address_line1 = data.address.line1
        customer.address_line2 = data.address.line2
        customer.address_city = data.address.city
        customer.address_state = data.address.state
        customer.address_postal_code = data.address.postal_code
        customer.address_country = data.address.country
    if data.shipping:
        customer.shipping_name = data.shipping.get("name")
        customer.shipping_phone = data.shipping.get("phone")
        shipping_address = data.shipping.get("address", {})
        customer.shipping_line1 = shipping_address.get("line1")
        customer.shipping_line2 = shipping_address.get("line2")
        customer.shipping_city = shipping_address.get("city")
        customer.shipping_state = shipping_address.get("state")
        customer.shipping_postal_code = shipping_address.get("postal_code")
        customer.shipping_country = shipping_address.get("country")
    await session.commit()
    return customer_to_response(customer)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = CustomerRepository(session)
    customer = await repo.get_by_id(customer_id)
    if not customer or customer.is_deleted:
        raise NotFoundError(f"Customer {customer_id} not found")
    return customer_to_response(customer)


@router.post("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    request: Request,
    data: CustomerUpdateRequest,
    session = Depends(get_session),
):
    repo = CustomerRepository(session)
    customer = await repo.get_by_id(customer_id)
    if not customer or customer.is_deleted:
        raise NotFoundError(f"Customer {customer_id} not found")
    update_data = data.dict(exclude_unset=True)
    if "email" in update_data and update_data["email"]:
        update_data["email"] = update_data["email"].lower()
    if "address" in update_data and update_data["address"]:
        addr = update_data.pop("address")
        customer.address_line1 = addr.line1 if hasattr(addr, "line1") else addr.get("line1")
        customer.address_line2 = addr.line2 if hasattr(addr, "line2") else addr.get("line2")
        customer.address_city = addr.city if hasattr(addr, "city") else addr.get("city")
        customer.address_state = addr.state if hasattr(addr, "state") else addr.get("state")
        customer.address_postal_code = addr.postal_code if hasattr(addr, "postal_code") else addr.get("postal_code")
        customer.address_country = addr.country if hasattr(addr, "country") else addr.get("country")
    if "shipping" in update_data and update_data["shipping"]:
        shipping = update_data.pop("shipping")
        customer.shipping_name = shipping.get("name")
        customer.shipping_phone = shipping.get("phone")
        shipping_addr = shipping.get("address", {})
        customer.shipping_line1 = shipping_addr.get("line1")
        customer.shipping_line2 = shipping_addr.get("line2")
        customer.shipping_city = shipping_addr.get("city")
        customer.shipping_state = shipping_addr.get("state")
        customer.shipping_postal_code = shipping_addr.get("postal_code")
        customer.shipping_country = shipping_addr.get("country")
    await repo.update(customer_id, **update_data)
    await session.commit()
    return customer_to_response(customer)


@router.delete("/{customer_id}", response_model=CustomerResponse)
async def delete_customer(
    customer_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = CustomerRepository(session)
    customer = await repo.get_by_id(customer_id)
    if not customer or customer.is_deleted:
        raise NotFoundError(f"Customer {customer_id} not found")
    await repo.soft_delete(customer_id)
    await session.commit()
    return customer_to_response(customer)


@router.get("", response_model=PaginatedResponse[CustomerResponse])
async def list_customers(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    ending_before: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
    created: Optional[Dict[str, int]] = None,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = CustomerRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if email:
        filters["email"] = email.lower()
    customers = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(customers) > limit
    if has_more:
        customers = customers[:limit]
    return PaginatedResponse(
        data=[customer_to_response(c) for c in customers],
        has_more=has_more,
    )


@router.get("/{customer_id}/payment_methods", response_model=Dict[str, Any])
async def list_customer_payment_methods(
    customer_id: str,
    request: Request,
    type: str = Query(default="card"),
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import PaymentMethodRepository
    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_by_id(customer_id)
    if not customer or customer.is_deleted:
        raise NotFoundError(f"Customer {customer_id} not found")
    pm_repo = PaymentMethodRepository(session)
    payment_methods = await pm_repo.get_by_customer(customer_id)
    filtered = [pm for pm in payment_methods if pm.type == type]
    return {
        "object": "list",
        "data": [
            {
                "id": pm.id,
                "object": "payment_method",
                "type": pm.type,
                "card": pm.card,
                "billing_details": pm.billing_details,
                "customer": pm.customer_id,
            }
            for pm in filtered
        ],
        "has_more": False,
    }
