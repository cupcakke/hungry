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


class ClimateProductType(str, enum.Enum):
    CARBON_REMOVAL = "carbon_removal"
    CARBON_AVOIDANCE = "carbon_avoidance"


class ClimateOrderStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    FULFILLED = "fulfilled"
    CANCELED = "canceled"
    FAILED = "failed"
    REFUNDED = "refunded"


class CarbonCreditStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RETIRED = "retired"
    TRANSFERRED = "transferred"
    EXPIRED = "expired"


class VerificationStandard(str, enum.Enum):
    GOLD_STANDARD = "gold_standard"
    VCS = "vcs"
    CDM = "cdm"
    CAR = "car"
    ACR = "acr"
    VERRA = "verra"


class ClimateReportStatus(str, enum.Enum):
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


class ClimateProduct(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "climate_products"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="climate.product", nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(
        SQLEnum(ClimateProductType),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metric_tons_available: Mapped[Decimal] = mapped_column(Numeric(15, 6), nullable=False)
    price_per_ton: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    verification_standard: Mapped[str] = mapped_column(
        SQLEnum(VerificationStandard),
        nullable=False,
    )
    project_location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    project_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    vintage_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    co_benefits: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    sdg_impact: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    images: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    orders: Mapped[List["ClimateOrder"]] = relationship(
        "ClimateOrder", back_populates="product"
    )

    __table_args__ = (
        Index("ix_climate_products_type", "type"),
        Index("ix_climate_products_verification", "verification_standard"),
        Index("ix_climate_products_active", "active"),
        Index("ix_climate_products_project", "project_id"),
    )


class ClimateOrder(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "climate_orders"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="climate.order", nullable=False)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("climate_products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    metric_tons: Mapped[Decimal] = mapped_column(Numeric(15, 6), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(ClimateOrderStatus),
        default=ClimateOrderStatus.PENDING,
        nullable=False,
    )
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    certificate_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    certificate_generated_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    canceled_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fulfilled_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    product: Mapped["ClimateProduct"] = relationship(
        "ClimateProduct", back_populates="orders"
    )
    credits: Mapped[List["CarbonCredit"]] = relationship(
        "CarbonCredit", back_populates="order"
    )

    __table_args__ = (
        Index("ix_climate_orders_account", "account_id"),
        Index("ix_climate_orders_product", "product_id"),
        Index("ix_climate_orders_status", "status"),
        Index("ix_climate_orders_created", "created"),
    )


class CarbonCredit(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "carbon_credits"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="climate.carbon_credit", nullable=False)
    order_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("climate_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_tons: Mapped[Decimal] = mapped_column(Numeric(15, 6), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    vintage_year: Mapped[int] = mapped_column(Integer, nullable=False)
    verification_standard: Mapped[str] = mapped_column(
        SQLEnum(VerificationStandard),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(CarbonCreditStatus),
        default=CarbonCreditStatus.PENDING,
        nullable=False,
    )
    certificate_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    issued_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    retired_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    transferred_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    transferred_to: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    retirement_beneficiary: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    retirement_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    order: Mapped["ClimateOrder"] = relationship(
        "ClimateOrder", back_populates="credits"
    )
    verifications: Mapped[List["ProjectVerification"]] = relationship(
        "ProjectVerification", back_populates="credit"
    )

    __table_args__ = (
        Index("ix_carbon_credits_order", "order_id"),
        Index("ix_carbon_credits_serial", "serial_number"),
        Index("ix_carbon_credits_status", "status"),
        Index("ix_carbon_credits_project", "project_id"),
    )


class ClimateImpact(Base, TimestampMixin):
    __tablename__ = "climate_impacts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="climate.impact", nullable=False)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    total_metric_tons: Mapped[Decimal] = mapped_column(Numeric(15, 6), default=0, nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    contributions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    carbon_removal_tons: Mapped[Decimal] = mapped_column(Numeric(15, 6), default=0, nullable=False)
    carbon_avoidance_tons: Mapped[Decimal] = mapped_column(Numeric(15, 6), default=0, nullable=False)
    projects_supported: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    co2_equivalent_kg: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_climate_impacts_account", "account_id"),
        Index("ix_climate_impacts_year", "year"),
        UniqueConstraint("account_id", "year", name="uq_climate_impacts_account_year"),
    )


class ProjectVerification(Base, TimestampMixin):
    __tablename__ = "project_verifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="climate.project_verification", nullable=False)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    credit_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("carbon_credits.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    standard: Mapped[str] = mapped_column(
        SQLEnum(VerificationStandard),
        nullable=False,
    )
    verification_date: Mapped[int] = mapped_column(BigInteger, nullable=False)
    certifier: Mapped[str] = mapped_column(String(200), nullable=False)
    certificate_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    verification_body: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    valid_from: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    valid_until: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    verification_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    credit: Mapped[Optional["CarbonCredit"]] = relationship(
        "CarbonCredit", back_populates="verifications"
    )

    __table_args__ = (
        Index("ix_project_verifications_project", "project_id"),
        Index("ix_project_verifications_standard", "standard"),
        Index("ix_project_verifications_credit", "credit_id"),
    )


class ClimateReport(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "climate_reports"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="climate.report", nullable=False)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    period_start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_offset: Mapped[Decimal] = mapped_column(Numeric(15, 6), default=0, nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="usd")
    certificates_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    certificates: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    projects: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    report_type: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(ClimateReportStatus),
        default=ClimateReportStatus.PENDING,
        nullable=False,
    )
    report_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_climate_reports_account", "account_id"),
        Index("ix_climate_reports_period", "period_start", "period_end"),
        Index("ix_climate_reports_status", "status"),
        Index("ix_climate_reports_type", "report_type"),
    )


class CarbonLedgerEntry(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "carbon_ledger_entries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="climate.ledger_entry", nullable=False)
    account_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    credit_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    metric_tons: Mapped[Decimal] = mapped_column(Numeric(15, 6), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(15, 6), nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    effective_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_carbon_ledger_entries_account", "account_id"),
        Index("ix_carbon_ledger_entries_credit", "credit_id"),
        Index("ix_carbon_ledger_entries_order", "order_id"),
        Index("ix_carbon_ledger_entries_effective_at", "effective_at"),
        CheckConstraint(
            "entry_type IN ('issuance', 'retirement', 'transfer_in', 'transfer_out', 'adjustment', 'expiration')",
            name="ck_carbon_ledger_entry_type",
        ),
    )
