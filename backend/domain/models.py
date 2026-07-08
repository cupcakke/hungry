from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Date, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym, declared_attr
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import enum
import uuid

from payment_platform.backend.infrastructure.database import Base
from payment_platform.shared.models.enums import (
    PaymentStatus, PaymentMethodType, ChargeStatus, RefundStatus,
    SubscriptionStatus, SubscriptionInterval, InvoiceStatus, InvoiceCollectionMethod,
    CheckoutSessionStatus, PayoutStatus, TransferStatus, BalanceTransactionType,
    EventType, WebhookEndpointStatus, APIKeyType, AccountType, AccountCapabilityStatus,
    CardBrand, CardFundingType, CardVerificationResult, RiskLevel, TaxBehavior,
    DisputeStatus, DisputeReason, SetupIntentStatus, ConfirmationMethod, CaptureMethod,
    PriceType, PriceTiersMode, ProductType,
)


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


class SoftDeleteMixin:
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class MetadataMixin:
    metadata_: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )

    def get_metadata(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if self.metadata_ is None:
            return default
        return self.metadata_.get(key, default)

    def set_metadata(self, key: str, value: str) -> None:
        if self.metadata_ is None:
            self.metadata_ = {}
        self.metadata_[key] = value


class Customer(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="customer", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    address_line1: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address_postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    shipping_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_line1: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    default_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    default_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    invoice_prefix: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    invoice_settings_default_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    invoice_settings_custom_fields: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    invoice_settings_footer: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    invoice_settings_rendering_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tax_exempt: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    tax_ids: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    preferred_locales: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    next_invoice_sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        Index("ix_customers_email_account", "email", "account_id"),
        Index("ix_customers_created_at", "created_at"),
    )


class PaymentIntent(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "payment_intents"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="payment_intent", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_capturable: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_received: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    application: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    application_fee_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    automatic_payment_methods: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    capture_method: Mapped[str] = mapped_column(String(20), default="automatic", nullable=False)
    charges: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    client_secret: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    confirmation_method: Mapped[str] = mapped_column(String(20), default="automatic", nullable=False)
    confirmed_on: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_payment_error: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    latest_charge: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method_configuration_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    payment_method_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    payment_method_types: Mapped[List[str]] = mapped_column(ARRAY(String), default=["card"], nullable=False)
    processing: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    receipt_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    review: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    setup_future_usage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_line1: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_address_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_address_city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_address_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    shipping_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_carrier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    statement_descriptor_suffix: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="requires_payment_method", nullable=False)
    transfer_data: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    transfer_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_payment_intents_status", "status"),
        Index("ix_payment_intents_customer_created", "customer_id", "created_at"),
        Index("ix_payment_intents_account_created", "account_id", "created_at"),
    )


class Charge(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "charges"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="charge", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_captured: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_refunded: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    application: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    application_fee: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    application_fee_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    billing_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    calculated_statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    captured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dispute: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failure_balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    fraud_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    latest_payment_intent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    order: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    outcome: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("payment_intents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    radar_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    receipt_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    receipt_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    receipt_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    refunds: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    review: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_line1: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_address_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_address_city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_address_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    shipping_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_carrier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    source_transfer: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    statement_descriptor_suffix: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    transfer: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transfer_data: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    transfer_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_charges_status", "status"),
        Index("ix_charges_customer_created", "customer_id", "created_at"),
        Index("ix_charges_payment_intent", "payment_intent_id"),
    )


class Refund(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "refunds"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="refund", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    charge_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("charges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    failure_balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    instructions_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    instructions_payer_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    next_action: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="customer_balance", nullable=False)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    receipt_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    status_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_refunds_charge", "charge_id"),
        Index("ix_refunds_status", "status"),
    )


class Subscription(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="subscription", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    application: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    application_fee_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    automatic_tax: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    billing_cycle_anchor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    billing_thresholds: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    cancel_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    canceled_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    cancellation_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    collection_method: Mapped[str] = mapped_column(String(30), default="charge_automatically", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    current_period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    days_until_due: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    default_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    default_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    default_tax_rates: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    discount: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    discounts: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    ended_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    invoice_settings: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    items: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    latest_invoice_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    next_pending_invoice_item_invoice: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    pause_collection: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    payment_settings: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    pending_invoice_item_interval: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    pending_setup_intent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    pending_update: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    plan: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    schedule: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_date: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="incomplete", nullable=False)
    test_clock: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transfer_data: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    trial_end: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    trial_settings: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    trial_start: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_subscriptions_customer_status", "customer_id", "status"),
        Index("ix_subscriptions_status", "status"),
    )


