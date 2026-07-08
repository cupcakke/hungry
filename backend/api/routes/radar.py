from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError

router = APIRouter()


class RuleConditionRequest(BaseModel):
    field: str = Field(..., description="Field to check: amount, email, ip, country, card_fingerprint, device_id")
    operator: str = Field(..., description="Operator: equals, contains, starts_with, greater_than, less_than, in_list")
    value: str = Field(..., description="Value to compare against")


class RuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Rule name")
    description: Optional[str] = Field(default=None, description="Rule description")
    rule_type: str = Field(..., description="Rule type: block, review, allow")
    conditions: List[RuleConditionRequest] = Field(..., min_items=1, description="List of conditions")
    action: Optional[Dict[str, Any]] = Field(default=None, description="Action to take when rule matches")
    priority: int = Field(default=100, ge=1, le=1000, description="Rule priority (lower = higher priority)")
    enabled: bool = Field(default=True, description="Whether rule is enabled")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class RuleUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None)
    conditions: Optional[List[RuleConditionRequest]] = Field(default=None, min_items=1)
    action: Optional[Dict[str, Any]] = Field(default=None)
    priority: Optional[int] = Field(default=None, ge=1, le=1000)
    enabled: Optional[bool] = Field(default=None)
    metadata: Optional[Dict[str, str]] = Field(default=None)


class RuleConditionResponse(BaseModel):
    id: str
    object: str = "radar.condition"
    field: str
    operator: str
    value: str


class RuleResponse(BaseModel):
    id: str
    object: str = "radar.rule"
    account_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    rule_type: str
    status: str
    action: Optional[Dict[str, Any]] = None
    priority: int
    enabled: bool
    conditions: List[RuleConditionResponse] = []
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ReviewResponse(BaseModel):
    id: str
    object: str = "radar.review"
    payment_intent_id: str
    account_id: Optional[str] = None
    status: str
    risk_score: Optional[int] = None
    risk_factors: Optional[List[str]] = None
    assigned_to: Optional[str] = None
    decision_at: Optional[int] = None
    decision_reason: Optional[str] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ReviewDecisionRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Reason for the decision")
    assigned_to: Optional[str] = Field(default=None, description="User to assign the review to")


class ValueListCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Value list name")
    alias: Optional[str] = Field(default=None, min_length=1, max_length=100, description="Unique alias for the list")
    list_type: str = Field(..., description="Type: card_fingerprint, email, ip, country, device_id")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ValueListItemCreateRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=500, description="Value to add to the list")


class ValueListItemResponse(BaseModel):
    id: str
    object: str = "radar.value_list_item"
    value_list_id: str
    value: str
    created: int


class ValueListResponse(BaseModel):
    id: str
    object: str = "radar.value_list"
    account_id: Optional[str] = None
    name: str
    alias: Optional[str] = None
    list_type: str
    items_count: int
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class RiskFactorResponse(BaseModel):
    id: str
    object: str = "radar.risk_factor"
    session_id: str
    type: str
    severity: str
    description: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    score_impact: Optional[int] = None
    created: int


class SessionResponse(BaseModel):
    id: str
    object: str = "radar.session"
    payment_intent_id: str
    risk_score: Optional[int] = None
    risk_level: str
    risk_factors: Optional[List[str]] = None
    charge_probability: Optional[float] = None
    fraud_outcome: Optional[str] = None
    factors: List[RiskFactorResponse] = []
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class EarlyFraudWarningResponse(BaseModel):
    id: str
    object: str = "radar.early_fraud_warning"
    payment_intent_id: str
    charge_id: str
    fraud_type: str
    status: str
    evidence: Optional[Dict[str, Any]] = None
    risk_score: Optional[int] = None
    confirmed_at: Optional[int] = None
    safe_at: Optional[int] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ConfirmFraudRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Reason for confirming fraud")


class MarkSafeRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Reason for marking as safe")


def _get_account_id(request: Request) -> Optional[str]:
    return getattr(request.state, "account_id", None)


def _generate_id(prefix: str) -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{prefix}_{random_part}"


def _get_timestamp() -> int:
    import time
    return int(time.time())


