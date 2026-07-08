from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.admin_service.domain.models import (
    AdminUser,
    SystemAlert,
    AlertType,
    AlertSeverity,
)
from payment_platform.admin_service.api.routes.auth import get_current_admin, log_audit
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_id

router = APIRouter()


class AlertResponse(BaseModel):
    id: str
    alert_type: str
    severity: str
    title: str
    message: str
    metadata: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    is_active: bool
    notification_sent: bool
    created_at: datetime


class AlertCreateRequest(BaseModel):
    alert_type: str = Field(..., description="Alert type")
    severity: str = Field(default="warning", description="Severity: info, warning, error, critical")
    title: str = Field(..., min_length=5, max_length=200, description="Alert title")
    message: str = Field(..., min_length=10, description="Alert message")
    metadata: Optional[Dict[str, Any]] = None
    source: Optional[str] = Field(default=None, max_length=100, description="Alert source")
    resource_type: Optional[str] = Field(default=None, max_length=50, description="Related resource type")
    resource_id: Optional[str] = Field(default=None, max_length=50, description="Related resource ID")


class AcknowledgeRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=500, description="Acknowledgment notes")


class AlertStatsResponse(BaseModel):
    total_active: int
    by_severity: Dict[str, int]
    by_type: Dict[str, int]
    unacknowledged: int
    critical_unacknowledged: int


def alert_to_response(alert: SystemAlert) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        alert_type=alert.alert_type.value if hasattr(alert.alert_type, 'value') else alert.alert_type,
        severity=alert.severity.value if hasattr(alert.severity, 'value') else alert.severity,
        title=alert.title,
        message=alert.message,
        metadata=alert.metadata,
        source=alert.source,
        resource_type=alert.resource_type,
        resource_id=alert.resource_id,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        resolved_at=alert.resolved_at,
        resolved_by=alert.resolved_by,
        is_active=alert.is_active,
        notification_sent=alert.notification_sent,
        created_at=alert.created_at,
    )


@router.get("", response_model=PaginatedResponse[AlertResponse])
async def list_alerts(
    request: Request,
    severity: Optional[str] = Query(default=None, description="Filter by severity"),
    alert_type: Optional[str] = Query(default=None, alias="type", description="Filter by alert type"),
    is_active: Optional[bool] = Query(default=None, description="Filter by active status"),
    acknowledged: Optional[bool] = Query(default=None, description="Filter by acknowledged status"),
    resource_type: Optional[str] = Query(default=None, description="Filter by resource type"),
    resource_id: Optional[str] = Query(default=None, description="Filter by resource ID"),
    limit: int = Query(default=20, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(SystemAlert)

    if severity:
        try:
            severity_enum = AlertSeverity(severity.lower())
            query = query.where(SystemAlert.severity == severity_enum)
        except ValueError:
            pass

    if alert_type:
        try:
            type_enum = AlertType(alert_type.lower())
            query = query.where(SystemAlert.alert_type == type_enum)
        except ValueError:
            pass

    if is_active is not None:
        query = query.where(SystemAlert.is_active == is_active)

    if acknowledged is not None:
        if acknowledged:
            query = query.where(SystemAlert.acknowledged_at.isnot(None))
        else:
            query = query.where(SystemAlert.acknowledged_at.is_(None))

    if resource_type:
        query = query.where(SystemAlert.resource_type == resource_type)

    if resource_id:
        query = query.where(SystemAlert.resource_id == resource_id)

    if starting_after:
        result = await session.execute(
            select(SystemAlert).where(SystemAlert.id == starting_after)
        )
        cursor_alert = result.scalar_one_or_none()
        if cursor_alert:
            query = query.where(SystemAlert.created_at < cursor_alert.created_at)

    query = query.order_by(
        SystemAlert.severity.desc(),
        SystemAlert.created_at.desc()
    ).limit(limit + 1)

    result = await session.execute(query)
    alerts = result.scalars().all()

    has_more = len(alerts) > limit
    if has_more:
        alerts = alerts[:limit]

    return PaginatedResponse(
        data=[alert_to_response(a) for a in alerts],
        has_more=has_more,
    )


@router.get("/stats", response_model=AlertStatsResponse)
async def get_alert_stats(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(func.count()).select_from(SystemAlert).where(SystemAlert.is_active == True)
    )
    total_active = result.scalar() or 0

    result = await session.execute(
        select(SystemAlert.severity, func.count().label("count"))
        .where(SystemAlert.is_active == True)
        .group_by(SystemAlert.severity)
    )
    by_severity = {}
    for row in result:
        severity_name = row.severity.value if hasattr(row.severity, 'value') else row.severity
        by_severity[severity_name] = row.count

    result = await session.execute(
        select(SystemAlert.alert_type, func.count().label("count"))
        .where(SystemAlert.is_active == True)
        .group_by(SystemAlert.alert_type)
    )
    by_type = {}
    for row in result:
        type_name = row.alert_type.value if hasattr(row.alert_type, 'value') else row.alert_type
        by_type[type_name] = row.count

    result = await session.execute(
        select(func.count()).select_from(SystemAlert).where(
            and_(
                SystemAlert.is_active == True,
                SystemAlert.acknowledged_at.is_(None),
            )
        )
    )
    unacknowledged = result.scalar() or 0

    result = await session.execute(
        select(func.count()).select_from(SystemAlert).where(
            and_(
                SystemAlert.is_active == True,
                SystemAlert.acknowledged_at.is_(None),
                SystemAlert.severity == AlertSeverity.CRITICAL,
            )
        )
    )
    critical_unacknowledged = result.scalar() or 0

    return AlertStatsResponse(
        total_active=total_active,
        by_severity=by_severity,
        by_type=by_type,
        unacknowledged=unacknowledged,
        critical_unacknowledged=critical_unacknowledged,
    )


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SystemAlert).where(SystemAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise NotFoundError(f"Alert {alert_id} not found")

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "view_alert", "system_alert",
        resource_id=alert_id,
        ip_address=ip_address
    )
    await session.commit()

    return alert_to_response(alert)


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    request: Request,
    data: AlertCreateRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        alert_type_enum = AlertType(data.alert_type.lower())
    except ValueError:
        alert_type_enum = AlertType.SYSTEM_ERROR

    try:
        severity_enum = AlertSeverity(data.severity.lower())
    except ValueError:
        severity_enum = AlertSeverity.WARNING

    alert = SystemAlert(
        id=generate_id("alert"),
        alert_type=alert_type_enum,
        severity=severity_enum,
        title=data.title,
        message=data.message,
        metadata=data.metadata,
        source=data.source,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        is_active=True,
        notification_sent=False,
    )
    session.add(alert)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "create_alert", "system_alert",
        resource_id=alert.id,
        new_values={"type": data.alert_type, "severity": data.severity, "title": data.title},
        ip_address=ip_address
    )

    await session.commit()

    return alert_to_response(alert)