class Invoice(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="invoice", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    account_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    account_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    account_tax_ids: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    amount_due: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_paid: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_remaining: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_shipping: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    application: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    application_fee_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempted_extensions: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    auto_advance: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    automatic_tax: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    billing_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    charge_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    collection_method: Mapped[str] = mapped_column(String(30), default="charge_automatically", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    custom_fields: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_address: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    customer_shipping: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    customer_tax_exempt: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    customer_tax_ids: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    default_payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    default_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    default_tax_rates: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    discount: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    discounts: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    due_date: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    effective_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ending_balance: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    footer: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    from_invoice: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    hosted_invoice_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    invoice_pdf: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_finalization_error: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    latest_payment_intent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    marked_uncollectible_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    next_payment_attempt: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paid_out_of_band: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_settings: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    post_payment_credit_notes_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pre_payment_credit_notes_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    prepayment_credit_notes: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    quote_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    receipt_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    rendering_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    shipping_cost: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    shipping_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    starting_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    status_transitions: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    subscription_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    subscription_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    subscription_proration_date: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subtotal_excluding_tax: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tax: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    test_clock: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_discount_amounts: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    total_excluding_tax: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_tax_amounts: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    transfer_data: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    webhooks_delivered_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_invoices_customer_status", "customer_id", "status"),
        Index("ix_invoices_subscription", "subscription_id"),
        Index("ix_invoices_status", "status"),
    )


class InvoiceItem(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "invoice_items"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="invoiceitem", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    date: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    discountable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    discounts: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    plan: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    price_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    proration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    proration_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    subscription_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    subscription_item: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tax_rates: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    test_clock: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    unit_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    unit_amount_decimal: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 12), nullable=True)

    __table_args__ = (
        Index("ix_invoice_items_invoice", "invoice_id"),
        Index("ix_invoice_items_customer_date", "customer_id", "date"),
    )


class CheckoutSession(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "checkout_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="checkout.session", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    after_expiration: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    allow_promotion_codes: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    amount_subtotal: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount_total: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    automatic_tax: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    billing_address_collection: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    billing_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    cancel_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    client_reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    client_secret: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    consent: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    consent_collection: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    currency_conversion: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    custom_fields: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    custom_text: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    customer_creation: Mapped[str] = mapped_column(String(20), default="if_required", nullable=False)
    customer_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    customer_tax_ids: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    discounts: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    invoice_creation: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    line_items: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    locale: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_link: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method_collection: Mapped[str] = mapped_column(String(30), default="if_required", nullable=False)
    payment_method_configuration_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    payment_method_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    payment_method_types: Mapped[List[str]] = mapped_column(ARRAY(String), default=["card"], nullable=False)
    payment_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    payment_method_usage: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone_number_collection: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    recovered_from: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    redirect_on_completion: Mapped[str] = mapped_column(String(30), default="always", nullable=False)
    return_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    setup_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_collection: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    shipping_cost: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    shipping_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    shipping_options: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    submit_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    subscription_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    success_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tax_id_collection: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    total_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    ui_mode: Mapped[str] = mapped_column(String(20), default="hosted", nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_checkout_sessions_status", "status"),
        Index("ix_checkout_sessions_customer", "customer_id"),
        Index("ix_checkout_sessions_expires", "expires_at"),
    )


class PaymentMethod(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="payment_method", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    acss_debit: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    affirm: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    afterpay_clearpay: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    alipay: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    au_becs_debit: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    bacs_debit: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    bancontact: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    billing_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    blik: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    card: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    card_present: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    cashapp: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    eps: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    fpx: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    giropay: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    grabpay: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    ideal: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    interac_present: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    klarna: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    konbini: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    link: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    multibanco: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    oxxo: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    p24: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    paynow: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    paypal: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    pix: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    promptpay: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    radar_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    sepa_debit: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    sofort: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    us_bank_account: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    wechat_pay: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    zip: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_payment_methods_customer_type", "customer_id", "type"),
        Index("ix_payment_methods_type", "type"),
    )


class Balance(Base, TimestampMixin):
    __tablename__ = "balances"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    available: Mapped[List[Dict]] = mapped_column(JSONB, default=list, nullable=False)
    connect_reserved: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    instant_available: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    issuing: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending: Mapped[List[Dict]] = mapped_column(JSONB, default=list, nullable=False)


class BalanceTransaction(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "balance_transactions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="balance_transaction", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    available_on: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 10), nullable=True)
    fee: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    fee_details: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    financial_transaction_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    funding: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    net: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reporting_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        Index("ix_balance_transactions_type", "type"),
        Index("ix_balance_transactions_source", "source"),
        Index("ix_balance_transactions_created", "created"),
    )


class WebhookEndpoint(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="webhook_endpoint", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    api_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    application: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    enabled_events: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    secret: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="enabled", nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (
        Index("ix_webhook_endpoints_account", "account_id"),
        Index("ix_webhook_endpoints_status", "status"),
    )


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="event", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    api_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    data: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_webhooks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    __table_args__ = (
        Index("ix_events_type_created", "type", "created"),
    )


class EventDelivery(Base, TimestampMixin):
    __tablename__ = "event_deliveries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    webhook_endpoint_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    request_headers: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    request_payload: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_headers: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    response_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    webhook_url: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (
        Index("ix_event_deliveries_status", "status"),
        Index("ix_event_deliveries_next_retry", "next_retry_at"),
    )


class APIKey(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    type: Mapped[str] = mapped_column(String(20), default="secret", nullable=False)

    __table_args__ = (
        Index("ix_api_keys_account", "account_id"),
    )


class RestrictedAPIKey(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "restricted_api_keys"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    permissions: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_restricted_api_keys_account", "account_id"),
    )


class Account(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="account", nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), default="standard", nullable=False)
    business_profile: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    business_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    capabilities: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    charges_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    company: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    controller: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    details_submitted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    external_accounts: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    individual: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    invoices_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[Optional[Dict[str, Any]]] = mapped_column("metadata", JSONB, nullable=True, default=dict)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requirements: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    settings: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    tos_acceptance: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_accounts_type", "account_type"),
        Index("ix_accounts_country", "country"),
    )


