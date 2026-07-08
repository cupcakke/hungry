from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Date, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
import enum

from payment_platform.backend.infrastructure.database import Base


class RecognitionMethod(str, enum.Enum):
    STRAIGHT_LINE = "straight_line"
    PERFORMANCE = "performance"
    USAGE = "usage"


class RecognitionTrigger(str, enum.Enum):
    AT_SALE = "at_sale"
    OVER_TIME = "over_time"
    UPON_DELIVERY = "upon_delivery"


class ScheduleStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ADJUSTED = "adjusted"


class PeriodStatus(str, enum.Enum):
    PENDING = "pending"
    RECOGNIZED = "recognized"
    PARTIAL = "partial"
    CANCELED = "canceled"


class DeferredRevenueStatus(str, enum.Enum):
    PENDING = "pending"
    RECOGNIZING = "recognizing"
    RECOGNIZED = "recognized"
    CANCELED = "canceled"


class TransactionType(str, enum.Enum):
    RECOGNITION = "recognition"
    ADJUSTMENT = "adjustment"
    REVERSAL = "reversal"
    DEFERRAL = "deferral"
    RELEASE = "release"


class MilestoneStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELED = "canceled"
    SKIPPED = "skipped"


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


class RecognitionSchedule(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "recognition_schedules"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="recognition.schedule", nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    recognized_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    deferred_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(ScheduleStatus),
        default=ScheduleStatus.PENDING,
        nullable=False,
    )
    recognition_method: Mapped[str] = mapped_column(
        SQLEnum(RecognitionMethod),
        default=RecognitionMethod.STRAIGHT_LINE,
        nullable=False,
    )
    performance_obligation_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contract_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    performance_obligation_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    total_periods: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recognized_periods: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    adjustment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_recognition_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    periods: Mapped[List["RecognitionPeriod"]] = relationship(
        "RecognitionPeriod", back_populates="schedule", cascade="all, delete-orphan"
    )
    milestones: Mapped[List["RecognitionMilestone"]] = relationship(
        "RecognitionMilestone", back_populates="schedule", cascade="all, delete-orphan"
    )
    transactions: Mapped[List["RecognitionTransaction"]] = relationship(
        "RecognitionTransaction", back_populates="schedule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_recognition_schedules_transaction", "transaction_id"),
        Index("ix_recognition_schedules_status", "status"),
        Index("ix_recognition_schedules_date_range", "start_date", "end_date"),
        Index("ix_recognition_schedules_contract", "contract_id"),
    )


class RecognitionPeriod(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "recognition_periods"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="recognition.period", nullable=False)
    schedule_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("recognition_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_to_recognize: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recognized_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(PeriodStatus),
        default=PeriodStatus.PENDING,
        nullable=False,
    )
    recognized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    journal_entry_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    recognition_rule_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    schedule: Mapped["RecognitionSchedule"] = relationship(
        "RecognitionSchedule", back_populates="periods"
    )

    __table_args__ = (
        Index("ix_recognition_periods_schedule", "schedule_id"),
        Index("ix_recognition_periods_status", "status"),
        Index("ix_recognition_periods_date_range", "period_start", "period_end"),
        UniqueConstraint("schedule_id", "period_number", name="uq_recognition_periods_schedule_period"),
    )


class DeferredRevenue(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "deferred_revenues"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="recognition.deferred_revenue", nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    schedule_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("recognition_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    expected_recognition_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_recognition_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(DeferredRevenueStatus),
        default=DeferredRevenueStatus.PENDING,
        nullable=False,
    )
    recognized_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    remaining_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contract_liability_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contract_asset_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_deferred_revenues_account", "account_id"),
        Index("ix_deferred_revenues_source", "source_type", "source_id"),
        Index("ix_deferred_revenues_status", "status"),
        Index("ix_deferred_revenues_expected_date", "expected_recognition_date"),
    )


class RevenueAllocation(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "revenue_allocations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="recognition.allocation", nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    schedule_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("recognition_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    product_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    performance_obligation_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    allocated_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fair_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    standalone_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_allocation: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    allocation_percentage: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    allocation_method: Mapped[str] = mapped_column(String(30), default="standalone_price", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bundle_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_revenue_allocations_transaction", "transaction_id"),
        Index("ix_revenue_allocations_product", "product_id"),
        Index("ix_revenue_allocations_schedule", "schedule_id"),
        Index("ix_revenue_allocations_bundle", "bundle_id"),
    )


class RecognitionTransaction(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "recognition_transactions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="recognition.transaction", nullable=False)
    schedule_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("recognition_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("recognition_periods.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[str] = mapped_column(
        SQLEnum(TransactionType),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    journal_entry_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reversal_transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    revenue_account_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    deferred_account_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    schedule: Mapped["RecognitionSchedule"] = relationship(
        "RecognitionSchedule", back_populates="transactions"
    )

    __table_args__ = (
        Index("ix_recognition_transactions_schedule", "schedule_id"),
        Index("ix_recognition_transactions_period", "period_id"),
        Index("ix_recognition_transactions_timestamp", "timestamp"),
        Index("ix_recognition_transactions_type", "transaction_type"),
    )


class RecognitionRule(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "recognition_rules"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="recognition.rule", nullable=False)
    product_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    recognition_trigger: Mapped[str] = mapped_column(
        SQLEnum(RecognitionTrigger),
        default=RecognitionTrigger.OVER_TIME,
        nullable=False,
    )
    recognition_period_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    milestone_based: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recognition_method: Mapped[str] = mapped_column(
        SQLEnum(RecognitionMethod),
        default=RecognitionMethod.STRAIGHT_LINE,
        nullable=False,
    )
    revenue_account_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    deferred_account_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    performance_obligation_template: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    auto_recognize: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recognition_frequency: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_recognition_rules_product", "product_id"),
        Index("ix_recognition_rules_active", "is_active"),
    )


class RecognitionMilestone(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "recognition_milestones"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="recognition.milestone", nullable=False)
    schedule_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("recognition_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(MilestoneStatus),
        default=MilestoneStatus.PENDING,
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    journal_entry_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    schedule: Mapped["RecognitionSchedule"] = relationship(
        "RecognitionSchedule", back_populates="milestones"
    )

    __table_args__ = (
        Index("ix_recognition_milestones_schedule", "schedule_id"),
        Index("ix_recognition_milestones_status", "status"),
        Index("ix_recognition_milestones_sequence", "schedule_id", "sequence"),
    )
