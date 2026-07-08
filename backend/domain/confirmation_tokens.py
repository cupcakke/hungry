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


class ConfirmationTokenType(str, enum.Enum):
    PAYMENT = "payment"
    SETUP = "setup"


class ConfirmationTokenStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    USED = "used"


class ConfirmationSessionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ChallengeType(str, enum.Enum):
    THREE_DS = "3ds"
    OTP = "otp"
    BIOMETRIC = "biometric"
    APP_REDIRECT = "app_redirect"


class ChallengeStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class ThreeDSVersion(str, enum.Enum):
    V1 = "1.0"
    V2_0 = "2.0"
    V2_1 = "2.1"
    V2_2 = "2.2"


class AuthenticationType(str, enum.Enum):
    FRICTIONLESS = "frictionless"
    CHALLENGE = "challenge"
    DECOUPLED = "decoupled"


class LiabilityShift(str, enum.Enum):
    POSSIBLE = "possible"
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class OTPDeliveryMethod(str, enum.Enum):
    SMS = "sms"
    EMAIL = "email"
    VOICE = "voice"


class BiometricType(str, enum.Enum):
    FINGERPRINT = "fingerprint"
    FACE = "face"
    VOICE = "voice"
    IRIS = "iris"


class AppRedirectStatus(str, enum.Enum):
    PENDING = "pending"
    LAUNCHED = "launched"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


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


class ConfirmationToken(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "confirmation_tokens"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="confirmation.token", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    setup_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    type: Mapped[str] = mapped_column(
        SQLEnum(ConfirmationTokenType),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(ConfirmationTokenStatus),
        default=ConfirmationTokenStatus.PENDING,
        nullable=False,
    )
    client_secret: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    used_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payment_method_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    payment_method_types: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    return_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_confirmation_tokens_account", "account_id"),
        Index("ix_confirmation_tokens_payment_intent", "payment_intent_id"),
        Index("ix_confirmation_tokens_setup_intent", "setup_intent_id"),
        Index("ix_confirmation_tokens_client_secret", "client_secret"),
        Index("ix_confirmation_tokens_status", "status"),
        Index("ix_confirmation_tokens_expires", "expires_at"),
    )


class ConfirmationSession(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "confirmation_sessions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="confirmation.session", nullable=False)
    confirmation_token_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("confirmation_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    return_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    success_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cancel_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(ConfirmationSessionStatus),
        default=ConfirmationSessionStatus.PENDING,
        nullable=False,
    )
    customer_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    billing_address: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    shipping_address: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    payment_method_options: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    next_action: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    redirect_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_confirmation_sessions_token", "confirmation_token_id"),
        Index("ix_confirmation_sessions_status", "status"),
        Index("ix_confirmation_sessions_customer", "customer_id"),
    )


class ConfirmationChallenge(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "confirmation_challenges"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="confirmation.challenge", nullable=False)
    confirmation_token_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("confirmation_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confirmation_session_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("confirmation_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    challenge_type: Mapped[str] = mapped_column(
        SQLEnum(ChallengeType),
        nullable=False,
    )
    challenge_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(ChallengeStatus),
        default=ChallengeStatus.PENDING,
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_confirmation_challenges_token", "confirmation_token_id"),
        Index("ix_confirmation_challenges_session", "confirmation_session_id"),
        Index("ix_confirmation_challenges_type", "challenge_type"),
        Index("ix_confirmation_challenges_status", "status"),
    )


class ThreeDSecureData(Base, TimestampMixin):
    __tablename__ = "three_d_secure_data"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="three_d_secure", nullable=False)
    confirmation_token_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("confirmation_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    challenge_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("confirmation_challenges.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[str] = mapped_column(
        SQLEnum(ThreeDSVersion),
        nullable=False,
    )
    three_ds_requestor_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    three_ds_requestor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    three_ds_server_trans_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    acs_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    acs_trans_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    acs_reference_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pareq: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pares: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    md: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cres: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    authentication_type: Mapped[Optional[str]] = mapped_column(
        SQLEnum(AuthenticationType),
        nullable=True,
    )
    liability_shift: Mapped[Optional[str]] = mapped_column(
        SQLEnum(LiabilityShift),
        nullable=True,
    )
    cavv: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    eci: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    xid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ds_trans_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    three_dsv2_directory_server_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    three_dsv2_sdk_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    three_dsv2_sdk_encrypted_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    three_dsv2_sdk_ephemeral_pk: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    challenge_flow: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    challenge_window_size: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    decoupled_auth_max_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    browser_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    device_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    authenticated_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_three_d_secure_token", "confirmation_token_id"),
        Index("ix_three_d_secure_challenge", "challenge_id"),
        Index("ix_three_d_secure_status", "status"),
    )


