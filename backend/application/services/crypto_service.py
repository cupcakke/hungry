from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import secrets
import asyncio
import json

from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.crypto import (
    CryptoPayment,
    CryptoAddress,
    CryptoTransaction,
    CryptoExchangeRate,
    CryptoSettlement,
    WalletConfig,
    Cryptocurrency,
    CryptoPaymentStatus,
    CryptoAddressStatus,
    CryptoTransactionStatus,
    SettlementSchedule,
    ExchangeRateSource,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    CryptoError,
)
from payment_platform.shared.utils.identifiers import generate_id


CONFIRMATION_THRESHOLDS = {
    Cryptocurrency.BTC: 6,
    Cryptocurrency.ETH: 12,
    Cryptocurrency.USDC: 12,
    Cryptocurrency.USDT: 12,
}

HD_WALLET_MASTER_SEED = "default_master_seed_for_hd_wallet_derivation"


@dataclass
class PaymentConversionResult:
    crypto_amount: Decimal
    exchange_rate: Decimal
    rate_source: str


@dataclass
class AddressInfo:
    address: str
    derivation_path: str
    public_key: str


@dataclass
class BlockchainTransactionInfo:
    transaction_hash: str
    from_address: str
    to_address: str
    amount: Decimal
    block_number: int
    confirmations: int
    status: str
    fee: Decimal


class CryptoPaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.address_service = None
        self.rate_service = None

    async def create(
        self,
        account_id: Optional[str],
        payment_intent_id: Optional[str],
        cryptocurrency: str,
        amount_fiat: int,
        settlement_currency: str,
        expiration_minutes: Optional[int] = 60,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CryptoPayment:
        crypto_enum = self._parse_cryptocurrency(cryptocurrency)
        
        if self.rate_service is None:
            self.rate_service = ExchangeRateService(self.session)
        
        conversion = await self.rate_service.calculate_conversion(
            crypto_enum, amount_fiat, settlement_currency
        )
        
        if self.address_service is None:
            self.address_service = AddressService(self.session)
        
        address = await self.address_service.get_or_create_address(
            account_id=account_id,
            cryptocurrency=crypto_enum,
        )
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        expiration_time = timestamp + (expiration_minutes * 60) if expiration_minutes else None
        
        confirmation_threshold = CONFIRMATION_THRESHOLDS.get(crypto_enum, 6)
        
        payment = CryptoPayment(
            id=self._generate_id("cp"),
            payment_intent_id=payment_intent_id,
            cryptocurrency=crypto_enum,
            amount_crypto=conversion.crypto_amount,
            amount_fiat=amount_fiat,
            exchange_rate=conversion.exchange_rate,
            settlement_currency=settlement_currency.lower(),
            status=CryptoPaymentStatus.WAITING_PAYMENT,
            confirmation_blocks=0,
            required_confirmations=confirmation_threshold,
            to_address=address.address,
            expiration_time=expiration_time,
            account_id=account_id,
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(payment)
        await self.session.flush()
        
        return payment

    async def track(self, payment_id: str) -> Optional[CryptoPayment]:
        query = select(CryptoPayment).where(CryptoPayment.id == payment_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def confirm(
        self,
        payment_id: str,
        transaction_hash: str,
        confirmation_blocks: int,
    ) -> CryptoPayment:
        payment = await self.track(payment_id)
        if not payment:
            raise NotFoundError(f"Crypto payment {payment_id} not found")
        
        if payment.status in [
            CryptoPaymentStatus.COMPLETED,
            CryptoPaymentStatus.FAILED,
            CryptoPaymentStatus.EXPIRED,
            CryptoPaymentStatus.CANCELED,
        ]:
            raise CryptoError(
                f"Payment {payment_id} is in terminal state: {payment.status.value}",
            )
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        if payment.status == CryptoPaymentStatus.WAITING_PAYMENT:
            payment.status = CryptoPaymentStatus.PAYMENT_DETECTED
            payment.transaction_hash = transaction_hash
            payment.detected_at = timestamp
        
        payment.confirmation_blocks = confirmation_blocks
        
        if confirmation_blocks >= payment.required_confirmations:
            payment.status = CryptoPaymentStatus.CONFIRMED
            payment.confirmed_at = timestamp
        
        await self.session.flush()
        return payment

    async def get_payment(self, payment_id: str) -> Optional[CryptoPayment]:
        return await self.track(payment_id)

    async def list_payments(
        self,
        account_id: Optional[str] = None,
        cryptocurrency: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[CryptoPayment]:
        query = select(CryptoPayment)
        
        if account_id:
            query = query.where(CryptoPayment.account_id == account_id)
        if cryptocurrency:
            query = query.where(CryptoPayment.cryptocurrency == cryptocurrency.lower())
        if status:
            query = query.where(CryptoPayment.status == status)
        
        query = query.order_by(CryptoPayment.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def expire_payment(self, payment_id: str) -> CryptoPayment:
        payment = await self.track(payment_id)
        if not payment:
            raise NotFoundError(f"Crypto payment {payment_id} not found")
        
        if payment.status not in [CryptoPaymentStatus.WAITING_PAYMENT, CryptoPaymentStatus.PENDING]:
            raise CryptoError(f"Payment {payment_id} cannot be expired in current state")
        
        payment.status = CryptoPaymentStatus.EXPIRED
        await self.session.flush()
        return payment

    async def cancel_payment(self, payment_id: str) -> CryptoPayment:
        payment = await self.track(payment_id)
        if not payment:
            raise NotFoundError(f"Crypto payment {payment_id} not found")
        
        if payment.status not in [CryptoPaymentStatus.WAITING_PAYMENT, CryptoPaymentStatus.PENDING]:
            raise CryptoError(f"Payment {payment_id} cannot be canceled in current state")
        
        payment.status = CryptoPaymentStatus.CANCELED
        await self.session.flush()
        return payment

    async def fail_payment(
        self,
        payment_id: str,
        failure_code: str,
        failure_message: str,
    ) -> CryptoPayment:
        payment = await self.track(payment_id)
        if not payment:
            raise NotFoundError(f"Crypto payment {payment_id} not found")
        
        payment.status = CryptoPaymentStatus.FAILED
        payment.failure_code = failure_code
        payment.failure_message = failure_message
        await self.session.flush()
        return payment

    def _parse_cryptocurrency(self, crypto: str) -> Cryptocurrency:
        crypto_map = {
            "btc": Cryptocurrency.BTC,
            "eth": Cryptocurrency.ETH,
            "usdc": Cryptocurrency.USDC,
            "usdt": Cryptocurrency.USDT,
        }
        crypto_lower = crypto.lower()
        if crypto_lower not in crypto_map:
            raise ValidationError(f"Invalid cryptocurrency: {crypto}", param="cryptocurrency")
        return crypto_map[crypto_lower]

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class AddressService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate(
        self,
        account_id: str,
        cryptocurrency: str,
        derivation_index: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CryptoAddress:
        crypto_enum = self._parse_cryptocurrency(cryptocurrency)
        
        if derivation_index is None:
            derivation_index = await self._get_next_derivation_index(account_id, crypto_enum)
        
        address_info = self._generate_hd_address(crypto_enum, derivation_index)
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        address = CryptoAddress(
            id=self._generate_id("ca"),
            account_id=account_id,
            cryptocurrency=crypto_enum,
            address=address_info.address,
            derivation_path=address_info.derivation_path,
            derivation_index=derivation_index,
            public_key=address_info.public_key,
            status=CryptoAddressStatus.ACTIVE,
            total_received=Decimal("0"),
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(address)
        await self.session.flush()
        
        return address

    async def validate(
        self,
        address: str,
        cryptocurrency: str,
    ) -> bool:
        crypto_enum = self._parse_cryptocurrency(cryptocurrency)
        
        if crypto_enum == Cryptocurrency.BTC:
            return self._validate_btc_address(address)
        elif crypto_enum == Cryptocurrency.ETH:
            return self._validate_eth_address(address)
        elif crypto_enum in [Cryptocurrency.USDC, Cryptocurrency.USDT]:
            return self._validate_eth_address(address)
        
        return False

    async def monitor(self, address_id: str) -> Dict[str, Any]:
        address = await self.get_address(address_id)
        if not address:
            raise NotFoundError(f"Address {address_id} not found")
        
        pending_transactions = await self._get_pending_transactions_for_address(address.address)
        
        return {
            "address_id": address_id,
            "address": address.address,
            "cryptocurrency": address.cryptocurrency.value,
            "status": address.status.value,
            "pending_transactions": pending_transactions,
            "total_received": str(address.total_received),
            "last_checked": int(datetime.now(timezone.utc).timestamp()),
        }

    async def get_address(self, address_id: str) -> Optional[CryptoAddress]:
        query = select(CryptoAddress).where(CryptoAddress.id == address_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_or_create_address(
        self,
        account_id: Optional[str],
        cryptocurrency: Cryptocurrency,
    ) -> CryptoAddress:
        if account_id:
            query = select(CryptoAddress).where(
                and_(
                    CryptoAddress.account_id == account_id,
                    CryptoAddress.cryptocurrency == cryptocurrency,
                    CryptoAddress.status == CryptoAddressStatus.ACTIVE,
                    CryptoAddress.used_for_payment.is_(None),
                )
            ).limit(1)
            
            result = await self.session.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                return existing
        
        return await self.generate(
            account_id=account_id or "default",
            cryptocurrency=cryptocurrency.value,
        )

    async def list_addresses(
        self,
        account_id: Optional[str] = None,
        cryptocurrency: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[CryptoAddress]:
        query = select(CryptoAddress)
        
        if account_id:
            query = query.where(CryptoAddress.account_id == account_id)
        if cryptocurrency:
            query = query.where(CryptoAddress.cryptocurrency == cryptocurrency.lower())
        if status:
            query = query.where(CryptoAddress.status == status)
        
        query = query.order_by(CryptoAddress.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def archive_address(self, address_id: str) -> CryptoAddress:
        address = await self.get_address(address_id)
        if not address:
            raise NotFoundError(f"Address {address_id} not found")
        
        address.status = CryptoAddressStatus.ARCHIVED
        await self.session.flush()
        return address

    def _generate_hd_address(self, cryptocurrency: Cryptocurrency, index: int) -> AddressInfo:
        seed = hashlib.sha256(f"{HD_WALLET_MASTER_SEED}_{cryptocurrency.value}_{index}".encode()).hexdigest()
        
        if cryptocurrency == Cryptocurrency.BTC:
            address = self._generate_btc_address_from_seed(seed)
            derivation_path = f"m/44'/0'/{index}'/0/0"
        else:
            address = self._generate_eth_address_from_seed(seed)
            derivation_path = f"m/44'/60'/{index}'/0/0"
        
        public_key = hashlib.sha256(seed.encode()).hexdigest()[:64]
        
        return AddressInfo(
            address=address,
            derivation_path=derivation_path,
            public_key=public_key,
        )

    def _generate_btc_address_from_seed(self, seed: str) -> str:
        hash_bytes = hashlib.sha256(seed.encode()).digest()
        address_hash = hashlib.new('ripemd160', hash_bytes).digest()
        versioned = bytes([0x00]) + address_hash
        checksum = hashlib.sha256(hashlib.sha256(versioned).digest()).digest()[:4]
        address_bytes = versioned + checksum
        import base58
        return base58.b58encode(address_bytes).decode()

    def _generate_eth_address_from_seed(self, seed: str) -> str:
        hash_bytes = hashlib.sha256(seed.encode()).digest()
        return "0x" + hash_bytes[:20].hex()

    def _validate_btc_address(self, address: str) -> bool:
        if address.startswith(("1", "3", "bc1")):
            return len(address) >= 26 and len(address) <= 62
        return False

    def _validate_eth_address(self, address: str) -> bool:
        if address.startswith("0x") and len(address) == 42:
            try:
                int(address[2:], 16)
                return True
            except ValueError:
                return False
        return False

    async def _get_next_derivation_index(self, account_id: str, cryptocurrency: Cryptocurrency) -> int:
        query = select(func.max(CryptoAddress.derivation_index)).where(
            and_(
                CryptoAddress.account_id == account_id,
                CryptoAddress.cryptocurrency == cryptocurrency,
            )
        )
        result = await self.session.execute(query)
        max_index = result.scalar()
        return (max_index or 0) + 1

    async def _get_pending_transactions_for_address(self, address: str) -> List[Dict[str, Any]]:
        query = select(CryptoTransaction).where(
            and_(
                CryptoTransaction.to_address == address,
                CryptoTransaction.status.in_([
                    CryptoTransactionStatus.PENDING,
                    CryptoTransactionStatus.CONFIRMING,
                ]),
            )
        )
        result = await self.session.execute(query)
        transactions = result.scalars().all()
        
        return [
            {
                "transaction_hash": tx.transaction_hash,
                "amount": str(tx.amount),
                "confirmations": tx.confirmations,
                "status": tx.status.value,
            }
            for tx in transactions
        ]

    def _parse_cryptocurrency(self, crypto: str) -> Cryptocurrency:
        crypto_map = {
            "btc": Cryptocurrency.BTC,
            "eth": Cryptocurrency.ETH,
            "usdc": Cryptocurrency.USDC,
            "usdt": Cryptocurrency.USDT,
        }
        crypto_lower = crypto.lower()
        if crypto_lower not in crypto_map:
            raise ValidationError(f"Invalid cryptocurrency: {crypto}", param="cryptocurrency")
        return crypto_map[crypto_lower]

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ExchangeRateService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._rate_cache: Dict[str, Tuple[Decimal, int]] = {}
        self._cache_ttl = 60

    async def fetch_rates(
        self,
        cryptocurrency: Optional[str] = None,
        fiat_currency: Optional[str] = None,
    ) -> List[CryptoExchangeRate]:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        rates = []
        
        cryptos = [Cryptocurrency.BTC, Cryptocurrency.ETH, Cryptocurrency.USDC, Cryptocurrency.USDT]
        fiats = ["usd", "eur", "gbp"]
        
        if cryptocurrency:
            cryptos = [self._parse_cryptocurrency(cryptocurrency)]
        if fiat_currency:
            fiats = [fiat_currency.lower()]
        
        for crypto in cryptos:
            for fiat in fiats:
                rate_data = await self._fetch_rate_from_provider(crypto, fiat)
                
                exchange_rate = CryptoExchangeRate(
                    id=self._generate_id("cer"),
                    cryptocurrency=crypto,
                    fiat_currency=fiat,
                    rate=rate_data["rate"],
                    inverse_rate=Decimal("1") / rate_data["rate"] if rate_data["rate"] > 0 else None,
                    timestamp=timestamp,
                    source=rate_data["source"],
                    bid=rate_data.get("bid"),
                    ask=rate_data.get("ask"),
                    volume_24h=rate_data.get("volume_24h"),
                    created=timestamp,
                )
                
                self.session.add(exchange_rate)
                rates.append(exchange_rate)
        
        await self.session.flush()
        return rates

    async def calculate_conversion(
        self,
        cryptocurrency: Cryptocurrency,
        amount_fiat: int,
        fiat_currency: str,
    ) -> PaymentConversionResult:
        rate = await self._get_cached_rate(cryptocurrency, fiat_currency)
        
        if rate is None:
            rate_data = await self._fetch_rate_from_provider(cryptocurrency, fiat_currency)
            rate = rate_data["rate"]
            source = rate_data["source"]
        else:
            source = "cache"
        
        fiat_amount_decimal = Decimal(amount_fiat) / Decimal(100)
        crypto_amount = fiat_amount_decimal / rate
        
        return PaymentConversionResult(
            crypto_amount=crypto_amount,
            exchange_rate=rate,
            rate_source=source,
        )

    async def get_current_rate(
        self,
        cryptocurrency: Cryptocurrency,
        fiat_currency: str,
    ) -> Optional[CryptoExchangeRate]:
        query = select(CryptoExchangeRate).where(
            and_(
                CryptoExchangeRate.cryptocurrency == cryptocurrency,
                CryptoExchangeRate.fiat_currency == fiat_currency.lower(),
            )
        ).order_by(CryptoExchangeRate.timestamp.desc()).limit(1)
        
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _get_cached_rate(
        self,
        cryptocurrency: Cryptocurrency,
        fiat_currency: str,
    ) -> Optional[Decimal]:
        cache_key = f"{cryptocurrency.value}_{fiat_currency.lower()}"
        
        if cache_key in self._rate_cache:
            rate, timestamp = self._rate_cache[cache_key]
            current_time = int(datetime.now(timezone.utc).timestamp())
            
            if current_time - timestamp < self._cache_ttl:
                return rate
        
        return None

    async def _fetch_rate_from_provider(
        self,
        cryptocurrency: Cryptocurrency,
        fiat_currency: str,
    ) -> Dict[str, Any]:
        await asyncio.sleep(0.01)
        
        simulated_rates = {
            (Cryptocurrency.BTC, "usd"): Decimal("45000.00"),
            (Cryptocurrency.BTC, "eur"): Decimal("42000.00"),
            (Cryptocurrency.BTC, "gbp"): Decimal("36000.00"),
            (Cryptocurrency.ETH, "usd"): Decimal("3000.00"),
            (Cryptocurrency.ETH, "eur"): Decimal("2800.00"),
            (Cryptocurrency.ETH, "gbp"): Decimal("2400.00"),
            (Cryptocurrency.USDC, "usd"): Decimal("1.00"),
            (Cryptocurrency.USDC, "eur"): Decimal("0.93"),
            (Cryptocurrency.USDC, "gbp"): Decimal("0.80"),
            (Cryptocurrency.USDT, "usd"): Decimal("1.00"),
            (Cryptocurrency.USDT, "eur"): Decimal("0.93"),
            (Cryptocurrency.USDT, "gbp"): Decimal("0.80"),
        }
        
        rate = simulated_rates.get((cryptocurrency, fiat_currency.lower()), Decimal("1.00"))
        
        cache_key = f"{cryptocurrency.value}_{fiat_currency.lower()}"
        self._rate_cache[cache_key] = (rate, int(datetime.now(timezone.utc).timestamp()))
        
        return {
            "rate": rate,
            "source": ExchangeRateSource.COINBASE,
            "bid": rate * Decimal("0.999"),
            "ask": rate * Decimal("1.001"),
            "volume_24h": Decimal("1000000000.00"),
        }

    def _parse_cryptocurrency(self, crypto: str) -> Cryptocurrency:
        crypto_map = {
            "btc": Cryptocurrency.BTC,
            "eth": Cryptocurrency.ETH,
            "usdc": Cryptocurrency.USDC,
            "usdt": Cryptocurrency.USDT,
        }
        crypto_lower = crypto.lower()
        if crypto_lower not in crypto_map:
            raise ValidationError(f"Invalid cryptocurrency: {crypto}", param="cryptocurrency")
        return crypto_map[crypto_lower]

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class SettlementService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.rate_service = ExchangeRateService(session)

    async def auto_convert(
        self,
        crypto_payment_id: str,
    ) -> Optional[CryptoSettlement]:
        query = select(CryptoPayment).where(CryptoPayment.id == crypto_payment_id)
        result = await self.session.execute(query)
        payment = result.scalar_one_or_none()
        
        if not payment:
            raise NotFoundError(f"Crypto payment {crypto_payment_id} not found")
        
        if payment.status != CryptoPaymentStatus.CONFIRMED:
            return None
        
        query = select(WalletConfig).where(WalletConfig.account_id == payment.account_id)
        config_result = await self.session.execute(query)
        config = config_result.scalar_one_or_none()
        
        if not config or not config.auto_convert:
            return None
        
        return await self._create_settlement(payment, "auto")

    async def manual_settlement(
        self,
        crypto_payment_id: str,
        settlement_currency: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CryptoSettlement:
        query = select(CryptoPayment).where(CryptoPayment.id == crypto_payment_id)
        result = await self.session.execute(query)
        payment = result.scalar_one_or_none()
        
        if not payment:
            raise NotFoundError(f"Crypto payment {crypto_payment_id} not found")
        
        if payment.status not in [CryptoPaymentStatus.CONFIRMED, CryptoPaymentStatus.SETTLING]:
            raise CryptoError(
                f"Payment {crypto_payment_id} is not ready for settlement. Current status: {payment.status.value}",
            )
        
        currency = settlement_currency or payment.settlement_currency
        
        return await self._create_settlement(payment, "manual", currency, metadata)

    async def process_scheduled_settlements(
        self,
        account_id: Optional[str] = None,
    ) -> List[CryptoSettlement]:
        query = select(WalletConfig)
        if account_id:
            query = query.where(WalletConfig.account_id == account_id)
        
        result = await self.session.execute(query)
        configs = result.scalars().all()
        
        settlements = []
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        for config in configs:
            if config.settlement_schedule == SettlementSchedule.MANUAL:
                continue
            
            if self._should_settle(config, timestamp):
                account_settlements = await self._settle_pending_payments(config)
                settlements.extend(account_settlements)
        
        return settlements

    async def list_settlements(
        self,
        account_id: Optional[str] = None,
        crypto_payment_id: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[CryptoSettlement]:
        query = select(CryptoSettlement)
        
        if account_id:
            query = query.where(CryptoSettlement.account_id == account_id)
        if crypto_payment_id:
            query = query.where(CryptoSettlement.crypto_payment_id == crypto_payment_id)
        
        query = query.order_by(CryptoSettlement.settled_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _create_settlement(
        self,
        payment: CryptoPayment,
        method: str,
        settlement_currency: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CryptoSettlement:
        currency = settlement_currency or payment.settlement_currency
        
        current_rate = await self.rate_service.get_current_rate(
            payment.cryptocurrency,
            currency,
        )
        
        if current_rate:
            settlement_rate = current_rate.rate
        else:
            settlement_rate = payment.exchange_rate
        
        crypto_amount = payment.amount_crypto
        settled_amount_decimal = crypto_amount * settlement_rate
        settled_amount = int(settled_amount_decimal * Decimal(100))
        
        fee_rate = Decimal("0.01")
        fee_amount = int(settled_amount * fee_rate)
        final_amount = settled_amount - fee_amount
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        settlement = CryptoSettlement(
            id=self._generate_id("cs"),
            crypto_payment_id=payment.id,
            account_id=payment.account_id,
            settled_amount=final_amount,
            settlement_currency=currency,
            settlement_rate=settlement_rate,
            original_crypto_amount=crypto_amount,
            original_crypto_currency=payment.cryptocurrency.value,
            fee_amount=fee_amount,
            fee_currency=currency,
            settled_at=timestamp,
            settlement_method=method,
            status="completed",
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(settlement)
        
        payment.status = CryptoPaymentStatus.SETTLED
        payment.settled_at = timestamp
        
        if payment.account_id:
            await self._update_wallet_config(payment.account_id, final_amount, crypto_amount)
        
        await self.session.flush()
        return settlement

    async def _settle_pending_payments(self, config: WalletConfig) -> List[CryptoSettlement]:
        query = select(CryptoPayment).where(
            and_(
                CryptoPayment.account_id == config.account_id,
                CryptoPayment.status == CryptoPaymentStatus.CONFIRMED,
            )
        )
        
        result = await self.session.execute(query)
        payments = result.scalars().all()
        
        settlements = []
        for payment in payments:
            if payment.amount_fiat >= config.min_settlement_amount:
                settlement = await self._create_settlement(payment, "scheduled")
                settlements.append(settlement)
        
        return settlements

    def _should_settle(self, config: WalletConfig, current_timestamp: int) -> bool:
        if config.last_settlement_at is None:
            return True
        
        time_since_last = current_timestamp - config.last_settlement_at
        
        if config.settlement_schedule == SettlementSchedule.IMMEDIATE:
            return True
        elif config.settlement_schedule == SettlementSchedule.HOURLY:
            return time_since_last >= 3600
        elif config.settlement_schedule == SettlementSchedule.DAILY:
            return time_since_last >= 86400
        elif config.settlement_schedule == SettlementSchedule.WEEKLY:
            return time_since_last >= 604800
        
        return False

    async def _update_wallet_config(
        self,
        account_id: str,
        settled_amount: int,
        crypto_amount: Decimal,
    ):
        query = select(WalletConfig).where(WalletConfig.account_id == account_id)
        result = await self.session.execute(query)
        config = result.scalar_one_or_none()
        
        if config:
            config.total_settled += settled_amount
            config.total_crypto_received += crypto_amount
            config.last_settlement_at = int(datetime.now(timezone.utc).timestamp())

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class BlockchainService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def monitor_confirmations(
        self,
        transaction_hash: str,
        cryptocurrency: str,
    ) -> Dict[str, Any]:
        crypto_enum = self._parse_cryptocurrency(cryptocurrency)
        
        tx_info = await self._get_transaction_from_blockchain(transaction_hash, crypto_enum)
        
        query = select(CryptoTransaction).where(
            and_(
                CryptoTransaction.transaction_hash == transaction_hash,
                CryptoTransaction.cryptocurrency == crypto_enum,
            )
        )
        result = await self.session.execute(query)
        db_tx = result.scalar_one_or_none()
        
        if db_tx:
            db_tx.confirmations = tx_info["confirmations"]
            db_tx.block_number = tx_info["block_number"]
            
            if tx_info["confirmations"] >= CONFIRMATION_THRESHOLDS.get(crypto_enum, 6):
                db_tx.status = CryptoTransactionStatus.CONFIRMED
            elif tx_info["confirmations"] > 0:
                db_tx.status = CryptoTransactionStatus.CONFIRMING
            
            await self.session.flush()
        
        return tx_info

    async def transaction_status(
        self,
        transaction_hash: str,
        cryptocurrency: str,
    ) -> Dict[str, Any]:
        crypto_enum = self._parse_cryptocurrency(cryptocurrency)
        return await self._get_transaction_from_blockchain(transaction_hash, crypto_enum)

    async def record_transaction(
        self,
        crypto_payment_id: str,
        transaction_hash: str,
        from_address: str,
        to_address: str,
        amount: Decimal,
        cryptocurrency: str,
        block_number: Optional[int] = None,
        fee: Optional[Decimal] = None,
    ) -> CryptoTransaction:
        crypto_enum = self._parse_cryptocurrency(cryptocurrency)
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        transaction = CryptoTransaction(
            id=self._generate_id("ctx"),
            crypto_payment_id=crypto_payment_id,
            transaction_hash=transaction_hash,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            cryptocurrency=crypto_enum,
            block_number=block_number,
            confirmations=0,
            status=CryptoTransactionStatus.PENDING,
            fee=fee,
            fee_currency=crypto_enum.value if crypto_enum in [Cryptocurrency.BTC, Cryptocurrency.ETH] else "eth",
            created=timestamp,
        )
        
        self.session.add(transaction)
        await self.session.flush()
        
        return transaction

    async def get_transactions_for_payment(
        self,
        crypto_payment_id: str,
    ) -> List[CryptoTransaction]:
        query = select(CryptoTransaction).where(
            CryptoTransaction.crypto_payment_id == crypto_payment_id
        ).order_by(CryptoTransaction.created_at.desc())
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def process_blockchain_webhook(
        self,
        webhook_data: Dict[str, Any],
        cryptocurrency: str,
    ) -> Dict[str, Any]:
        crypto_enum = self._parse_cryptocurrency(cryptocurrency)
        
        transaction_hash = webhook_data.get("hash") or webhook_data.get("tx_hash")
        if not transaction_hash:
            raise ValidationError("Missing transaction hash in webhook data")
        
        tx_info = await self._get_transaction_from_blockchain(transaction_hash, crypto_enum)
        
        query = select(CryptoTransaction).where(
            and_(
                CryptoTransaction.transaction_hash == transaction_hash,
                CryptoTransaction.cryptocurrency == crypto_enum,
            )
        )
        result = await self.session.execute(query)
        db_tx = result.scalar_one_or_none()
        
        processed_payments = []
        
        if db_tx:
            db_tx.confirmations = tx_info["confirmations"]
            db_tx.block_number = tx_info["block_number"]
            db_tx.status = CryptoTransactionStatus.CONFIRMING if tx_info["confirmations"] > 0 else CryptoTransactionStatus.PENDING
            
            if db_tx.crypto_payment_id:
                payment_service = CryptoPaymentService(self.session)
                try:
                    payment = await payment_service.confirm(
                        db_tx.crypto_payment_id,
                        transaction_hash,
                        tx_info["confirmations"],
                    )
                    processed_payments.append({
                        "payment_id": payment.id,
                        "status": payment.status.value,
                        "confirmations": tx_info["confirmations"],
                    })
                except Exception:
                    pass
            
            await self.session.flush()
        
        return {
            "transaction_hash": transaction_hash,
            "processed": db_tx is not None,
            "confirmations": tx_info["confirmations"],
            "processed_payments": processed_payments,
        }

    async def _get_transaction_from_blockchain(
        self,
        transaction_hash: str,
        cryptocurrency: Cryptocurrency,
    ) -> Dict[str, Any]:
        await asyncio.sleep(0.01)
        
        mock_confirmations = secrets.randbelow(20)
        
        return {
            "transaction_hash": transaction_hash,
            "from_address": "mock_from_address",
            "to_address": "mock_to_address",
            "amount": Decimal("0.1"),
            "block_number": secrets.randbelow(1000000),
            "confirmations": mock_confirmations,
            "status": "confirmed" if mock_confirmations >= CONFIRMATION_THRESHOLDS.get(cryptocurrency, 6) else "pending",
            "fee": Decimal("0.001"),
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
        }

    def _parse_cryptocurrency(self, crypto: str) -> Cryptocurrency:
        crypto_map = {
            "btc": Cryptocurrency.BTC,
            "eth": Cryptocurrency.ETH,
            "usdc": Cryptocurrency.USDC,
            "usdt": Cryptocurrency.USDT,
        }
        crypto_lower = crypto.lower()
        if crypto_lower not in crypto_map:
            raise ValidationError(f"Invalid cryptocurrency: {crypto}", param="cryptocurrency")
        return crypto_map[crypto_lower]

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class WebhookService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._webhook_signing_secret = "whsec_default_signing_secret"

    async def send_webhook(
        self,
        url: str,
        event_type: str,
        data: Dict[str, Any],
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        payload = {
            "id": self._generate_id("evt"),
            "object": "event",
            "type": event_type,
            "data": data,
            "created": timestamp,
            "livemode": False,
        }
        
        if account_id:
            payload["account"] = account_id
        
        signature = self._generate_signature(payload)
        
        webhook_log = {
            "id": payload["id"],
            "url": url,
            "event_type": event_type,
            "payload": payload,
            "signature": signature,
            "timestamp": timestamp,
            "status": "sent",
        }
        
        return webhook_log

    async def process_incoming_webhook(
        self,
        payload: bytes,
        signature: str,
        cryptocurrency: str,
    ) -> Dict[str, Any]:
        if not self._verify_signature(payload, signature):
            raise ValidationError("Invalid webhook signature")
        
        try:
            data = json.loads(payload.decode())
        except json.JSONDecodeError:
            raise ValidationError("Invalid JSON payload")
        
        blockchain_service = BlockchainService(self.session)
        
        return await blockchain_service.process_blockchain_webhook(data, cryptocurrency)

    async def notify_payment_detected(
        self,
        payment: CryptoPayment,
        transaction_hash: str,
    ) -> Dict[str, Any]:
        if not payment.account_id:
            return {"sent": False, "reason": "No account ID"}
        
        config = await self._get_wallet_config(payment.account_id)
        if not config or not config.webhooks_enabled or not config.webhook_url:
            return {"sent": False, "reason": "Webhooks not configured"}
        
        event_data = {
            "payment": {
                "id": payment.id,
                "cryptocurrency": payment.cryptocurrency.value,
                "amount_crypto": str(payment.amount_crypto),
                "amount_fiat": payment.amount_fiat,
                "status": payment.status.value,
                "transaction_hash": transaction_hash,
            }
        }
        
        return await self.send_webhook(
            url=config.webhook_url,
            event_type="crypto.payment.detected",
            data=event_data,
            account_id=payment.account_id,
        )

    async def notify_payment_confirmed(
        self,
        payment: CryptoPayment,
    ) -> Dict[str, Any]:
        if not payment.account_id:
            return {"sent": False, "reason": "No account ID"}
        
        config = await self._get_wallet_config(payment.account_id)
        if not config or not config.webhooks_enabled or not config.webhook_url:
            return {"sent": False, "reason": "Webhooks not configured"}
        
        event_data = {
            "payment": {
                "id": payment.id,
                "cryptocurrency": payment.cryptocurrency.value,
                "amount_crypto": str(payment.amount_crypto),
                "amount_fiat": payment.amount_fiat,
                "status": payment.status.value,
                "confirmed_at": payment.confirmed_at,
            }
        }
        
        return await self.send_webhook(
            url=config.webhook_url,
            event_type="crypto.payment.confirmed",
            data=event_data,
            account_id=payment.account_id,
        )

    async def notify_settlement_completed(
        self,
        settlement: CryptoSettlement,
    ) -> Dict[str, Any]:
        if not settlement.account_id:
            return {"sent": False, "reason": "No account ID"}
        
        config = await self._get_wallet_config(settlement.account_id)
        if not config or not config.webhooks_enabled or not config.webhook_url:
            return {"sent": False, "reason": "Webhooks not configured"}
        
        event_data = {
            "settlement": {
                "id": settlement.id,
                "settled_amount": settlement.settled_amount,
                "settlement_currency": settlement.settlement_currency,
                "original_crypto_amount": str(settlement.original_crypto_amount),
                "original_crypto_currency": settlement.original_crypto_currency,
                "settled_at": settlement.settled_at,
            }
        }
        
        return await self.send_webhook(
            url=config.webhook_url,
            event_type="crypto.settlement.completed",
            data=event_data,
            account_id=settlement.account_id,
        )

    async def _get_wallet_config(self, account_id: str) -> Optional[WalletConfig]:
        query = select(WalletConfig).where(WalletConfig.account_id == account_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def _generate_signature(self, payload: Dict[str, Any]) -> str:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        payload_str = json.dumps(payload, sort_keys=True)
        signed_payload = f"{timestamp}.{payload_str}"
        
        signature = hmac.new(
            self._webhook_signing_secret.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        
        return f"t={timestamp},v1={signature}"

    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        try:
            parts = {}
            for part in signature.split(","):
                key, value = part.split("=", 1)
                parts[key] = value
            
            timestamp = int(parts.get("t", 0))
            v1_signature = parts.get("v1", "")
            
            current_time = int(datetime.now(timezone.utc).timestamp())
            if current_time - timestamp > 300:
                return False
            
            signed_payload = f"{timestamp}.{payload.decode()}"
            expected_signature = hmac.new(
                self._webhook_signing_secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            
            return hmac.compare_digest(v1_signature, expected_signature)
        except Exception:
            return False

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
