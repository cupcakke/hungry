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


class DeviceType(str, enum.Enum):
    VERIFONE_P400 = "verifone_p400"
    STRIPE_M2 = "stripe_m2"
    BBPOS_WISEPAD3 = "bbpos_wisepad3"
    BBPOS_WISEPOS_E = "bbpos_wisepos_e"


class ReaderStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    UPDATING = "updating"


class ConnectionTokenStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    USED = "used"
    REVOKED = "revoked"


class TerminalPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_INPUT = "awaiting_input"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"


class CardEntryMode(str, enum.Enum):
    CHIP = "chip"
    CONTACTLESS = "contactless"
    SWIPE = "swipe"
    FALLBACK = "fallback"
    MANUAL = "manual"


class CaptureMethod(str, enum.Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class ActionType(str, enum.Enum):
    DISPLAY = "display"
    PROMPT = "prompt"
    SET_BRANDING = "set_branding"
    COLLECT_SIGNATURE = "collect_signature"
    COLLECT_TIP = "collect_tip"
    CONFIRM_PAYMENT = "confirm_payment"
    REFUND = "refund"


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    TIMED_OUT = "timed_out"


class TerminalEventType(str, enum.Enum):
    READER_CONNECTED = "reader_connected"
    READER_DISCONNECTED = "reader_disconnected"
    READER_UPDATE_AVAILABLE = "reader_update_available"
    PAYMENT_STARTED = "payment_started"
    PAYMENT_COMPLETED = "payment_completed"
    PAYMENT_FAILED = "payment_failed"
    CARD_INSERTED = "card_inserted"
    CARD_REMOVED = "card_removed"
    SIGNATURE_REQUIRED = "signature_required"
    SIGNATURE_COLLECTED = "signature_collected"
    TIP_SELECTED = "tip_selected"
    ACTION_REQUESTED = "action_requested"
    ACTION_COMPLETED = "action_completed"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


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


class TerminalReader(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "terminal_readers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.reader", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    device_type: Mapped[str] = mapped_column(
        SQLEnum(DeviceType),
        nullable=False,
    )
    device_sw_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    location_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("terminal_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(ReaderStatus),
        default=ReaderStatus.OFFLINE,
        nullable=False,
    )
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    last_seen_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    capabilities: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    configuration_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_heartbeat_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    offline_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offline_transaction_limit: Mapped[int] = mapped_column(Integer, default=50000, nullable=False)
    offline_amount_limit: Mapped[int] = mapped_column(Integer, default=1000000, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_readers_account", "account_id"),
        Index("ix_terminal_readers_location", "location_id"),
        Index("ix_terminal_readers_status", "status"),
        Index("ix_terminal_readers_serial", "serial_number"),
    )


class TerminalConnectionToken(Base, TimestampMixin):
    __tablename__ = "terminal_connection_tokens"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.connection_token", nullable=False)
    reader_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("terminal_readers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(ConnectionTokenStatus),
        default=ConnectionTokenStatus.ACTIVE,
        nullable=False,
    )
    used_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_connection_tokens_reader", "reader_id"),
        Index("ix_terminal_connection_tokens_token", "token"),
        Index("ix_terminal_connection_tokens_status", "status"),
    )


class TerminalLocation(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "terminal_locations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.location", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    address_line1: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    configuration_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    geolocation: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_locations_account", "account_id"),
        Index("ix_terminal_locations_country", "country"),
    )


class CardPresentData(Base, TimestampMixin):
    __tablename__ = "terminal_card_present_data"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.card_present_data", nullable=False)
    entry_mode: Mapped[str] = mapped_column(
        SQLEnum(CardEntryMode),
        nullable=False,
    )
    card_brand: Mapped[str] = mapped_column(String(50), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    exp_month: Mapped[int] = mapped_column(Integer, nullable=False)
    exp_year: Mapped[int] = mapped_column(Integer, nullable=False)
    cardholder_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    application_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    aid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tvr: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    tsq: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    receipt_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    emv_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    card_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    generated_card: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_card_present_data_card_fingerprint", "card_fingerprint"),
    )


class TerminalPayment(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "terminal_payments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.payment", nullable=False)
    reader_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("terminal_readers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_present_data_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("terminal_card_present_data.id", ondelete="SET NULL"),
        nullable=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_capturable: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_received: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    application_fee_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(TerminalPaymentStatus),
        default=TerminalPaymentStatus.PENDING,
        nullable=False,
    )
    capture_method: Mapped[str] = mapped_column(
        SQLEnum(CaptureMethod),
        default=CaptureMethod.AUTOMATIC,
        nullable=False,
    )
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    receipt_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    receipt_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tip_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tip_collected_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    signature_collected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signature_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    signature_collected_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    offline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offline_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    offline_details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    processed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    canceled_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_payments_reader", "reader_id"),
        Index("ix_terminal_payments_payment_intent", "payment_intent_id"),
        Index("ix_terminal_payments_status", "status"),
        Index("ix_terminal_payments_created", "created"),
    )


