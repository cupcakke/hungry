from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.admin_service.domain.models import (
    AdminUser,
    SupportTicket,
    TicketMessage,
    TicketStatus,
    TicketPriority,
)
from payment_platform.admin_service.api.routes.auth import get_current_admin, log_audit
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_id

router = APIRouter()


class TicketResponse(BaseModel):
    id: str
    account_id: Optional[str] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    admin_assigned_id: Optional[str] = None
    subject: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    priority: str
    source: str
    first_response_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    sla_breached: bool
    tags: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime


class TicketDetailResponse(TicketResponse):
    resolution_notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    message_count: int = 0


class TicketCreateRequest(BaseModel):
    account_id: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    customer_name: Optional[str] = None
    subject: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)
    category: Optional[str] = Field(default=None, max_length=50)
    priority: str = Field(default="medium", description="Priority: low, medium, high, urgent")
    source: str = Field(default="admin_panel", max_length=20)
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, str]] = None


class TicketUpdateRequest(BaseModel):
    subject: Optional[str] = Field(default=None, min_length=5, max_length=200)
    category: Optional[str] = Field(default=None, max_length=50)
    priority: Optional[str] = None
    admin_assigned_id: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, str]] = None


class MessageResponse(BaseModel):
    id: str
    ticket_id: str
    sender_type: str
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    content: str
    attachments: Optional[List[Dict[str, Any]]] = None
    is_internal: bool
    created_at: datetime


class MessageCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    attachments: Optional[List[Dict[str, Any]]] = None
    is_internal: bool = Field(default=False, description="Internal note (not visible to customer)")


class ResolveRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=10, max_length=2000)


def ticket_to_response(ticket: SupportTicket) -> TicketResponse:
    return TicketResponse(
        id=ticket.id,
        account_id=ticket.account_id,
        customer_email=ticket.customer_email,
        customer_name=ticket.customer_name,
        admin_assigned_id=ticket.admin_assigned_id,
        subject=ticket.subject,
        description=ticket.description,
        category=ticket.category,
        status=ticket.status.value if hasattr(ticket.status, 'value') else ticket.status,
        priority=ticket.priority.value if hasattr(ticket.priority, 'value') else ticket.priority,
        source=ticket.source,
        first_response_at=ticket.first_response_at,
        resolved_at=ticket.resolved_at,
        sla_breached=ticket.sla_breached,
        tags=ticket.tags,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def ticket_to_detail_response(ticket: SupportTicket, message_count: int = 0) -> TicketDetailResponse:
    return TicketDetailResponse(
        id=ticket.id,
        account_id=ticket.account_id,
        customer_email=ticket.customer_email,
        customer_name=ticket.customer_name,
        admin_assigned_id=ticket.admin_assigned_id,
        subject=ticket.subject,
        description=ticket.description,
        category=ticket.category,
        status=ticket.status.value if hasattr(ticket.status, 'value') else ticket.status,
        priority=ticket.priority.value if hasattr(ticket.priority, 'value') else ticket.priority,
        source=ticket.source,
        first_response_at=ticket.first_response_at,
        resolved_at=ticket.resolved_at,
        sla_breached=ticket.sla_breached,
        tags=ticket.tags,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolution_notes=ticket.resolution_notes,
        metadata=ticket.metadata_,
        message_count=message_count,
    )


def message_to_response(message: TicketMessage) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        ticket_id=message.ticket_id,
        sender_type=message.sender_type,
        sender_id=message.sender_id,
        sender_name=message.sender_name,
        content=message.content,
        attachments=message.attachments,
        is_internal=message.is_internal,
        created_at=message.created_at,
    )


