from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from payment_platform.webhook_service.domain.models import (
    DeliveryStatus,
    EndpointStatus,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
    DeadLetterEntry,
)
from payment_platform.webhook_service.services.delivery_service import WebhookDeliveryService
from payment_platform.webhook_service.services.retry_service import WebhookRetryService
from payment_platform.webhook_service.services.event_builder import EventBuilderService
from payment_platform.webhook_service.services.dead_letter_service import DeadLetterService


router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])

_delivery_service = WebhookDeliveryService()
_dead_letter_service = DeadLetterService()
_retry_service = WebhookRetryService(dead_letter_service=_dead_letter_service)
_event_builder = EventBuilderService()

_endpoints: Dict[str, WebhookEndpoint] = {}
_events: Dict[str, WebhookEvent] = {}


class DeliverRequest(BaseModel):
    event_id: str
    endpoint_id: str
    account_id: Optional[str] = None


class DeliverResponse(BaseModel):
    status: str
    delivery_id: Optional[str] = None
    event_id: str
    endpoint_id: str
    attempt_number: int
    response_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None


class DeliveryListResponse(BaseModel):
    data: List[WebhookDelivery]
    has_more: bool
    total_count: int


class RetryRequest(BaseModel):
    delivery_id: str
    force: bool = False


class RetryResponse(BaseModel):
    status: str
    delivery_id: str
    message: Optional[str] = None
    scheduled_at: Optional[str] = None


class ServiceStatusResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: int
    delivery_stats: Dict[str, Any]
    retry_stats: Dict[str, Any]
    dead_letter_stats: Dict[str, Any]
    endpoints_count: int
    events_count: int


class CreateEndpointRequest(BaseModel):
    url: str
    events_subscribed: List[str] = Field(default_factory=lambda: ["*"])
    account_id: Optional[str] = None
    description: Optional[str] = None


class EndpointResponse(BaseModel):
    id: str
    url: str
    status: str
    events_subscribed: List[str]
    secret: str
    failure_count: int
    last_success_at: Optional[str] = None


class CreateEventRequest(BaseModel):
    type: str
    data: Dict[str, Any]
    account_id: Optional[str] = None
    livemode: bool = False


class EventResponse(BaseModel):
    id: str
    type: str
    created_at: str
    account_id: Optional[str] = None


class DeadLetterListResponse(BaseModel):
    data: List[DeadLetterEntry]
    has_more: bool
    total_count: int


class ReplayRequest(BaseModel):
    entry_ids: List[str]


class ReplayResponse(BaseModel):
    status: str
    replayed_count: int
    results: Dict[str, Optional[str]]


_start_time = datetime.now(timezone.utc)


@router.post("/deliver", response_model=DeliverResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_delivery(request: DeliverRequest):
    event = _events.get(request.event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {request.event_id} not found"
        )
    endpoint = _endpoints.get(request.endpoint_id)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint {request.endpoint_id} not found"
        )
    if endpoint.status != EndpointStatus.ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Endpoint is not enabled"
        )
    if not endpoint.is_subscribed_to(event.type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Endpoint is not subscribed to event type {event.type}"
        )
    delivery = await _delivery_service.deliver(endpoint, event)
    if delivery.status == DeliveryStatus.FAILED:
        await _retry_service.schedule_retry(
            delivery=delivery,
            endpoint=endpoint,
            event_payload=event.to_payload(),
            failure_reason=delivery.error_message,
        )
    return DeliverResponse(
        status=delivery.status.value,
        delivery_id=delivery.id,
        event_id=delivery.event_id,
        endpoint_id=delivery.endpoint_id,
        attempt_number=delivery.attempt_number,
        response_code=delivery.response_code,
        duration_ms=delivery.duration_ms,
        error_message=delivery.error_message,
    )


@router.get("/deliveries", response_model=DeliveryListResponse)
async def list_deliveries(
    endpoint_id: Optional[str] = Query(None),
    event_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    status_enum = None
    if status_filter:
        try:
            status_enum = DeliveryStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}"
            )
    deliveries = await _delivery_service.list_deliveries(
        endpoint_id=endpoint_id,
        event_id=event_id,
        status=status_enum,
        limit=limit + 1,
        offset=offset,
    )
    has_more = len(deliveries) > limit
    if has_more:
        deliveries = deliveries[:limit]
    stats = await _delivery_service.get_delivery_stats()
    return DeliveryListResponse(
        data=deliveries,
        has_more=has_more,
        total_count=stats["total_deliveries"],
    )


@router.post("/retry", response_model=RetryResponse)
async def manual_retry(request: RetryRequest):
    delivery = await _delivery_service.track_delivery(request.delivery_id)
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery {request.delivery_id} not found"
        )
    if delivery.status == DeliveryStatus.SUCCEEDED and not request.force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delivery already succeeded. Use force=true to retry."
        )
    event = _events.get(delivery.event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {delivery.event_id} not found"
        )
    endpoint = _endpoints.get(delivery.endpoint_id)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint {delivery.endpoint_id} not found"
        )
    if endpoint.status != EndpointStatus.ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Endpoint is not enabled"
        )
    new_attempt = delivery.attempt_number + 1
    new_delivery = await _delivery_service.deliver(endpoint, event, attempt_number=new_attempt)
    if new_delivery.status == DeliveryStatus.FAILED:
        await _retry_service.schedule_retry(
            delivery=new_delivery,
            endpoint=endpoint,
            event_payload=event.to_payload(),
            failure_reason=new_delivery.error_message,
        )
    return RetryResponse(
        status="retrying",
        delivery_id=new_delivery.id,
        message=f"Retry attempt {new_attempt} initiated",
        scheduled_at=new_delivery.delivered_at.isoformat() if new_delivery.delivered_at else None,
    )


