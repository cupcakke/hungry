from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from decimal import Decimal

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, CryptoError

router = APIRouter()


class CryptoPaymentCreateRequest(BaseModel):
    payment_intent_id: Optional[str] = Field(default=None, description="Associated payment intent ID")
    cryptocurrency: str = Field(..., description="Cryptocurrency: btc, eth, usdc, usdt")
    amount_fiat: int = Field(..., gt=0, description="Amount in fiat cents")
    settlement_currency: str = Field(default="usd", description="Settlement currency")
    expiration_minutes: Optional[int] = Field(default=60, description="Payment expiration in minutes")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class CryptoPaymentResponse(BaseModel):
    id: str
    object: str = "crypto.payment"
    payment_intent_id: Optional[str] = None
    cryptocurrency: str
    amount_crypto: Optional[Decimal] = None
    amount_fiat: int
    exchange_rate: Optional[Decimal] = None
    settlement_currency: str
    status: str
    confirmation_blocks: int = 0
    required_confirmations: int = 6
    transaction_hash: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    expiration_time: Optional[int] = None
    detected_at: Optional[int] = None
    confirmed_at: Optional[int] = None
    settled_at: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    account_id: Optional[str] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class CryptoAddressCreateRequest(BaseModel):
    cryptocurrency: str = Field(..., description="Cryptocurrency: btc, eth, usdc, usdt")
    derivation_index: Optional[int] = Field(default=None, description="HD wallet derivation index")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class CryptoAddressResponse(BaseModel):
    id: str
    object: str = "crypto.address"
    account_id: Optional[str] = None
    cryptocurrency: str
    address: str
    derivation_path: Optional[str] = None
    derivation_index: Optional[int] = None
    public_key: Optional[str] = None
    status: str
    used_for_payment: Optional[str] = None
    last_used_at: Optional[int] = None
    total_received: Optional[Decimal] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ExchangeRateResponse(BaseModel):
    id: str
    object: str = "crypto.exchange_rate"
    cryptocurrency: str
    fiat_currency: str
    rate: Decimal
    inverse_rate: Optional[Decimal] = None
    timestamp: int
    source: str
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume_24h: Optional[Decimal] = None
    created: int


class ExchangeRatesListResponse(BaseModel):
    rates: List[ExchangeRateResponse]
    timestamp: int


class CryptoTransactionResponse(BaseModel):
    id: str
    object: str = "crypto.transaction"
    crypto_payment_id: Optional[str] = None
    transaction_hash: str
    from_address: Optional[str] = None
    to_address: str
    amount: Decimal
    cryptocurrency: str
    block_number: Optional[int] = None
    block_hash: Optional[str] = None
    confirmations: int
    status: str
    fee: Optional[Decimal] = None
    fee_currency: Optional[str] = None
    network_timestamp: Optional[int] = None
    processed_at: Optional[int] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class CryptoSettlementCreateRequest(BaseModel):
    crypto_payment_id: str = Field(..., description="Crypto payment ID to settle")
    settlement_currency: Optional[str] = Field(default=None, description="Override settlement currency")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class CryptoSettlementResponse(BaseModel):
    id: str
    object: str = "crypto.settlement"
    crypto_payment_id: Optional[str] = None
    account_id: Optional[str] = None
    settled_amount: int
    settlement_currency: str
    settlement_rate: Decimal
    original_crypto_amount: Decimal
    original_crypto_currency: str
    fee_amount: int
    fee_currency: str
    settled_at: int
    settlement_method: str
    reference_id: Optional[str] = None
    status: str
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class WalletConfigResponse(BaseModel):
    id: str
    object: str = "crypto.wallet_config"
    account_id: Optional[str] = None
    supported_cryptos: Optional[List[str]] = None
    auto_convert: bool
    settlement_schedule: str
    settlement_currency: str
    min_settlement_amount: int
    confirmation_threshold: int
    webhooks_enabled: bool
    webhook_url: Optional[str] = None
    last_settlement_at: Optional[int] = None
    next_scheduled_settlement: Optional[int] = None
    total_settled: int
    total_crypto_received: Optional[Decimal] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class WalletConfigUpdateRequest(BaseModel):
    supported_cryptos: Optional[List[str]] = Field(default=None, description="List of supported cryptocurrencies")
    auto_convert: Optional[bool] = Field(default=None, description="Enable auto convert to fiat")
    settlement_schedule: Optional[str] = Field(default=None, description="Settlement schedule: immediate, hourly, daily, weekly, manual")
    settlement_currency: Optional[str] = Field(default=None, description="Settlement currency")
    min_settlement_amount: Optional[int] = Field(default=None, description="Minimum settlement amount in cents")
    confirmation_threshold: Optional[int] = Field(default=None, description="Required block confirmations")
    webhooks_enabled: Optional[bool] = Field(default=None, description="Enable webhooks")
    webhook_url: Optional[str] = Field(default=None, description="Webhook URL")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