@router.post("/rules", response_model=RuleResponse, status_code=201)
async def create_rule(
    request: Request,
    data: RuleCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.radar import (
        RadarRule, RadarCondition, RuleType, RuleStatus, ConditionField, ConditionOperator
    )
    from sqlalchemy import select
    
    rule_type = RuleType.BLOCK
    if data.rule_type == "review":
        rule_type = RuleType.REVIEW
    elif data.rule_type == "allow":
        rule_type = RuleType.ALLOW
    
    rule_id = _generate_id("rr")
    timestamp = _get_timestamp()
    account_id = _get_account_id(request)
    
    rule = RadarRule(
        id=rule_id,
        account_id=account_id,
        name=data.name,
        description=data.description,
        rule_type=rule_type,
        status=RuleStatus.ACTIVE,
        action=data.action,
        priority=data.priority,
        enabled=data.enabled,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(rule)
    
    condition_responses = []
    for cond in data.conditions:
        field = ConditionField.AMOUNT
        try:
            field = ConditionField(cond.field)
        except ValueError:
            pass
        
        operator = ConditionOperator.EQUALS
        try:
            operator = ConditionOperator(cond.operator)
        except ValueError:
            pass
        
        condition = RadarCondition(
            id=_generate_id("rc"),
            rule_id=rule_id,
            field=field,
            operator=operator,
            value=cond.value,
            created=timestamp,
        )
        session.add(condition)
        condition_responses.append(RuleConditionResponse(
            id=condition.id,
            field=condition.field.value,
            operator=condition.operator.value,
            value=condition.value,
        ))
    
    await session.flush()
    
    return RuleResponse(
        id=rule.id,
        account_id=rule.account_id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type.value,
        status=rule.status.value,
        action=rule.action,
        priority=rule.priority,
        enabled=rule.enabled,
        conditions=condition_responses,
        created=rule.created,
        metadata=rule.metadata_,
    )


@router.get("/rules", response_model=PaginatedResponse[RuleResponse])
async def list_rules(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    rule_type: Optional[str] = None,
    status: Optional[str] = None,
    enabled: Optional[bool] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarRule, RadarCondition, RuleType, RuleStatus
    
    account_id = _get_account_id(request)
    
    query = select(RadarRule)
    
    if account_id:
        query = query.where(RadarRule.account_id == account_id)
    if rule_type:
        query = query.where(RadarRule.rule_type == rule_type)
    if status:
        query = query.where(RadarRule.status == status)
    if enabled is not None:
        query = query.where(RadarRule.enabled == enabled)
    if starting_after:
        query = query.where(RadarRule.id > starting_after)
    
    query = query.order_by(RadarRule.priority.asc(), RadarRule.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    rules = list(result.scalars().all())
    
    has_more = len(rules) > limit
    if has_more:
        rules = rules[:limit]
    
    data = []
    for rule in rules:
        cond_query = select(RadarCondition).where(RadarCondition.rule_id == rule.id)
        cond_result = await session.execute(cond_query)
        conditions = list(cond_result.scalars().all())
        
        data.append(RuleResponse(
            id=rule.id,
            account_id=rule.account_id,
            name=rule.name,
            description=rule.description,
            rule_type=rule.rule_type.value,
            status=rule.status.value,
            action=rule.action,
            priority=rule.priority,
            enabled=rule.enabled,
            conditions=[
                RuleConditionResponse(
                    id=c.id,
                    field=c.field.value,
                    operator=c.operator.value,
                    value=c.value,
                )
                for c in conditions
            ],
            created=rule.created,
            metadata=rule.metadata_,
        ))
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarRule, RadarCondition
    
    query = select(RadarRule).where(RadarRule.id == rule_id)
    result = await session.execute(query)
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise NotFoundError(f"Rule {rule_id} not found")
    
    cond_query = select(RadarCondition).where(RadarCondition.rule_id == rule.id)
    cond_result = await session.execute(cond_query)
    conditions = list(cond_result.scalars().all())
    
    return RuleResponse(
        id=rule.id,
        account_id=rule.account_id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type.value,
        status=rule.status.value,
        action=rule.action,
        priority=rule.priority,
        enabled=rule.enabled,
        conditions=[
            RuleConditionResponse(
                id=c.id,
                field=c.field.value,
                operator=c.operator.value,
                value=c.value,
            )
            for c in conditions
        ],
        created=rule.created,
        metadata=rule.metadata_,
    )


@router.post("/rules/{rule_id}/update", response_model=RuleResponse)
async def update_rule(
    rule_id: str,
    request: Request,
    data: RuleUpdateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select, delete
    from payment_platform.backend.domain.radar import (
        RadarRule, RadarCondition, RuleType, RuleStatus, ConditionField, ConditionOperator
    )
    
    query = select(RadarRule).where(RadarRule.id == rule_id)
    result = await session.execute(query)
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise NotFoundError(f"Rule {rule_id} not found")
    
    if data.name is not None:
        rule.name = data.name
    if data.description is not None:
        rule.description = data.description
    if data.action is not None:
        rule.action = data.action
    if data.priority is not None:
        rule.priority = data.priority
    if data.enabled is not None:
        rule.enabled = data.enabled
    if data.metadata is not None:
        rule.metadata_ = data.metadata
    
    condition_responses = []
    
    if data.conditions is not None:
        await session.execute(delete(RadarCondition).where(RadarCondition.rule_id == rule_id))
        
        timestamp = _get_timestamp()
        for cond in data.conditions:
            field = ConditionField.AMOUNT
            try:
                field = ConditionField(cond.field)
            except ValueError:
                pass
            
            operator = ConditionOperator.EQUALS
            try:
                operator = ConditionOperator(cond.operator)
            except ValueError:
                pass
            
            condition = RadarCondition(
                id=_generate_id("rc"),
                rule_id=rule_id,
                field=field,
                operator=operator,
                value=cond.value,
                created=timestamp,
            )
            session.add(condition)
            condition_responses.append(RuleConditionResponse(
                id=condition.id,
                field=condition.field.value,
                operator=condition.operator.value,
                value=condition.value,
            ))
    else:
        cond_query = select(RadarCondition).where(RadarCondition.rule_id == rule.id)
        cond_result = await session.execute(cond_query)
        conditions = list(cond_result.scalars().all())
        condition_responses = [
            RuleConditionResponse(
                id=c.id,
                field=c.field.value,
                operator=c.operator.value,
                value=c.value,
            )
            for c in conditions
        ]
    
    await session.flush()
    
    return RuleResponse(
        id=rule.id,
        account_id=rule.account_id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type.value,
        status=rule.status.value,
        action=rule.action,
        priority=rule.priority,
        enabled=rule.enabled,
        conditions=condition_responses,
        created=rule.created,
        metadata=rule.metadata_,
    )


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select, delete
    from payment_platform.backend.domain.radar import RadarRule
    
    query = select(RadarRule).where(RadarRule.id == rule_id)
    result = await session.execute(query)
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise NotFoundError(f"Rule {rule_id} not found")
    
    await session.execute(delete(RadarRule).where(RadarRule.id == rule_id))
    await session.flush()
    
    return {"id": rule_id, "object": "radar.rule", "deleted": True}


@router.get("/reviews", response_model=PaginatedResponse[ReviewResponse])
async def list_reviews(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarReview, ReviewStatus
    
    account_id = _get_account_id(request)
    
    query = select(RadarReview)
    
    if account_id:
        query = query.where(RadarReview.account_id == account_id)
    if status:
        query = query.where(RadarReview.status == status)
    if assigned_to:
        query = query.where(RadarReview.assigned_to == assigned_to)
    if starting_after:
        query = query.where(RadarReview.id > starting_after)
    
    query = query.order_by(RadarReview.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    reviews = list(result.scalars().all())
    
    has_more = len(reviews) > limit
    if has_more:
        reviews = reviews[:limit]
    
    data = [
        ReviewResponse(
            id=r.id,
            payment_intent_id=r.payment_intent_id,
            account_id=r.account_id,
            status=r.status.value,
            risk_score=r.risk_score,
            risk_factors=r.risk_factors,
            assigned_to=r.assigned_to,
            decision_at=r.decision_at,
            decision_reason=r.decision_reason,
            created=r.created,
            metadata=r.metadata_,
        )
        for r in reviews
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/reviews/{review_id}", response_model=ReviewResponse)
async def get_review(
    review_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarReview
    
    query = select(RadarReview).where(RadarReview.id == review_id)
    result = await session.execute(query)
    review = result.scalar_one_or_none()
    
    if not review:
        raise NotFoundError(f"Review {review_id} not found")
    
    return ReviewResponse(
        id=review.id,
        payment_intent_id=review.payment_intent_id,
        account_id=review.account_id,
        status=review.status.value,
        risk_score=review.risk_score,
        risk_factors=review.risk_factors,
        assigned_to=review.assigned_to,
        decision_at=review.decision_at,
        decision_reason=review.decision_reason,
        created=review.created,
        metadata=review.metadata_,
    )


@router.post("/reviews/{review_id}/approve", response_model=ReviewResponse)
async def approve_review(
    review_id: str,
    request: Request,
    data: ReviewDecisionRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarReview, ReviewStatus
    
    query = select(RadarReview).where(RadarReview.id == review_id)
    result = await session.execute(query)
    review = result.scalar_one_or_none()
    
    if not review:
        raise NotFoundError(f"Review {review_id} not found")
    
    if review.status != ReviewStatus.OPEN:
        raise ValidationError(f"Cannot approve review in {review.status.value} status")
    
    timestamp = _get_timestamp()
    review.status = ReviewStatus.APPROVED
    review.decision_at = timestamp
    review.decision_reason = data.reason
    
    if data.assigned_to:
        review.assigned_to = data.assigned_to
    
    await session.flush()
    
    return ReviewResponse(
        id=review.id,
        payment_intent_id=review.payment_intent_id,
        account_id=review.account_id,
        status=review.status.value,
        risk_score=review.risk_score,
        risk_factors=review.risk_factors,
        assigned_to=review.assigned_to,
        decision_at=review.decision_at,
        decision_reason=review.decision_reason,
        created=review.created,
        metadata=review.metadata_,
    )


@router.post("/reviews/{review_id}/block", response_model=ReviewResponse)
async def block_review(
    review_id: str,
    request: Request,
    data: ReviewDecisionRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarReview, ReviewStatus
    
    query = select(RadarReview).where(RadarReview.id == review_id)
    result = await session.execute(query)
    review = result.scalar_one_or_none()
    
    if not review:
        raise NotFoundError(f"Review {review_id} not found")
    
    if review.status != ReviewStatus.OPEN:
        raise ValidationError(f"Cannot block review in {review.status.value} status")
    
    timestamp = _get_timestamp()
    review.status = ReviewStatus.BLOCKED
    review.decision_at = timestamp
    review.decision_reason = data.reason
    
    if data.assigned_to:
        review.assigned_to = data.assigned_to
    
    await session.flush()
    
    return ReviewResponse(
        id=review.id,
        payment_intent_id=review.payment_intent_id,
        account_id=review.account_id,
        status=review.status.value,
        risk_score=review.risk_score,
        risk_factors=review.risk_factors,
        assigned_to=review.assigned_to,
        decision_at=review.decision_at,
        decision_reason=review.decision_reason,
        created=review.created,
        metadata=review.metadata_,
    )


@router.post("/value_lists", response_model=ValueListResponse, status_code=201)
async def create_value_list(
    request: Request,
    data: ValueListCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.radar import RadarValueList, ValueListType
    
    list_type = ValueListType.EMAIL
    try:
        list_type = ValueListType(data.list_type)
    except ValueError:
        pass
    
    list_id = _generate_id("rvl")
    timestamp = _get_timestamp()
    account_id = _get_account_id(request)
    
    value_list = RadarValueList(
        id=list_id,
        account_id=account_id,
        name=data.name,
        alias=data.alias,
        list_type=list_type,
        items_count=0,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(value_list)
    await session.flush()
    
    return ValueListResponse(
        id=value_list.id,
        account_id=value_list.account_id,
        name=value_list.name,
        alias=value_list.alias,
        list_type=value_list.list_type.value,
        items_count=value_list.items_count,
        created=value_list.created,
        metadata=value_list.metadata_,
    )


@router.get("/value_lists", response_model=PaginatedResponse[ValueListResponse])
async def list_value_lists(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    list_type: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarValueList
    
    account_id = _get_account_id(request)
    
    query = select(RadarValueList)
    
    if account_id:
        query = query.where(RadarValueList.account_id == account_id)
    if list_type:
        query = query.where(RadarValueList.list_type == list_type)
    if starting_after:
        query = query.where(RadarValueList.id > starting_after)
    
    query = query.order_by(RadarValueList.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    value_lists = list(result.scalars().all())
    
    has_more = len(value_lists) > limit
    if has_more:
        value_lists = value_lists[:limit]
    
    data = [
        ValueListResponse(
            id=vl.id,
            account_id=vl.account_id,
            name=vl.name,
            alias=vl.alias,
            list_type=vl.list_type.value,
            items_count=vl.items_count,
            created=vl.created,
            metadata=vl.metadata_,
        )
        for vl in value_lists
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/value_lists/{list_id}", response_model=ValueListResponse)
async def get_value_list(
    list_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarValueList
    
    query = select(RadarValueList).where(RadarValueList.id == list_id)
    result = await session.execute(query)
    value_list = result.scalar_one_or_none()
    
    if not value_list:
        raise NotFoundError(f"Value list {list_id} not found")
    
    return ValueListResponse(
        id=value_list.id,
        account_id=value_list.account_id,
        name=value_list.name,
        alias=value_list.alias,
        list_type=value_list.list_type.value,
        items_count=value_list.items_count,
        created=value_list.created,
        metadata=value_list.metadata_,
    )


@router.post("/value_lists/{list_id}/items", response_model=ValueListItemResponse, status_code=201)
async def add_value_list_item(
    list_id: str,
    request: Request,
    data: ValueListItemCreateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarValueList, RadarValueListItem
    
    vl_query = select(RadarValueList).where(RadarValueList.id == list_id)
    vl_result = await session.execute(vl_query)
    value_list = vl_result.scalar_one_or_none()
    
    if not value_list:
        raise NotFoundError(f"Value list {list_id} not found")
    
    item_id = _generate_id("rvli")
    timestamp = _get_timestamp()
    
    item = RadarValueListItem(
        id=item_id,
        value_list_id=list_id,
        value=data.value,
        created=timestamp,
    )
    
    session.add(item)
    value_list.items_count += 1
    await session.flush()
    
    return ValueListItemResponse(
        id=item.id,
        value_list_id=item.value_list_id,
        value=item.value,
        created=item.created,
    )


@router.delete("/value_lists/{list_id}/items/{item_id}")
async def remove_value_list_item(
    list_id: str,
    item_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select, delete
    from payment_platform.backend.domain.radar import RadarValueList, RadarValueListItem
    
    vl_query = select(RadarValueList).where(RadarValueList.id == list_id)
    vl_result = await session.execute(vl_query)
    value_list = vl_result.scalar_one_or_none()
    
    if not value_list:
        raise NotFoundError(f"Value list {list_id} not found")
    
    item_query = select(RadarValueListItem).where(
        RadarValueListItem.id == item_id,
        RadarValueListItem.value_list_id == list_id,
    )
    item_result = await session.execute(item_query)
    item = item_result.scalar_one_or_none()
    
    if not item:
        raise NotFoundError(f"Item {item_id} not found in value list {list_id}")
    
    await session.execute(
        delete(RadarValueListItem).where(RadarValueListItem.id == item_id)
    )
    
    value_list.items_count = max(0, value_list.items_count - 1)
    await session.flush()
    
    return {"id": item_id, "object": "radar.value_list_item", "deleted": True}


@router.get("/sessions", response_model=PaginatedResponse[SessionResponse])
async def list_sessions(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    risk_level: Optional[str] = None,
    fraud_outcome: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarSession, RiskFactor
    
    query = select(RadarSession)
    
    if risk_level:
        query = query.where(RadarSession.risk_level == risk_level)
    if fraud_outcome:
        query = query.where(RadarSession.fraud_outcome == fraud_outcome)
    if starting_after:
        query = query.where(RadarSession.id > starting_after)
    
    query = query.order_by(RadarSession.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    sessions = list(result.scalars().all())
    
    has_more = len(sessions) > limit
    if has_more:
        sessions = sessions[:limit]
    
    data = []
    for s in sessions:
        factors_query = select(RiskFactor).where(RiskFactor.session_id == s.id)
        factors_result = await session.execute(factors_query)
        factors = list(factors_result.scalars().all())
        
        data.append(SessionResponse(
            id=s.id,
            payment_intent_id=s.payment_intent_id,
            risk_score=s.risk_score,
            risk_level=s.risk_level.value,
            risk_factors=s.risk_factors,
            charge_probability=s.charge_probability,
            fraud_outcome=s.fraud_outcome.value if s.fraud_outcome else None,
            factors=[
                RiskFactorResponse(
                    id=f.id,
                    session_id=f.session_id,
                    type=f.type,
                    severity=f.severity.value,
                    description=f.description,
                    evidence=f.evidence,
                    score_impact=f.score_impact,
                    created=f.created,
                )
                for f in factors
            ],
            created=s.created,
            metadata=s.metadata_,
        ))
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/early_fraud_warnings", response_model=PaginatedResponse[EarlyFraudWarningResponse])
async def list_early_fraud_warnings(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    fraud_type: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarEarlyFraudWarning
    
    query = select(RadarEarlyFraudWarning)
    
    if status:
        query = query.where(RadarEarlyFraudWarning.status == status)
    if fraud_type:
        query = query.where(RadarEarlyFraudWarning.fraud_type == fraud_type)
    if starting_after:
        query = query.where(RadarEarlyFraudWarning.id > starting_after)
    
    query = query.order_by(RadarEarlyFraudWarning.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    warnings = list(result.scalars().all())
    
    has_more = len(warnings) > limit
    if has_more:
        warnings = warnings[:limit]
    
    data = [
        EarlyFraudWarningResponse(
            id=w.id,
            payment_intent_id=w.payment_intent_id,
            charge_id=w.charge_id,
            fraud_type=w.fraud_type.value,
            status=w.status.value,
            evidence=w.evidence,
            risk_score=w.risk_score,
            confirmed_at=w.confirmed_at,
            safe_at=w.safe_at,
            created=w.created,
            metadata=w.metadata_,
        )
        for w in warnings
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/early_fraud_warnings/{warning_id}/confirm", response_model=EarlyFraudWarningResponse)
async def confirm_fraud(
    warning_id: str,
    request: Request,
    data: ConfirmFraudRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarEarlyFraudWarning, EarlyFraudWarningStatus
    
    query = select(RadarEarlyFraudWarning).where(RadarEarlyFraudWarning.id == warning_id)
    result = await session.execute(query)
    warning = result.scalar_one_or_none()
    
    if not warning:
        raise NotFoundError(f"Early fraud warning {warning_id} not found")
    
    if warning.status != EarlyFraudWarningStatus.OPEN:
        raise ValidationError(f"Cannot confirm warning in {warning.status.value} status")
    
    timestamp = _get_timestamp()
    warning.status = EarlyFraudWarningStatus.CONFIRMED
    warning.confirmed_at = timestamp
    
    if warning.evidence is None:
        warning.evidence = {}
    if data.reason:
        warning.evidence["confirmation_reason"] = data.reason
    
    await session.flush()
    
    return EarlyFraudWarningResponse(
        id=warning.id,
        payment_intent_id=warning.payment_intent_id,
        charge_id=warning.charge_id,
        fraud_type=warning.fraud_type.value,
        status=warning.status.value,
        evidence=warning.evidence,
        risk_score=warning.risk_score,
        confirmed_at=warning.confirmed_at,
        safe_at=warning.safe_at,
        created=warning.created,
        metadata=warning.metadata_,
    )


@router.post("/early_fraud_warnings/{warning_id}/safe", response_model=EarlyFraudWarningResponse)
async def mark_safe(
    warning_id: str,
    request: Request,
    data: MarkSafeRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.radar import RadarEarlyFraudWarning, EarlyFraudWarningStatus
    
    query = select(RadarEarlyFraudWarning).where(RadarEarlyFraudWarning.id == warning_id)
    result = await session.execute(query)
    warning = result.scalar_one_or_none()
    
    if not warning:
        raise NotFoundError(f"Early fraud warning {warning_id} not found")
    
    if warning.status != EarlyFraudWarningStatus.OPEN:
        raise ValidationError(f"Cannot mark warning as safe in {warning.status.value} status")
    
    timestamp = _get_timestamp()
    warning.status = EarlyFraudWarningStatus.SAFE
    warning.safe_at = timestamp
    
    if warning.evidence is None:
        warning.evidence = {}
    if data.reason:
        warning.evidence["safe_reason"] = data.reason
    
    await session.flush()
    
    return EarlyFraudWarningResponse(
        id=warning.id,
        payment_intent_id=warning.payment_intent_id,
        charge_id=warning.charge_id,
        fraud_type=warning.fraud_type.value,
        status=warning.status.value,
        evidence=warning.evidence,
        risk_score=warning.risk_score,
        confirmed_at=warning.confirmed_at,
        safe_at=warning.safe_at,
        created=warning.created,
        metadata=warning.metadata_,
    )
