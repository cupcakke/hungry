from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import hashlib
import secrets
import string
import re
import json
import time

from sqlalchemy import select, update, and_, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.radar import (
    RadarRule,
    RadarCondition,
    RadarReview,
    RadarValueList,
    RadarValueListItem,
    RadarSession,
    RiskFactor,
    RadarEarlyFraudWarning,
    VelocityCheck,
    RadarEvaluationLog,
    MachineLearningModel,
    FraudIndicator,
    RuleType,
    RuleStatus,
    ConditionField,
    ConditionOperator,
    ReviewStatus,
    ValueListType,
    RiskLevel,
    FraudOutcome,
    RiskFactorSeverity,
    EarlyFraudWarningStatus,
    FraudType,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
)


@dataclass
class EvaluationResult:
    action: str
    rule_id: Optional[str]
    rule_name: Optional[str]
    matched: bool
    risk_score_adjustment: int


@dataclass
class RiskAssessment:
    risk_score: int
    risk_level: str
    risk_factors: List[Dict[str, Any]]
    recommendation: str
    charge_probability: float


@dataclass
class VelocityResult:
    key: str
    count: int
    total_amount: Optional[int]
    limit_exceeded: bool
    limit_type: Optional[str]


@dataclass
class FeatureVector:
    features: Dict[str, float]
    feature_names: List[str]
    created_at: int


