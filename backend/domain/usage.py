from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import enum

from payment_platform.backend.infrastructure.database import Base


class UsageRecordAction(str, enum.Enum):
    INCREMENT = "increment"
    SET = "set"


class UsageRecordStatus(str, enum.Enum):
    PENDING = "pending"
    INVOICED = "invoiced"
    CANCELED = "canceled"


class AggregationType(str, enum.Enum):
    SUM = "sum"
    MAX = "max"
    LAST = "last"


class ResetPeriod(str, enum.Enum):
    NEVER = "never"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class MeterEventAdjustmentType(str, enum.Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class UsageAlertStatus(str, enum.Enum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    DISABLED = "disabled"


class UsageReportStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


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


class UsageRecord(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="usage_record", nullable=False)
    subscription_item_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("subscription_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(
        SQLEnum(UsageRecordAction),
        default=UsageRecordAction.INCREMENT,
        nullable=False,
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True)
    period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(UsageRecordStatus),
        default=UsageRecordStatus.PENDING,
        nullable=False,
    )
    invoice_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_usage_records_subscription_item", "subscription_item_id"),
        Index("ix_usage_records_timestamp", "timestamp"),
        Index("ix_usage_records_period", "period_start", "period_end"),
        Index("ix_usage_records_status", "status"),
        UniqueConstraint("idempotency_key", name="uq_usage_records_idempotency_key"),
    )


class UsageRecordSummary(Base, TimestampMixin):
    __tablename__ = "usage_record_summaries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="usage_record_summary", nullable=False)
    subscription_item_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("subscription_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_usage: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    invoice_usage: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    period_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_usage_record_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    aggregated_values: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_usage_record_summaries_subscription_item", "subscription_item_id"),
        Index("ix_usage_record_summaries_period", "period_start", "period_end"),
    )


class Meter(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "meters"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="meter", nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    aggregation_type: Mapped[str] = mapped_column(
        SQLEnum(AggregationType),
        default=AggregationType.SUM,
        nullable=False,
    )
    unit_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reset_period: Mapped[str] = mapped_column(
        SQLEnum(ResetPeriod),
        default=ResetPeriod.MONTHLY,
        nullable=False,
    )
    default_price_per_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    event_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_mapping: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    value_property: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_meters_account", "account_id"),
        Index("ix_meters_name", "name"),
        Index("ix_meters_status", "status"),
    )


class MeterEvent(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "meter_events"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="meter_event", nullable=False)
    meter_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("meters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    properties: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    identifier: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="processed", nullable=False)
    processed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_meter_events_meter", "meter_id"),
        Index("ix_meter_events_customer", "customer_id"),
        Index("ix_meter_events_timestamp", "timestamp"),
        Index("ix_meter_events_subscription", "subscription_id"),
    )


class MeterEventAdjustment(Base, TimestampMixin):
    __tablename__ = "meter_event_adjustments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="meter_event_adjustment", nullable=False)
    meter_event_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("meter_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    adjustment_type: Mapped[str] = mapped_column(
        SQLEnum(MeterEventAdjustmentType),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="applied", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_meter_event_adjustments_meter_event", "meter_event_id"),
    )


class MeterPriceTier(Base, TimestampMixin):
    __tablename__ = "meter_price_tiers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="meter_price_tier", nullable=False)
    meter_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("meters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    up_to: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    flat_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tier_type: Mapped[str] = mapped_column(String(20), default="volume", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_meter_price_tiers_meter", "meter_id"),
        Index("ix_meter_price_tiers_price", "price_id"),
    )


class UsageAlert(Base, TimestampMixin):
    __tablename__ = "usage_alerts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="usage_alert", nullable=False)
    subscription_item_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("subscription_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    threshold: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notification_emails: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    triggered_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    current_usage: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(UsageAlertStatus),
        default=UsageAlertStatus.ACTIVE,
        nullable=False,
    )
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_usage_alerts_subscription_item", "subscription_item_id"),
        Index("ix_usage_alerts_status", "status"),
    )


class UsageReport(Base, TimestampMixin):
    __tablename__ = "usage_reports"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="usage_report", nullable=False)
    subscription_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usage_summary: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    line_items: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    total_usage: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(UsageReportStatus),
        default=UsageReportStatus.PENDING,
        nullable=False,
    )
    generated_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_usage_reports_subscription", "subscription_id"),
        Index("ix_usage_reports_period", "period_start", "period_end"),
        Index("ix_usage_reports_status", "status"),
    )
