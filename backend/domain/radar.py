from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func, Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import enum

from payment_platform.backend.infrastructure.database import Base


class RuleType(str, enum.Enum):
    BLOCK = "block"
    REVIEW = "review"
    ALLOW = "allow"


class RuleStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class ConditionField(str, enum.Enum):
    AMOUNT = "amount"
    EMAIL = "email"
    IP = "ip"
    COUNTRY = "country"
    CARD_FINGERPRINT = "card_fingerprint"
    DEVICE_ID = "device_id"
    CURRENCY = "currency"
    CUSTOMER_ID = "customer_id"
    PAYMENT_METHOD_ID = "payment_method_id"
    DESCRIPTION = "description"
    METADATA = "metadata"


class ConditionOperator(str, enum.Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    IN_LIST = "in_list"
    NOT_IN_LIST = "not_in_list"
    MATCHES_REGEX = "matches_regex"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class ReviewStatus(str, enum.Enum):
    OPEN = "open"
    APPROVED = "approved"
    BLOCKED = "blocked"
    CLOSED = "closed"


class ValueListType(str, enum.Enum):
    CARD_FINGERPRINT = "card_fingerprint"
    EMAIL = "email"
    IP = "ip"
    COUNTRY = "country"
    DEVICE_ID = "device_id"
    CUSTOMER_ID = "customer_id"
    PAYMENT_METHOD = "payment_method"


class RiskLevel(str, enum.Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGHEST = "highest"


class FraudOutcome(str, enum.Enum):
    FRAUD = "fraud"
    SAFE = "safe"
    PENDING = "pending"


class RiskFactorSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EarlyFraudWarningStatus(str, enum.Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    SAFE = "safe"
    EXPIRED = "expired"


class FraudType(str, enum.Enum):
    FRAUDULENT_CHARGE = "fraudulent_charge"
    CHARGEBACK_FRAUD = "chargeback_fraud"
    ACCOUNT_TAKEOVER = "account_takeover"
    CARD_TESTING = "card_testing"
    FIRST_PARTY_FRAUD = "first_party_fraud"
    FRIENDLY_FRAUD = "friendly_fraud"
    IDENTITY_THEFT = "identity_theft"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MetadataMixin:
    metadata_: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )


class RadarRule(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "radar_rules"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.rule", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(
        SQLEnum(RuleType),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(RuleStatus),
        default=RuleStatus.ACTIVE,
        nullable=False,
    )
    action: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    conditions: Mapped[List["RadarCondition"]] = relationship(
        "RadarCondition",
        back_populates="rule",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_radar_rules_account", "account_id"),
        Index("ix_radar_rules_type", "rule_type"),
        Index("ix_radar_rules_status", "status"),
        Index("ix_radar_rules_priority", "priority"),
        Index("ix_radar_rules_enabled", "enabled"),
    )


class RadarCondition(Base, TimestampMixin):
    __tablename__ = "radar_conditions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.condition", nullable=False)
    rule_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("radar_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field: Mapped[str] = mapped_column(
        SQLEnum(ConditionField),
        nullable=False,
    )
    operator: Mapped[str] = mapped_column(
        SQLEnum(ConditionOperator),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    rule: Mapped["RadarRule"] = relationship("RadarRule", back_populates="conditions")

    __table_args__ = (
        Index("ix_radar_conditions_rule", "rule_id"),
        Index("ix_radar_conditions_field", "field"),
    )


class RadarReview(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "radar_reviews"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.review", nullable=False)
    payment_intent_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(ReviewStatus),
        default=ReviewStatus.OPEN,
        nullable=False,
    )
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_factors: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    assigned_to: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    decision_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_radar_reviews_payment_intent", "payment_intent_id"),
        Index("ix_radar_reviews_account", "account_id"),
        Index("ix_radar_reviews_status", "status"),
        Index("ix_radar_reviews_assigned", "assigned_to"),
    )


class RadarValueList(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "radar_value_lists"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.value_list", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    alias: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    list_type: Mapped[str] = mapped_column(
        SQLEnum(ValueListType),
        nullable=False,
    )
    items_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    items: Mapped[List["RadarValueListItem"]] = relationship(
        "RadarValueListItem",
        back_populates="value_list",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_radar_value_lists_account", "account_id"),
        Index("ix_radar_value_lists_type", "list_type"),
        Index("ix_radar_value_lists_alias", "alias"),
    )


class RadarValueListItem(Base, TimestampMixin):
    __tablename__ = "radar_value_list_items"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.value_list_item", nullable=False)
    value_list_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("radar_value_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    value_list: Mapped["RadarValueList"] = relationship("RadarValueList", back_populates="items")

    __table_args__ = (
        Index("ix_radar_value_list_items_list", "value_list_id"),
        Index("ix_radar_value_list_items_value", "value"),
        UniqueConstraint("value_list_id", "value", name="uq_value_list_item"),
    )


class RadarSession(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "radar_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.session", nullable=False)
    payment_intent_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str] = mapped_column(
        SQLEnum(RiskLevel),
        default=RiskLevel.NORMAL,
        nullable=False,
    )
    risk_factors: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    charge_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fraud_outcome: Mapped[Optional[str]] = mapped_column(
        SQLEnum(FraudOutcome),
        nullable=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    factors: Mapped[List["RiskFactor"]] = relationship(
        "RiskFactor",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_radar_sessions_payment_intent", "payment_intent_id"),
        Index("ix_radar_sessions_risk_level", "risk_level"),
        Index("ix_radar_sessions_fraud_outcome", "fraud_outcome"),
    )


class RiskFactor(Base, TimestampMixin):
    __tablename__ = "radar_risk_factors"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.risk_factor", nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("radar_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(
        SQLEnum(RiskFactorSeverity),
        default=RiskFactorSeverity.LOW,
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    score_impact: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    session: Mapped["RadarSession"] = relationship("RadarSession", back_populates="factors")

    __table_args__ = (
        Index("ix_radar_risk_factors_session", "session_id"),
        Index("ix_radar_risk_factors_type", "type"),
        Index("ix_radar_risk_factors_severity", "severity"),
    )


class RadarEarlyFraudWarning(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "radar_early_fraud_warnings"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.early_fraud_warning", nullable=False)
    payment_intent_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    charge_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("charges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fraud_type: Mapped[str] = mapped_column(
        SQLEnum(FraudType),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(EarlyFraudWarningStatus),
        default=EarlyFraudWarningStatus.OPEN,
        nullable=False,
    )
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confirmed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    safe_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_radar_early_fraud_warnings_payment_intent", "payment_intent_id"),
        Index("ix_radar_early_fraud_warnings_charge", "charge_id"),
        Index("ix_radar_early_fraud_warnings_status", "status"),
        Index("ix_radar_early_fraud_warnings_fraud_type", "fraud_type"),
    )


class VelocityCheck(Base, TimestampMixin):
    __tablename__ = "radar_velocity_checks"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.velocity_check", nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    key_type: Mapped[str] = mapped_column(String(50), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    last_reset_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_radar_velocity_checks_key", "key"),
        Index("ix_radar_velocity_checks_key_type", "key_type"),
        Index("ix_radar_velocity_checks_last_reset", "last_reset_at"),
        UniqueConstraint("key", "window_seconds", name="uq_velocity_key_window"),
    )


class RadarEvaluationLog(Base, TimestampMixin):
    __tablename__ = "radar_evaluation_logs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.evaluation_log", nullable=False)
    payment_intent_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    rule_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    rule_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    action_taken: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    conditions_evaluated: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    conditions_matched: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    evaluation_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_radar_evaluation_logs_payment_intent", "payment_intent_id"),
        Index("ix_radar_evaluation_logs_rule", "rule_id"),
        Index("ix_radar_evaluation_logs_matched", "matched"),
    )


class MachineLearningModel(Base, TimestampMixin):
    __tablename__ = "radar_ml_models"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.ml_model", nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    features: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    thresholds: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recall: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f1_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trained_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    deployed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_radar_ml_models_name", "name"),
        Index("ix_radar_ml_models_active", "is_active"),
    )


class FraudIndicator(Base, TimestampMixin):
    __tablename__ = "radar_fraud_indicators"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="radar.fraud_indicator", nullable=False)
    indicator_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    indicator_value: Mapped[str] = mapped_column(String(500), nullable=False)
    risk_weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    first_seen_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_seen_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_radar_fraud_indicators_type", "indicator_type"),
        Index("ix_radar_fraud_indicators_value", "indicator_value"),
        Index("ix_radar_fraud_indicators_source", "source"),
        Index("ix_radar_fraud_indicators_expires", "expires_at"),
        UniqueConstraint("indicator_type", "indicator_value", name="uq_fraud_indicator"),
    )
