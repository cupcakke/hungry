from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import secrets
import hashlib
import json

from sqlalchemy import select, update, and_, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.terminal import (
    TerminalReader,
    TerminalConnectionToken,
    TerminalLocation,
    TerminalPayment,
    CardPresentData,
    TerminalConfiguration,
    TerminalAction,
    TerminalEvent,
    TerminalOfflineQueue,
    TerminalSignature,
    TerminalReceipt,
    DeviceType,
    ReaderStatus,
    ConnectionTokenStatus,
    TerminalPaymentStatus,
    CardEntryMode,
    CaptureMethod,
    ActionType,
    ActionStatus,
    TerminalEventType,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    TerminalError,
)
from payment_platform.shared.utils.identifiers import generate_id


@dataclass
class ReaderInfo:
    reader_id: str
    status: str
    last_seen: Optional[int]
    capabilities: Dict[str, Any]


@dataclass
class PaymentResult:
    payment_id: str
    status: str
    amount: int
    currency: str
    tip_amount: Optional[int]
    card_last4: Optional[str]


@dataclass
class ReceiptData:
    receipt_number: str
    payment_id: str
    amount: int
    currency: str
    tip_amount: Optional[int]
    total_amount: int
    merchant_name: Optional[str]
    card_last4: Optional[str]
    created: int


class ReaderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def register(
        self,
        account_id: str,
        device_type: str,
        location_id: Optional[str] = None,
        label: Optional[str] = None,
        serial_number: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TerminalReader:
        device_type_map = {
            "verifone_p400": DeviceType.VERIFONE_P400,
            "stripe_m2": DeviceType.STRIPE_M2,
            "bbpos_wisepad3": DeviceType.BBPOS_WISEPAD3,
            "bbpos_wisepos_e": DeviceType.BBPOS_WISEPOS_E,
        }
        
        if device_type not in device_type_map:
            raise ValidationError(f"Invalid device type: {device_type}", param="device_type")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        reader = TerminalReader(
            id=self._generate_id("tmr"),
            account_id=account_id,
            device_type=device_type_map[device_type],
            location_id=location_id,
            status=ReaderStatus.OFFLINE,
            label=label,
            serial_number=serial_number,
            capabilities=self._get_device_capabilities(device_type),
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(reader)
        await self.session.flush()
        return reader

    async def get(self, reader_id: str) -> Optional[TerminalReader]:
        query = select(TerminalReader).where(TerminalReader.id == reader_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        location_id: Optional[str] = None,
        device_type: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TerminalReader]:
        query = select(TerminalReader)

        if account_id:
            query = query.where(TerminalReader.account_id == account_id)
        if status:
            query = query.where(TerminalReader.status == status)
        if location_id:
            query = query.where(TerminalReader.location_id == location_id)
        if device_type:
            query = query.where(TerminalReader.device_type == device_type)

        query = query.order_by(TerminalReader.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def handoff(
        self,
        reader_id: str,
        location_id: Optional[str] = None,
        configuration_id: Optional[str] = None,
    ) -> TerminalReader:
        reader = await self.get(reader_id)
        if not reader:
            raise NotFoundError(f"Reader {reader_id} not found")

        if location_id:
            reader.location_id = location_id
        if configuration_id:
            reader.configuration_id = configuration_id

        await self.session.flush()
        return reader

    async def unregister(self, reader_id: str) -> bool:
        reader = await self.get(reader_id)
        if not reader:
            raise NotFoundError(f"Reader {reader_id} not found")

        reader.is_active = False
        reader.status = ReaderStatus.OFFLINE
        await self.session.flush()
        return True

    async def heartbeat(
        self,
        reader_id: str,
        status: Optional[str] = None,
        ip_address: Optional[str] = None,
        firmware_version: Optional[str] = None,
        offline_transaction_count: Optional[int] = None,
        offline_total_amount: Optional[int] = None,
    ) -> TerminalReader:
        reader = await self.get(reader_id)
        if not reader:
            raise NotFoundError(f"Reader {reader_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        reader.last_seen_at = timestamp
        reader.last_heartbeat_at = timestamp

        if status:
            status_map = {
                "online": ReaderStatus.ONLINE,
                "offline": ReaderStatus.OFFLINE,
                "busy": ReaderStatus.BUSY,
                "unavailable": ReaderStatus.UNAVAILABLE,
                "updating": ReaderStatus.UPDATING,
            }
            if status in status_map:
                reader.status = status_map[status]

        if ip_address:
            reader.ip_address = ip_address
        if firmware_version:
            reader.firmware_version = firmware_version

        await self.session.flush()
        return reader

    async def get_by_serial(self, serial_number: str) -> Optional[TerminalReader]:
        query = select(TerminalReader).where(TerminalReader.serial_number == serial_number)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def count_by_location(self, location_id: str) -> int:
        query = select(func.count()).select_from(TerminalReader).where(
            and_(
                TerminalReader.location_id == location_id,
                TerminalReader.is_active == True,
            )
        )
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def count_online_by_account(self, account_id: str) -> int:
        query = select(func.count()).select_from(TerminalReader).where(
            and_(
                TerminalReader.account_id == account_id,
                TerminalReader.status == ReaderStatus.ONLINE,
                TerminalReader.is_active == True,
            )
        )
        result = await self.session.execute(query)
        return result.scalar() or 0

    def _get_device_capabilities(self, device_type: str) -> Dict[str, Any]:
        capabilities_map = {
            "verifone_p400": {
                "chip": True,
                "contactless": True,
                "swipe": True,
                "signature": True,
                "display": True,
                "printer": True,
                "wifi": True,
                "ethernet": True,
            },
            "stripe_m2": {
                "chip": True,
                "contactless": True,
                "swipe": True,
                "signature": False,
                "display": False,
                "printer": False,
                "wifi": False,
                "bluetooth": True,
            },
            "bbpos_wisepad3": {
                "chip": True,
                "contactless": True,
                "swipe": True,
                "signature": False,
                "display": False,
                "printer": False,
                "wifi": False,
                "bluetooth": True,
            },
            "bbpos_wisepos_e": {
                "chip": True,
                "contactless": True,
                "swipe": True,
                "signature": True,
                "display": True,
                "printer": True,
                "wifi": True,
                "ethernet": True,
            },
        }
        return capabilities_map.get(device_type, {})

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ConnectionTokenService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate(
        self,
        reader_id: Optional[str] = None,
        ttl_seconds: int = 3600,
    ) -> TerminalConnectionToken:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        token = secrets.token_urlsafe(64)

        connection_token = TerminalConnectionToken(
            id=self._generate_id("tct"),
            reader_id=reader_id,
            token=token,
            expires_at=timestamp + ttl_seconds,
            status=ConnectionTokenStatus.ACTIVE,
            created=timestamp,
        )

        self.session.add(connection_token)
        await self.session.flush()
        return connection_token

    async def validate(self, token: str) -> Optional[TerminalConnectionToken]:
        query = select(TerminalConnectionToken).where(
            and_(
                TerminalConnectionToken.token == token,
                TerminalConnectionToken.status == ConnectionTokenStatus.ACTIVE,
            )
        )
        result = await self.session.execute(query)
        conn_token = result.scalar_one_or_none()

        if not conn_token:
            return None

        timestamp = int(datetime.now(timezone.utc).timestamp())
        if conn_token.expires_at < timestamp:
            conn_token.status = ConnectionTokenStatus.EXPIRED
            await self.session.flush()
            return None

        return conn_token

    async def use_token(self, token: str, ip_address: Optional[str] = None) -> TerminalConnectionToken:
        conn_token = await self.validate(token)
        if not conn_token:
            raise TerminalError("Invalid or expired connection token")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        conn_token.status = ConnectionTokenStatus.USED
        conn_token.used_at = timestamp
        conn_token.ip_address = ip_address

        await self.session.flush()
        return conn_token

    async def revoke(self, token_id: str) -> bool:
        query = select(TerminalConnectionToken).where(TerminalConnectionToken.id == token_id)
        result = await self.session.execute(query)
        conn_token = result.scalar_one_or_none()

        if not conn_token:
            raise NotFoundError(f"Connection token {token_id} not found")

        conn_token.status = ConnectionTokenStatus.REVOKED
        await self.session.flush()
        return True

    async def cleanup_expired(self) -> int:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        query = (
            update(TerminalConnectionToken)
            .where(
                and_(
                    TerminalConnectionToken.status == ConnectionTokenStatus.ACTIVE,
                    TerminalConnectionToken.expires_at < timestamp,
                )
            )
            .values(status=ConnectionTokenStatus.EXPIRED)
        )
        result = await self.session.execute(query)
        await self.session.flush()
        return result.rowcount

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class LocationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        display_name: str,
        country: str,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        postal_code: Optional[str] = None,
        configuration_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TerminalLocation:
        timestamp = int(datetime.now(timezone.utc).timestamp())

        location = TerminalLocation(
            id=self._generate_id("tml"),
            account_id=account_id,
            display_name=display_name,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            postal_code=postal_code,
            country=country.upper(),
            configuration_id=configuration_id,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(location)
        await self.session.flush()
        return location

    async def get(self, location_id: str) -> Optional[TerminalLocation]:
        query = select(TerminalLocation).where(TerminalLocation.id == location_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        account_id: Optional[str] = None,
        country: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TerminalLocation]:
        query = select(TerminalLocation)

        if account_id:
            query = query.where(TerminalLocation.account_id == account_id)
        if country:
            query = query.where(TerminalLocation.country == country.upper())

        query = query.order_by(TerminalLocation.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update(
        self,
        location_id: str,
        display_name: Optional[str] = None,
        address_line1: Optional[str] = None,
        address_line2: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        postal_code: Optional[str] = None,
        configuration_id: Optional[str] = None,
    ) -> TerminalLocation:
        location = await self.get(location_id)
        if not location:
            raise NotFoundError(f"Location {location_id} not found")

        if display_name:
            location.display_name = display_name
        if address_line1 is not None:
            location.address_line1 = address_line1
        if address_line2 is not None:
            location.address_line2 = address_line2
        if city is not None:
            location.city = city
        if state is not None:
            location.state = state
        if postal_code is not None:
            location.postal_code = postal_code
        if configuration_id is not None:
            location.configuration_id = configuration_id

        await self.session.flush()
        return location

    async def delete(self, location_id: str) -> bool:
        location = await self.get(location_id)
        if not location:
            raise NotFoundError(f"Location {location_id} not found")

        location.is_active = False
        await self.session.flush()
        return True

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class TerminalPaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.reader_service = ReaderService(session)

    async def create_intent(
        self,
        reader_id: str,
        amount: int,
        currency: str,
        capture_method: str = "automatic",
        statement_descriptor: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TerminalPayment:
        reader = await self.reader_service.get(reader_id)
        if not reader:
            raise NotFoundError(f"Reader {reader_id} not found")

        if reader.status != ReaderStatus.ONLINE:
            raise TerminalError(f"Reader {reader_id} is not online", reader_id=reader_id)

        timestamp = int(datetime.now(timezone.utc).timestamp())
        capture_enum = CaptureMethod.MANUAL if capture_method == "manual" else CaptureMethod.AUTOMATIC

        payment = TerminalPayment(
            id=self._generate_id("tpi"),
            reader_id=reader_id,
            amount=amount,
            currency=currency.lower(),
            status=TerminalPaymentStatus.PENDING,
            capture_method=capture_enum,
            statement_descriptor=statement_descriptor,
            description=description,
            created=timestamp,
            metadata_=metadata or {},
        )

        reader.status = ReaderStatus.BUSY

        self.session.add(payment)
        await self.session.flush()
        return payment

    async def process_payment(
        self,
        payment_id: str,
        card_data: Dict[str, Any],
        entry_mode: str = "chip",
    ) -> TerminalPayment:
        payment = await self.get(payment_id)
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        if payment.status != TerminalPaymentStatus.PENDING:
            raise TerminalError(f"Payment {payment_id} cannot be processed", payment_id=payment_id)

        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.status = TerminalPaymentStatus.PROCESSING

        entry_mode_map = {
            "chip": CardEntryMode.CHIP,
            "contactless": CardEntryMode.CONTACTLESS,
            "swipe": CardEntryMode.SWIPE,
            "fallback": CardEntryMode.FALLBACK,
            "manual": CardEntryMode.MANUAL,
        }

        card_present = CardPresentData(
            id=self._generate_id("tcp"),
            entry_mode=entry_mode_map.get(entry_mode, CardEntryMode.CHIP),
            card_brand=card_data.get("brand", "unknown"),
            last4=card_data.get("last4", "****"),
            exp_month=card_data.get("exp_month", 1),
            exp_year=card_data.get("exp_year", 2025),
            cardholder_name=card_data.get("cardholder_name"),
            application_label=card_data.get("application_label"),
            aid=card_data.get("aid"),
            tvr=card_data.get("tvr"),
            tsq=card_data.get("tsq"),
            receipt_data=card_data.get("receipt_data"),
            emv_data=card_data.get("emv_data"),
            created=timestamp,
        )

        self.session.add(card_present)
        payment.card_present_data_id = card_present.id

        await self.session.flush()
        return payment

    async def complete_payment(
        self,
        payment_id: str,
        auth_code: Optional[str] = None,
        offline: bool = False,
    ) -> TerminalPayment:
        payment = await self.get(payment_id)
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.status = TerminalPaymentStatus.SUCCEEDED
        payment.processed_at = timestamp
        payment.offline = offline

        if payment.capture_method == CaptureMethod.AUTOMATIC:
            payment.amount_received = payment.amount
        else:
            payment.amount_capturable = payment.amount

        reader = await self.reader_service.get(payment.reader_id)
        if reader:
            reader.status = ReaderStatus.ONLINE

        await self.session.flush()
        return payment

    async def capture(
        self,
        payment_id: str,
        amount: Optional[int] = None,
    ) -> TerminalPayment:
        payment = await self.get(payment_id)
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        if payment.status != TerminalPaymentStatus.SUCCEEDED:
            raise TerminalError(f"Payment {payment_id} cannot be captured", payment_id=payment_id)

        if payment.capture_method != CaptureMethod.MANUAL:
            raise TerminalError(f"Payment {payment_id} is automatic capture", payment_id=payment_id)

        capture_amount = amount if amount else payment.amount_capturable
        timestamp = int(datetime.now(timezone.utc).timestamp())

        payment.amount_received = capture_amount
        payment.amount_capturable = 0
        payment.processed_at = timestamp

        await self.session.flush()
        return payment

    async def cancel(
        self,
        payment_id: str,
        reason: Optional[str] = None,
    ) -> TerminalPayment:
        payment = await self.get(payment_id)
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        if payment.status not in [TerminalPaymentStatus.PENDING, TerminalPaymentStatus.IN_PROGRESS]:
            raise TerminalError(f"Payment {payment_id} cannot be canceled", payment_id=payment_id)

        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.status = TerminalPaymentStatus.CANCELED
        payment.canceled_at = timestamp
        if reason:
            payment.failure_message = reason

        reader = await self.reader_service.get(payment.reader_id)
        if reader:
            reader.status = ReaderStatus.ONLINE

        await self.session.flush()
        return payment

    async def fail(
        self,
        payment_id: str,
        failure_code: str,
        failure_message: str,
    ) -> TerminalPayment:
        payment = await self.get(payment_id)
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.status = TerminalPaymentStatus.FAILED
        payment.failed_at = timestamp
        payment.failure_code = failure_code
        payment.failure_message = failure_message

        reader = await self.reader_service.get(payment.reader_id)
        if reader:
            reader.status = ReaderStatus.ONLINE

        await self.session.flush()
        return payment

    async def get(self, payment_id: str) -> Optional[TerminalPayment]:
        query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        reader_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TerminalPayment]:
        query = select(TerminalPayment)

        if reader_id:
            query = query.where(TerminalPayment.reader_id == reader_id)
        if status:
            query = query.where(TerminalPayment.status == status)

        query = query.order_by(TerminalPayment.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def add_tip(
        self,
        payment_id: str,
        tip_amount: int,
    ) -> TerminalPayment:
        payment = await self.get(payment_id)
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.tip_amount = tip_amount
        payment.tip_collected_at = timestamp

        await self.session.flush()
        return payment

    async def add_signature(
        self,
        payment_id: str,
        signature_data: Dict[str, Any],
    ) -> TerminalSignature:
        payment = await self.get(payment_id)
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        signature = TerminalSignature(
            id=self._generate_id("tsg"),
            payment_id=payment_id,
            reader_id=payment.reader_id,
            signature_data=signature_data,
            signature_format=signature_data.get("format", "svg"),
            collected_at=timestamp,
            created=timestamp,
        )

        payment.signature_collected = True
        payment.signature_data = signature_data
        payment.signature_collected_at = timestamp

        self.session.add(signature)
        await self.session.flush()
        return signature

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ConfigurationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        tipping_enabled: bool = True,
        tipping_percentages: Optional[List[int]] = None,
        tipping_fixed_amounts: Optional[List[int]] = None,
        collect_signature: bool = False,
        collect_name: bool = False,
        show_amount_confirmation: bool = True,
        timeout_seconds: int = 120,
        ui_language: Optional[str] = None,
        receipt_language: Optional[str] = None,
        receipt_header: Optional[str] = None,
        receipt_footer: Optional[str] = None,
        offline_mode_enabled: bool = False,
        offline_transaction_limit: int = 50000,
        offline_amount_limit: int = 1000000,
        branding_logo_url: Optional[str] = None,
        branding_primary_color: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TerminalConfiguration:
        timestamp = int(datetime.now(timezone.utc).timestamp())

        configuration = TerminalConfiguration(
            id=self._generate_id("tmc"),
            account_id=account_id,
            tipping_enabled=tipping_enabled,
            tipping_percentages=tipping_percentages or [15, 20, 25],
            tipping_fixed_amounts=tipping_fixed_amounts,
            collect_signature=collect_signature,
            collect_name=collect_name,
            show_amount_confirmation=show_amount_confirmation,
            timeout_seconds=timeout_seconds,
            ui_language=ui_language,
            receipt_language=receipt_language,
            receipt_header=receipt_header,
            receipt_footer=receipt_footer,
            offline_mode_enabled=offline_mode_enabled,
            offline_transaction_limit=offline_transaction_limit,
            offline_amount_limit=offline_amount_limit,
            branding_logo_url=branding_logo_url,
            branding_primary_color=branding_primary_color,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(configuration)
        await self.session.flush()
        return configuration

    async def get(self, config_id: str) -> Optional[TerminalConfiguration]:
        query = select(TerminalConfiguration).where(TerminalConfiguration.id == config_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_default(self, account_id: str) -> Optional[TerminalConfiguration]:
        query = select(TerminalConfiguration).where(
            and_(
                TerminalConfiguration.account_id == account_id,
                TerminalConfiguration.is_default == True,
                TerminalConfiguration.is_active == True,
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        account_id: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TerminalConfiguration]:
        query = select(TerminalConfiguration)

        if account_id:
            query = query.where(TerminalConfiguration.account_id == account_id)

        query = query.order_by(TerminalConfiguration.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update(
        self,
        config_id: str,
        **kwargs,
    ) -> TerminalConfiguration:
        config = await self.get(config_id)
        if not config:
            raise NotFoundError(f"Configuration {config_id} not found")

        allowed_fields = [
            "tipping_enabled", "tipping_percentages", "tipping_fixed_amounts",
            "collect_signature", "collect_name", "show_amount_confirmation",
            "timeout_seconds", "ui_language", "receipt_language",
            "receipt_header", "receipt_footer", "offline_mode_enabled",
            "offline_transaction_limit", "offline_amount_limit",
            "branding_logo_url", "branding_primary_color", "branding_secondary_color",
        ]

        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                setattr(config, key, value)

        await self.session.flush()
        return config

    async def set_default(self, config_id: str) -> TerminalConfiguration:
        config = await self.get(config_id)
        if not config:
            raise NotFoundError(f"Configuration {config_id} not found")

        query = (
            update(TerminalConfiguration)
            .where(TerminalConfiguration.account_id == config.account_id)
            .values(is_default=False)
        )
        await self.session.execute(query)

        config.is_default = True
        await self.session.flush()
        return config

    async def apply_to_reader(
        self,
        config_id: str,
        reader_id: str,
    ) -> TerminalConfiguration:
        from payment_platform.backend.domain.terminal import TerminalReader

        config = await self.get(config_id)
        if not config:
            raise NotFoundError(f"Configuration {config_id} not found")

        query = select(TerminalReader).where(TerminalReader.id == reader_id)
        result = await self.session.execute(query)
        reader = result.scalar_one_or_none()

        if not reader:
            raise NotFoundError(f"Reader {reader_id} not found")

        reader.configuration_id = config_id
        reader.offline_mode_enabled = config.offline_mode_enabled
        reader.offline_transaction_limit = config.offline_transaction_limit
        reader.offline_amount_limit = config.offline_amount_limit

        await self.session.flush()
        return config

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ActionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.reader_service = ReaderService(session)

    async def send_action(
        self,
        reader_id: str,
        action_type: str,
        request_data: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 120,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TerminalAction:
        reader = await self.reader_service.get(reader_id)
        if not reader:
            raise NotFoundError(f"Reader {reader_id} not found")

        if reader.status != ReaderStatus.ONLINE:
            raise TerminalError(f"Reader {reader_id} is not online", reader_id=reader_id)

        action_type_map = {
            "display": ActionType.DISPLAY,
            "prompt": ActionType.PROMPT,
            "set_branding": ActionType.SET_BRANDING,
            "collect_signature": ActionType.COLLECT_SIGNATURE,
            "collect_tip": ActionType.COLLECT_TIP,
            "confirm_payment": ActionType.CONFIRM_PAYMENT,
            "refund": ActionType.REFUND,
        }

        if action_type not in action_type_map:
            raise ValidationError(f"Invalid action type: {action_type}", param="type")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        action = TerminalAction(
            id=self._generate_id("tac"),
            reader_id=reader_id,
            type=action_type_map[action_type],
            status=ActionStatus.PENDING,
            request_data=request_data,
            timeout_seconds=timeout_seconds,
            sent_at=timestamp,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(action)
        await self.session.flush()
        return action

    async def handle_response(
        self,
        action_id: str,
        response_data: Dict[str, Any],
    ) -> TerminalAction:
        query = select(TerminalAction).where(TerminalAction.id == action_id)
        result = await self.session.execute(query)
        action = result.scalar_one_or_none()

        if not action:
            raise NotFoundError(f"Action {action_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        action.status = ActionStatus.COMPLETED
        action.response_data = response_data
        action.completed_at = timestamp

        await self.session.flush()
        return action

    async def fail_action(
        self,
        action_id: str,
        error_code: str,
        error_message: str,
    ) -> TerminalAction:
        query = select(TerminalAction).where(TerminalAction.id == action_id)
        result = await self.session.execute(query)
        action = result.scalar_one_or_none()

        if not action:
            raise NotFoundError(f"Action {action_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        action.status = ActionStatus.FAILED
        action.error_code = error_code
        action.error_message = error_message
        action.completed_at = timestamp

        await self.session.flush()
        return action

    async def timeout_action(self, action_id: str) -> TerminalAction:
        query = select(TerminalAction).where(TerminalAction.id == action_id)
        result = await self.session.execute(query)
        action = result.scalar_one_or_none()

        if not action:
            raise NotFoundError(f"Action {action_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        action.status = ActionStatus.TIMED_OUT
        action.expired_at = timestamp

        await self.session.flush()
        return action

    async def get(self, action_id: str) -> Optional[TerminalAction]:
        query = select(TerminalAction).where(TerminalAction.id == action_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        reader_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TerminalAction]:
        query = select(TerminalAction)

        if reader_id:
            query = query.where(TerminalAction.reader_id == reader_id)
        if status:
            query = query.where(TerminalAction.status == status)

        query = query.order_by(TerminalAction.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def cancel_action(self, action_id: str) -> TerminalAction:
        query = select(TerminalAction).where(TerminalAction.id == action_id)
        result = await self.session.execute(query)
        action = result.scalar_one_or_none()

        if not action:
            raise NotFoundError(f"Action {action_id} not found")

        if action.status != ActionStatus.PENDING:
            raise TerminalError(f"Action {action_id} cannot be canceled", action_id=action_id)

        action.status = ActionStatus.CANCELED
        await self.session.flush()
        return action

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ReceiptService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate_receipt(
        self,
        payment_id: str,
        reader_id: Optional[str] = None,
        receipt_type: str = "standard",
    ) -> TerminalReceipt:
        payment_query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
        payment_result = await self.session.execute(payment_query)
        payment = payment_result.scalar_one_or_none()

        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        receipt_number = f"RE-{payment_id[-8:].upper()}"

        receipt = TerminalReceipt(
            id=self._generate_id("trc"),
            payment_id=payment_id,
            reader_id=reader_id or payment.reader_id,
            receipt_type=receipt_type,
            receipt_number=receipt_number,
            receipt_data=self._build_receipt_data(payment),
            created=timestamp,
        )

        payment.receipt_number = receipt_number

        self.session.add(receipt)
        await self.session.flush()
        return receipt

    async def email_receipt(
        self,
        payment_id: str,
        email: str,
    ) -> TerminalReceipt:
        receipt = await self.generate_receipt(payment_id, receipt_type="email")
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        receipt.email_sent = True
        receipt.email_sent_at = timestamp
        receipt.email_address = email

        await self.session.flush()
        return receipt

    async def sms_receipt(
        self,
        payment_id: str,
        phone_number: str,
    ) -> TerminalReceipt:
        receipt = await self.generate_receipt(payment_id, receipt_type="sms")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        receipt.sms_sent = True
        receipt.sms_sent_at = timestamp
        receipt.phone_number = phone_number

        await self.session.flush()
        return receipt

    async def get_receipt(self, receipt_id: str) -> Optional[TerminalReceipt]:
        query = select(TerminalReceipt).where(TerminalReceipt.id == receipt_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_receipts(
        self,
        payment_id: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TerminalReceipt]:
        query = select(TerminalReceipt)

        if payment_id:
            query = query.where(TerminalReceipt.payment_id == payment_id)

        query = query.order_by(TerminalReceipt.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _build_receipt_data(self, payment: TerminalPayment) -> Dict[str, Any]:
        return {
            "payment_id": payment.id,
            "amount": payment.amount,
            "currency": payment.currency.upper(),
            "tip_amount": payment.tip_amount or 0,
            "total_amount": payment.amount + (payment.tip_amount or 0),
            "created": payment.created,
            "status": payment.status.value if payment.status else "unknown",
            "offline": payment.offline,
            "description": payment.description,
            "statement_descriptor": payment.statement_descriptor,
        }

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class OfflineModeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.reader_service = ReaderService(session)

    async def queue_transaction(
        self,
        reader_id: str,
        amount: int,
        currency: str,
        card_data: Dict[str, Any],
        offline_id: Optional[str] = None,
    ) -> TerminalOfflineQueue:
        reader = await self.reader_service.get(reader_id)
        if not reader:
            raise NotFoundError(f"Reader {reader_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        offline_id = offline_id or f"OFF-{secrets.token_hex(8).upper()}"

        queue_entry = TerminalOfflineQueue(
            id=self._generate_id("toq"),
            reader_id=reader_id,
            offline_id=offline_id,
            amount=amount,
            currency=currency.lower(),
            card_present_data=card_data,
            created_at_reader=timestamp,
            created=timestamp,
        )

        self.session.add(queue_entry)
        await self.session.flush()
        return queue_entry

    async def sync_transaction(self, queue_id: str) -> TerminalPayment:
        query = select(TerminalOfflineQueue).where(TerminalOfflineQueue.id == queue_id)
        result = await self.session.execute(query)
        queue_entry = result.scalar_one_or_none()

        if not queue_entry:
            raise NotFoundError(f"Offline queue entry {queue_id} not found")

        payment_service = TerminalPaymentService(self.session)

        payment = TerminalPayment(
            id=self._generate_id("tpi"),
            reader_id=queue_entry.reader_id,
            amount=queue_entry.amount,
            currency=queue_entry.currency,
            status=TerminalPaymentStatus.SUCCEEDED,
            capture_method=CaptureMethod.AUTOMATIC,
            offline=True,
            offline_id=queue_entry.offline_id,
            amount_received=queue_entry.amount,
            created=queue_entry.created_at_reader,
        )

        self.session.add(payment)

        timestamp = int(datetime.now(timezone.utc).timestamp())
        queue_entry.synced = True
        queue_entry.synced_at = timestamp
        queue_entry.payment_id = payment.id

        await self.session.flush()
        return payment

    async def get_pending(self, reader_id: str) -> List[TerminalOfflineQueue]:
        query = select(TerminalOfflineQueue).where(
            and_(
                TerminalOfflineQueue.reader_id == reader_id,
                TerminalOfflineQueue.synced == False,
            )
        ).order_by(TerminalOfflineQueue.created_at_reader)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_sync_stats(self, reader_id: str) -> Dict[str, Any]:
        pending_query = select(func.count()).select_from(TerminalOfflineQueue).where(
            and_(
                TerminalOfflineQueue.reader_id == reader_id,
                TerminalOfflineQueue.synced == False,
            )
        )
        pending_result = await self.session.execute(pending_query)
        pending_count = pending_result.scalar() or 0

        amount_query = select(func.sum(TerminalOfflineQueue.amount)).select_from(TerminalOfflineQueue).where(
            and_(
                TerminalOfflineQueue.reader_id == reader_id,
                TerminalOfflineQueue.synced == False,
            )
        )
        amount_result = await self.session.execute(amount_query)
        pending_amount = amount_result.scalar() or 0

        failed_query = select(func.count()).select_from(TerminalOfflineQueue).where(
            and_(
                TerminalOfflineQueue.reader_id == reader_id,
                TerminalOfflineQueue.synced == False,
                TerminalOfflineQueue.sync_failure_count > 0,
            )
        )
        failed_result = await self.session.execute(failed_query)
        failed_count = failed_result.scalar() or 0

        return {
            "reader_id": reader_id,
            "pending_count": pending_count,
            "pending_amount": pending_amount,
            "failed_count": failed_count,
        }

    async def mark_sync_failed(
        self,
        queue_id: str,
        error_message: str,
    ) -> TerminalOfflineQueue:
        query = select(TerminalOfflineQueue).where(TerminalOfflineQueue.id == queue_id)
        result = await self.session.execute(query)
        queue_entry = result.scalar_one_or_none()

        if not queue_entry:
            raise NotFoundError(f"Offline queue entry {queue_id} not found")

        queue_entry.sync_failure_count += 1
        queue_entry.last_sync_failure = error_message

        await self.session.flush()
        return queue_entry

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class EventService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_event(
        self,
        reader_id: str,
        event_type: TerminalEventType,
        event_data: Optional[Dict[str, Any]] = None,
    ) -> TerminalEvent:
        timestamp = int(datetime.now(timezone.utc).timestamp())

        event = TerminalEvent(
            id=self._generate_id("tev"),
            reader_id=reader_id,
            event_type=event_type,
            event_data=event_data,
            timestamp=timestamp,
        )

        self.session.add(event)
        await self.session.flush()
        return event

    async def get(self, event_id: str) -> Optional[TerminalEvent]:
        query = select(TerminalEvent).where(TerminalEvent.id == event_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        reader_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TerminalEvent]:
        query = select(TerminalEvent)

        if reader_id:
            query = query.where(TerminalEvent.reader_id == reader_id)
        if event_type:
            query = query.where(TerminalEvent.event_type == event_type)

        query = query.order_by(TerminalEvent.timestamp.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def mark_processed(self, event_id: str) -> TerminalEvent:
        event = await self.get(event_id)
        if not event:
            raise NotFoundError(f"Event {event_id} not found")

        event.processed = True
        await self.session.flush()
        return event

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
