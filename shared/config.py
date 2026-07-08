import os
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    name: str = Field(default="payment_platform", description="Database name")
    user: str = Field(default="postgres", description="Database user")
    password: str = Field(default="", description="Database password")
    min_pool_size: int = Field(default=5, ge=1, le=100, description="Minimum connection pool size")
    max_pool_size: int = Field(default=20, ge=1, le=200, description="Maximum connection pool size")
    max_overflow: int = Field(default=10, ge=0, le=50, description="Maximum overflow connections")
    pool_timeout: int = Field(default=30, ge=1, le=300, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=3600, ge=60, le=86400, description="Connection recycle time in seconds")
    echo: bool = Field(default=False, description="Echo SQL statements")
    ssl_mode: str = Field(default="prefer", description="SSL mode: disable, prefer, require, verify-ca, verify-full")
    ssl_cert: Optional[str] = Field(default=None, description="Path to SSL certificate")
    ssl_key: Optional[str] = Field(default=None, description="Path to SSL key")
    ssl_root_cert: Optional[str] = Field(default=None, description="Path to SSL root certificate")

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, description="Redis port")
    password: Optional[str] = Field(default=None, description="Redis password")
    db: int = Field(default=0, ge=0, le=15, description="Redis database number")
    max_connections: int = Field(default=50, ge=1, le=500, description="Maximum connections")
    socket_timeout: float = Field(default=5.0, ge=0.1, le=60.0, description="Socket timeout")
    socket_connect_timeout: float = Field(default=5.0, ge=0.1, le=60.0, description="Connection timeout")
    retry_on_timeout: bool = Field(default=True, description="Retry on timeout")
    health_check_interval: int = Field(default=30, ge=5, le=300, description="Health check interval")

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class CelerySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CELERY_")

    broker_url: str = Field(default="redis://localhost:6379/1", description="Celery broker URL")
    result_backend: str = Field(default="redis://localhost:6379/2", description="Celery result backend")
    task_serializer: str = Field(default="json", description="Task serializer")
    result_serializer: str = Field(default="json", description="Result serializer")
    accept_content: List[str] = Field(default_factory=lambda: ["json"], description="Accepted content types")
    timezone: str = Field(default="UTC", description="Timezone")
    enable_utc: bool = Field(default=True, description="Enable UTC")
    task_track_started: bool = Field(default=True, description="Track task start")
    task_time_limit: int = Field(default=3600, ge=60, le=86400, description="Task time limit in seconds")
    task_soft_time_limit: int = Field(default=3000, ge=30, le=72000, description="Task soft time limit")
    worker_prefetch_multiplier: int = Field(default=4, ge=1, le=100, description="Worker prefetch multiplier")
    worker_max_tasks_per_child: int = Field(default=1000, ge=10, le=10000, description="Max tasks per worker")
    worker_concurrency: int = Field(default=4, ge=1, le=64, description="Worker concurrency")
    task_acks_late: bool = Field(default=True, description="Acknowledge tasks late")
    task_reject_on_worker_lost: bool = Field(default=True, description="Reject on worker lost")
    task_default_retry_delay: int = Field(default=60, ge=1, le=3600, description="Default retry delay")
    task_max_retries: int = Field(default=5, ge=0, le=20, description="Maximum retries")


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    secret_key: str = Field(default="change-me-in-production", description="Application secret key")
    api_key_prefix: str = Field(default="pk_live_", description="API key prefix")
    test_api_key_prefix: str = Field(default="pk_test_", description="Test API key prefix")
    restricted_key_prefix: str = Field(default="rk_live_", description="Restricted key prefix")
    webhook_secret_prefix: str = Field(default="whsec_", description="Webhook secret prefix")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_access_token_expire_minutes: int = Field(default=60, ge=1, le=1440, description="Access token expiry")
    jwt_refresh_token_expire_days: int = Field(default=30, ge=1, le=365, description="Refresh token expiry")
    password_min_length: int = Field(default=12, ge=8, le=128, description="Minimum password length")
    password_require_uppercase: bool = Field(default=True, description="Require uppercase in password")
    password_require_lowercase: bool = Field(default=True, description="Require lowercase in password")
    password_require_digit: bool = Field(default=True, description="Require digit in password")
    password_require_special: bool = Field(default=True, description="Require special char in password")
    mfa_issuer: str = Field(default="PaymentPlatform", description="MFA issuer name")
    mfa_digits: int = Field(default=6, ge=6, le=8, description="MFA code digits")
    mfa_interval: int = Field(default=30, ge=15, le=120, description="MFA interval in seconds")
    encryption_algorithm: str = Field(default="AES-256-GCM", description="Encryption algorithm")
    encryption_key: Optional[str] = Field(default=None, description="Encryption key for sensitive data")
    hash_algorithm: str = Field(default="sha256", description="Hash algorithm")
    idempotency_key_expiry: int = Field(default=86400, ge=60, le=604800, description="Idempotency key expiry")
    csrf_enabled: bool = Field(default=True, description="Enable CSRF protection")
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], description="CORS allowed origins")
    cors_allow_credentials: bool = Field(default=True, description="CORS allow credentials")
    cors_allow_methods: List[str] = Field(default_factory=lambda: ["*"], description="CORS allowed methods")
    cors_allow_headers: List[str] = Field(default_factory=lambda: ["*"], description="CORS allowed headers")
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests_per_minute: int = Field(default=100, ge=1, le=10000, description="Requests per minute")
    rate_limit_requests_per_hour: int = Field(default=1000, ge=1, le=100000, description="Requests per hour")
    ip_whitelist: List[str] = Field(default_factory=list, description="IP whitelist")
    ip_blacklist: List[str] = Field(default_factory=list, description="IP blacklist")


class PaymentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYMENT_")

    default_currency: str = Field(default="USD", description="Default currency")
    supported_currencies: List[str] = Field(
        default_factory=lambda: [
            "USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "SEK", "NOK", "DKK",
            "NZD", "SGD", "HKD", "MXN", "BRL", "INR", "CNY", "KRW", "PLN", "CZK",
            "HUF", "RUB", "TRY", "ZAR", "AED", "SAR", "ILS", "THB", "MYR", "PHP",
        ],
        description="Supported currencies"
    )
    min_payment_amount: Dict[str, int] = Field(
        default_factory=lambda: {
            "USD": 50, "EUR": 50, "GBP": 30, "CAD": 50, "AUD": 50, "JPY": 50,
            "CHF": 50, "SEK": 300, "NOK": 300, "DKK": 250, "NZD": 50, "SGD": 50,
            "HKD": 400, "MXN": 1000, "BRL": 50, "INR": 50, "CNY": 100, "KRW": 500,
        },
        description="Minimum payment amounts in minor units"
    )
    max_payment_amount: Dict[str, int] = Field(
        default_factory=lambda: {
            "USD": 99999999, "EUR": 99999999, "GBP": 99999999, "CAD": 99999999,
            "AUD": 99999999, "JPY": 9999999999, "CHF": 99999999, "SEK": 999999999,
            "NOK": 999999999, "DKK": 999999999, "NZD": 99999999, "SGD": 99999999,
            "HKD": 999999999, "MXN": 9999999999, "BRL": 999999999, "INR": 9999999999,
            "CNY": 999999999, "KRW": 999999999999,
        },
        description="Maximum payment amounts in minor units"
    )
    default_capture_method: str = Field(default="automatic", description="Default capture method")
    default_confirmation_method: str = Field(default="automatic", description="Default confirmation method")
    authorization_expiry_hours: int = Field(default=168, ge=1, le=720, description="Authorization expiry in hours")
    refund_window_days: int = Field(default=365, ge=1, le=730, description="Refund window in days")
    partial_refund_enabled: bool = Field(default=True, description="Enable partial refunds")
    dispute_response_window_days: int = Field(default=30, ge=7, le=90, description="Dispute response window")
    smart_retry_enabled: bool = Field(default=True, description="Enable smart retry")
    smart_retry_max_attempts: int = Field(default=8, ge=1, le=20, description="Max retry attempts")
    smart_retry_intervals: List[int] = Field(
        default_factory=lambda: [1, 3, 5, 7, 14, 21, 28, 35],
        description="Retry intervals in days"
    )


class SubscriptionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBSCRIPTION_")

    default_billing_cycle_anchor: str = Field(default="start_of_period", description="Default billing anchor")
    proration_behavior: str = Field(default="create_prorations", description="Default proration behavior")
    trial_period_days: Optional[int] = Field(default=None, ge=0, le=365, description="Default trial period")
    grace_period_days: int = Field(default=7, ge=0, le=30, description="Grace period for failed payments")
    collection_method: str = Field(default="charge_automatically", description="Default collection method")
    days_until_due: int = Field(default=30, ge=1, le=90, description="Days until invoice due")
    automatic_tax_enabled: bool = Field(default=True, description="Enable automatic tax")
    pending_update_expiry_hours: int = Field(default=24, ge=1, le=168, description="Pending update expiry")


class InvoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVOICE_")

    default_due_days: int = Field(default=30, ge=1, le=90, description="Default due days")
    auto_advance: bool = Field(default=True, description="Auto advance invoices")
    collection_method: str = Field(default="charge_automatically", description="Default collection method")
    footer_text: Optional[str] Field(default=None, description="Default footer text")
    custom_fields: List[Dict[str, str]] = Field(default_factory=list, description="Custom fields")
    render_pdf: bool = Field(default=True, description="Render PDF")
    default_tax_rates: List[str] = Field(default_factory=list, description="Default tax rate IDs")
    number_prefix: str = Field(default="", description="Invoice number prefix")
    number_suffix: str = Field(default="", description="Invoice number suffix")
    next_number: int = Field(default=1, ge=1, description="Next invoice number")


class WebhookSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEBHOOK_")

    max_retries: int = Field(default=10, ge=1, le=20, description="Maximum retry attempts")
    retry_intervals: List[int] = Field(
        default_factory=lambda: [1, 2, 5, 10, 30, 60, 120, 300, 600, 900],
        description="Retry intervals in seconds"
    )
    timeout_seconds: int = Field(default=30, ge=5, le=120, description="Webhook timeout")
    max_payload_size: int = Field(default=65536, ge=1024, le=1048576, description="Max payload size in bytes")
    signature_version: int = Field(default=1, ge=1, description="Signature version")
    enabled: bool = Field(default=True, description="Enable webhook delivery")
    async_delivery: bool = Field(default=True, description="Enable async delivery")
    dead_letter_enabled: bool = Field(default=True, description="Enable dead letter queue")


class PayoutSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAYOUT_")

    default_schedule: str = Field(default="daily", description="Default payout schedule")
    minimum_payout_amounts: Dict[str, int] = Field(
        default_factory=lambda: {
            "USD": 100, "EUR": 100, "GBP": 100, "CAD": 100, "AUD": 100, "JPY": 10000,
            "CHF": 100, "SEK": 1000, "NOK": 1000, "DKK": 1000, "NZD": 100, "SGD": 100,
        },
        description="Minimum payout amounts in minor units"
    )
    maximum_payout_amounts: Dict[str, int] = Field(
        default_factory=lambda: {
            "USD": 10000000000, "EUR": 10000000000, "GBP": 10000000000, "CAD": 10000000000,
            "AUD": 10000000000, "JPY": 1000000000000, "CHF": 10000000000, "SEK": 100000000000,
            "NOK": 100000000000, "DKK": 100000000000, "NZD": 10000000000, "SGD": 10000000000,
        },
        description="Maximum payout amounts in minor units"
    )
    instant_payout_enabled: bool = Field(default=True, description="Enable instant payout")
    instant_payout_fee_percent: Decimal = Field(default=Decimal("1.5"), description="Instant payout fee percent")
    debit_negative_balance: bool = Field(default=False, description="Debit negative balance")


class TaxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAX_")

    provider: str = Field(default="internal", description="Tax provider: internal, stripe_tax, taxjar, avalara")
    default_tax_behavior: str = Field(default="exclusive", description="Default tax behavior: exclusive, inclusive")
    auto_calculate: bool = Field(default=True, description="Auto calculate tax")
    validate_tax_ids: bool = Field(default=True, description="Validate tax IDs")
    supported_tax_id_types: List[str] = Field(
        default_factory=lambda: [
            "ae_trn", "au_abn", "br_cnpj", "br_cpf", "ca_bn", "ca_gst_hst",
            "ca_pst_bc", "ca_pst_mb", "ca_pst_sk", "ca_qst", "ch_vat", "cl_tin",
            "es_cif", "eu_vat", "gb_vat", "hk_br", "id_npw", "il_vat", "in_gst",
            "jp_cn", "jp_rn", "jp_trn", "kr_brn", "li_uid", "mx_rfc", "my_frp",
            "my_itn", "my_sst", "no_vat", "nz_gst", "ph_tin", "ru_inn", "ru_kpp",
            "sa_vat", "sg_gst", "sg_uen", "si_vat", "th_vat", "tw_vat", "us_ein",
            "za_vat",
        ],
        description="Supported tax ID types"
    )


class FraudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FRAUD_")

    enabled: bool = Field(default=True, description="Enable fraud detection")
    provider: str = Field(default="internal", description="Fraud provider: internal, stripe_radar, signified")
    block_high_risk: bool = Field(default=True, description="Block high risk transactions")
    review_medium_risk: bool = Field(default=True, description="Review medium risk transactions")
    score_threshold_high: float = Field(default=75.0, ge=0.0, le=100.0, description="High risk threshold")
    score_threshold_medium: float = Field(default=50.0, ge=0.0, le=100.0, description="Medium risk threshold")
    velocity_checks_enabled: bool = Field(default=True, description="Enable velocity checks")
    velocity_window_minutes: int = Field(default=60, ge=1, le=1440, description="Velocity window")
    max_transactions_per_window: int = Field(default=100, ge=1, le=10000, description="Max transactions per window")
    max_amount_per_window: Dict[str, int] = Field(
        default_factory=lambda: {"USD": 10000000, "EUR": 10000000, "GBP": 10000000},
        description="Max amount per window in minor units"
    )
    ip_geolocation_enabled: bool = Field(default=True, description="Enable IP geolocation")
    device_fingerprinting_enabled: bool = Field(default=True, description="Enable device fingerprinting")
    ml_model_enabled: bool = Field(default=True, description="Enable ML model")
    custom_rules_enabled: bool = Field(default=True, description="Enable custom rules")


class PlatformSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_")

    enabled: bool = Field(default=True, description="Enable platform features")
    default_fee_percent: Decimal = Field(default=Decimal("2.9"), description="Default platform fee percent")
    default_fee_fixed: Dict[str, int] = Field(
        default_factory=lambda: {"USD": 30, "EUR": 25, "GBP": 20},
        description="Default fixed fee in minor units"
    )
    reserve_hold_days: int = Field(default=7, ge=0, le=90, description="Reserve hold days")
    reserve_percent: Decimal = Field(default=Decimal("10.0"), ge=Decimal("0"), le=Decimal("100"), description="Reserve percent")
    onboarding_enabled: bool = Field(default=True, description="Enable onboarding")
    kyc_provider: str = Field(default="internal", description="KYC provider")
    payout_schedule: str = Field(default="daily", description="Default payout schedule for connected accounts")


class CardIssuingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARD_ISSUING_")

    enabled: bool = Field(default=False, description="Enable card issuing")
    provider: str = Field(default="stripe", description="Card issuing provider")
    supported_card_types: List[str] = Field(
        default_factory=lambda: ["visa", "mastercard"],
        description="Supported card types"
    )
    virtual_cards_enabled: bool = Field(default=True, description="Enable virtual cards")
    physical_cards_enabled: bool = Field(default=True, description="Enable physical cards")
    default_spending_limits: Dict[str, int] = Field(
        default_factory=lambda: {"daily": 50000, "weekly": 200000, "monthly": 1000000},
        description="Default spending limits in minor units"
    )
    authorization_webhook_enabled: bool = Field(default=True, description="Enable authorization webhooks")


class TreasurySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TREASURY_")

    enabled: bool = Field(default=False, description="Enable treasury features")
    provider: str = Field(default="stripe", description="Treasury provider")
    supported_financial_account_types: List[str] = Field(
        default_factory=lambda: ["checking", "savings"],
        description="Supported financial account types"
    )
    inbound_transfer_enabled: bool = Field(default=True, description="Enable inbound transfers")
    outbound_transfer_enabled: bool = Field(default=True, description="Enable outbound transfers")
    minimum_transfer_amount: int = Field(default=100, ge=1, description="Minimum transfer amount in minor units")


class CapitalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAPITAL_")

    enabled: bool = Field(default=False, description="Enable capital/financing")
    provider: str = Field(default="internal", description="Capital provider")
    min_offer_amount: int = Field(default=100000, ge=10000, description="Minimum offer amount in minor units")
    max_offer_amount: int = Field(default=100000000, le=1000000000, description="Maximum offer amount in minor units")
    default_interest_rate: Decimal = Field(default=Decimal("15.0"), description="Default annual interest rate")
    max_term_months: int = Field(default=36, ge=3, le=84, description="Maximum term in months")
    repayment_method: str = Field(default="fixed", description="Repayment method: fixed, revenue_share")


class CryptoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRYPTO_")

    enabled: bool = Field(default=False, description="Enable crypto payments")
    provider: str = Field(default="internal", description="Crypto provider")
    supported_cryptocurrencies: List[str] = Field(
        default_factory=lambda: ["btc", "eth", "usdc", "usdt"],
        description="Supported cryptocurrencies"
    )
    settlement_currency: str = Field(default="USD", description="Settlement currency")
    auto_convert: bool = Field(default=True, description="Auto convert to fiat")
    confirmation_blocks: Dict[str, int] = Field(
        default_factory=lambda: {"btc": 6, "eth": 12, "usdc": 12, "usdt": 12},
        description="Required confirmation blocks"
    )


class ClimateSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLIMATE_")

    enabled: bool = Field(default=False, description="Enable climate contributions")
    provider: str = Field(default="stripe", description="Climate provider")
    default_contribution_percent: Decimal = Field(default=Decimal("1.0"), description="Default contribution percent")
    available_projects: List[str] = Field(default_factory=list, description="Available climate projects")


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    provider: str = Field(default="local", description="Storage provider: local, s3, gcs, azure")
    bucket_name: Optional[str] = Field(default=None, description="Bucket name")
    region: str = Field(default="us-east-1", description="Storage region")
    access_key: Optional[str] = Field(default=None, description="Access key")
    secret_key: Optional[str] = Field(default=None, description="Secret key")
    endpoint_url: Optional[str] = Field(default=None, description="Custom endpoint URL")
    local_path: str = Field(default="/tmp/payment_platform_storage", description="Local storage path")
    presigned_url_expiry: int = Field(default=3600, ge=60, le=86400, description="Presigned URL expiry")
    max_file_size: int = Field(default=10485760, ge=1024, le=104857600, description="Max file size in bytes")


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMAIL_")

    provider: str = Field(default="smtp", description="Email provider: smtp, sendgrid, ses, mailgun")
    smtp_host: Optional[str] = Field(default=None, description="SMTP host")
    smtp_port: int = Field(default=587, description="SMTP port")
    smtp_user: Optional[str] = Field(default=None, description="SMTP user")
    smtp_password: Optional[str] = Field(default=None, description="SMTP password")
    smtp_use_tls: bool = Field(default=True, description="Use TLS")
    from_email: str = Field(default="noreply@paymentplatform.com", description="From email address")
    from_name: str = Field(default="Payment Platform", description="From name")
    reply_to: Optional[str] = Field(default=None, description="Reply to email")
    api_key: Optional[str] = Field(default=None, description="Email provider API key")


class SMSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMS_")

    provider: str = Field(default="twilio", description="SMS provider: twilio, nexmo, sns")
    account_sid: Optional[str] = Field(default=None, description="Account SID")
    auth_token: Optional[str] = Field(default=None, description="Auth token")
    from_number: Optional[str] = Field(default=None, description="From phone number")
    enabled: bool = Field(default=True, description="Enable SMS")


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OBSERVABILITY_")

    tracing_enabled: bool = Field(default=True, description="Enable tracing")
    tracing_provider: str = Field(default="otlp", description="Tracing provider: otlp, jaeger, zipkin")
    tracing_endpoint: Optional[str] = Field(default=None, description="Tracing endpoint")
    tracing_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0, description="Tracing sample rate")
    metrics_enabled: bool = Field(default=True, description="Enable metrics")
    metrics_provider: str = Field(default="prometheus", description="Metrics provider: prometheus, datadog")
    metrics_port: int = Field(default=9090, ge=1024, le=65535, description="Metrics port")
    logging_format: str = Field(default="json", description="Logging format: json, text")
    logging_level: LogLevel = Field(default=LogLevel.INFO, description="Logging level")
    logging_include_timestamp: bool = Field(default=True, description="Include timestamp in logs")
    logging_include_level: bool = Field(default=True, description="Include level in logs")
    logging_include_caller: bool = Field(default=False, description="Include caller in logs")
    logging_include_request_id: bool = Field(default=True, description="Include request ID in logs")
    sentry_dsn: Optional[str] = Field(default=None, description="Sentry DSN")
    sentry_environment: Optional[str] = Field(default=None, description="Sentry environment")
    sentry_traces_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0, description="Sentry traces sample rate")


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_")

    version: str = Field(default="2024-01-01", description="API version")
    version_header: str = Field(default="Stripe-Version", description="Version header name")
    title: str = Field(default="Payment Platform API", description="API title")
    description: str = Field(default="Production-ready payment and financial infrastructure API", description="API description")
    docs_url: Optional[str] = Field(default="/docs", description="Docs URL")
    redoc_url: Optional[str] = Field(default="/redoc", description="ReDoc URL")
    openapi_url: Optional[str] = Field(default="/openapi.json", description="OpenAPI URL")
    max_request_size: int = Field(default=10485760, ge=1024, le=104857600, description="Max request size")
    default_page_size: int = Field(default=10, ge=1, le=100, description="Default page size")
    max_page_size: int = Field(default=100, ge=1, le=1000, description="Maximum page size")
    request_timeout: int = Field(default=30, ge=5, le=300, description="Request timeout")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Field(default=Environment.DEVELOPMENT, description="Application environment")
    debug: bool = Field(default=False, description="Debug mode")
    app_name: str = Field(default="Payment Platform", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    app_url: str = Field(default="http://localhost:8000", description="Application URL")
    dashboard_url: str = Field(default="http://localhost:3000", description="Dashboard URL")
    hosted_checkout_url: str = Field(default="http://localhost:8001", description="Hosted checkout URL")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    celery: CelerySettings = Field(default_factory=CelerySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    payment: PaymentSettings = Field(default_factory=PaymentSettings)
    subscription: SubscriptionSettings = Field(default_factory=SubscriptionSettings)
    invoice: InvoiceSettings = Field(default_factory=InvoiceSettings)
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)
    payout: PayoutSettings = Field(default_factory=PayoutSettings)
    tax: TaxSettings = Field(default_factory=TaxSettings)
    fraud: FraudSettings = Field(default_factory=FraudSettings)
    platform: PlatformSettings = Field(default_factory=PlatformSettings)
    card_issuing: CardIssuingSettings = Field(default_factory=CardIssuingSettings)
    treasury: TreasurySettings = Field(default_factory=TreasurySettings)
    capital: CapitalSettings = Field(default_factory=CapitalSettings)
    crypto: CryptoSettings = Field(default_factory=CryptoSettings)
    climate: ClimateSettings = Field(default_factory=ClimateSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    sms: SMSSettings = Field(default_factory=SMSSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    api: APISettings = Field(default_factory=APISettings)

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_staging(self) -> bool:
        return self.environment == Environment.STAGING

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_testing(self) -> bool:
        return self.environment == Environment.TESTING

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.is_production:
            if self.security.secret_key == "change-me-in-production":
                raise ValueError("SECRET_KEY must be changed in production")
            if not self.security.encryption_key:
                raise ValueError("SECURITY_ENCRYPTION_KEY is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