@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: str,
    request: Request,
    data: AcknowledgeRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SystemAlert).where(SystemAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise NotFoundError(f"Alert {alert_id} not found")

    if alert.acknowledged_at:
        raise ValidationError("Alert is already acknowledged")

    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = current_user.id

    if data.notes:
        if alert.metadata:
            alert.metadata["acknowledgment_notes"] = data.notes
        else:
            alert.metadata = {"acknowledgment_notes": data.notes}

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "acknowledge_alert", "system_alert",
        resource_id=alert_id,
        ip_address=ip_address
    )

    await session.commit()

    return alert_to_response(alert)


@router.post("/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: str,
    request: Request,
    data: AcknowledgeRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SystemAlert).where(SystemAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise NotFoundError(f"Alert {alert_id} not found")

    if alert.resolved_at:
        raise ValidationError("Alert is already resolved")

    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolved_by = current_user.id
    alert.is_active = False

    if not alert.acknowledged_at:
        alert.acknowledged_at = datetime.now(timezone.utc)
        alert.acknowledged_by = current_user.id

    if data.notes:
        if alert.metadata:
            alert.metadata["resolution_notes"] = data.notes
        else:
            alert.metadata = {"resolution_notes": data.notes}

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "resolve_alert", "system_alert",
        resource_id=alert_id,
        ip_address=ip_address
    )

    await session.commit()

    return alert_to_response(alert)


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SystemAlert).where(SystemAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise NotFoundError(f"Alert {alert_id} not found")

    await session.delete(alert)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "delete_alert", "system_alert",
        resource_id=alert_id,
        ip_address=ip_address
    )

    await session.commit()

    return {"message": "Alert deleted successfully", "id": alert_id}


@router.post("/{alert_id}/escalate")
async def escalate_alert(
    alert_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(SystemAlert).where(SystemAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()

    if not alert:
        raise NotFoundError(f"Alert {alert_id} not found")

    severity_order = [AlertSeverity.INFO, AlertSeverity.WARNING, AlertSeverity.ERROR, AlertSeverity.CRITICAL]
    current_index = severity_order.index(alert.severity)

    if current_index < len(severity_order) - 1:
        alert.severity = severity_order[current_index + 1]

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "escalate_alert", "system_alert",
        resource_id=alert_id,
        new_values={"new_severity": alert.severity.value if hasattr(alert.severity, 'value') else alert.severity},
        ip_address=ip_address
    )

    await session.commit()

    return {
        "message": "Alert escalated successfully",
        "id": alert_id,
        "new_severity": alert.severity.value if hasattr(alert.severity, 'value') else alert.severity,
    }


@router.post("/bulk/acknowledge")
async def bulk_acknowledge_alerts(
    request: Request,
    alert_ids: List[str],
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    acknowledged_count = 0
    already_acknowledged = 0

    for alert_id in alert_ids:
        result = await session.execute(
            select(SystemAlert).where(SystemAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if alert and not alert.acknowledged_at:
            alert.acknowledged_at = datetime.now(timezone.utc)
            alert.acknowledged_by = current_user.id
            acknowledged_count += 1
        elif alert and alert.acknowledged_at:
            already_acknowledged += 1

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "bulk_acknowledge_alerts", "system_alert",
        new_values={"alert_ids": alert_ids, "acknowledged_count": acknowledged_count},
        ip_address=ip_address
    )

    await session.commit()

    return {
        "message": "Bulk acknowledgment completed",
        "acknowledged_count": acknowledged_count,
        "already_acknowledged": already_acknowledged,
    }


@router.post("/bulk/resolve")
async def bulk_resolve_alerts(
    request: Request,
    alert_ids: List[str],
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    resolved_count = 0
    already_resolved = 0

    for alert_id in alert_ids:
        result = await session.execute(
            select(SystemAlert).where(SystemAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()

        if alert and not alert.resolved_at:
            alert.resolved_at = datetime.now(timezone.utc)
            alert.resolved_by = current_user.id
            alert.is_active = False

            if not alert.acknowledged_at:
                alert.acknowledged_at = datetime.now(timezone.utc)
                alert.acknowledged_by = current_user.id

            resolved_count += 1
        elif alert and alert.resolved_at:
            already_resolved += 1

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "bulk_resolve_alerts", "system_alert",
        new_values={"alert_ids": alert_ids, "resolved_count": resolved_count},
        ip_address=ip_address
    )

    await session.commit()

    return {
        "message": "Bulk resolution completed",
        "resolved_count": resolved_count,
        "already_resolved": already_resolved,
    }