class AccountCapability(Base, TimestampMixin):
    __tablename__ = "account_capabilities"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability: Mapped[str] = mapped_column(String(50), nullable=False)
    requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unrequested", nullable=False)
    status_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "capability", name="uq_account_capability"),
    )


class Product(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="product", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    attributes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    default_price_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    delete_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    images: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    marketing_features: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    package_dimensions: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    shippable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    tax_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    type: Mapped[str] = mapped_column(String(20), default="service", nullable=False)
    unit_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    updated: Mapped[int] = mapped_column(BigInteger, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_products_active", "active"),
        Index("ix_products_name", "name"),
    )


class Price(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "prices"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="price", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    billing_scheme: Mapped[str] = mapped_column(String(30), default="per_unit", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    currency_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    custom_unit_amount: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lookup_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    product_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recurring_aggregate_usage: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    recurring_interval: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    recurring_interval_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    recurring_usage_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    tax_behavior: Mapped[str] = mapped_column(String(20), default="unspecified", nullable=False)
    tiers: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    tiers_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    transform_quantity: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    type: Mapped[str] = mapped_column(String(20), default="recurring", nullable=False)
    unit_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    unit_amount_decimal: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 12), nullable=True)

    __table_args__ = (
        Index("ix_prices_product", "product_id"),
        Index("ix_prices_active_currency", "active", "currency"),
    )


class Coupon(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "coupons"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="coupon", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount_off: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    applies_to: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    currency_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    duration: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_in_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_redemptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    percent_off: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    redeem_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    redemption_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    times_redeemed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_coupons_valid", "valid"),
    )


class PromotionCode(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "promotion_codes"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="promotion_code", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    coupon_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("coupons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    customer_constraint: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_redemptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    restrictions: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    times_redeemed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        Index("ix_promotion_codes_active", "active"),
        Index("ix_promotion_codes_code", "code"),
    )


class Dispute(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="dispute", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_transactions: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    charge_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("charges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    evidence: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    evidence_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    is_charge_refundable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        Index("ix_disputes_status", "status"),
        Index("ix_disputes_charge", "charge_id"),
    )


class DisputeEvidence(Base, TimestampMixin):
    __tablename__ = "dispute_evidence"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    dispute_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("disputes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    access_activity_log: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    billing_address: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    cancellation_policy: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cancellation_policy_disclosure: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cancellation_rebuttal: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    customer_communication: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    customer_email_address: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_purchase_ip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    customer_signature: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duplicate_charge_documentation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duplicate_charge_explanation: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    duplicate_charge_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    has_evidence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    past_due: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    product_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    receipt: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    refund_policy: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    refund_policy_disclosure: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    refund_refusal_explanation: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    service_date: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    service_documentation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    shipping_carrier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_date: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    shipping_documentation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    submitted_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    uncategorized_file: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    uncategorized_text: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class Payout(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "payouts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="payout", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    arrival_date: Mapped[int] = mapped_column(BigInteger, nullable=False)
    automatic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    debit_from: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    method: Mapped[str] = mapped_column(String(20), default="standard", nullable=False)
    original_payout: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reconciliation_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reversed_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), default="card", nullable=False)
    statement_descriptor: Mapped[Optional[str]] = mapped_column(String(22), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    terminal_refund: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    type: Mapped[str] = mapped_column(String(20), default="bank_account", nullable=False)

    __table_args__ = (
        Index("ix_payouts_status", "status"),
        Index("ix_payouts_account_created", "account_id", "created"),
    )


class Transfer(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "transfers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="transfer", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_reversed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    destination: Mapped[str] = mapped_column(String(50), nullable=False)
    destination_payment: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), default="card", nullable=False)
    transfer_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_transfers_destination", "destination"),
        Index("ix_transfers_status", "reversed"),
    )


class TaxRate(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "tax_rates"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="tax_rate", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    inclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    jurisdiction_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tax_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        Index("ix_tax_rates_active", "active"),
    )


class TaxId(Base, TimestampMixin):
    __tablename__ = "tax_ids"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="tax_id", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[str] = mapped_column(String(50), nullable=False)
    verification: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_tax_ids_customer", "customer_id"),
    )


