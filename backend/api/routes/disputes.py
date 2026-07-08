from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import time

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.backend.infrastructure.persistence import DisputeRepository
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class DisputeResponse(BaseModel):
    id: str
    object: str = "dispute"
    amount: int
    balance_transactions: List[Dict[str, Any]] = []
    charge: str
    created: int
    currency: str
    evidence: Optional[Dict[str, Any]] = None
    evidence_details: Optional[Dict[str, Any]] = None
    is_charge_refundable: bool
    livemode: bool = False
    metadata: Dict[str, str] = {}
    payment_intent: Optional[str] = None
    reason: str
    status: str


def dispute_to_response(dispute: Any) -> DisputeResponse:
    return DisputeResponse(
        id=dispute.id,
        amount=dispute.amount,
        balance_transactions=dispute.balance_transactions or [],
        charge=dispute.charge_id,
        created=int(dispute.created_at.timestamp()),
        currency=dispute.currency,
        evidence=dispute.evidence,
        evidence_details=dispute.evidence_details,
        is_charge_refundable=dispute.is_charge_refundable,
        livemode=dispute.livemode,
        metadata=dispute.metadata_ or {},
        payment_intent=dispute.payment_intent_id,
        reason=dispute.reason,
        status=dispute.status,
    )


@router.get("/{dispute_id}", response_model=DisputeResponse)
async def get_dispute(
    dispute_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = DisputeRepository(session)
    dispute = await repo.get_by_id(dispute_id)
    if not dispute:
        raise NotFoundError(f"Dispute {dispute_id} not found")
    return dispute_to_response(dispute)


@router.post("/{dispute_id}", response_model=DisputeResponse)
async def update_dispute(
    dispute_id: str,
    request: Request,
    data: Dict[str, Any],
    session = Depends(get_session),
):
    repo = DisputeRepository(session)
    dispute = await repo.get_by_id(dispute_id)
    if not dispute:
        raise NotFoundError(f"Dispute {dispute_id} not found")
    if dispute.status not in ["warning_needs_response", "needs_response"]:
        raise ValidationError("Dispute cannot be updated in its current state")
    if "metadata" in data:
        dispute.metadata_ = data["metadata"]
    if "submit_evidence" in data:
        dispute.evidence = data["submit_evidence"]
    await session.commit()
    return dispute_to_response(dispute)


@router.post("/{dispute_id}/close", response_model=DisputeResponse)
async def close_dispute(
    dispute_id: str,
    request: Request,
    session = Depends(get_session),
):
    repo = DisputeRepository(session)
    dispute = await repo.get_by_id(dispute_id)
    if not dispute:
        raise NotFoundError(f"Dispute {dispute_id} not found")
    dispute.status = "lost"
    await session.commit()
    return dispute_to_response(dispute)


@router.get("", response_model=PaginatedResponse[DisputeResponse])
async def list_disputes(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    charge: Optional[str] = Query(default=None),
    payment_intent: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    session = Depends(get_session),
):
    account_id = getattr(request.state, "account_id", None)
    repo = DisputeRepository(session)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if charge:
        filters["charge_id"] = charge
    if payment_intent:
        filters["payment_intent_id"] = payment_intent
    if status_filter:
        filters["status"] = status_filter
    disputes = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(disputes) > limit
    if has_more:
        disputes = disputes[:limit]
    return PaginatedResponse(
        data=[dispute_to_response(d) for d in disputes],
        has_more=has_more,
    )