class RuleService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: Optional[str],
        name: str,
        rule_type: RuleType,
        conditions: List[Dict[str, Any]],
        action: Optional[Dict[str, Any]] = None,
        priority: int = 100,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RadarRule:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        rule = RadarRule(
            id=self._generate_id("rr"),
            account_id=account_id,
            name=name,
            description=description,
            rule_type=rule_type,
            status=RuleStatus.ACTIVE,
            action=action,
            priority=priority,
            enabled=True,
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(rule)
        
        for cond_data in conditions:
            condition = RadarCondition(
                id=self._generate_id("rc"),
                rule_id=rule.id,
                field=cond_data.get("field", ConditionField.AMOUNT),
                operator=cond_data.get("operator", ConditionOperator.EQUALS),
                value=cond_data.get("value", ""),
                created=timestamp,
            )
            self.session.add(condition)
        
        await self.session.flush()
        return rule

    async def evaluate(
        self,
        payment_data: Dict[str, Any],
        account_id: Optional[str] = None,
    ) -> EvaluationResult:
        start_time = time.time()
        
        query = select(RadarRule).where(
            and_(
                RadarRule.enabled == True,
                RadarRule.status == RuleStatus.ACTIVE,
            )
        )
        
        if account_id:
            query = query.where(
                or_(
                    RadarRule.account_id == account_id,
                    RadarRule.account_id == None,
                )
            )
        else:
            query = query.where(RadarRule.account_id == None)
        
        query = query.order_by(RadarRule.priority.asc())
        
        result = await self.session.execute(query)
        rules = list(result.scalars().all())
        
        default_result = EvaluationResult(
            action="allow",
            rule_id=None,
            rule_name=None,
            matched=False,
            risk_score_adjustment=0,
        )
        
        for rule in rules:
            matched, conditions_evaluated, conditions_matched = await self._evaluate_rule(rule, payment_data)
            
            evaluation_time = (time.time() - start_time) * 1000
            
            log = RadarEvaluationLog(
                id=self._generate_id("rel"),
                payment_intent_id=payment_data.get("payment_intent_id", ""),
                rule_id=rule.id,
                rule_name=rule.name,
                rule_type=rule.rule_type.value,
                matched=matched,
                action_taken=rule.rule_type.value if matched else None,
                conditions_evaluated=conditions_evaluated,
                conditions_matched=conditions_matched,
                evaluation_time_ms=evaluation_time,
                created=int(datetime.now(timezone.utc).timestamp()),
            )
            self.session.add(log)
            
            if matched:
                action = rule.rule_type.value
                risk_adjustment = self._get_risk_adjustment(rule.rule_type)
                
                await self.session.flush()
                
                return EvaluationResult(
                    action=action,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    matched=True,
                    risk_score_adjustment=risk_adjustment,
                )
        
        await self.session.flush()
        return default_result

    async def _evaluate_rule(
        self,
        rule: RadarRule,
        payment_data: Dict[str, Any],
    ) -> Tuple[bool, int, int]:
        cond_query = select(RadarCondition).where(RadarCondition.rule_id == rule.id)
        cond_result = await self.session.execute(cond_query)
        conditions = list(cond_result.scalars().all())
        
        if not conditions:
            return False, 0, 0
        
        conditions_evaluated = 0
        conditions_matched = 0
        
        for condition in conditions:
            conditions_evaluated += 1
            if await self._evaluate_condition(condition, payment_data):
                conditions_matched += 1
        
        all_matched = conditions_matched == len(conditions)
        
        return all_matched, conditions_evaluated, conditions_matched

    async def _evaluate_condition(
        self,
        condition: RadarCondition,
        payment_data: Dict[str, Any],
    ) -> bool:
        field_value = self._get_field_value(condition.field, payment_data)
        condition_value = condition.value
        
        if field_value is None:
            return condition.operator == ConditionOperator.IS_NULL
        
        field_str = str(field_value).lower() if field_value is not None else ""
        cond_str = condition_value.lower()
        
        if condition.operator == ConditionOperator.EQUALS:
            return field_str == cond_str
        elif condition.operator == ConditionOperator.NOT_EQUALS:
            return field_str != cond_str
        elif condition.operator == ConditionOperator.CONTAINS:
            return cond_str in field_str
        elif condition.operator == ConditionOperator.NOT_CONTAINS:
            return cond_str not in field_str
        elif condition.operator == ConditionOperator.STARTS_WITH:
            return field_str.startswith(cond_str)
        elif condition.operator == ConditionOperator.ENDS_WITH:
            return field_str.endswith(cond_str)
        elif condition.operator == ConditionOperator.GREATER_THAN:
            try:
                return float(field_value) > float(condition_value)
            except (ValueError, TypeError):
                return False
        elif condition.operator == ConditionOperator.LESS_THAN:
            try:
                return float(field_value) < float(condition_value)
            except (ValueError, TypeError):
                return False
        elif condition.operator == ConditionOperator.GREATER_THAN_OR_EQUAL:
            try:
                return float(field_value) >= float(condition_value)
            except (ValueError, TypeError):
                return False
        elif condition.operator == ConditionOperator.LESS_THAN_OR_EQUAL:
            try:
                return float(field_value) <= float(condition_value)
            except (ValueError, TypeError):
                return False
        elif condition.operator == ConditionOperator.IN_LIST:
            values = [v.strip().lower() for v in condition_value.split(",")]
            return field_str in values
        elif condition.operator == ConditionOperator.NOT_IN_LIST:
            values = [v.strip().lower() for v in condition_value.split(",")]
            return field_str not in values
        elif condition.operator == ConditionOperator.MATCHES_REGEX:
            try:
                return bool(re.search(condition_value, field_str))
            except re.error:
                return False
        elif condition.operator == ConditionOperator.IS_NOT_NULL:
            return field_value is not None
        elif condition.operator == ConditionOperator.IS_NULL:
            return field_value is None
        
        return False

    def _get_field_value(self, field: ConditionField, payment_data: Dict[str, Any]) -> Any:
        field_mapping = {
            ConditionField.AMOUNT: "amount",
            ConditionField.EMAIL: "email",
            ConditionField.IP: "ip",
            ConditionField.COUNTRY: "country",
            ConditionField.CARD_FINGERPRINT: "card_fingerprint",
            ConditionField.DEVICE_ID: "device_id",
            ConditionField.CURRENCY: "currency",
            ConditionField.CUSTOMER_ID: "customer_id",
            ConditionField.PAYMENT_METHOD_ID: "payment_method_id",
            ConditionField.DESCRIPTION: "description",
            ConditionField.METADATA: "metadata",
        }
        
        key = field_mapping.get(field, field.value)
        return payment_data.get(key)

    def _get_risk_adjustment(self, rule_type: RuleType) -> int:
        adjustments = {
            RuleType.BLOCK: 50,
            RuleType.REVIEW: 30,
            RuleType.ALLOW: -20,
        }
        return adjustments.get(rule_type, 0)

    async def update(
        self,
        rule_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        conditions: Optional[List[Dict[str, Any]]] = None,
        action: Optional[Dict[str, Any]] = None,
        priority: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> RadarRule:
        query = select(RadarRule).where(RadarRule.id == rule_id)
        result = await self.session.execute(query)
        rule = result.scalar_one_or_none()
        
        if not rule:
            raise NotFoundError(f"Rule {rule_id} not found")
        
        if name is not None:
            rule.name = name
        if description is not None:
            rule.description = description
        if action is not None:
            rule.action = action
        if priority is not None:
            rule.priority = priority
        if enabled is not None:
            rule.enabled = enabled
        
        if conditions is not None:
            await self.session.execute(
                delete(RadarCondition).where(RadarCondition.rule_id == rule_id)
            )
            
            timestamp = int(datetime.now(timezone.utc).timestamp())
            for cond_data in conditions:
                condition = RadarCondition(
                    id=self._generate_id("rc"),
                    rule_id=rule.id,
                    field=cond_data.get("field", ConditionField.AMOUNT),
                    operator=cond_data.get("operator", ConditionOperator.EQUALS),
                    value=cond_data.get("value", ""),
                    created=timestamp,
                )
                self.session.add(condition)
        
        await self.session.flush()
        return rule

    async def delete(self, rule_id: str) -> bool:
        query = select(RadarRule).where(RadarRule.id == rule_id)
        result = await self.session.execute(query)
        rule = result.scalar_one_or_none()
        
        if not rule:
            raise NotFoundError(f"Rule {rule_id} not found")
        
        await self.session.execute(delete(RadarRule).where(RadarRule.id == rule_id))
        await self.session.flush()
        return True

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_review(
        self,
        payment_intent_id: str,
        account_id: Optional[str],
        risk_score: Optional[int] = None,
        risk_factors: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RadarReview:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        review = RadarReview(
            id=self._generate_id("rrv"),
            payment_intent_id=payment_intent_id,
            account_id=account_id,
            status=ReviewStatus.OPEN,
            risk_score=risk_score,
            risk_factors=risk_factors or [],
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(review)
        await self.session.flush()
        return review

    async def approve(
        self,
        review_id: str,
        reason: Optional[str] = None,
    ) -> RadarReview:
        query = select(RadarReview).where(RadarReview.id == review_id)
        result = await self.session.execute(query)
        review = result.scalar_one_or_none()
        
        if not review:
            raise NotFoundError(f"Review {review_id} not found")
        
        if review.status != ReviewStatus.OPEN:
            raise ValidationError(f"Review is not in open status: {review.status.value}")
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        review.status = ReviewStatus.APPROVED
        review.decision_at = timestamp
        review.decision_reason = reason
        
        await self.session.flush()
        return review

    async def block(
        self,
        review_id: str,
        reason: Optional[str] = None,
    ) -> RadarReview:
        query = select(RadarReview).where(RadarReview.id == review_id)
        result = await self.session.execute(query)
        review = result.scalar_one_or_none()
        
        if not review:
            raise NotFoundError(f"Review {review_id} not found")
        
        if review.status != ReviewStatus.OPEN:
            raise ValidationError(f"Review is not in open status: {review.status.value}")
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        review.status = ReviewStatus.BLOCKED
        review.decision_at = timestamp
        review.decision_reason = reason
        
        await self.session.flush()
        return review

    async def assign(
        self,
        review_id: str,
        assigned_to: str,
    ) -> RadarReview:
        query = select(RadarReview).where(RadarReview.id == review_id)
        result = await self.session.execute(query)
        review = result.scalar_one_or_none()
        
        if not review:
            raise NotFoundError(f"Review {review_id} not found")
        
        review.assigned_to = assigned_to
        await self.session.flush()
        return review

    async def get_open_reviews(
        self,
        account_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[RadarReview]:
        query = select(RadarReview).where(RadarReview.status == ReviewStatus.OPEN)
        
        if account_id:
            query = query.where(RadarReview.account_id == account_id)
        
        query = query.order_by(RadarReview.created_at.asc()).limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ValueListService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: Optional[str],
        name: str,
        list_type: ValueListType,
        alias: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RadarValueList:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        value_list = RadarValueList(
            id=self._generate_id("rvl"),
            account_id=account_id,
            name=name,
            alias=alias,
            list_type=list_type,
            items_count=0,
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(value_list)
        await self.session.flush()
        return value_list

    async def add_item(
        self,
        value_list_id: str,
        value: str,
    ) -> RadarValueListItem:
        query = select(RadarValueList).where(RadarValueList.id == value_list_id)
        result = await self.session.execute(query)
        value_list = result.scalar_one_or_none()
        
        if not value_list:
            raise NotFoundError(f"Value list {value_list_id} not found")
        
        existing_query = select(RadarValueListItem).where(
            and_(
                RadarValueListItem.value_list_id == value_list_id,
                RadarValueListItem.value == value,
            )
        )
        existing_result = await self.session.execute(existing_query)
        if existing_result.scalar_one_or_none():
            raise ValidationError(f"Value {value} already exists in list")
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        item = RadarValueListItem(
            id=self._generate_id("rvli"),
            value_list_id=value_list_id,
            value=value,
            created=timestamp,
        )
        
        self.session.add(item)
        value_list.items_count += 1
        await self.session.flush()
        return item

    async def remove_item(
        self,
        value_list_id: str,
        item_id: str,
    ) -> bool:
        query = select(RadarValueListItem).where(
            and_(
                RadarValueListItem.id == item_id,
                RadarValueListItem.value_list_id == value_list_id,
            )
        )
        result = await self.session.execute(query)
        item = result.scalar_one_or_none()
        
        if not item:
            raise NotFoundError(f"Item {item_id} not found in value list")
        
        vl_query = select(RadarValueList).where(RadarValueList.id == value_list_id)
        vl_result = await self.session.execute(vl_query)
        value_list = vl_result.scalar_one_or_none()
        
        if value_list:
            value_list.items_count = max(0, value_list.items_count - 1)
        
        await self.session.execute(
            delete(RadarValueListItem).where(RadarValueListItem.id == item_id)
        )
        await self.session.flush()
        return True

    async def check_membership(
        self,
        value: str,
        list_type: Optional[ValueListType] = None,
        alias: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> bool:
        query = select(RadarValueList)
        
        if alias:
            query = query.where(RadarValueList.alias == alias)
        elif list_type:
            query = query.where(RadarValueList.list_type == list_type)
        
        if account_id:
            query = query.where(
                or_(
                    RadarValueList.account_id == account_id,
                    RadarValueList.account_id == None,
                )
            )
        
        result = await self.session.execute(query)
        value_lists = list(result.scalars().all())
        
        if not value_lists:
            return False
        
        list_ids = [vl.id for vl in value_lists]
        
        item_query = select(RadarValueListItem).where(
            and_(
                RadarValueListItem.value_list_id.in_(list_ids),
                RadarValueListItem.value == value,
            )
        )
        
        item_result = await self.session.execute(item_query)
        return item_result.scalar_one_or_none() is not None

    async def get_items(
        self,
        value_list_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[RadarValueListItem]:
        query = select(RadarValueListItem).where(
            RadarValueListItem.value_list_id == value_list_id
        ).order_by(RadarValueListItem.created_at.desc()).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class RiskScoringService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def calculate_score(
        self,
        payment_data: Dict[str, Any],
        account_id: Optional[str] = None,
    ) -> RiskAssessment:
        base_score = 0
        risk_factors = []
        
        email = payment_data.get("email", "")
        if email:
            email_risk = await self._score_email(email)
            base_score += email_risk["score"]
            risk_factors.extend(email_risk["factors"])
        
        ip = payment_data.get("ip", "")
        if ip:
            ip_risk = await self._score_ip(ip)
            base_score += ip_risk["score"]
            risk_factors.extend(ip_risk["factors"])
        
        amount = payment_data.get("amount", 0)
        if amount:
            amount_risk = self._score_amount(amount)
            base_score += amount_risk["score"]
            risk_factors.extend(amount_risk["factors"])
        
        country = payment_data.get("country", "")
        if country:
            country_risk = await self._score_country(country)
            base_score += country_risk["score"]
            risk_factors.extend(country_risk["factors"])
        
        card_fingerprint = payment_data.get("card_fingerprint", "")
        if card_fingerprint:
            card_risk = await self._score_card_fingerprint(card_fingerprint)
            base_score += card_risk["score"]
            risk_factors.extend(card_risk["factors"])
        
        velocity_risk = await self._check_velocity_risk(payment_data)
        base_score += velocity_risk["score"]
        risk_factors.extend(velocity_risk["factors"])
        
        base_score = min(max(base_score, 0), 100)
        
        risk_level = self._get_risk_level(base_score)
        recommendation = self._get_recommendation(base_score)
        charge_probability = self._calculate_charge_probability(base_score)
        
        return RiskAssessment(
            risk_score=base_score,
            risk_level=risk_level,
            risk_factors=risk_factors,
            recommendation=recommendation,
            charge_probability=charge_probability,
        )

    async def _score_email(self, email: str) -> Dict[str, Any]:
        score = 0
        factors = []
        
        if not email:
            return {"score": 10, "factors": [{"type": "missing_email", "severity": "medium"}]}
        
        disposable_domains = ["tempmail.com", "throwaway.com", "guerrillamail.com", "10minutemail.com"]
        domain = email.split("@")[-1].lower() if "@" in email else ""
        
        if domain in disposable_domains:
            score += 30
            factors.append({"type": "disposable_email", "severity": "high", "domain": domain})
        
        if domain in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"]:
            score -= 5
            factors.append({"type": "trusted_email_provider", "severity": "low"})
        
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        if not email_pattern.match(email):
            score += 20
            factors.append({"type": "invalid_email_format", "severity": "high"})
        
        return {"score": max(score, 0), "factors": factors}

    async def _score_ip(self, ip: str) -> Dict[str, Any]:
        score = 0
        factors = []
        
        if not ip:
            return {"score": 15, "factors": [{"type": "missing_ip", "severity": "high"}]}
        
        vpn_indicators = await self._check_vpn_proxy(ip)
        if vpn_indicators["is_vpn"]:
            score += 25
            factors.append({"type": "vpn_detected", "severity": "high"})
        
        if vpn_indicators["is_proxy"]:
            score += 20
            factors.append({"type": "proxy_detected", "severity": "high"})
        
        tor_indicators = await self._check_tor(ip)
        if tor_indicators:
            score += 40
            factors.append({"type": "tor_exit_node", "severity": "critical"})
        
        return {"score": score, "factors": factors}

    def _score_amount(self, amount: int) -> Dict[str, Any]:
        score = 0
        factors = []
        
        amount_decimal = amount / 100
        
        if amount_decimal >= 10000:
            score += 25
            factors.append({"type": "high_value_transaction", "severity": "high", "amount": amount})
        elif amount_decimal >= 1000:
            score += 10
            factors.append({"type": "moderate_value_transaction", "severity": "medium", "amount": amount})
        
        if amount_decimal < 1:
            score += 15
            factors.append({"type": "micro_transaction", "severity": "medium", "amount": amount})
        
        rounded = amount_decimal == round(amount_decimal)
        if rounded and amount_decimal >= 100:
            score += 5
            factors.append({"type": "round_amount", "severity": "low", "amount": amount})
        
        return {"score": score, "factors": factors}

    async def _score_country(self, country: str) -> Dict[str, Any]:
        score = 0
        factors = []
        
        high_risk_countries = ["NG", "GH", "PK", "ID", "RO", "RU", "UA", "BY"]
        medium_risk_countries = ["BR", "IN", "MX", "TR", "TH", "VN", "PH"]
        
        country_upper = country.upper()
        
        if country_upper in high_risk_countries:
            score += 30
            factors.append({"type": "high_risk_country", "severity": "high", "country": country_upper})
        elif country_upper in medium_risk_countries:
            score += 15
            factors.append({"type": "medium_risk_country", "severity": "medium", "country": country_upper})
        
        return {"score": score, "factors": factors}

    async def _score_card_fingerprint(self, fingerprint: str) -> Dict[str, Any]:
        score = 0
        factors = []
        
        query = select(FraudIndicator).where(
            and_(
                FraudIndicator.indicator_type == "card_fingerprint",
                FraudIndicator.indicator_value == fingerprint,
                FraudIndicator.is_confirmed == True,
            )
        )
        result = await self.session.execute(query)
        confirmed_fraud = result.scalar_one_or_none()
        
        if confirmed_fraud:
            score += 60
            factors.append({"type": "known_fraudulent_card", "severity": "critical"})
        
        return {"score": score, "factors": factors}

    async def _check_velocity_risk(self, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        score = 0
        factors = []
        
        velocity_service = VelocityService(self.session)
        
        ip = payment_data.get("ip")
        if ip:
            velocity = await velocity_service.check_velocity(
                key=f"ip:{ip}",
                key_type="ip",
                window_seconds=3600,
            )
            if velocity.count > 10:
                score += 20
                factors.append({"type": "high_ip_velocity", "severity": "high", "count": velocity.count})
            elif velocity.count > 5:
                score += 10
                factors.append({"type": "moderate_ip_velocity", "severity": "medium", "count": velocity.count})
        
        email = payment_data.get("email")
        if email:
            velocity = await velocity_service.check_velocity(
                key=f"email:{email}",
                key_type="email",
                window_seconds=86400,
            )
            if velocity.count > 20:
                score += 15
                factors.append({"type": "high_email_velocity", "severity": "medium", "count": velocity.count})
        
        card_fingerprint = payment_data.get("card_fingerprint")
        if card_fingerprint:
            velocity = await velocity_service.check_velocity(
                key=f"card:{card_fingerprint}",
                key_type="card_fingerprint",
                window_seconds=3600,
            )
            if velocity.count > 5:
                score += 30
                factors.append({"type": "high_card_velocity", "severity": "critical", "count": velocity.count})
        
        return {"score": score, "factors": factors}

    async def _check_vpn_proxy(self, ip: str) -> Dict[str, bool]:
        return {"is_vpn": False, "is_proxy": False}

    async def _check_tor(self, ip: str) -> bool:
        return False

    def _get_risk_level(self, score: int) -> str:
        if score < 20:
            return RiskLevel.NORMAL.value
        elif score < 50:
            return RiskLevel.ELEVATED.value
        else:
            return RiskLevel.HIGHEST.value

    def _get_recommendation(self, score: int) -> str:
        if score < 20:
            return "approve"
        elif score < 40:
            return "review"
        elif score < 70:
            return "manual_review"
        else:
            return "block"

    def _calculate_charge_probability(self, score: int) -> float:
        if score >= 80:
            return 0.1
        elif score >= 60:
            return 0.3
        elif score >= 40:
            return 0.5
        elif score >= 20:
            return 0.7
        else:
            return 0.9

    async def get_risk_factors(
        self,
        payment_intent_id: str,
    ) -> List[Dict[str, Any]]:
        query = select(RiskFactor).where(RiskFactor.session_id == payment_intent_id)
        result = await self.session.execute(query)
        factors = list(result.scalars().all())
        
        return [
            {
                "id": f.id,
                "type": f.type,
                "severity": f.severity.value,
                "description": f.description,
                "evidence": f.evidence,
                "score_impact": f.score_impact,
            }
            for f in factors
        ]

    async def predict_fraud(
        self,
        payment_data: Dict[str, Any],
    ) -> float:
        ml_service = MachineLearningService(self.session)
        
        features = await ml_service.extract_features(payment_data)
        score = await ml_service.get_ml_score(features)
        
        return score

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class VelocityService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_velocity(
        self,
        key: str,
        key_type: str,
        window_seconds: int = 3600,
        amount: Optional[int] = None,
        currency: Optional[str] = None,
    ) -> VelocityResult:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        window_start = timestamp - window_seconds
        
        query = select(VelocityCheck).where(
            and_(
                VelocityCheck.key == key,
                VelocityCheck.window_seconds == window_seconds,
            )
        )
        result = await self.session.execute(query)
        velocity = result.scalar_one_or_none()
        
        if not velocity:
            velocity = VelocityCheck(
                id=self._generate_id("vc"),
                key=key,
                key_type=key_type,
                window_seconds=window_seconds,
                count=1,
                total_amount=amount,
                currency=currency,
                last_reset_at=timestamp,
                created=timestamp,
            )
            self.session.add(velocity)
            await self.session.flush()
            
            return VelocityResult(
                key=key,
                count=1,
                total_amount=amount,
                limit_exceeded=False,
                limit_type=None,
            )
        
        if velocity.last_reset_at < window_start:
            velocity.count = 1
            velocity.total_amount = amount
            velocity.last_reset_at = timestamp
        else:
            velocity.count += 1
            if amount:
                velocity.total_amount = (velocity.total_amount or 0) + amount
        
        limit_exceeded, limit_type = self._check_limits(key_type, velocity.count, velocity.total_amount)
        
        await self.session.flush()
        
        return VelocityResult(
            key=key,
            count=velocity.count,
            total_amount=velocity.total_amount,
            limit_exceeded=limit_exceeded,
            limit_type=limit_type,
        )

    def _check_limits(
        self,
        key_type: str,
        count: int,
        total_amount: Optional[int],
    ) -> Tuple[bool, Optional[str]]:
        limits = {
            "ip": {"count": 50, "amount": 10000000},
            "email": {"count": 100, "amount": 50000000},
            "card_fingerprint": {"count": 10, "amount": 5000000},
            "device_id": {"count": 30, "amount": 15000000},
            "customer_id": {"count": 200, "amount": 100000000},
        }
        
        key_limits = limits.get(key_type, {"count": 1000, "amount": 1000000000})
        
        if count > key_limits["count"]:
            return True, "count"
        
        if total_amount and total_amount > key_limits["amount"]:
            return True, "amount"
        
        return False, None

    async def reset_counters(
        self,
        key: Optional[str] = None,
        key_type: Optional[str] = None,
    ) -> int:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        if key:
            result = await self.session.execute(
                update(VelocityCheck)
                .where(VelocityCheck.key == key)
                .values(count=0, total_amount=0, last_reset_at=timestamp)
            )
        elif key_type:
            result = await self.session.execute(
                update(VelocityCheck)
                .where(VelocityCheck.key_type == key_type)
                .values(count=0, total_amount=0, last_reset_at=timestamp)
            )
        else:
            result = await self.session.execute(
                update(VelocityCheck)
                .values(count=0, total_amount=0, last_reset_at=timestamp)
            )
        
        await self.session.flush()
        return result.rowcount

    async def get_limits(self) -> Dict[str, Dict[str, int]]:
        return {
            "ip": {"count": 50, "amount": 10000000},
            "email": {"count": 100, "amount": 50000000},
            "card_fingerprint": {"count": 10, "amount": 5000000},
            "device_id": {"count": 30, "amount": 15000000},
            "customer_id": {"count": 200, "amount": 100000000},
        }

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class EarlyFraudWarningService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def process_warning(
        self,
        payment_intent_id: str,
        charge_id: str,
        fraud_type: FraudType,
        evidence: Optional[Dict[str, Any]] = None,
        risk_score: Optional[int] = None,
    ) -> RadarEarlyFraudWarning:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        warning = RadarEarlyFraudWarning(
            id=self._generate_id("efw"),
            payment_intent_id=payment_intent_id,
            charge_id=charge_id,
            fraud_type=fraud_type,
            status=EarlyFraudWarningStatus.OPEN,
            evidence=evidence,
            risk_score=risk_score,
            created=timestamp,
        )
        
        self.session.add(warning)
        await self.session.flush()
        return warning

    async def confirm(
        self,
        warning_id: str,
        reason: Optional[str] = None,
    ) -> RadarEarlyFraudWarning:
        query = select(RadarEarlyFraudWarning).where(RadarEarlyFraudWarning.id == warning_id)
        result = await self.session.execute(query)
        warning = result.scalar_one_or_none()
        
        if not warning:
            raise NotFoundError(f"Early fraud warning {warning_id} not found")
        
        if warning.status != EarlyFraudWarningStatus.OPEN:
            raise ValidationError(f"Warning is not in open status: {warning.status.value}")
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        warning.status = EarlyFraudWarningStatus.CONFIRMED
        warning.confirmed_at = timestamp
        
        if warning.evidence is None:
            warning.evidence = {}
        if reason:
            warning.evidence["confirmation_reason"] = reason
        
        await self._add_fraud_indicator(warning)
        
        await self.session.flush()
        return warning

    async def mark_safe(
        self,
        warning_id: str,
        reason: Optional[str] = None,
    ) -> RadarEarlyFraudWarning:
        query = select(RadarEarlyFraudWarning).where(RadarEarlyFraudWarning.id == warning_id)
        result = await self.session.execute(query)
        warning = result.scalar_one_or_none()
        
        if not warning:
            raise NotFoundError(f"Early fraud warning {warning_id} not found")
        
        if warning.status != EarlyFraudWarningStatus.OPEN:
            raise ValidationError(f"Warning is not in open status: {warning.status.value}")
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        warning.status = EarlyFraudWarningStatus.SAFE
        warning.safe_at = timestamp
        
        if warning.evidence is None:
            warning.evidence = {}
        if reason:
            warning.evidence["safe_reason"] = reason
        
        await self.session.flush()
        return warning

    async def _add_fraud_indicator(self, warning: RadarEarlyFraudWarning) -> None:
        if not warning.evidence:
            return
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        indicator_fields = {
            "card_fingerprint": "card_fingerprint",
            "ip": "ip",
            "email": "email",
            "device_id": "device_id",
        }
        
        for field, indicator_type in indicator_fields.items():
            value = warning.evidence.get(field)
            if value:
                indicator = FraudIndicator(
                    id=self._generate_id("fi"),
                    indicator_type=indicator_type,
                    indicator_value=value,
                    risk_weight=1.0,
                    confidence=0.8,
                    source="early_fraud_warning",
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                    occurrence_count=1,
                    is_confirmed=True,
                    created=timestamp,
                )
                self.session.add(indicator)

    async def get_open_warnings(
        self,
        limit: int = 100,
    ) -> List[RadarEarlyFraudWarning]:
        query = select(RadarEarlyFraudWarning).where(
            RadarEarlyFraudWarning.status == EarlyFraudWarningStatus.OPEN
        ).order_by(RadarEarlyFraudWarning.created_at.asc()).limit(limit)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class MachineLearningService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_ml_score(
        self,
        features: FeatureVector,
    ) -> float:
        model = await self._get_active_model()
        
        if not model:
            return self._heuristic_score(features)
        
        score = await self._run_model_inference(model, features)
        return score

    async def extract_features(
        self,
        payment_data: Dict[str, Any],
    ) -> FeatureVector:
        features = {}
        
        amount = payment_data.get("amount", 0)
        features["amount"] = float(amount)
        features["amount_log"] = self._safe_log(amount + 1)
        features["amount_normalized"] = min(amount / 1000000, 1.0)
        
        email = payment_data.get("email", "")
        features["email_length"] = len(email)
        features["has_email"] = 1.0 if email else 0.0
        features["email_domain_length"] = len(email.split("@")[-1]) if "@" in email else 0
        
        ip = payment_data.get("ip", "")
        features["has_ip"] = 1.0 if ip else 0.0
        
        country = payment_data.get("country", "")
        features["has_country"] = 1.0 if country else 0.0
        features["country_high_risk"] = 1.0 if country.upper() in ["NG", "GH", "PK", "RU"] else 0.0
        
        hour_of_day = datetime.now(timezone.utc).hour
        features["hour_of_day"] = float(hour_of_day)
        features["is_night"] = 1.0 if hour_of_day < 6 or hour_of_day > 22 else 0.0
        features["is_business_hours"] = 1.0 if 9 <= hour_of_day <= 17 else 0.0
        
        day_of_week = datetime.now(timezone.utc).weekday()
        features["day_of_week"] = float(day_of_week)
        features["is_weekend"] = 1.0 if day_of_week >= 5 else 0.0
        
        card_fingerprint = payment_data.get("card_fingerprint", "")
        features["has_card_fingerprint"] = 1.0 if card_fingerprint else 0.0
        
        device_id = payment_data.get("device_id", "")
        features["has_device_id"] = 1.0 if device_id else 0.0
        
        velocity_service = VelocityService(self.session)
        limits = await velocity_service.get_limits()
        
        features["velocity_limit_ip"] = float(limits.get("ip", {}).get("count", 0))
        features["velocity_limit_email"] = float(limits.get("email", {}).get("count", 0))
        
        return FeatureVector(
            features=features,
            feature_names=list(features.keys()),
            created_at=int(datetime.now(timezone.utc).timestamp()),
        )

    async def _get_active_model(self) -> Optional[MachineLearningModel]:
        query = select(MachineLearningModel).where(
            MachineLearningModel.is_active == True
        ).order_by(MachineLearningModel.deployed_at.desc())
        
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _run_model_inference(
        self,
        model: MachineLearningModel,
        features: FeatureVector,
    ) -> float:
        if not model.features:
            return self._heuristic_score(features)
        
        weighted_score = 0.0
        total_weight = 0.0
        
        for feature_name in model.features:
            if feature_name in features.features:
                weight = 1.0 / len(model.features)
                weighted_score += features.features[feature_name] * weight
                total_weight += weight
        
        if total_weight > 0:
            normalized_score = weighted_score / total_weight
            return min(max(normalized_score * 100, 0), 100)
        
        return 50.0

    def _heuristic_score(self, features: FeatureVector) -> float:
        score = 0.0
        
        amount = features.features.get("amount", 0)
        if amount > 1000000:
            score += 20
        elif amount > 100000:
            score += 10
        
        if not features.features.get("has_email", True):
            score += 15
        
        if not features.features.get("has_ip", True):
            score += 20
        
        if features.features.get("country_high_risk", 0) > 0:
            score += 25
        
        if features.features.get("is_night", 0) > 0:
            score += 5
        
        if not features.features.get("has_device_id", True):
            score += 10
        
        return min(max(score, 0), 100)

    def _safe_log(self, value: float) -> float:
        import math
        try:
            return math.log(value) if value > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    async def create_model(
        self,
        name: str,
        version: str,
        model_type: str,
        features: Optional[List[str]] = None,
        thresholds: Optional[Dict[str, Any]] = None,
    ) -> MachineLearningModel:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        model = MachineLearningModel(
            id=self._generate_id("mlm"),
            name=name,
            version=version,
            model_type=model_type,
            features=features,
            thresholds=thresholds,
            is_active=True,
            trained_at=timestamp,
            deployed_at=timestamp,
            created=timestamp,
        )
        
        self.session.add(model)
        await self.session.flush()
        return model

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