class SetupIntent(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "setup_intents"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="setup_intent", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    application: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    client_secret: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    flow_directions: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    last_setup_error: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    latest_attempt: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mandate: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    next_action: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method_configuration_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    payment_method_options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    payment_method_types: Mapped[List[str]] = mapped_column(ARRAY(String), default=["card"], nullable=False)
    single_use_mandate: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="requires_payment_method", nullable=False)
    usage: Mapped[str] = mapped_column(String(20), default="off_session", nullable=False)

    __table_args__ = (
        Index("ix_setup_intents_customer", "customer_id"),
        Index("ix_setup_intents_status", "status"),
    )


class Mandate(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "mandates"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="mandate", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    customer_acceptance: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    multi_use: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    single_use: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        Index("ix_mandates_payment_method", "payment_method"),
    )


class CreditNote(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "credit_notes"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="credit_note", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_shipping: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    customer_address: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    customer_balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    customer_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    customer_shipping: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    discount_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    discount_amounts: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    effective_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    invoice_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    memo: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    out_of_band_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    pdf: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    refund: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_cost: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)
    subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subtotal_excluding_tax: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tax: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_excluding_tax: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    voided_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_credit_notes_invoice", "invoice_id"),
        Index("ix_credit_notes_customer", "customer_id"),
    )


class ApplicationFee(Base, TimestampMixin):
    __tablename__ = "application_fees"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="application_fee", nullable=False)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_refunded: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    application: Mapped[str] = mapped_column(String(50), nullable=False)
    balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    charge_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    originating_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    refunds: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_application_fees_charge", "charge_id"),
    )


class File(Base, TimestampMixin):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="file", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    links: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="report", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    categories: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interval: Mapped[str] = mapped_column(String(20), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    next_run_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    report_run: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    updated: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReportRun(Base, TimestampMixin):
    __tablename__ = "report_runs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="report_run", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    error: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parameters: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    report_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    succeeded_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_report_runs_status", "status"),
    )


class TerminalReader(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "terminal_readers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="terminal.reader", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    action: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    device_type: Mapped[str] = mapped_column(String(30), nullable=False)
    device_sw_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    location_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    serial_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="offline", nullable=False)

    __table_args__ = (
        Index("ix_terminal_readers_location", "location_id"),
    )


class Location(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="terminal.location", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    address_line1: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address_postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address_country: Mapped[str] = mapped_column(String(2), nullable=False)
    configuration_overrides: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_locations_account", "account_id"),
    )


class Cardholder(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "cardholders"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.cardholder", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    billing_address_line1: Mapped[str] = mapped_column(String(100), nullable=False)
    billing_address_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    billing_address_city: Mapped[str] = mapped_column(String(50), nullable=False)
    billing_address_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    billing_address_postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_address_country: Mapped[str] = mapped_column(String(2), nullable=False)
    company: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    individual: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    requirements: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    spending_controls: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        Index("ix_cardholders_status", "status"),
    )


