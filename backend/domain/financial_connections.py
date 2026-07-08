from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Date, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import enum
import uuid

from payment_platform.backend.infrastructure.database import Base


class ConnectionStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"
    ERROR = "error"


class ConnectionType(str, enum.Enum):
    PLAID = "plaid"
    MX = "mx"
    YODLEE = "yodlee"
    FINICITY = "finicity"
    TELLER = "teller"


class LinkedAccountType(str, enum.Enum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    LOAN = "loan"
    MORTGAGE = "mortgage"
    BROKERAGE = "brokerage"
    RETIREMENT = "retirement"
    OTHER = "other"


class LinkedAccountStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CLOSED = "closed"
    PENDING = "pending"


class TransactionType(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    TRANSFER = "transfer"
    PAYMENT = "payment"
    REFUND = "refund"
    FEE = "fee"
    INTEREST = "interest"
    OTHER = "other"


class SyncStatusType(str, enum.Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class OwnershipType(str, enum.Enum):
    INDIVIDUAL = "individual"
    JOINT = "joint"
    BUSINESS = "business"
    TRUST = "trust"


class CredentialsType(str, enum.Enum):
    OAUTH = "oauth"
    API_KEY = "api_key"
    TOKEN = "token"
    CERTIFICATE = "certificate"


class SubscriptionEventType(str, enum.Enum):
    ACCOUNT_CONNECTED = "account_connected"
    ACCOUNT_DISCONNECTED = "account_disconnected"
    ACCOUNT_UPDATED = "account_updated"
    TRANSACTION_NEW = "transaction_new"
    TRANSACTION_UPDATED = "transaction_updated"
    TRANSACTION_REMOVED = "transaction_removed"
    BALANCE_UPDATED = "balance_updated"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_EXPIRED = "token_expired"


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


class FinancialConnection(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "financial_connections"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="financial_connection", nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    institution_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(ConnectionStatus),
        default=ConnectionStatus.PENDING,
        nullable=False,
    )
    connection_type: Mapped[str] = mapped_column(
        SQLEnum(ConnectionType),
        nullable=False,
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_connection_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    link_session_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    consent_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    consent_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    products: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    linked_accounts: Mapped[List["LinkedAccount"]] = relationship(
        "LinkedAccount", back_populates="connection", cascade="all, delete-orphan"
    )
    sync_statuses: Mapped[List["SyncStatus"]] = relationship(
        "SyncStatus", back_populates="connection", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="connection", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_financial_connections_account_status", "account_id", "status"),
        Index("ix_financial_connections_institution", "institution_id"),
        Index("ix_financial_connections_last_synced", "last_synced_at"),
    )


class LinkedAccount(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "linked_accounts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="linked_account", nullable=False)
    connection_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financial_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_account_id: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(
        SQLEnum(LinkedAccountType),
        nullable=False,
    )
    account_subtype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    mask: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    official_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    balance_available: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    balance_current: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    balance_limit: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    balance_unavailable: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(LinkedAccountStatus),
        default=LinkedAccountStatus.ACTIVE,
        nullable=False,
    )
    owner_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    owner_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_balance_update: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_transaction_update: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    connection: Mapped["FinancialConnection"] = relationship("FinancialConnection", back_populates="linked_accounts")
    transactions: Mapped[List["AccountTransaction"]] = relationship(
        "AccountTransaction", back_populates="linked_account", cascade="all, delete-orphan"
    )
    balances: Mapped[List["AccountBalance"]] = relationship(
        "AccountBalance", back_populates="linked_account", cascade="all, delete-orphan"
    )
    ownerships: Mapped[List["AccountOwnership"]] = relationship(
        "AccountOwnership", back_populates="linked_account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_linked_accounts_connection", "connection_id"),
        Index("ix_linked_accounts_external_id", "external_account_id"),
        Index("ix_linked_accounts_type", "account_type"),
        UniqueConstraint("connection_id", "external_account_id", name="uq_linked_account_external"),
    )


class AccountTransaction(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "account_transactions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="account_transaction", nullable=False)
    linked_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("linked_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_transaction_id: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    merchant_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    merchant_category_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    authorized_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_transaction_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    transaction_type: Mapped[str] = mapped_column(
        SQLEnum(TransactionType),
        nullable=False,
    )
    payment_channel: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_meta: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    location: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    check_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transaction_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    linked_account: Mapped["LinkedAccount"] = relationship("LinkedAccount", back_populates="transactions")

    __table_args__ = (
        Index("ix_account_transactions_account_date", "linked_account_id", "date"),
        Index("ix_account_transactions_pending", "pending"),
        Index("ix_account_transactions_category", "category"),
        UniqueConstraint("linked_account_id", "external_transaction_id", name="uq_transaction_external"),
    )


class Institution(Base, TimestampMixin):
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="institution", nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    countries_supported: Mapped[List[str]] = mapped_column(ARRAY(String), default=["US"], nullable=False)
    credentials_type: Mapped[str] = mapped_column(
        SQLEnum(CredentialsType),
        default=CredentialsType.OAUTH,
        nullable=False,
    )
    oauth_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    routing_numbers: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    products: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    health_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_status_update: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_institutions_name", "name"),
        Index("ix_institutions_countries", "countries_supported"),
    )


class AccountBalance(Base, TimestampMixin):
    __tablename__ = "account_balances"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="account_balance", nullable=False)
    linked_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("linked_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    available: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    current: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    limit: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    linked_account: Mapped["LinkedAccount"] = relationship("LinkedAccount", back_populates="balances")

    __table_args__ = (
        Index("ix_account_balances_account_as_of", "linked_account_id", "as_of"),
    )


class AccountOwnership(Base, TimestampMixin):
    __tablename__ = "account_ownerships"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="account_ownership", nullable=False)
    linked_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("linked_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    owner_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    owner_address: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ownership_type: Mapped[str] = mapped_column(
        SQLEnum(OwnershipType),
        default=OwnershipType.INDIVIDUAL,
        nullable=False,
    )
    ownership_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    linked_account: Mapped["LinkedAccount"] = relationship("LinkedAccount", back_populates="ownerships")

    __table_args__ = (
        Index("ix_account_ownerships_account", "linked_account_id"),
    )


class SyncStatus(Base, TimestampMixin):
    __tablename__ = "sync_statuses"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="sync_status", nullable=False)
    connection_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financial_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(SyncStatusType),
        default=SyncStatusType.PENDING,
        nullable=False,
    )
    sync_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    items_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_more: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    connection: Mapped["FinancialConnection"] = relationship("FinancialConnection", back_populates="sync_statuses")

    __table_args__ = (
        Index("ix_sync_statuses_connection", "connection_id"),
        Index("ix_sync_statuses_status", "status"),
    )


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="refresh_token", nullable=False)
    connection_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financial_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scope: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    connection: Mapped["FinancialConnection"] = relationship("FinancialConnection", back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_tokens_connection", "connection_id"),
        Index("ix_refresh_tokens_expires", "expires_at"),
    )


class ConnectionSubscription(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "connection_subscriptions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="connection_subscription", nullable=False)
    connection_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financial_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    webhook_url: Mapped[str] = mapped_column(String(500), nullable=False)
    event_types: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False)
    secret: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_connection_subscriptions_connection", "connection_id"),
        Index("ix_connection_subscriptions_account", "account_id"),
    )


class LinkSession(Base, TimestampMixin):
    __tablename__ = "link_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="link_session", nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    connection_type: Mapped[str] = mapped_column(
        SQLEnum(ConnectionType),
        nullable=False,
    )
    institution_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    products: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False)
    country_codes: Mapped[List[str]] = mapped_column(ARRAY(String), default=["US"], nullable=False)
    language: Mapped[str] = mapped_column(String(5), default="en", nullable=False)
    webhook: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    redirect_uri: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    oauth_state: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    connection_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_link_sessions_account", "account_id"),
        Index("ix_link_sessions_expires", "expires_at"),
    )


class TransactionCategory(Base, TimestampMixin):
    __tablename__ = "transaction_categories"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="transaction_category", nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_transaction_categories_name", "name"),
    )