def _get_account_id(request: Request) -> Optional[str]:
    return getattr(request.state, "account_id", None)


def _generate_id(prefix: str) -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{prefix}_{random_part}"


def _get_timestamp() -> int:
    import time
    return int(time.time())


def _validate_cryptocurrency(crypto: str) -> str:
    valid_cryptos = ["btc", "eth", "usdc", "usdt"]
    crypto_lower = crypto.lower()
    if crypto_lower not in valid_cryptos:
        raise ValidationError(f"Invalid cryptocurrency. Supported: {', '.join(valid_cryptos)}", param="cryptocurrency")
    return crypto_lower


@router.post("/payments", response_model=CryptoPaymentResponse, status_code=201)
async def create_crypto_payment(
    request: Request,
    data: CryptoPaymentCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.crypto import (
        CryptoPayment, CryptoPaymentStatus, Cryptocurrency
    )
    from payment_platform.backend.application.services.crypto_service import CryptoPaymentService
    
    account_id = _get_account_id(request)
    cryptocurrency = _validate_cryptocurrency(data.cryptocurrency)
    
    service = CryptoPaymentService(session)
    payment = await service.create(
        account_id=account_id,
        payment_intent_id=data.payment_intent_id,
        cryptocurrency=cryptocurrency,
        amount_fiat=data.amount_fiat,
        settlement_currency=data.settlement_currency.lower(),
        expiration_minutes=data.expiration_minutes,
        metadata=data.metadata,
    )
    
    return CryptoPaymentResponse(
        id=payment.id,
        payment_intent_id=payment.payment_intent_id,
        cryptocurrency=payment.cryptocurrency.value,
        amount_crypto=payment.amount_crypto,
        amount_fiat=payment.amount_fiat,
        exchange_rate=payment.exchange_rate,
        settlement_currency=payment.settlement_currency,
        status=payment.status.value,
        confirmation_blocks=payment.confirmation_blocks,
        required_confirmations=payment.required_confirmations,
        transaction_hash=payment.transaction_hash,
        from_address=payment.from_address,
        to_address=payment.to_address,
        expiration_time=payment.expiration_time,
        detected_at=payment.detected_at,
        confirmed_at=payment.confirmed_at,
        settled_at=payment.settled_at,
        failure_code=payment.failure_code,
        failure_message=payment.failure_message,
        account_id=payment.account_id,
        created=payment.created,
        livemode=payment.livemode,
        metadata=payment.metadata_,
    )


@router.get("/payments", response_model=PaginatedResponse[CryptoPaymentResponse])
async def list_crypto_payments(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    cryptocurrency: Optional[str] = None,
    status: Optional[str] = None,
    account_id: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import CryptoPayment
    
    query = select(CryptoPayment)
    
    req_account_id = _get_account_id(request)
    if req_account_id:
        query = query.where(CryptoPayment.account_id == req_account_id)
    elif account_id:
        query = query.where(CryptoPayment.account_id == account_id)
    
    if cryptocurrency:
        query = query.where(CryptoPayment.cryptocurrency == cryptocurrency.lower())
    if status:
        query = query.where(CryptoPayment.status == status)
    if starting_after:
        query = query.where(CryptoPayment.id > starting_after)
    
    query = query.order_by(CryptoPayment.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    payments = list(result.scalars().all())
    
    has_more = len(payments) > limit
    if has_more:
        payments = payments[:limit]
    
    data = [
        CryptoPaymentResponse(
            id=p.id,
            payment_intent_id=p.payment_intent_id,
            cryptocurrency=p.cryptocurrency.value,
            amount_crypto=p.amount_crypto,
            amount_fiat=p.amount_fiat,
            exchange_rate=p.exchange_rate,
            settlement_currency=p.settlement_currency,
            status=p.status.value,
            confirmation_blocks=p.confirmation_blocks,
            required_confirmations=p.required_confirmations,
            transaction_hash=p.transaction_hash,
            from_address=p.from_address,
            to_address=p.to_address,
            expiration_time=p.expiration_time,
            detected_at=p.detected_at,
            confirmed_at=p.confirmed_at,
            settled_at=p.settled_at,
            failure_code=p.failure_code,
            failure_message=p.failure_message,
            account_id=p.account_id,
            created=p.created,
            livemode=p.livemode,
            metadata=p.metadata_,
        )
        for p in payments
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/payments/{payment_id}", response_model=CryptoPaymentResponse)
async def get_crypto_payment(
    payment_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import CryptoPayment
    
    query = select(CryptoPayment).where(CryptoPayment.id == payment_id)
    result = await session.execute(query)
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Crypto payment {payment_id} not found")
    
    return CryptoPaymentResponse(
        id=payment.id,
        payment_intent_id=payment.payment_intent_id,
        cryptocurrency=payment.cryptocurrency.value,
        amount_crypto=payment.amount_crypto,
        amount_fiat=payment.amount_fiat,
        exchange_rate=payment.exchange_rate,
        settlement_currency=payment.settlement_currency,
        status=payment.status.value,
        confirmation_blocks=payment.confirmation_blocks,
        required_confirmations=payment.required_confirmations,
        transaction_hash=payment.transaction_hash,
        from_address=payment.from_address,
        to_address=payment.to_address,
        expiration_time=payment.expiration_time,
        detected_at=payment.detected_at,
        confirmed_at=payment.confirmed_at,
        settled_at=payment.settled_at,
        failure_code=payment.failure_code,
        failure_message=payment.failure_message,
        account_id=payment.account_id,
        created=payment.created,
        livemode=payment.livemode,
        metadata=payment.metadata_,
    )


@router.post("/addresses", response_model=CryptoAddressResponse, status_code=201)
async def generate_deposit_address(
    request: Request,
    data: CryptoAddressCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.crypto_service import AddressService
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    cryptocurrency = _validate_cryptocurrency(data.cryptocurrency)
    
    service = AddressService(session)
    address = await service.generate(
        account_id=account_id,
        cryptocurrency=cryptocurrency,
        derivation_index=data.derivation_index,
        metadata=data.metadata,
    )
    
    return CryptoAddressResponse(
        id=address.id,
        account_id=address.account_id,
        cryptocurrency=address.cryptocurrency.value,
        address=address.address,
        derivation_path=address.derivation_path,
        derivation_index=address.derivation_index,
        public_key=address.public_key,
        status=address.status.value,
        used_for_payment=address.used_for_payment,
        last_used_at=address.last_used_at,
        total_received=address.total_received,
        created=address.created,
        livemode=address.livemode,
        metadata=address.metadata_,
    )


@router.get("/addresses", response_model=PaginatedResponse[CryptoAddressResponse])
async def list_addresses(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    cryptocurrency: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import CryptoAddress
    
    query = select(CryptoAddress)
    
    account_id = _get_account_id(request)
    if account_id:
        query = query.where(CryptoAddress.account_id == account_id)
    
    if cryptocurrency:
        query = query.where(CryptoAddress.cryptocurrency == cryptocurrency.lower())
    if status:
        query = query.where(CryptoAddress.status == status)
    if starting_after:
        query = query.where(CryptoAddress.id > starting_after)
    
    query = query.order_by(CryptoAddress.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    addresses = list(result.scalars().all())
    
    has_more = len(addresses) > limit
    if has_more:
        addresses = addresses[:limit]
    
    data = [
        CryptoAddressResponse(
            id=a.id,
            account_id=a.account_id,
            cryptocurrency=a.cryptocurrency.value,
            address=a.address,
            derivation_path=a.derivation_path,
            derivation_index=a.derivation_index,
            public_key=a.public_key,
            status=a.status.value,
            used_for_payment=a.used_for_payment,
            last_used_at=a.last_used_at,
            total_received=a.total_received,
            created=a.created,
            livemode=a.livemode,
            metadata=a.metadata_,
        )
        for a in addresses
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/exchange_rates", response_model=ExchangeRatesListResponse)
async def get_exchange_rates(
    request: Request,
    cryptocurrency: Optional[str] = None,
    fiat_currency: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import CryptoExchangeRate, Cryptocurrency
    from payment_platform.backend.application.services.crypto_service import ExchangeRateService
    
    service = ExchangeRateService(session)
    rates = await service.fetch_rates(cryptocurrency, fiat_currency)
    
    rate_responses = [
        ExchangeRateResponse(
            id=r.id,
            cryptocurrency=r.cryptocurrency.value,
            fiat_currency=r.fiat_currency,
            rate=r.rate,
            inverse_rate=r.inverse_rate,
            timestamp=r.timestamp,
            source=r.source.value,
            bid=r.bid,
            ask=r.ask,
            volume_24h=r.volume_24h,
            created=r.created,
        )
        for r in rates
    ]
    
    return ExchangeRatesListResponse(
        rates=rate_responses,
        timestamp=_get_timestamp(),
    )


@router.get("/transactions", response_model=PaginatedResponse[CryptoTransactionResponse])
async def list_transactions(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    cryptocurrency: Optional[str] = None,
    status: Optional[str] = None,
    crypto_payment_id: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import CryptoTransaction
    
    query = select(CryptoTransaction)
    
    if cryptocurrency:
        query = query.where(CryptoTransaction.cryptocurrency == cryptocurrency.lower())
    if status:
        query = query.where(CryptoTransaction.status == status)
    if crypto_payment_id:
        query = query.where(CryptoTransaction.crypto_payment_id == crypto_payment_id)
    if starting_after:
        query = query.where(CryptoTransaction.id > starting_after)
    
    query = query.order_by(CryptoTransaction.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    transactions = list(result.scalars().all())
    
    has_more = len(transactions) > limit
    if has_more:
        transactions = transactions[:limit]
    
    data = [
        CryptoTransactionResponse(
            id=t.id,
            crypto_payment_id=t.crypto_payment_id,
            transaction_hash=t.transaction_hash,
            from_address=t.from_address,
            to_address=t.to_address,
            amount=t.amount,
            cryptocurrency=t.cryptocurrency.value,
            block_number=t.block_number,
            block_hash=t.block_hash,
            confirmations=t.confirmations,
            status=t.status.value,
            fee=t.fee,
            fee_currency=t.fee_currency,
            network_timestamp=t.network_timestamp,
            processed_at=t.processed_at,
            created=t.created,
            livemode=t.livemode,
            metadata=t.metadata_,
        )
        for t in transactions
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/settlements", response_model=CryptoSettlementResponse, status_code=201)
async def trigger_manual_settlement(
    request: Request,
    data: CryptoSettlementCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.crypto_service import SettlementService
    
    account_id = _get_account_id(request)
    
    service = SettlementService(session)
    settlement = await service.manual_settlement(
        crypto_payment_id=data.crypto_payment_id,
        settlement_currency=data.settlement_currency,
        metadata=data.metadata,
    )
    
    return CryptoSettlementResponse(
        id=settlement.id,
        crypto_payment_id=settlement.crypto_payment_id,
        account_id=settlement.account_id,
        settled_amount=settlement.settled_amount,
        settlement_currency=settlement.settlement_currency,
        settlement_rate=settlement.settlement_rate,
        original_crypto_amount=settlement.original_crypto_amount,
        original_crypto_currency=settlement.original_crypto_currency,
        fee_amount=settlement.fee_amount,
        fee_currency=settlement.fee_currency,
        settled_at=settlement.settled_at,
        settlement_method=settlement.settlement_method,
        reference_id=settlement.reference_id,
        status=settlement.status,
        created=settlement.created,
        livemode=settlement.livemode,
        metadata=settlement.metadata_,
    )


@router.get("/settlements", response_model=PaginatedResponse[CryptoSettlementResponse])
async def list_settlements(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    account_id: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import CryptoSettlement
    
    query = select(CryptoSettlement)
    
    req_account_id = _get_account_id(request)
    if req_account_id:
        query = query.where(CryptoSettlement.account_id == req_account_id)
    elif account_id:
        query = query.where(CryptoSettlement.account_id == account_id)
    
    if starting_after:
        query = query.where(CryptoSettlement.id > starting_after)
    
    query = query.order_by(CryptoSettlement.settled_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    settlements = list(result.scalars().all())
    
    has_more = len(settlements) > limit
    if has_more:
        settlements = settlements[:limit]
    
    data = [
        CryptoSettlementResponse(
            id=s.id,
            crypto_payment_id=s.crypto_payment_id,
            account_id=s.account_id,
            settled_amount=s.settled_amount,
            settlement_currency=s.settlement_currency,
            settlement_rate=s.settlement_rate,
            original_crypto_amount=s.original_crypto_amount,
            original_crypto_currency=s.original_crypto_currency,
            fee_amount=s.fee_amount,
            fee_currency=s.fee_currency,
            settled_at=s.settled_at,
            settlement_method=s.settlement_method,
            reference_id=s.reference_id,
            status=s.status,
            created=s.created,
            livemode=s.livemode,
            metadata=s.metadata_,
        )
        for s in settlements
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/wallet_config", response_model=WalletConfigResponse)
async def get_wallet_config(
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import WalletConfig
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    query = select(WalletConfig).where(WalletConfig.account_id == account_id)
    result = await session.execute(query)
    config = result.scalar_one_or_none()
    
    if not config:
        config = WalletConfig(
            id=_generate_id("wc"),
            account_id=account_id,
            supported_cryptos=["btc", "eth", "usdc", "usdt"],
            auto_convert=True,
            settlement_schedule="immediate",
            settlement_currency="usd",
            min_settlement_amount=1000,
            confirmation_threshold=6,
            webhooks_enabled=True,
            total_settled=0,
            total_crypto_received=Decimal("0"),
            created=_get_timestamp(),
        )
        session.add(config)
        await session.flush()
    
    return WalletConfigResponse(
        id=config.id,
        account_id=config.account_id,
        supported_cryptos=config.supported_cryptos,
        auto_convert=config.auto_convert,
        settlement_schedule=config.settlement_schedule.value if hasattr(config.settlement_schedule, 'value') else config.settlement_schedule,
        settlement_currency=config.settlement_currency,
        min_settlement_amount=config.min_settlement_amount,
        confirmation_threshold=config.confirmation_threshold,
        webhooks_enabled=config.webhooks_enabled,
        webhook_url=config.webhook_url,
        last_settlement_at=config.last_settlement_at,
        next_scheduled_settlement=config.next_scheduled_settlement,
        total_settled=config.total_settled,
        total_crypto_received=config.total_crypto_received,
        created=config.created,
        livemode=config.livemode,
        metadata=config.metadata_,
    )


@router.put("/wallet_config", response_model=WalletConfigResponse)
async def update_wallet_config(
    request: Request,
    data: WalletConfigUpdateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.crypto import WalletConfig, SettlementSchedule
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    query = select(WalletConfig).where(WalletConfig.account_id == account_id)
    result = await session.execute(query)
    config = result.scalar_one_or_none()
    
    if not config:
        config = WalletConfig(
            id=_generate_id("wc"),
            account_id=account_id,
            supported_cryptos=["btc", "eth", "usdc", "usdt"],
            auto_convert=True,
            settlement_schedule=SettlementSchedule.IMMEDIATE,
            settlement_currency="usd",
            min_settlement_amount=1000,
            confirmation_threshold=6,
            webhooks_enabled=True,
            total_settled=0,
            total_crypto_received=Decimal("0"),
            created=_get_timestamp(),
        )
        session.add(config)
    
    if data.supported_cryptos is not None:
        for crypto in data.supported_cryptos:
            _validate_cryptocurrency(crypto)
        config.supported_cryptos = data.supported_cryptos
    
    if data.auto_convert is not None:
        config.auto_convert = data.auto_convert
    
    if data.settlement_schedule is not None:
        schedule_map = {
            "immediate": SettlementSchedule.IMMEDIATE,
            "hourly": SettlementSchedule.HOURLY,
            "daily": SettlementSchedule.DAILY,
            "weekly": SettlementSchedule.WEEKLY,
            "manual": SettlementSchedule.MANUAL,
        }
        if data.settlement_schedule.lower() not in schedule_map:
            raise ValidationError(
                f"Invalid settlement schedule. Supported: {', '.join(schedule_map.keys())}",
                param="settlement_schedule",
            )
        config.settlement_schedule = schedule_map[data.settlement_schedule.lower()]
    
    if data.settlement_currency is not None:
        config.settlement_currency = data.settlement_currency.lower()
    
    if data.min_settlement_amount is not None:
        config.min_settlement_amount = data.min_settlement_amount
    
    if data.confirmation_threshold is not None:
        if data.confirmation_threshold < 1:
            raise ValidationError("Confirmation threshold must be at least 1", param="confirmation_threshold")
        config.confirmation_threshold = data.confirmation_threshold
    
    if data.webhooks_enabled is not None:
        config.webhooks_enabled = data.webhooks_enabled
    
    if data.webhook_url is not None:
        config.webhook_url = data.webhook_url
    
    if data.metadata is not None:
        config.metadata_ = data.metadata
    
    await session.flush()
    
    return WalletConfigResponse(
        id=config.id,
        account_id=config.account_id,
        supported_cryptos=config.supported_cryptos,
        auto_convert=config.auto_convert,
        settlement_schedule=config.settlement_schedule.value,
        settlement_currency=config.settlement_currency,
        min_settlement_amount=config.min_settlement_amount,
        confirmation_threshold=config.confirmation_threshold,
        webhooks_enabled=config.webhooks_enabled,
        webhook_url=config.webhook_url,
        last_settlement_at=config.last_settlement_at,
        next_scheduled_settlement=config.next_scheduled_settlement,
        total_settled=config.total_settled,
        total_crypto_received=config.total_crypto_received,
        created=config.created,
        livemode=config.livemode,
        metadata=config.metadata_,
    )
