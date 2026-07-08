from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
import enum

from payment_platform.backend.infrastructure.database import Base


class PaymentLinkStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class AfterCompletionType(str, enum.Enum):
    REDIRECT = "redirect"
    HOSTED_PAGE = "hosted_page"
    MESSAGE = "message"


class PaymentLinkPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


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


class PaymentLink(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "payment_links"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="payment_link", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    payment_intent_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    line_items: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    after_completion: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_payment_links_account", "account_id"),
        Index("ix_payment_links_active", "active"),
        Index("ix_payment_links_url", "url"),
    )


class PaymentLinkLineItem(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "payment_link_line_items"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="payment_link.line_item", nullable=False)
    payment_link_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price_id: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    adjustable_quantity: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_payment_link_line_items_payment_link", "payment_link_id"),
        Index("ix_payment_link_line_items_price", "price_id"),
    )


class PaymentLinkPayment(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "payment_link_payments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="payment_link.payment", nullable=False)
    payment_link_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(PaymentLinkPaymentStatus),
        default=PaymentLinkPaymentStatus.PENDING,
        nullable=False,
    )
    paid_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_payment_link_payments_payment_link", "payment_link_id"),
        Index("ix_payment_link_payments_customer", "customer_id"),
        Index("ix_payment_link_payments_status", "status"),
    )


class PaymentLinkRestrictions(Base, TimestampMixin):
    __tablename__ = "payment_link_restrictions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="payment_link.restrictions", nullable=False)
    payment_link_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_links.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expiry_date: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    allowed_emails: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    require_customer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_payment_link_restrictions_payment_link", "payment_link_id"),
    )


class PaymentLinkCustomization(Base, TimestampMixin):
    __tablename__ = "payment_link_customizations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="payment_link.customization", nullable=False)
    payment_link_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_links.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    brand_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    button_text: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    custom_fields: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    terms_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    privacy_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_payment_link_customizations_payment_link", "payment_link_id"),
    )


class PaymentLinkAnalytics(Base, TimestampMixin):
    __tablename__ = "payment_link_analytics"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="payment_link.analytics", nullable=False)
    payment_link_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("payment_links.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    views: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    unique_visitors: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    started_checkouts: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completed_payments: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_payment_link_analytics_payment_link", "payment_link_id"),
    )
