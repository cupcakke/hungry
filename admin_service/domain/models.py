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


class AdminRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    ANALYST = "analyst"
    SUPPORT = "support"


class AdminUserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_CUSTOMER = "waiting_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(str, enum.Enum):
    FRAUD_DETECTED = "fraud_detected"
    HIGH_VOLUME = "high_volume"
    DISPUTE_SPIKE = "dispute_spike"
    SYSTEM_ERROR = "system_error"
    COMPLIANCE_ALERT = "compliance_alert"
    MERCHANT_RISK = "merchant_risk"
    PAYMENT_FAILURE = "payment_failure"
    SECURITY_ALERT = "security_alert"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OnboardingStatus(str, enum.Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


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


class AdminUser(Base, TimestampMixin, SoftDeleteMixin, MetadataMixin):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(
        SQLEnum(AdminRole),
        default=AdminRole.ADMIN,
        nullable=False,
    )
    permissions: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(AdminUserStatus),
        default=AdminUserStatus.PENDING,
        nullable=False,
    )
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[List["AdminSession"]] = relationship(
        "AdminSession", back_populates="admin_user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[List["AdminAuditLog"]] = relationship(
        "AdminAuditLog", back_populates="admin_user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["ApiKey"]] = relationship(
        "ApiKey", back_populates="admin_user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_admin_users_email", "email"),
        Index("ix_admin_users_status", "status"),
    )


class AdminSession(Base, TimestampMixin):
    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    refresh_token_hash: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(SessionStatus),
        default=SessionStatus.ACTIVE,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    admin_user: Mapped["AdminUser"] = relationship("AdminUser", back_populates="sessions")

    __table_args__ = (
        Index("ix_admin_sessions_token_hash", "token_hash"),
        Index("ix_admin_sessions_admin_user_id", "admin_user_id"),
        Index("ix_admin_sessions_expires_at", "expires_at"),
    )


class AdminAuditLog(Base, TimestampMixin):
    __tablename__ = "admin_audit_logs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    changes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    old_values: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    admin_user: Mapped["AdminUser"] = relationship("AdminUser", back_populates="audit_logs")

    __table_args__ = (
        Index("ix_admin_audit_logs_admin_user_id", "admin_user_id"),
        Index("ix_admin_audit_logs_action", "action"),
        Index("ix_admin_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_admin_audit_logs_timestamp", "created_at"),
    )


class PlatformMetrics(Base, TimestampMixin):
    __tablename__ = "platform_metrics"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    total_volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_transactions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    successful_transactions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    failed_transactions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_customers: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    new_customers: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    active_merchants: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    new_merchants: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    disputes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disputes_volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    disputes_rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), default=Decimal("0.00000"), nullable=False)
    fraud_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fraud_volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    fraud_rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), default=Decimal("0.00000"), nullable=False)
    refunds_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    refunds_volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    chargeback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chargeback_volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    revenue: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    fee_revenue: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    __table_args__ = (
        Index("ix_platform_metrics_date", "date", unique=True),
    )


class MerchantOverview(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "merchant_overviews"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    business_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    business_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    processing_volume: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    transaction_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    chargeback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chargeback_rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), default=Decimal("0.00000"), nullable=False)
    refund_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    refund_rate: Mapped[Decimal] = mapped_column(Numeric(8, 5), default=Decimal("0.00000"), nullable=False)
    dispute_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_level: Mapped[str] = mapped_column(
        SQLEnum(RiskLevel),
        default=RiskLevel.LOW,
        nullable=False,
    )
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    onboarding_status: Mapped[str] = mapped_column(
        SQLEnum(OnboardingStatus),
        default=OnboardingStatus.PENDING,
        nullable=False,
    )
    charges_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    suspension_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    primary_contact_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    primary_contact_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    mcc_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    monthly_volume_limit: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_merchant_overviews_account_id", "account_id"),
        Index("ix_merchant_overviews_risk_level", "risk_level"),
        Index("ix_merchant_overviews_onboarding_status", "onboarding_status"),
    )


class SupportTicket(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    admin_assigned_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(TicketStatus),
        default=TicketStatus.OPEN,
        nullable=False,
    )
    priority: Mapped[str] = mapped_column(
        SQLEnum(TicketPriority),
        default=TicketPriority.MEDIUM,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(20), default="admin_panel", nullable=False)
    first_response_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)

    messages: Mapped[List["TicketMessage"]] = relationship(
        "TicketMessage", back_populates="ticket", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_support_tickets_account_id", "account_id"),
        Index("ix_support_tickets_status", "status"),
        Index("ix_support_tickets_priority", "priority"),
        Index("ix_support_tickets_admin_assigned_id", "admin_assigned_id"),
    )


class TicketMessage(Base, TimestampMixin):
    __tablename__ = "ticket_messages"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sender_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    ticket: Mapped["SupportTicket"] = relationship("SupportTicket", back_populates="messages")

    __table_args__ = (
        Index("ix_ticket_messages_ticket_id", "ticket_id"),
    )


class SystemAlert(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "system_alerts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    alert_type: Mapped[str] = mapped_column(
        SQLEnum(AlertType),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        SQLEnum(AlertSeverity),
        default=AlertSeverity.WARNING,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_system_alerts_alert_type", "alert_type"),
        Index("ix_system_alerts_severity", "severity"),
        Index("ix_system_alerts_is_active", "is_active"),
        Index("ix_system_alerts_created_at", "created_at"),
    )


class ApiKey(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "admin_api_keys"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    permissions: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    scopes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rate_limit: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)

    admin_user: Mapped["AdminUser"] = relationship("AdminUser", back_populates="api_keys")

    __table_args__ = (
        Index("ix_admin_api_keys_key_hash", "key_hash"),
        Index("ix_admin_api_keys_admin_user_id", "admin_user_id"),
    )


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_permissions_name", "name", unique=True),
        Index("ix_permissions_resource_action", "resource", "action"),
    )


class RolePermission(Base, TimestampMixin):
    __tablename__ = "role_permissions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    role: Mapped[str] = mapped_column(
        SQLEnum(AdminRole),
        nullable=False,
        index=True,
    )
    permission_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("role", "permission_id", name="uq_role_permission"),
        Index("ix_role_permissions_role", "role"),
    )


class MerchantRiskAssessment(Base, TimestampMixin):
    __tablename__ = "merchant_risk_assessments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("merchant_overviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assessed_by: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=False,
    )
    risk_level: Mapped[str] = mapped_column(
        SQLEnum(RiskLevel),
        nullable=False,
    )
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_factors: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    recommendations: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_review_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_merchant_risk_assessments_merchant_id", "merchant_id"),
        Index("ix_merchant_risk_assessments_risk_level", "risk_level"),
    )


class DashboardCache(Base, TimestampMixin):
    __tablename__ = "dashboard_cache"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    cache_data: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_dashboard_cache_cache_key", "cache_key", unique=True),
        Index("ix_dashboard_cache_expires_at", "expires_at"),
    )
