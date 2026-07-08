from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import EventRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError

router = APIRouter()


class EventResponse(BaseModel):
    id: str
    object: str = "event"
    account: Optional[str] = None
    api_version: str
    created: int
    data: Dict[str, Any]
    livemode: bool = False
    pending_webhooks: int = 0
    request: Optional[Dict[str, Any]] = None
    type: str


def event_to_response(event: Any) -> EventResponse:
    return EventResponse(
        id=event.id,
        account=event.account_id,
        api_version=event.api_version,
        created=int(event.created_at.timestamp()),
        data=event.data,
        livemode=event.livemode,
        pending_webhooks=event.pending_webhooks,
        request=event.request,
        type=event.type,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = EventRepository(session)
    event = await repo.get_by_id(event_id)
    if not event:
        raise NotFoundError(f"Event {event_id} not found")
    return event_to_response(event)


@router.get("", response_model=PaginatedResponse[EventResponse])
async def list_events(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    type: Optional[str] = Query(default=None),
    types: Optional[List[str]] = Query(default=None),
    created: Optional[Dict[str, int]] = None,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = EventRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if type:
        filters["type"] = type
    events = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]
    return PaginatedResponse(
        data=[event_to_response(e) for e in events],
        has_more=has_more,
    )
