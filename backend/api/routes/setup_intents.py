from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time
import secrets

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import SetupIntentRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_setup_intent_id

router = APIRouter()


class SetupIntentCreateRequest(BaseModel):
    customer: Optional[str] = Field(default=None, description="Customer ID")
    description: Optional[str] = Field(default=None, max_length=500)
    metadata: Optional[Dict[str, str]] = Field(default=None)
    payment_method_types: Optional[List[str]] = Field(default=["card"])
    payment_method_options: Optional[Dict[str, Any]] = Field(default=None)
    payment_method_data: Optional[Dict[str, Any]] = Field(default=None)
    on_behalf_of: Optional[str] = Field(default=None)
    return_url: Optional[str] = Field(default=None)
    confirm: Optional[bool] = Field(default=False)
    usage: Optional[str] = Field(default="off_session", description="off_session or on_session")
    attach_to_self: Optional[bool] = Field(default=False)
    flow_directions: Optional[List[str]] = Field(default=None)
    mandate_data: Optional[Dict[str, Any]] = Field(default=None)
    single_use: Optional[Dict[str, Any]] = Field(default=None)


class SetupIntentConfirmRequest(BaseModel):
    payment_method: Optional[str] = Field(default=None)
    payment_method_options: Optional[Dict[str, Any]] = Field(default=None)
    payment_method_data: Optional[Dict[str, Any]] = Field(default=None)
    mandate_data: Optional[Dict[str, Any]] = Field(default=None)
    return_url: Optional[str] = Field(default=None)
    mandate: Optional[str] = Field(default=None)


class SetupIntentResponse(BaseModel):
    id: str
    object: str = "setup_intent"
    application: Optional[str] = None
    attach_to_self: Optional[bool] = None
    cancellation_reason: Optional[str] = None
    client_secret: Optional[str] = None
    created: int
    customer: Optional[str] = None
    description: Optional[str] = None
    flow_directions: Optional[List[str]] = None
    last_setup_error: Optional[Dict[str, Any]] = None
    latest_attempt: Optional[str] = None
    livemode: bool = False
    mandate: Optional[str] = None
    metadata: Dict[str, str] = {}
    next_action: Optional[Dict[str, Any]] = None
    on_behalf_of: Optional[str] = None
    payment_method: Optional[str] = None
    payment_method_configuration_details: Optional[Dict[str, Any]] = None
    payment_method_options: Optional[Dict[str, Any]] = None
    payment_method_types: List[str] = ["card"]
    single_use_mandate: Optional[str] = None
    status: str
    usage: str
    attach_to_self: Optional[bool] = None


def setup_intent_to_response(si: Any) -> SetupIntentResponse:
    return SetupIntentResponse(
        id=si.id,
        application=si.application,
        attach_to_self=si.attach_to_self,
        cancellation_reason=si.cancellation_reason,
        client_secret=si.client_secret,
        created=int(si.created_at.timestamp()),
        customer=si.customer_id,
        description=si.description,
        flow_directions=si.flow_directions,
        last_setup_error=si.last_setup_error,
        latest_attempt=si.latest_attempt,
        livemode=si.livemode,
        mandate=si.mandate,
        metadata=si.metadata_ or {},
        next_action=si.next_action,
        on_behalf_of=si.on_behalf_of,
        payment_method=si.payment_method,
        payment_method_configuration_details=si.payment_method_configuration_details,
        payment_method_options=si.payment_method_options,
        payment_method_types=si.payment_method_types or ["card"],
        single_use_mandate=si.single_use_mandate,
        status=si.status,
        usage=si.usage or "off_session",
    )


@router.post("", response_model=SetupIntentResponse, status_code=status.HTTP_201_CREATED)
async def create_setup_intent(
    request: Request,
    data: SetupIntentCreateRequest,
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = SetupIntentRepository(session)
    setup_intent = await repo.create_setup_intent(
        id=generate_setup_intent_id(),
        account_id=account_id,
        customer_id=data.customer,
        payment_method_types=data.payment_method_types or ["card"],
        usage=data.usage or "off_session",
        description=data.description,
        metadata=data.metadata,
    )
    setup_intent.client_secret = f"{setup_intent.id}_secret_{secrets.token_urlsafe(24)}"
    if data.confirm and data.payment_method:
        setup_intent.status = "succeeded"
        setup_intent.payment_method = data.payment_method
    await session.commit()
    return setup_intent_to_response(setup_intent)


@router.get("/{setup_intent_id}", response_model=SetupIntentResponse)
async def get_setup_intent(
    setup_intent_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = SetupIntentRepository(session)
    setup_intent = await repo.get_by_id(setup_intent_id)
    if not setup_intent:
        raise NotFoundError(f"Setup intent {setup_intent_id} not found")
    return setup_intent_to_response(setup_intent)


@router.post("/{setup_intent_id}", response_model=SetupIntentResponse)
async def update_setup_intent(
    setup_intent_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = SetupIntentRepository(session)
    setup_intent = await repo.get_by_id(setup_intent_id)
    if not setup_intent:
        raise NotFoundError(f"Setup intent {setup_intent_id} not found")
    if setup_intent.status not in ["requires_payment_method", "requires_confirmation"]:
        raise ValidationError("Setup intent cannot be updated in its current state")
    update_data = {}
    for key in ["customer", "description", "metadata", "payment_method_types", "payment_method_options"]:
        if key in data:
            if key == "customer":
                update_data["customer_id"] = data[key]
            elif key == "metadata":
                update_data["metadata_"] = data[key]
            else:
                update_data[key] = data[key]
    if update_data:
        await repo.update(setup_intent_id, **update_data)
        await session.commit()
    return setup_intent_to_response(setup_intent)


@router.post("/{setup_intent_id}/confirm", response_model=SetupIntentResponse)
async def confirm_setup_intent(
    setup_intent_id: str,
    request: Request,
    data: SetupIntentConfirmRequest,
    session = Depends(get_session),
):
    repo = SetupIntentRepository(session)
    setup_intent = await repo.get_by_id(setup_intent_id)
    if not setup_intent:
        raise NotFoundError(f"Setup intent {setup_intent_id} not found")
    if setup_intent.status not in ["requires_payment_method", "requires_confirmation"]:
        raise ValidationError("Setup intent cannot be confirmed in its current state")
    if data.payment_method:
        setup_intent.payment_method = data.payment_method
    setup_intent.status = "succeeded"
    await session.commit()
    return setup_intent_to_response(setup_intent)


@router.post("/{setup_intent_id}/cancel", response_model=SetupIntentResponse)
async def cancel_setup_intent(
    setup_intent_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = SetupIntentRepository(session)
    setup_intent = await repo.get_by_id(setup_intent_id)
    if not setup_intent:
        raise NotFoundError(f"Setup intent {setup_intent_id} not found")
    if setup_intent.status not in ["requires_payment_method", "requires_confirmation", "requires_action"]:
        raise ValidationError("Setup intent cannot be canceled in its current state")
    setup_intent.status = "canceled"
    await session.commit()
    return setup_intent_to_response(setup_intent)


@router.get("", response_model=PaginatedResponse[SetupIntentResponse])
async def list_setup_intents(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    customer: Optional[str] = Query(default=None),
    payment_method: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = SetupIntentRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if customer:
        filters["customer_id"] = customer
    if payment_method:
        filters["payment_method"] = payment_method
    setup_intents = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(setup_intents) > limit
    if has_more:
        setup_intents = setup_intents[:limit]
    return PaginatedResponse(
        data=[setup_intent_to_response(si) for si in setup_intents],
        has_more=has_more,
    )