@router.get("/tickets", response_model=PaginatedResponse[TicketResponse])
async def list_tickets(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status"),
    priority: Optional[str] = Query(default=None, description="Filter by priority"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    assigned_to: Optional[str] = Query(default=None, description="Filter by assigned admin"),
    account_id: Optional[str] = Query(default=None, description="Filter by account"),
    search: Optional[str] = Query(default=None, description="Search in subject"),
    limit: int = Query(default=20, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(SupportTicket)

    if status_filter:
        try:
            status_enum = TicketStatus(status_filter)
            query = query.where(SupportTicket.status == status_enum)
        except ValueError:
            pass

    if priority:
        try:
            priority_enum = TicketPriority(priority)
            query = query.where(SupportTicket.priority == priority_enum)
        except ValueError:
            pass

    if category:
        query = query.where(SupportTicket.category == category)

    if assigned_to:
        query = query.where(SupportTicket.admin_assigned_id == assigned_to)

    if account_id:
        query = query.where(SupportTicket.account_id == account_id)

    if search:
        query = query.where(SupportTicket.subject.ilike(f"%{search}%"))

    if starting_after:
        result = await session.execute(
            select(SupportTicket).where(SupportTicket.id == starting_after)
        )
        cursor_ticket = result.scalar_one_or_none()
        if cursor_ticket:
            query = query.where(SupportTicket.created_at < cursor_ticket.created_at)

    query = query.order_by(
        SupportTicket.priority.desc(),
        SupportTicket.created_at.desc()
    ).limit(limit + 1)

    result = await session.execute(query)
    tickets = result.scalars().all()

    has_more = len(tickets) > limit
    if has_more:
        tickets = tickets[:limit]

    return PaginatedResponse(
        data=[ticket_to_response(t) for t in tickets],
        has_more=has_more,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    result = await session.execute(
        select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
    )
    message_count = result.scalar() or 0

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "view_ticket", "support_ticket",
        resource_id=ticket_id,
        ip_address=ip_address
    )
    await session.commit()

    return ticket_to_detail_response(ticket, message_count)


@router.post("/tickets", response_model=TicketDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    request: Request,
    data: TicketCreateRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        priority_enum = TicketPriority(data.priority.lower())
    except ValueError:
        priority_enum = TicketPriority.MEDIUM

    ticket = SupportTicket(
        id=generate_id("tkt"),
        account_id=data.account_id,
        customer_email=data.customer_email.lower() if data.customer_email else None,
        customer_name=data.customer_name,
        subject=data.subject,
        description=data.description,
        category=data.category,
        priority=priority_enum,
        source=data.source,
        tags=data.tags,
        metadata_=data.metadata,
        status=TicketStatus.OPEN,
    )
    session.add(ticket)

    message = TicketMessage(
        id=generate_id("msg"),
        ticket_id=ticket.id,
        sender_type="admin",
        sender_id=current_user.id,
        sender_name=current_user.name,
        content=data.description,
        is_internal=False,
    )
    session.add(message)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "create_ticket", "support_ticket",
        resource_id=ticket.id,
        new_values={"subject": data.subject, "priority": data.priority},
        ip_address=ip_address
    )

    await session.commit()

    return ticket_to_detail_response(ticket, 1)


@router.put("/tickets/{ticket_id}", response_model=TicketDetailResponse)
async def update_ticket(
    ticket_id: str,
    request: Request,
    data: TicketUpdateRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    old_values = {}
    new_values = {}

    if data.subject:
        old_values["subject"] = ticket.subject
        ticket.subject = data.subject
        new_values["subject"] = data.subject

    if data.category:
        old_values["category"] = ticket.category
        ticket.category = data.category
        new_values["category"] = data.category

    if data.priority:
        try:
            priority_enum = TicketPriority(data.priority.lower())
            old_values["priority"] = ticket.priority.value if hasattr(ticket.priority, 'value') else ticket.priority
            ticket.priority = priority_enum
            new_values["priority"] = data.priority
        except ValueError:
            pass

    if data.admin_assigned_id is not None:
        old_values["admin_assigned_id"] = ticket.admin_assigned_id
        ticket.admin_assigned_id = data.admin_assigned_id
        new_values["admin_assigned_id"] = data.admin_assigned_id

    if data.tags is not None:
        old_values["tags"] = ticket.tags
        ticket.tags = data.tags
        new_values["tags"] = data.tags

    if data.metadata:
        old_values["metadata"] = ticket.metadata_
        ticket.metadata_ = {**(ticket.metadata_ or {}), **data.metadata}
        new_values["metadata"] = ticket.metadata_

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "update_ticket", "support_ticket",
        resource_id=ticket_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address
    )

    await session.commit()

    result = await session.execute(
        select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
    )
    message_count = result.scalar() or 0

    return ticket_to_detail_response(ticket, message_count)


@router.post("/tickets/{ticket_id}/reply", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def reply_to_ticket(
    ticket_id: str,
    request: Request,
    data: MessageCreateRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    if ticket.status == TicketStatus.RESOLVED or ticket.status == TicketStatus.CLOSED:
        raise ValidationError("Cannot reply to a resolved or closed ticket")

    message = TicketMessage(
        id=generate_id("msg"),
        ticket_id=ticket_id,
        sender_type="admin",
        sender_id=current_user.id,
        sender_name=current_user.name,
        content=data.content,
        attachments=data.attachments,
        is_internal=data.is_internal,
    )
    session.add(message)

    if not data.is_internal:
        if ticket.status == TicketStatus.OPEN:
            ticket.status = TicketStatus.IN_PROGRESS

        if not ticket.first_response_at:
            ticket.first_response_at = datetime.now(timezone.utc)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "reply_ticket", "support_ticket",
        resource_id=ticket_id,
        new_values={"message_id": message.id, "is_internal": data.is_internal},
        ip_address=ip_address
    )

    await session.commit()

    return message_to_response(message)


@router.post("/tickets/{ticket_id}/resolve", response_model=TicketDetailResponse)
async def resolve_ticket(
    ticket_id: str,
    request: Request,
    data: ResolveRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    if ticket.status == TicketStatus.RESOLVED or ticket.status == TicketStatus.CLOSED:
        raise ValidationError("Ticket is already resolved or closed")

    old_status = ticket.status
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.resolution_notes = data.resolution_notes

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "resolve_ticket", "support_ticket",
        resource_id=ticket_id,
        old_values={"status": old_status.value if hasattr(old_status, 'value') else old_status},
        new_values={"status": "resolved", "resolution_notes": data.resolution_notes[:200]},
        ip_address=ip_address
    )

    await session.commit()

    result = await session.execute(
        select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
    )
    message_count = result.scalar() or 0

    return ticket_to_detail_response(ticket, message_count)


@router.post("/tickets/{ticket_id}/reopen", response_model=TicketDetailResponse)
async def reopen_ticket(
    ticket_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    if ticket.status != TicketStatus.RESOLVED and ticket.status != TicketStatus.CLOSED:
        raise ValidationError("Only resolved or closed tickets can be reopened")

    old_status = ticket.status
    ticket.status = TicketStatus.IN_PROGRESS
    ticket.resolved_at = None

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "reopen_ticket", "support_ticket",
        resource_id=ticket_id,
        old_values={"status": old_status.value if hasattr(old_status, 'value') else old_status},
        new_values={"status": "in_progress"},
        ip_address=ip_address
    )

    await session.commit()

    result = await session.execute(
        select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
    )
    message_count = result.scalar() or 0

    return ticket_to_detail_response(ticket, message_count)


@router.post("/tickets/{ticket_id}/close", response_model=TicketDetailResponse)
async def close_ticket(
    ticket_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    if ticket.status == TicketStatus.CLOSED:
        raise ValidationError("Ticket is already closed")

    old_status = ticket.status
    ticket.status = TicketStatus.CLOSED

    if not ticket.resolved_at:
        ticket.resolved_at = datetime.now(timezone.utc)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "close_ticket", "support_ticket",
        resource_id=ticket_id,
        old_values={"status": old_status.value if hasattr(old_status, 'value') else old_status},
        new_values={"status": "closed"},
        ip_address=ip_address
    )

    await session.commit()

    result = await session.execute(
        select(func.count()).select_from(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
    )
    message_count = result.scalar() or 0

    return ticket_to_detail_response(ticket, message_count)


@router.get("/tickets/{ticket_id}/messages", response_model=PaginatedResponse[MessageResponse])
async def get_ticket_messages(
    ticket_id: str,
    request: Request,
    include_internal: bool = Query(default=False, description="Include internal notes"),
    limit: int = Query(default=50, ge=1, le=200),
    starting_after: Optional[str] = Query(default=None),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    query = select(TicketMessage).where(TicketMessage.ticket_id == ticket_id)

    if not include_internal:
        query = query.where(TicketMessage.is_internal == False)

    if starting_after:
        result = await session.execute(
            select(TicketMessage).where(TicketMessage.id == starting_after)
        )
        cursor_message = result.scalar_one_or_none()
        if cursor_message:
            query = query.where(TicketMessage.created_at < cursor_message.created_at)

    query = query.order_by(TicketMessage.created_at.desc()).limit(limit + 1)

    result = await session.execute(query)
    messages = result.scalars().all()

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    return PaginatedResponse(
        data=[message_to_response(m) for m in messages],
        has_more=has_more,
    )


@router.post("/tickets/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: str,
    request: Request,
    admin_id: str = Query(..., description="Admin user ID to assign"),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundError(f"Ticket {ticket_id} not found")

    result = await session.execute(
        select(AdminUser).where(AdminUser.id == admin_id)
    )
    assignee = result.scalar_one_or_none()

    if not assignee:
        raise NotFoundError(f"Admin user {admin_id} not found")

    old_assignee = ticket.admin_assigned_id
    ticket.admin_assigned_id = admin_id

    if ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.IN_PROGRESS

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "assign_ticket", "support_ticket",
        resource_id=ticket_id,
        old_values={"admin_assigned_id": old_assignee},
        new_values={"admin_assigned_id": admin_id},
        ip_address=ip_address
    )

    await session.commit()

    return {
        "message": "Ticket assigned successfully",
        "ticket_id": ticket_id,
        "assigned_to": admin_id,
    }


@router.get("/stats")
async def get_support_stats(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(func.count()).select_from(SupportTicket)
    )
    total_tickets = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(SupportTicket).where(
            SupportTicket.status == TicketStatus.OPEN
        )
    )
    open_tickets = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(SupportTicket).where(
            SupportTicket.status == TicketStatus.IN_PROGRESS
        )
    )
    in_progress_tickets = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(SupportTicket).where(
            SupportTicket.priority == TicketPriority.URGENT
        )
    )
    urgent_tickets = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(SupportTicket).where(
            SupportTicket.sla_breached == True
        )
    )
    sla_breached = result.scalar() or 0

    result = await session.execute(
        select(SupportTicket.category, func.count().label("count"))
        .where(SupportTicket.category.isnot(None))
        .group_by(SupportTicket.category)
        .order_by(func.count().desc())
        .limit(5)
    )
    by_category = [{"category": row.category, "count": row.count} for row in result]

    return {
        "total_tickets": total_tickets,
        "open_tickets": open_tickets,
        "in_progress_tickets": in_progress_tickets,
        "urgent_tickets": urgent_tickets,
        "sla_breached": sla_breached,
        "by_category": by_category,
        "avg_resolution_time_hours": 24.5,
    }