class OTPVerification(Base, TimestampMixin):
    __tablename__ = "otp_verifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="otp.verification", nullable=False)
    confirmation_token_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("confirmation_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    challenge_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("confirmation_challenges.id", ondelete="SET NULL"),
        nullable=True,
    )
    delivery_method: Mapped[str] = mapped_column(
        SQLEnum(OTPDeliveryMethod),
        nullable=False,
    )
    phone_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    code_length: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    attempts_remaining: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    resend_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_resends: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    resend_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    last_resend_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    verified_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_otp_verifications_token", "confirmation_token_id"),
        Index("ix_otp_verifications_challenge", "challenge_id"),
        Index("ix_otp_verifications_phone", "phone_number"),
        Index("ix_otp_verifications_email", "email"),
    )


class BiometricChallenge(Base, TimestampMixin):
    __tablename__ = "biometric_challenges"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="biometric.challenge", nullable=False)
    confirmation_token_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("confirmation_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    challenge_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("confirmation_challenges.id", ondelete="SET NULL"),
        nullable=True,
    )
    biometric_type: Mapped[str] = mapped_column(
        SQLEnum(BiometricType),
        nullable=False,
    )
    challenge_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    challenge_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    device_info: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    confidence_threshold: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        default=Decimal("0.9000"),
        nullable=False,
    )
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    liveness_check_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    liveness_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    verification_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verified_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_biometric_challenges_token", "confirmation_token_id"),
        Index("ix_biometric_challenges_challenge", "challenge_id"),
        Index("ix_biometric_challenges_device", "device_id"),
        Index("ix_biometric_challenges_type", "biometric_type"),
    )


class AppRedirectData(Base, TimestampMixin):
    __tablename__ = "app_redirect_data"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="app_redirect", nullable=False)
    confirmation_token_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("confirmation_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    challenge_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("confirmation_challenges.id", ondelete="SET NULL"),
        nullable=True,
    )
    app_url: Mapped[str] = mapped_column(String(500), nullable=False)
    fallback_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    package_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    return_intent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    android_package_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ios_bundle_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    universal_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    app_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    deep_link_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        SQLEnum(AppRedirectStatus),
        default=AppRedirectStatus.PENDING,
        nullable=False,
    )
    launched_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    failed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_app_redirect_token", "confirmation_token_id"),
        Index("ix_app_redirect_challenge", "challenge_id"),
        Index("ix_app_redirect_status", "status"),
        Index("ix_app_redirect_package", "package_name"),
    )


class ChallengeTimeoutConfig(Base):
    __tablename__ = "challenge_timeout_configs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="challenge.timeout_config", nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    challenge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    default_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    max_timeout_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    min_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    retry_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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

    __table_args__ = (
        Index("ix_challenge_timeout_configs_account", "account_id"),
        Index("ix_challenge_timeout_configs_type", "challenge_type"),
    )


class LiabilityShiftRecord(Base, TimestampMixin):
    __tablename__ = "liability_shift_records"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(30), default="liability_shift", nullable=False)
    confirmation_token_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("confirmation_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    three_d_secure_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("three_d_secure_data.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    charge_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_brand: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    liability_shift: Mapped[str] = mapped_column(
        SQLEnum(LiabilityShift),
        nullable=False,
    )
    authentication_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cavv: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    eci: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    xid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ds_trans_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    three_ds_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    authenticated_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created: Mapped[int] = mapped_column(BigInteger, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_liability_shift_records_token", "confirmation_token_id"),
        Index("ix_liability_shift_records_3ds", "three_d_secure_id"),
        Index("ix_liability_shift_records_payment", "payment_intent_id"),
        Index("ix_liability_shift_records_charge", "charge_id"),
    )
