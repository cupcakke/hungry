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
from payment_platform.shared.models.enums import CapitalOfferStatus


class RepaymentMethod(str, enum.Enum):
    FIXED = "fixed"
    REVENUE_SHARE = "revenue_share"


class InterestType(str, enum.Enum):
    SIMPLE = "simple"
    COMPOUND = "compound"


class FinancingStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAID = "paid"
    DEFAULTED = "defaulted"
    CANCELED = "canceled"


class RepaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class FinancingTransactionType(str, enum.Enum):
    DISBURSEMENT = "disbursement"
    REPAYMENT = "repayment"
    INTEREST_ACCRUAL = "interest_accrual"
    FEE = "fee"
    ADJUSTMENT = "adjustment"
    LATE_FEE = "late_fee"


class DelinquencyStatus(str, enum.Enum):
    CURRENT = "current"
    DELINQUENT_30 = "delinquent_30"
    DELINQUENT_60 = "delinquent_60"
    DELINQUENT_90 = "delinquent_90"
    DEFAULT = "default"


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


class FinancingOffer(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "financing_offers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="financing_offer", nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    interest_type: Mapped[str] = mapped_column(String(20), default="simple", nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    repayment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    revenue_share_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    fixed_payment_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_repayment_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    risk_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    eligibility_reasons: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_financing_offers_account_status", "account_id", "status"),
        Index("ix_financing_offers_expires_at", "expires_at"),
        CheckConstraint("amount > 0", name="ck_financing_offers_amount_positive"),
        CheckConstraint("interest_rate >= 0", name="ck_financing_offers_interest_rate_non_negative"),
        CheckConstraint("term_months > 0", name="ck_financing_offers_term_positive"),
    )


class Financing(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "financings"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="financing", nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financing_offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    interest_type: Mapped[str] = mapped_column(String(20), default="simple", nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    repayment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    revenue_share_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    disbursed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    outstanding_principal: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    outstanding_interest: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    outstanding_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_principal_paid: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_interest_paid: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_fees_paid: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    next_payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    next_payment_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    delinquency_status: Mapped[str] = mapped_column(String(20), default="current", nullable=False)
    delinquent_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    terms: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_financings_account_status", "account_id", "status"),
        Index("ix_financings_next_payment", "next_payment_date"),
        Index("ix_financings_delinquency", "delinquency_status"),
        CheckConstraint("amount > 0", name="ck_financings_amount_positive"),
    )


class RepaymentSchedule(Base, TimestampMixin):
    __tablename__ = "repayment_schedules"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="repayment_schedule", nullable=False)
    financing_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    installments: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_installments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    next_payment_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_remaining: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_paid: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    __table_args__ = (
        Index("ix_repayment_schedules_financing", "financing_id"),
        Index("ix_repayment_schedules_next_payment", "next_payment_date"),
    )


class Repayment(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "repayments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="repayment", nullable=False)
    financing_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_to_principal: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    applied_to_interest: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    applied_to_fees: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    balance_transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    installment_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_repayments_financing_paid", "financing_id", "paid_at"),
        Index("ix_repayments_account", "account_id"),
        CheckConstraint("amount > 0", name="ck_repayments_amount_positive"),
    )


class FinancingTransaction(Base, TimestampMixin):
    __tablename__ = "financing_transactions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="financing_transaction", nullable=False)
    financing_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_financing_transactions_financing_timestamp", "financing_id", "timestamp"),
        Index("ix_financing_transactions_account", "account_id"),
        Index("ix_financing_transactions_type", "type"),
    )


class OfferEligibility(Base, TimestampMixin):
    __tablename__ = "offer_eligibilities"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="offer_eligibility", nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    reason_codes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    risk_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    risk_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    monthly_revenue: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    processing_volume_90d: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    average_transaction_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    account_age_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chargeback_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5), nullable=True)
    refund_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_offer_eligibilities_account", "account_id"),
    )


class CollectionPlan(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "collection_plans"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="collection_plan", nullable=False)
    financing_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    plan_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_payment_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    modified_payment_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payment_frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    missed_payments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    late_fees_waived: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    interest_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_collection_plans_financing", "financing_id"),
        Index("ix_collection_plans_account_status", "account_id", "status"),
    )
