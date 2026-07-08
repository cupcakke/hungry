from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
import secrets

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, validator

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import WebhookEndpointRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.secrets import generate_webhook_secret

router = APIRouter()


class WebhookEndpointCreateRequest(BaseModel):
    url: str = Field(..., description="Webhook URL")
    enabled_events: List[str] = Field(..., description="Events to listen for")
    connect: Optional[bool] = Field(default=False, description="Listen to Connect events")
    description: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    api_version: Optional[str] = Field(default="2024-01-01")

    @validator("url")
    def validate_url(cls, v):
        if not v.startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS")
        return v


class WebhookEndpointResponse(BaseModel):
    id: str
    object: str = "webhook_endpoint"
    api_version: Optional[str] = None
    application: Optional[str] = None
    created: int
    description: Optional[str] = None
    enabled_events: List[str] = []
    livemode: bool = False
    metadata: Dict[str, str] = {}
    secret: Optional[str] = None
    status: str = "enabled"
    url: str


def endpoint_to_response(ep: Any, include_secret: bool = False) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=ep.id,
        api_version=ep.api_version,
        application=ep.application,
        created=int(ep.created_at.timestamp()),
        description=ep.description,
        enabled_events=ep.enabled_events or [],
        livemode=ep.livemode,
        metadata=ep.metadata_ or {},
        secret=ep.secret if include_secret else None,
        status=ep.status,
        url=ep.url,
    )


@router.post("", response_model=WebhookEndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook_endpoint(
    request: Request,
    data: WebhookEndpointCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = WebhookEndpointRepository(session)
    secret = generate_webhook_secret()
    endpoint = await repo.create(
        id=f"we_{secrets.token_urlsafe(24)}",
        account_id=account_id,
        url=data.url,
        enabled_events=data.enabled_events,
        description=data.description,
        secret=secret,
        api_version=data.api_version,
        status="enabled",
    )
    await session.commit()
    return endpoint_to_response(endpoint, include_secret=True)


@router.get("/{webhook_endpoint_id}", response_model=WebhookEndpointResponse)
async def get_webhook_endpoint(
    webhook_endpoint_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = WebhookEndpointRepository(session)
    endpoint = await repo.get_by_id(webhook_endpoint_id)
    if not endpoint:
        raise NotFoundError(f"Webhook endpoint {webhook_endpoint_id} not found")
    return endpoint_to_response(endpoint)


@router.post("/{webhook_endpoint_id}", response_model=WebhookEndpointResponse)
async def update_webhook_endpoint(
    webhook_endpoint_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = WebhookEndpointRepository(session)
    endpoint = await repo.get_by_id(webhook_endpoint_id)
    if not endpoint:
        raise NotFoundError(f"Webhook endpoint {webhook_endpoint_id} not found")
    if "enabled_events" in data:
        endpoint.enabled_events = data["enabled_events"]
    if "url" in data:
        if not data["url"].startswith("https://"):
            raise ValidationError("Webhook URL must use HTTPS")
        endpoint.url = data["url"]
    if "description" in data:
        endpoint.description = data["description"]
    if "metadata" in data:
        endpoint.metadata_ = data["metadata"]
    if "disabled" in data and data["disabled"]:
        endpoint.status = "disabled"
    if "status" in data:
        endpoint.status = data["status"]
    await session.commit()
    return endpoint_to_response(endpoint)


@router.delete("/{webhook_endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_endpoint(
    webhook_endpoint_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = WebhookEndpointRepository(session)
    endpoint = await repo.get_by_id(webhook_endpoint_id)
    if not endpoint:
        raise NotFoundError(f"Webhook endpoint {webhook_endpoint_id} not found")
    await repo.delete(webhook_endpoint_id)
    await session.commit()


@router.get("", response_model=PaginatedResponse[WebhookEndpointResponse])
async def list_webhook_endpoints(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = WebhookEndpointRepository(session)
    endpoints = await repo.list(
        filters={"account_id": account_id} if account_id else {},
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(endpoints) > limit
    if has_more:
        endpoints = endpoints[:limit]
    return PaginatedResponse(
        data=[endpoint_to_response(e) for e in endpoints],
        has_more=has_more,
    )
