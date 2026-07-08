from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Date, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import enum

from payment_platform.backend.infrastructure.database import Base
from payment_platform.shared.models.enums import (
    CardBrand, CardFundingType, DisputeStatus, DisputeReason,
)


class CardholderStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    BLOCKED = "blocked"
    UNDER_REVIEW = "under_review"


class CardholderType(str, enum.Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


class CardType(str, enum.Enum):
    VIRTUAL = "virtual"
    PHYSICAL = "physical"


class IssuingCardStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    CANCELED = "canceled"
    LOST = "lost"
    STOLEN = "stolen"
    EXPIRED = "expired"


class AuthorizationStatus(str, enum.Enum):
    PENDING = "pending"
    CLOSED = "closed"
    REVERSED = "reversed"
    DECLINED = "declined"


class SpendingLimitInterval(str, enum.Enum):
    PER_AUTHORIZATION = "per_authorization"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    ALL_TIME = "all_time"


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class IssuingDisputeStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    WON = "won"
    LOST = "lost"
    CLOSED = "closed"
    CANCELED = "canceled"


class IssuingDisputeReason(str, enum.Enum):
    FRAUDULENT = "fraudulent"
    NOT_RECEIVED = "not_received"
    CREDIT_NOT_PROCESSED = "credit_not_processed"
    CANCELED_RECURRING = "canceled_recurring"
    DUPLICATE = "duplicate"
    PRODUCT_NOT_AS_DESCRIBED = "product_not_as_described"
    OTHER = "other"


class AuthorizationMethod(str, enum.Enum):
    CHIP = "chip"
    CONTACTLESS = "contactless"
    KEYED = "keyed"
    ONLINE = "online"
    MANUAL = "manual"
    SWIPE = " swipe"


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


class SpendingLimit(Base):
    __tablename__ = "issuing_spending_limits"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.spending_limit", nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interval: Mapped[str] = mapped_column(String(30), nullable=False)
    categories: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    cardholder_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("cardholders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    card_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("issuing_cards.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enforced: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    merchant_categories: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)

    __table_args__ = (
        Index("ix_spending_limits_cardholder", "cardholder_id"),
        Index("ix_spending_limits_card", "card_id"),
    )


class CardholderVerification(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "cardholder_verifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.verification", nullable=False)
    cardholder_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("cardholders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    verification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    document_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    document_front_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    document_back_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    verification_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    requirements: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    verified_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_cardholder_verifications_cardholder", "cardholder_id"),
        Index("ix_cardholder_verifications_status", "status"),
    )


class IssuingDispute(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "issuing_disputes"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.dispute", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_transactions: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    evidence: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="submitted", nullable=False)
    transaction_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("issuing_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    treasurys: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    submitted_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    closed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    resolved_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    outcome: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_issuing_disputes_transaction", "transaction_id"),
        Index("ix_issuing_disputes_status", "status"),
    )


class MerchantData(Base):
    __tablename__ = "issuing_merchant_data"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.merchant_data", nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_code: Mapped[str] = mapped_column(String(10), nullable=False)
    network_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    terminal_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_merchant_data_category_code", "category_code"),
    )


class CardToken(Base, TimestampMixin):
    __tablename__ = "issuing_card_tokens"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.token", nullable=False)
    card_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("issuing_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    token: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    encrypted_pan: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_cvc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(20), default="pan_token", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_accessed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_card_tokens_card", "card_id"),
        Index("ix_card_tokens_token", "token"),
    )


class AuthorizationRequest(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "issuing_authorization_requests"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.authorization_request", nullable=False)
    authorization_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("issuing_authorizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    merchant_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant_data: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    authorization_method: Mapped[str] = mapped_column(String(30), nullable=False)
    verification_data: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    wallet_provider: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_held_amount: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    approved_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    decline_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    response_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    decision_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_authorization_requests_authorization", "authorization_id"),
    )


class CardNetworkResponse(Base, TimestampMixin):
    __tablename__ = "card_network_responses"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.network_response", nullable=False)
    authorization_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("issuing_authorizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    network: Mapped[str] = mapped_column(String(20), nullable=False)
    response_code: Mapped[str] = mapped_column(String(10), nullable=False)
    response_message: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    approval_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    retrieval_reference_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    system_trace_audit_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_response: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_network_responses_authorization", "authorization_id"),
    )


class FraudScore(Base, TimestampMixin):
    __tablename__ = "issuing_fraud_scores"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.fraud_score", nullable=False)
    authorization_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("issuing_authorizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    card_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    factors: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(20), nullable=False)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_fraud_scores_authorization", "authorization_id"),
        Index("ix_fraud_scores_card", "card_id"),
    )


class SpendingControlRule(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "spending_control_rules"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.spending_rule", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    cardholder_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("cardholders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    card_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("issuing_cards.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    conditions: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_spending_rules_cardholder", "cardholder_id"),
        Index("ix_spending_rules_card", "card_id"),
        Index("ix_spending_rules_priority", "priority"),
    )
