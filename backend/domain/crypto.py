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


class Cryptocurrency(str, enum.Enum):
    BTC = "btc"
    ETH = "eth"
    USDC = "usdc"
    USDT = "usdt"


class CryptoPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    WAITING_PAYMENT = "waiting_payment"
    PAYMENT_DETECTED = "payment_detected"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    SETTLING = "settling"
    SETTLED = "settled"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELED = "canceled"


class CryptoAddressStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class CryptoTransactionStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REJECTED = "rejected"


class SettlementSchedule(str, enum.Enum):
    IMMEDIATE = "immediate"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class ExchangeRateSource(str, enum.Enum):
    COINBASE = "coinbase"
    BINANCE = "binance"
    KRAKEN = "kraken"
    COINGECKO = "coingecko"
    MANUAL = "manual"


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


class CryptoPayment(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "crypto_payments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="crypto.payment", nullable=False)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("payment_intents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cryptocurrency: Mapped[str] = mapped_column(
        SQLEnum(Cryptocurrency),
        nullable=False,
    )
    amount_crypto: Mapped[Decimal] = mapped_column(Numeric(30, 18), nullable=False)
    amount_fiat: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(30, 2), nullable=False)
    settlement_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(CryptoPaymentStatus),
        default=CryptoPaymentStatus.PENDING,
        nullable=False,
    )
    confirmation_blocks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    required_confirmations: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    from_address: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    to_address: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    expiration_time: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    detected_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    settled_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_crypto_payments_payment_intent", "payment_intent_id"),
        Index("ix_crypto_payments_account", "account_id"),
        Index("ix_crypto_payments_status", "status"),
        Index("ix_crypto_payments_cryptocurrency", "cryptocurrency"),
        Index("ix_crypto_payments_created", "created"),
        Index("ix_crypto_payments_transaction_hash", "transaction_hash"),
    )


class CryptoAddress(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "crypto_addresses"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="crypto.address", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cryptocurrency: Mapped[str] = mapped_column(
        SQLEnum(Cryptocurrency),
        nullable=False,
    )
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    derivation_path: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    derivation_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    public_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(CryptoAddressStatus),
        default=CryptoAddressStatus.ACTIVE,
        nullable=False,
    )
    used_for_payment: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("crypto_payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_used_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_received: Mapped[Decimal] = mapped_column(Numeric(30, 18), default=Decimal("0"), nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_crypto_addresses_account", "account_id"),
        Index("ix_crypto_addresses_cryptocurrency", "cryptocurrency"),
        Index("ix_crypto_addresses_status", "status"),
        UniqueConstraint("cryptocurrency", "address", name="uq_crypto_address"),
    )


class CryptoTransaction(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "crypto_transactions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="crypto.transaction", nullable=False)
    crypto_payment_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("crypto_payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    from_address: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    to_address: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 18), nullable=False)
    cryptocurrency: Mapped[str] = mapped_column(
        SQLEnum(Cryptocurrency),
        nullable=False,
    )
    block_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    block_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(CryptoTransactionStatus),
        default=CryptoTransactionStatus.PENDING,
        nullable=False,
    )
    fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 18), nullable=True)
    fee_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    network_timestamp: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    processed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_crypto_transactions_payment", "crypto_payment_id"),
        Index("ix_crypto_transactions_hash", "transaction_hash"),
        Index("ix_crypto_transactions_status", "status"),
        Index("ix_crypto_transactions_block", "block_number"),
        UniqueConstraint("transaction_hash", "cryptocurrency", name="uq_crypto_tx_hash"),
    )


class CryptoExchangeRate(Base, TimestampMixin):
    __tablename__ = "crypto_exchange_rates"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="crypto.exchange_rate", nullable=False)
    cryptocurrency: Mapped[str] = mapped_column(
        SQLEnum(Cryptocurrency),
        nullable=False,
    )
    fiat_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(30, 2), nullable=False)
    inverse_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 18), nullable=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(
        SQLEnum(ExchangeRateSource),
        nullable=False,
    )
    bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 2), nullable=True)
    ask: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 2), nullable=True)
    volume_24h: Mapped[Optional[Decimal]] = mapped_column(Numeric(30, 2), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_crypto_exchange_rates_crypto", "cryptocurrency"),
        Index("ix_crypto_exchange_rates_fiat", "fiat_currency"),
        Index("ix_crypto_exchange_rates_timestamp", "timestamp"),
        UniqueConstraint("cryptocurrency", "fiat_currency", "timestamp", "source", name="uq_exchange_rate"),
    )


class CryptoSettlement(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "crypto_settlements"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="crypto.settlement", nullable=False)
    crypto_payment_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("crypto_payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    settled_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    settlement_rate: Mapped[Decimal] = mapped_column(Numeric(30, 2), nullable=False)
    original_crypto_amount: Mapped[Decimal] = mapped_column(Numeric(30, 18), nullable=False)
    original_crypto_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    fee_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fee_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    settled_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_method: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_crypto_settlements_payment", "crypto_payment_id"),
        Index("ix_crypto_settlements_account", "account_id"),
        Index("ix_crypto_settlements_settled_at", "settled_at"),
    )


class WalletConfig(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "crypto_wallet_configs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="crypto.wallet_config", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    supported_cryptos: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String),
        nullable=True,
        default=list,
    )
    auto_convert: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settlement_schedule: Mapped[str] = mapped_column(
        SQLEnum(SettlementSchedule),
        default=SettlementSchedule.IMMEDIATE,
        nullable=False,
    )
    settlement_currency: Mapped[str] = mapped_column(String(3), default="usd", nullable=False)
    min_settlement_amount: Mapped[int] = mapped_column(BigInteger, default=1000, nullable=False)
    confirmation_threshold: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    webhooks_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_settlement_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    next_scheduled_settlement: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_settled: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_crypto_received: Mapped[Decimal] = mapped_column(Numeric(30, 18), default=Decimal("0"), nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_crypto_wallet_configs_account", "account_id"),
    )