class IssuingCard(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "issuing_cards"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.card", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    brand: Mapped[str] = mapped_column(String(20), nullable=False)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    cardholder_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("cardholders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cvc_status: Mapped[str] = mapped_column(String(20), nullable=False)
    exp_month: Mapped[int] = mapped_column(Integer, nullable=False)
    exp_year: Mapped[int] = mapped_column(Integer, nullable=False)
    financial_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    number_status: Mapped[str] = mapped_column(String(20), nullable=False)
    personalization_design: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    replacement_for: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    replacement_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    shipping_address_line1: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_address_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_address_city: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shipping_address_postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_address_country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    shipping_carrier: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    shipping_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shipping_tracking_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    shipping_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    spending_controls: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="inactive", nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        Index("ix_issuing_cards_cardholder", "cardholder_id"),
        Index("ix_issuing_cards_status", "status"),
    )


class IssuingAuthorization(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "issuing_authorizations"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.authorization", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    authorization_method: Mapped[str] = mapped_column(String(30), nullable=False)
    balance_transactions: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    card_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("issuing_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cardholder_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    merchant_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    merchant_category: Mapped[str] = mapped_column(String(10), nullable=False)
    merchant_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant_data: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    merchant_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    network_risk_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pending_request: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    request_history: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    transactions: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    treasury: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    verification_data: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_issuing_authorizations_card", "card_id"),
        Index("ix_issuing_authorizations_status", "status"),
    )


class IssuingTransaction(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "issuing_transactions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="issuing.transaction", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authorization_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("issuing_authorizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    balance_transaction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    cardholder_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    dispute: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    merchant_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    merchant_category: Mapped[str] = mapped_column(String(10), nullable=False)
    merchant_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant_data: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    merchant_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    purchase_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    treasury: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        Index("ix_issuing_transactions_card", "card_id"),
        Index("ix_issuing_transactions_authorization", "authorization_id"),
    )


class FinancialAccount(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "financial_accounts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="treasury.financial_account", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    active_features: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    balance_cash: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    balance_inbound_pending: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    balance_outbound_pending: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    financial_addresses: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_features: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    restricted_features: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    status: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    submitted: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    supporter: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_financial_accounts_account", "account_id"),
    )


class TreasuryTransaction(Base, TimestampMixin):
    __tablename__ = "treasury_transactions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="treasury.transaction", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    balance_impact: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    financial_account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("financial_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    flow_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posted_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    status_transitions: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        Index("ix_treasury_transactions_financial_account", "financial_account_id"),
    )


class CapitalOffer(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "capital_offers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="capital.financing_offer", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    disbursement_method: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    fee_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payable_over: Mapped[Dict] = mapped_column(JSONB, nullable=False)
    repayment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_capital_offers_status", "status"),
    )


class VerificationSession(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "verification_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="identity.verification_session", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    client_reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    client_secret: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_error: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    last_verification_report: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    options: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    provided_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    redaction: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="requires_input", nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    verified_outputs: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_verification_sessions_status", "status"),
    )


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="review", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    billing_address: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    charge_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    closed_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ip_address_location: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    opened_reason: Mapped[str] = mapped_column(String(30), nullable=False)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    session: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_reviews_charge", "charge_id"),
        Index("ix_reviews_open", "open"),
    )


class Order(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="order", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount_captured: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount_returned: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount_subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    automatic_tax: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    billing_address: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    canceled_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    client_secret: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    discounts: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(30), default="unpaid", nullable=False)
    shipping_address: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    tax_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    total_details: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_orders_status", "status"),
        Index("ix_orders_customer", "customer_id"),
    )


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="order_item", nullable=False)
    amount_discount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_tax: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    amount_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    discounts: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)
    order_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    product: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        Index("ix_order_items_order", "order_id"),
    )


class SubscriptionItem(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "subscription_items"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="subscription_item", nullable=False)
    billing_thresholds: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discounts: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    plan: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    price_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    proration_behavior: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    proration_date: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    subscription_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tax_rates: Mapped[Optional[List[Dict]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_subscription_items_subscription", "subscription_id"),
    )


class UsageRecord(Base, TimestampMixin):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="usage_record", nullable=False)
    action: Mapped[str] = mapped_column(String(20), default="increment", nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subscription_item_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("subscription_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_usage_records_subscription_item", "subscription_item_id"),
    )


class IdempotencyKey(Base, TimestampMixin):
    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_method: Mapped[str] = mapped_column(String(10), nullable=False)
    request_params_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    request_path: Mapped[str] = mapped_column(String(500), nullable=False)
    request_raw_params: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_headers: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    response_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_idempotency_keys_expires", "expires_at"),
    )


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actor_ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(30), default="user", nullable=False)
    actor_user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    changes: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)

    __table_args__ = (
        Index("ix_audit_logs_account_created", "account_id", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )
