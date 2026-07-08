from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func, Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import enum

from payment_platform.backend.infrastructure.database import Base


class VerificationSessionType(str, enum.Enum):
    DOCUMENT = "document"
    ADDRESS = "address"
    IDENTITY = "identity"


class VerificationSessionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    REQUIRES_INPUT = "requires_input"
    VERIFIED = "verified"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class DocumentType(str, enum.Enum):
    PASSPORT = "passport"
    DRIVER_LICENSE = "driver_license"
    ID_CARD = "id_card"
    RESIDENCE_PERMIT = "residence_permit"


class DocumentVerificationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"
    REJECTED = "rejected"


class BiometricType(str, enum.Enum):
    FACE = "face"
    SELFIE = "selfie"


class BiometricStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"
    REJECTED = "rejected"


class AddressVerificationMethod(str, enum.Enum):
    DOCUMENT = "document"
    UTILITY_BILL = "utility_bill"
    BANK_STATEMENT = "bank_statement"
    GEOLOCATION = "geolocation"


class AddressVerificationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"
    REJECTED = "rejected"


class VerificationAttemptStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class OverallVerificationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"


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


class VerificationSession(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "identity_verification_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.verification_session", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        SQLEnum(VerificationSessionType),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(VerificationSessionStatus),
        default=VerificationSessionStatus.PENDING,
        nullable=False,
    )
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redacted_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_identity_verification_sessions_account", "account_id"),
        Index("ix_identity_verification_sessions_status", "status"),
        Index("ix_identity_verification_sessions_type", "type"),
        Index("ix_identity_verification_sessions_created", "created"),
    )


class DocumentVerification(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "identity_document_verifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.document_verification", nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(
        SQLEnum(DocumentType),
        nullable=False,
    )
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    images: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    images_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(DocumentVerificationStatus),
        default=DocumentVerificationStatus.PENDING,
        nullable=False,
    )
    extracted_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    verification_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    document_number_masked: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    holder_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    expiry_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    issue_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    processed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_identity_document_verifications_session", "session_id"),
        Index("ix_identity_document_verifications_status", "status"),
        Index("ix_identity_document_verifications_country", "country"),
    )


class BiometricVerification(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "identity_biometric_verifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.biometric_verification", nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        SQLEnum(BiometricType),
        nullable=False,
    )
    images: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    images_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(BiometricStatus),
        default=BiometricStatus.PENDING,
        nullable=False,
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    liveness_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    face_match_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    verification_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    processed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_identity_biometric_verifications_session", "session_id"),
        Index("ix_identity_biometric_verifications_status", "status"),
    )


class AddressVerification(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "identity_address_verifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.address_verification", nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    address_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    verification_method: Mapped[str] = mapped_column(
        SQLEnum(AddressVerificationMethod),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(AddressVerificationStatus),
        default=AddressVerificationStatus.PENDING,
        nullable=False,
    )
    evidence_documents: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    geocode_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    verification_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    formatted_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    processed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_identity_address_verifications_session", "session_id"),
        Index("ix_identity_address_verifications_status", "status"),
        Index("ix_identity_address_verifications_country", "country_code"),
    )


class VerificationResult(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "identity_verification_results"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.verification_result", nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    overall_status: Mapped[str] = mapped_column(
        SQLEnum(OverallVerificationStatus),
        default=OverallVerificationStatus.PENDING,
        nullable=False,
    )
    checks_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checks_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checks_pending: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_factors: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    failure_reasons: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    document_check: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    biometric_check: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    address_check: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    sanctions_check: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    pep_check: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    aml_check: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    compliance_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_identity_verification_results_session", "session_id"),
        Index("ix_identity_verification_results_status", "overall_status"),
    )


class IdentityDocument(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "identity_documents"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.document", nullable=False)
    verification_session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(
        SQLEnum(DocumentType),
        nullable=False,
    )
    document_number_masked: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    issuing_country: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    expiry_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    issue_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    holder_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    holder_dob: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    holder_nationality: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    holder_gender: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    holder_address: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    document_status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_identity_documents_session", "verification_session_id"),
        Index("ix_identity_documents_country", "issuing_country"),
    )


class VerificationAttempt(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "identity_verification_attempts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.verification_attempt", nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(VerificationAttemptStatus),
        default=VerificationAttemptStatus.PENDING,
        nullable=False,
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    browser_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    geo_location: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_identity_verification_attempts_session", "session_id"),
        Index("ix_identity_verification_attempts_status", "status"),
        Index("ix_identity_verification_attempts_created", "created"),
    )


class SanctionsScreeningResult(Base, TimestampMixin):
    __tablename__ = "identity_sanctions_screenings"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="identity.sanctions_screening", nullable=False)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    screening_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name_screened: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    matches: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    match_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    potential_match_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    screened_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_identity_sanctions_screenings_session", "session_id"),
        Index("ix_identity_sanctions_screenings_type", "screening_type"),
    )


class DataRetentionRecord(Base, TimestampMixin):
    __tablename__ = "identity_data_retention_records"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("identity_verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    retention_period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_deletion_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deleted_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    deletion_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_identity_data_retention_session", "session_id"),
        Index("ix_identity_data_retention_deletion", "scheduled_deletion_at"),
    )