class TerminalConfiguration(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "terminal_configurations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.configuration", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tipping_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tipping_percentages: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    tipping_fixed_amounts: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    collect_signature: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    collect_name: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    show_amount_confirmation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    verification_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    ui_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    receipt_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    receipt_email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    receipt_sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    receipt_header: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    receipt_footer: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    offline_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    offline_transaction_limit: Mapped[int] = mapped_column(Integer, default=50000, nullable=False)
    offline_amount_limit: Mapped[int] = mapped_column(Integer, default=1000000, nullable=False)
    offline_allow_charged_cards: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    offline_max_stored_transactions: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    branding_logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    branding_primary_color: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    branding_secondary_color: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_configurations_account", "account_id"),
        Index("ix_terminal_configurations_default", "is_default"),
    )


class TerminalAction(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "terminal_actions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.action", nullable=False)
    reader_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("terminal_readers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        SQLEnum(ActionType),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(ActionStatus),
        default=ActionStatus.PENDING,
        nullable=False,
    )
    request_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    response_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expired_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_actions_reader", "reader_id"),
        Index("ix_terminal_actions_status", "status"),
        Index("ix_terminal_actions_type", "type"),
    )


class TerminalEvent(Base, TimestampMixin):
    __tablename__ = "terminal_events"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.event", nullable=False)
    reader_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("terminal_readers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        SQLEnum(TerminalEventType),
        nullable=False,
    )
    event_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_events_reader", "reader_id"),
        Index("ix_terminal_events_type", "event_type"),
        Index("ix_terminal_events_timestamp", "timestamp"),
    )


class TerminalOfflineQueue(Base, TimestampMixin):
    __tablename__ = "terminal_offline_queue"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.offline_queue", nullable=False)
    reader_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("terminal_readers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    offline_id: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    card_present_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at_reader: Mapped[int] = mapped_column(BigInteger, nullable=False)
    synced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synced_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sync_failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sync_failure: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_offline_queue_reader", "reader_id"),
        Index("ix_terminal_offline_queue_synced", "synced"),
        Index("ix_terminal_offline_queue_offline_id", "offline_id"),
    )


class TerminalSignature(Base, TimestampMixin):
    __tablename__ = "terminal_signatures"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.signature", nullable=False)
    payment_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("terminal_payments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reader_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    signature_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signature_format: Mapped[str] = mapped_column(String(20), default="svg", nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    collected_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_signatures_payment", "payment_id"),
    )


class TerminalReceipt(Base, TimestampMixin):
    __tablename__ = "terminal_receipts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="terminal.receipt", nullable=False)
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("terminal_payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reader_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    receipt_type: Mapped[str] = mapped_column(String(20), nullable=False)
    receipt_number: Mapped[str] = mapped_column(String(20), nullable=False)
    receipt_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    receipt_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_sent_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    email_address: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sms_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sms_sent_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    printed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_terminal_receipts_payment", "payment_id"),
        Index("ix_terminal_receipts_number", "receipt_number"),
    )
