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


class FinancialAccountType(str, enum.Enum):
    CHECKING = "checking"
    SAVINGS = "savings"


class FinancialAccountStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    PENDING = "pending"
    RESTRICTED = "restricted"


class TransferNetwork(str, enum.Enum):
    ACH = "ach"
    WIRE = "wire"
    SEPA = "sepa"


class InboundTransferStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REQUIRES_ACTION = "requires_action"


class OutboundTransferStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    POSTED = "posted"
    FAILED = "failed"
    CANCELED = "canceled"
    RETURNED = "returned"
    REQUIRES_ACTION = "requires_action"


class OutboundPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    POSTED = "posted"
    FAILED = "failed"
    CANCELED = "canceled"
    RETURNED = "returned"
    REQUIRES_ACTION = "requires_action"


class TransactionFlowType(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    TRANSFER = "transfer"
    PAYOUT = "payout"
    REFUND = "refund"
    FEE = "fee"
    ADJUSTMENT = "adjustment"
    HOLD = "hold"
    RELEASE = "release"


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


class TreasuryFinancialAccount(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "treasury_financial_accounts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.financial_account", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    account_type: Mapped[str] = mapped_column(
        SQLEnum(FinancialAccountType),
        default=FinancialAccountType.CHECKING,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    available_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pending_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(FinancialAccountStatus),
        default=FinancialAccountStatus.OPEN,
        nullable=False,
    )
    features: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    active_features: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    pending_features: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    restricted_features: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    routing_numbers: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    financial_addresses: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_financial_accounts_account", "account_id"),
        Index("ix_treasury_financial_accounts_status", "status"),
        Index("ix_treasury_financial_accounts_currency", "currency"),
    )


class InboundTransfer(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "treasury_inbound_transfers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.inbound_transfer", nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("treasury_financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(InboundTransferStatus),
        default=InboundTransferStatus.PENDING,
        nullable=False,
    )
    origin_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    origin_payment_method_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    network: Mapped[str] = mapped_column(
        SQLEnum(TransferNetwork),
        nullable=False,
    )
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    expected_arrival_date: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    arrived_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_inbound_transfers_financial_account", "financial_account_id"),
        Index("ix_treasury_inbound_transfers_status", "status"),
        Index("ix_treasury_inbound_transfers_created", "created"),
    )


class OutboundTransfer(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "treasury_outbound_transfers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.outbound_transfer", nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("treasury_financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(OutboundTransferStatus),
        default=OutboundTransferStatus.PENDING,
        nullable=False,
    )
    destination: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    destination_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    destination_payment_method_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    network: Mapped[str] = mapped_column(
        SQLEnum(TransferNetwork),
        nullable=False,
    )
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    expected_arrival_date: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    posted_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    returned_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    returned_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_outbound_transfers_financial_account", "financial_account_id"),
        Index("ix_treasury_outbound_transfers_status", "status"),
        Index("ix_treasury_outbound_transfers_created", "created"),
    )


class OutboundPayment(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "treasury_outbound_payments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.outbound_payment", nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("treasury_financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(OutboundPaymentStatus),
        default=OutboundPaymentStatus.PENDING,
        nullable=False,
    )
    recipient_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    recipient_payment_method_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    expected_arrival_date: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    posted_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    returned_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    returned_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    cancelable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_outbound_payments_financial_account", "financial_account_id"),
        Index("ix_treasury_outbound_payments_status", "status"),
        Index("ix_treasury_outbound_payments_created", "created"),
    )


class ReceivedCredit(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "treasury_received_credits"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.received_credit", nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("treasury_financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    network: Mapped[str] = mapped_column(
        SQLEnum(TransferNetwork),
        nullable=False,
    )
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_received_credits_financial_account", "financial_account_id"),
        Index("ix_treasury_received_credits_created", "created"),
    )


class ReceivedDebit(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "treasury_received_debits"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.received_debit", nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("treasury_financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    network: Mapped[str] = mapped_column(
        SQLEnum(TransferNetwork),
        nullable=False,
    )
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_received_debits_financial_account", "financial_account_id"),
        Index("ix_treasury_received_debits_created", "created"),
    )


class TransactionEntry(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "treasury_transaction_entries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.transaction_entry", nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("treasury_financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    flow_type: Mapped[str] = mapped_column(
        SQLEnum(TransactionFlowType),
        nullable=False,
    )
    flow_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    flow_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    available_balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pending_balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_transaction_entries_financial_account", "financial_account_id"),
        Index("ix_treasury_transaction_entries_transaction", "transaction_id"),
        Index("ix_treasury_transaction_entries_effective_at", "effective_at"),
    )


class CreditBalance(Base, TimestampMixin):
    __tablename__ = "treasury_credit_balances"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="treasury.credit_balance", nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("treasury_financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    available: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pending: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_treasury_credit_balances_financial_account", "financial_account_id"),
    )
