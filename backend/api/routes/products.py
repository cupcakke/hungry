from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import ProductRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError

router = APIRouter()


class ProductCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=250)
    active: Optional[bool] = True
    description: Optional[str] = Field(default=None, max_length=500)
    images: Optional[List[str]] = None
    marketing_features: Optional[List[Dict[str, str]]] = None
    metadata: Optional[Dict[str, str]] = None
    package_dimensions: Optional[Dict[str, float]] = None
    shippable: Optional[bool] = None
    statement_descriptor: Optional[str] = Field(default=None, max_length=22)
    tax_code: Optional[str] = None
    type: Optional[str] = "service"
    unit_label: Optional[str] = None
    url: Optional[str] = None
    default_price: Optional[str] = None


class ProductResponse(BaseModel):
    id: str
    object: str = "product"
    active: bool
    attributes: Optional[List[str]] = None
    caption: Optional[str] = None
    created: int
    default_price: Optional[str] = None
    delete_at: Optional[int] = None
    deleted: bool = False
    description: Optional[str] = None
    images: List[str] = []
    livemode: bool = False
    marketing_features: List[Dict[str, str]] = []
    metadata: Dict[str, str] = {}
    name: str
    package_dimensions: Optional[Dict[str, float]] = None
    shippable: Optional[bool] = None
    statement_descriptor: Optional[str] = None
    tax_code: Optional[str] = None
    type: str
    unit_label: Optional[str] = None
    updated: int
    url: Optional[str] = None


def product_to_response(product: Any) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        active=product.active,
        attributes=product.attributes,
        caption=product.caption,
        created=int(product.created_at.timestamp()),
        default_price=product.default_price_id,
        delete_at=product.delete_at,
        deleted=product.is_deleted if hasattr(product, "is_deleted") else False,
        description=product.description,
        images=product.images or [],
        livemode=product.livemode,
        marketing_features=product.marketing_features or [],
        metadata=product.metadata_ or {},
        name=product.name,
        package_dimensions=product.package_dimensions,
        shippable=product.shippable,
        statement_descriptor=product.statement_descriptor,
        tax_code=product.tax_code,
        type=product.type,
        unit_label=product.unit_label,
        updated=int(product.updated_at.timestamp()),
        url=product.url,
    )


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    request: Request,
    data: ProductCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = ProductRepository(session)
    product = await repo.create_product(
        name=data.name,
        account_id=account_id,
        active=data.active,
        description=data.description,
        images=data.images,
        marketing_features=data.marketing_features,
        metadata=data.metadata,
        package_dimensions=data.package_dimensions,
        shippable=data.shippable,
        statement_descriptor=data.statement_descriptor,
        tax_code=data.tax_code,
        type=data.type or "service",
        unit_label=data.unit_label,
        url=data.url,
        default_price_id=data.default_price,
    )
    await session.commit()
    return product_to_response(product)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = ProductRepository(session)
    product = await repo.get_by_id(product_id)
    if not product or product.is_deleted:
        raise NotFoundError(f"Product {product_id} not found")
    return product_to_response(product)


@router.post("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = ProductRepository(session)
    product = await repo.get_by_id(product_id)
    if not product or product.is_deleted:
        raise NotFoundError(f"Product {product_id} not found")
    update_data = {}
    for key in ["name", "active", "description", "images", "marketing_features", "metadata", "package_dimensions", "shippable", "statement_descriptor", "tax_code", "type", "unit_label", "url", "default_price"]:
        if key in data:
            if key == "default_price":
                update_data["default_price_id"] = data[key]
            elif key == "metadata":
                update_data["metadata_"] = data[key]
            else:
                update_data[key] = data[key]
    if update_data:
        await repo.update(product_id, **update_data)
        await session.commit()
    return product_to_response(product)


@router.delete("/{product_id}", response_model=ProductResponse)
async def delete_product(
    product_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = ProductRepository(session)
    product = await repo.get_by_id(product_id)
    if not product:
        raise NotFoundError(f"Product {product_id} not found")
    await repo.soft_delete(product_id)
    await session.commit()
    return product_to_response(product)


@router.get("", response_model=PaginatedResponse[ProductResponse])
async def list_products(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    active: Optional[bool] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = ProductRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if active is not None:
        filters["active"] = active
    products = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(products) > limit
    if has_more:
        products = products[:limit]
    return PaginatedResponse(
        data=[product_to_response(p) for p in products],
        has_more=has_more,
    )
