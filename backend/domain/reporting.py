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


class ReportStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportType(str, enum.Enum):
    BALANCE_TRANSACTIONS = "balance_transactions"
    CHARGES = "charges"
    CUSTOMERS = "customers"
    DISPUTES = "disputes"
    INVOICES = "invoices"
    PAYOUTS = "payouts"
    REFUNDS = "refunds"
    SUBSCRIPTIONS = "subscriptions"
    TAX_RATES = "tax_rates"


class ScheduleFrequency(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ExportFormat(str, enum.Enum):
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"


class DataExportType(str, enum.Enum):
    FULL_ACCOUNT = "full_account"
    PAYMENT_HISTORY = "payment_history"
    CUSTOMER_LIST = "customer_list"


class DataExportStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
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


class Report(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="report", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    report_type: Mapped[str] = mapped_column(
        SQLEnum(ReportType),
        nullable=False,
    )
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(ReportStatus),
        default=ReportStatus.PENDING,
        nullable=False,
    )
    created_at_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    download_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_reports_account", "account_id"),
        Index("ix_reports_status", "status"),
        Index("ix_reports_type", "report_type"),
        Index("ix_reports_created", "created_at_timestamp"),
    )


class ReportRun(Base, TimestampMixin):
    __tablename__ = "report_runs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="report_run", nullable=False)
    report_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    rows_processed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    bytes_written: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_report_runs_report", "report_id"),
        Index("ix_report_runs_started", "started_at"),
    )


class ReportTypeModel(Base, TimestampMixin):
    __tablename__ = "report_types"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="report_type", nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_columns: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    available_filters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    data_source: Mapped[str] = mapped_column(String(100), nullable=False)
    schedule_support: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_report_types_name", "name"),
    )


class ReportSchedule(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "report_schedules"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="report_schedule", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    report_type: Mapped[str] = mapped_column(
        SQLEnum(ReportType),
        nullable=False,
    )
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    frequency: Mapped[str] = mapped_column(
        SQLEnum(ScheduleFrequency),
        nullable=False,
    )
    next_run_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_run_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_report_schedules_account", "account_id"),
        Index("ix_report_schedules_next_run", "next_run_at"),
        Index("ix_report_schedules_active", "active"),
    )


class ReportDownload(Base, TimestampMixin):
    __tablename__ = "report_downloads"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="report_download", nullable=False)
    report_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format: Mapped[str] = mapped_column(
        SQLEnum(ExportFormat),
        default=ExportFormat.CSV,
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_report_downloads_report", "report_id"),
        Index("ix_report_downloads_expires", "expires_at"),
    )


class SavedQuery(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "saved_queries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="saved_query", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    query_sql: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_run_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_saved_queries_account", "account_id"),
        Index("ix_saved_queries_name", "name"),
    )


class QueryResult(Base, TimestampMixin):
    __tablename__ = "query_results"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="query_result", nullable=False)
    saved_query_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("saved_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    result_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_query_results_saved_query", "saved_query_id"),
        Index("ix_query_results_created", "created_at_timestamp"),
    )


class DataExport(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "data_exports"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="data_export", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    export_type: Mapped[str] = mapped_column(
        SQLEnum(DataExportType),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(DataExportStatus),
        default=DataExportStatus.PENDING,
        nullable=False,
    )
    download_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at_timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_data_exports_account", "account_id"),
        Index("ix_data_exports_status", "status"),
        Index("ix_data_exports_type", "export_type"),
    )