@router.get("/status", response_model=ServiceStatusResponse)
async def get_service_status():
    now = datetime.now(timezone.utc)
    uptime = int((now - _start_time).total_seconds())
    delivery_stats = await _delivery_service.get_delivery_stats()
    retry_stats = await _retry_service.get_retry_stats()
    dead_letter_stats = await _dead_letter_service.get_stats()
    return ServiceStatusResponse(
        status="healthy",
        version="1.0.0",
        uptime_seconds=uptime,
        delivery_stats=delivery_stats,
        retry_stats=retry_stats,
        dead_letter_stats=dead_letter_stats,
        endpoints_count=len(_endpoints),
        events_count=len(_events),
    )


@router.post("/endpoints", response_model=EndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(request: CreateEndpointRequest):
    endpoint = WebhookEndpoint(
        id=f"we_{uuid4().hex[:24]}",
        url=request.url,
        events_subscribed=request.events_subscribed,
        account_id=request.account_id,
        description=request.description,
    )
    _endpoints[endpoint.id] = endpoint
    _retry_service.create_policy(endpoint.id)
    return EndpointResponse(
        id=endpoint.id,
        url=endpoint.url,
        status=endpoint.status.value,
        events_subscribed=endpoint.events_subscribed,
        secret=endpoint.secret,
        failure_count=endpoint.failure_count,
        last_success_at=endpoint.last_success_at.isoformat() if endpoint.last_success_at else None,
    )


@router.get("/endpoints", response_model=List[EndpointResponse])
async def list_endpoints(
    account_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
):
    endpoints = list(_endpoints.values())
    if account_id:
        endpoints = [e for e in endpoints if e.account_id == account_id]
    if status_filter:
        try:
            status_enum = EndpointStatus(status_filter)
            endpoints = [e for e in endpoints if e.status == status_enum]
        except ValueError:
            pass
    return [
        EndpointResponse(
            id=e.id,
            url=e.url,
            status=e.status.value,
            events_subscribed=e.events_subscribed,
            secret=e.secret,
            failure_count=e.failure_count,
            last_success_at=e.last_success_at.isoformat() if e.last_success_at else None,
        )
        for e in endpoints[:limit]
    ]


@router.get("/endpoints/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(endpoint_id: str):
    endpoint = _endpoints.get(endpoint_id)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Endpoint {endpoint_id} not found"
        )
    return EndpointResponse(
        id=endpoint.id,
        url=endpoint.url,
        status=endpoint.status.value,
        events_subscribed=endpoint.events_subscribed,
        secret=endpoint.secret,
        failure_count=endpoint.failure_count,
        last_success_at=endpoint.last_success_at.isoformat() if endpoint.last_success_at else None,
    )


@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(request: CreateEventRequest):
    event = WebhookEvent(
        id=f"evt_{uuid4().hex[:24]}",
        type=request.type,
        data=request.data,
        account_id=request.account_id,
        livemode=request.livemode,
    )
    _events[event.id] = event
    return EventResponse(
        id=event.id,
        type=event.type,
        created_at=event.created_at.isoformat(),
        account_id=event.account_id,
    )


@router.get("/events", response_model=List[EventResponse])
async def list_events(
    event_type: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
):
    events = list(_events.values())
    if event_type:
        events = [e for e in events if e.type == event_type]
    if account_id:
        events = [e for e in events if e.account_id == account_id]
    events.sort(key=lambda x: x.created_at, reverse=True)
    return [
        EventResponse(
            id=e.id,
            type=e.type,
            created_at=e.created_at.isoformat(),
            account_id=e.account_id,
        )
        for e in events[:limit]
    ]


@router.get("/dead-letter", response_model=DeadLetterListResponse)
async def list_dead_letter(
    endpoint_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if endpoint_id:
        entries = await _dead_letter_service.retrieve_by_endpoint(endpoint_id, limit + 1, offset)
    elif account_id:
        entries = await _dead_letter_service.retrieve_by_account(account_id, limit + 1, offset)
    else:
        entries = list(_dead_letter_service._entries.values())
        entries.sort(key=lambda x: x.created_at, reverse=True)
        entries = entries[offset:offset + limit + 1]
    has_more = len(entries) > limit
    if has_more:
        entries = entries[:limit]
    stats = await _dead_letter_service.get_stats()
    return DeadLetterListResponse(
        data=entries,
        has_more=has_more,
        total_count=stats["total_entries"],
    )


@router.post("/dead-letter/replay", response_model=ReplayResponse)
async def replay_dead_letter(request: ReplayRequest):
    results = await _dead_letter_service.replay_batch(request.entry_ids)
    replayed_events = {k: v.id if v else None for k, v in results.items()}
    successful = sum(1 for v in results.values() if v is not None)
    return ReplayResponse(
        status="completed",
        replayed_count=successful,
        results=replayed_events,
    )


@router.delete("/dead-letter/{entry_id}")
async def delete_dead_letter_entry(entry_id: str):
    success = await _dead_letter_service.delete(entry_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dead letter entry {entry_id} not found"
        )
    return {"status": "deleted", "entry_id": entry_id}


@router.post("/cleanup")
async def cleanup_expired():
    expired_count = await _dead_letter_service.cleanup_expired()
    return {
        "status": "completed",
        "expired_entries_removed": expired_count,
    }
