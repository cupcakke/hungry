from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, TerminalError

router = APIRouter()


class ReaderRegisterRequest(BaseModel):
    device_type: str = Field(..., description="Device type: verifone_p400, stripe_m2, bbpos_wisepad3, bbpos_wisepos_e")
    location_id: Optional[str] = Field(default=None, description="Location ID")
    label: Optional[str] = Field(default=None, description="Reader label")
    serial_number: Optional[str] = Field(default=None, description="Device serial number")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ReaderResponse(BaseModel):
    id: str
    object: str = "terminal.reader"
    account_id: Optional[str] = None
    device_type: str
    device_sw_version: Optional[str] = None
    location_id: Optional[str] = None
    status: str
    label: Optional[str] = None
    serial_number: Optional[str] = None
    ip_address: Optional[str] = None
    last_seen_at: Optional[int] = None
    is_active: bool = True
    firmware_version: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    configuration_id: Optional[str] = None
    offline_mode_enabled: bool = False
    offline_transaction_limit: int = 50000
    offline_amount_limit: int = 1000000
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ReaderHandoffRequest(BaseModel):
    location_id: Optional[str] = Field(default=None, description="New location ID for handoff")
    configuration_id: Optional[str] = Field(default=None, description="New configuration ID")


class ConnectionTokenCreateRequest(BaseModel):
    reader_id: Optional[str] = Field(default=None, description="Reader ID to associate")


class ConnectionTokenResponse(BaseModel):
    id: str
    object: str = "terminal.connection_token"
    reader_id: Optional[str] = None
    token: str
    expires_at: int
    status: str
    created: int
    livemode: bool = False


class LocationCreateRequest(BaseModel):
    display_name: str = Field(..., description="Display name for location")
    address_line1: Optional[str] = Field(default=None, description="Address line 1")
    address_line2: Optional[str] = Field(default=None, description="Address line 2")
    city: Optional[str] = Field(default=None, description="City")
    state: Optional[str] = Field(default=None, description="State/Province")
    postal_code: Optional[str] = Field(default=None, description="Postal code")
    country: str = Field(..., description="ISO 3166-1 alpha-2 country code")
    configuration_id: Optional[str] = Field(default=None, description="Configuration ID")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class LocationResponse(BaseModel):
    id: str
    object: str = "terminal.location"
    account_id: Optional[str] = None
    display_name: str
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str
    configuration_id: Optional[str] = None
    geolocation: Optional[Dict[str, Any]] = None
    is_active: bool = True
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class TerminalPaymentIntentCreateRequest(BaseModel):
    reader_id: str = Field(..., description="Reader ID")
    amount: int = Field(..., gt=0, description="Amount in cents")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency code")
    capture_method: Optional[str] = Field(default="automatic", description="Capture method: automatic or manual")
    statement_descriptor: Optional[str] = Field(default=None, max_length=22, description="Statement descriptor")
    description: Optional[str] = Field(default=None, description="Payment description")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class TerminalPaymentIntentResponse(BaseModel):
    id: str
    object: str = "terminal.payment"
    reader_id: Optional[str] = None
    payment_intent_id: Optional[str] = None
    amount: int
    amount_capturable: int = 0
    amount_received: int = 0
    currency: str
    status: str
    capture_method: str
    statement_descriptor: Optional[str] = None
    description: Optional[str] = None
    receipt_number: Optional[str] = None
    receipt_url: Optional[str] = None
    tip_amount: Optional[int] = None
    signature_collected: bool = False
    offline: bool = False
    offline_id: Optional[str] = None
    processed_at: Optional[int] = None
    failed_at: Optional[int] = None
    canceled_at: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    card_present_data: Optional[Dict[str, Any]] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class TerminalPaymentCaptureRequest(BaseModel):
    amount: Optional[int] = Field(default=None, description="Amount to capture (defaults to full)")


class TerminalPaymentCancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Cancellation reason")


class ConfigurationCreateRequest(BaseModel):
    tipping_enabled: Optional[bool] = Field(default=True, description="Enable tipping")
    tipping_percentages: Optional[List[int]] = Field(default=[15, 20, 25], description="Tip percentage options")
    tipping_fixed_amounts: Optional[List[int]] = Field(default=None, description="Fixed tip amounts in cents")
    collect_signature: Optional[bool] = Field(default=False, description="Require signature collection")
    collect_name: Optional[bool] = Field(default=False, description="Collect cardholder name")
    show_amount_confirmation: Optional[bool] = Field(default=True, description="Show amount confirmation screen")
    timeout_seconds: Optional[int] = Field(default=120, description="Payment timeout in seconds")
    ui_language: Optional[str] = Field(default=None, description="UI language code")
    receipt_language: Optional[str] = Field(default=None, description="Receipt language code")
    receipt_header: Optional[str] = Field(default=None, description="Receipt header text")
    receipt_footer: Optional[str] = Field(default=None, description="Receipt footer text")
    offline_mode_enabled: Optional[bool] = Field(default=False, description="Enable offline mode")
    offline_transaction_limit: Optional[int] = Field(default=50000, description="Offline transaction count limit")
    offline_amount_limit: Optional[int] = Field(default=1000000, description="Offline amount limit in cents")
    branding_logo_url: Optional[str] = Field(default=None, description="Branding logo URL")
    branding_primary_color: Optional[str] = Field(default=None, description="Primary branding color hex")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ConfigurationResponse(BaseModel):
    id: str
    object: str = "terminal.configuration"
    account_id: Optional[str] = None
    tipping_enabled: bool = True
    tipping_percentages: Optional[List[int]] = None
    tipping_fixed_amounts: Optional[List[int]] = None
    collect_signature: bool = False
    collect_name: bool = False
    show_amount_confirmation: bool = True
    timeout_seconds: int = 120
    idle_timeout_seconds: int = 30
    verification_timeout_seconds: int = 60
    ui_language: Optional[str] = None
    receipt_language: Optional[str] = None
    receipt_email_enabled: bool = True
    receipt_sms_enabled: bool = False
    receipt_header: Optional[str] = None
    receipt_footer: Optional[str] = None
    offline_mode_enabled: bool = False
    offline_transaction_limit: int = 50000
    offline_amount_limit: int = 1000000
    offline_allow_charged_cards: bool = True
    offline_max_stored_transactions: int = 100
    branding_logo_url: Optional[str] = None
    branding_primary_color: Optional[str] = None
    branding_secondary_color: Optional[str] = None
    is_default: bool = False
    is_active: bool = True
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ActionCreateRequest(BaseModel):
    reader_id: str = Field(..., description="Reader ID")
    type: str = Field(..., description="Action type: display, prompt, set_branding, collect_signature, collect_tip")
    request_data: Optional[Dict[str, Any]] = Field(default=None, description="Action request data")
    timeout_seconds: Optional[int] = Field(default=120, description="Action timeout in seconds")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ActionResponse(BaseModel):
    id: str
    object: str = "terminal.action"
    reader_id: str
    type: str
    status: str
    request_data: Optional[Dict[str, Any]] = None
    response_data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    sent_at: Optional[int] = None
    completed_at: Optional[int] = None
    timeout_seconds: int = 120
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class HeartbeatRequest(BaseModel):
    status: Optional[str] = Field(default=None, description="Reader status")
    ip_address: Optional[str] = Field(default=None, description="Reader IP address")
    firmware_version: Optional[str] = Field(default=None, description="Current firmware version")
    offline_transaction_count: Optional[int] = Field(default=None, description="Number of offline transactions queued")
    offline_total_amount: Optional[int] = Field(default=None, description="Total amount of offline transactions")


class ReceiptEmailRequest(BaseModel):
    email: str = Field(..., description="Email address to send receipt to")


class ReceiptSmsRequest(BaseModel):
    phone_number: str = Field(..., description="Phone number to send receipt to")


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


def _generate_token() -> str:
    import secrets
    return secrets.token_urlsafe(64)


@router.post("/readers", response_model=ReaderResponse, status_code=201)
async def register_reader(
    request: Request,
    data: ReaderRegisterRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.terminal import (
        TerminalReader, DeviceType, ReaderStatus
    )
    
    account_id = _get_account_id(request)
    
    device_type_map = {
        "verifone_p400": DeviceType.VERIFONE_P400,
        "stripe_m2": DeviceType.STRIPE_M2,
        "bbpos_wisepad3": DeviceType.BBPOS_WISEPAD3,
        "bbpos_wisepos_e": DeviceType.BBPOS_WISEPOS_E,
    }
    
    if data.device_type not in device_type_map:
        raise ValidationError(f"Invalid device type: {data.device_type}")
    
    reader_id = _generate_id("tmr")
    timestamp = _get_timestamp()
    
    reader = TerminalReader(
        id=reader_id,
        account_id=account_id,
        device_type=device_type_map[data.device_type],
        location_id=data.location_id,
        status=ReaderStatus.OFFLINE,
        label=data.label,
        serial_number=data.serial_number,
        capabilities=_get_device_capabilities(data.device_type),
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(reader)
    await session.flush()
    
    return ReaderResponse(
        id=reader.id,
        account_id=reader.account_id,
        device_type=reader.device_type.value,
        device_sw_version=reader.device_sw_version,
        location_id=reader.location_id,
        status=reader.status.value,
        label=reader.label,
        serial_number=reader.serial_number,
        ip_address=reader.ip_address,
        last_seen_at=reader.last_seen_at,
        is_active=reader.is_active,
        firmware_version=reader.firmware_version,
        capabilities=reader.capabilities,
        configuration_id=reader.configuration_id,
        offline_mode_enabled=reader.offline_mode_enabled,
        offline_transaction_limit=reader.offline_transaction_limit,
        offline_amount_limit=reader.offline_amount_limit,
        created=reader.created,
        metadata=reader.metadata_,
    )


@router.get("/readers", response_model=PaginatedResponse[ReaderResponse])
async def list_readers(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    location_id: Optional[str] = None,
    device_type: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalReader
    
    account_id = _get_account_id(request)
    
    query = select(TerminalReader)
    if account_id:
        query = query.where(TerminalReader.account_id == account_id)
    if status:
        query = query.where(TerminalReader.status == status)
    if location_id:
        query = query.where(TerminalReader.location_id == location_id)
    if device_type:
        query = query.where(TerminalReader.device_type == device_type)
    if starting_after:
        query = query.where(TerminalReader.id > starting_after)
    
    query = query.order_by(TerminalReader.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    readers = list(result.scalars().all())
    
    has_more = len(readers) > limit
    if has_more:
        readers = readers[:limit]
    
    data = [
        ReaderResponse(
            id=r.id,
            account_id=r.account_id,
            device_type=r.device_type.value,
            device_sw_version=r.device_sw_version,
            location_id=r.location_id,
            status=r.status.value,
            label=r.label,
            serial_number=r.serial_number,
            ip_address=r.ip_address,
            last_seen_at=r.last_seen_at,
            is_active=r.is_active,
            firmware_version=r.firmware_version,
            capabilities=r.capabilities,
            configuration_id=r.configuration_id,
            offline_mode_enabled=r.offline_mode_enabled,
            offline_transaction_limit=r.offline_transaction_limit,
            offline_amount_limit=r.offline_amount_limit,
            created=r.created,
            metadata=r.metadata_,
        )
        for r in readers
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/readers/{reader_id}", response_model=ReaderResponse)
async def get_reader(
    reader_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalReader
    
    query = select(TerminalReader).where(TerminalReader.id == reader_id)
    result = await session.execute(query)
    reader = result.scalar_one_or_none()
    
    if not reader:
        raise NotFoundError(f"Reader {reader_id} not found")
    
    return ReaderResponse(
        id=reader.id,
        account_id=reader.account_id,
        device_type=reader.device_type.value,
        device_sw_version=reader.device_sw_version,
        location_id=reader.location_id,
        status=reader.status.value,
        label=reader.label,
        serial_number=reader.serial_number,
        ip_address=reader.ip_address,
        last_seen_at=reader.last_seen_at,
        is_active=reader.is_active,
        firmware_version=reader.firmware_version,
        capabilities=reader.capabilities,
        configuration_id=reader.configuration_id,
        offline_mode_enabled=reader.offline_mode_enabled,
        offline_transaction_limit=reader.offline_transaction_limit,
        offline_amount_limit=reader.offline_amount_limit,
        created=reader.created,
        metadata=reader.metadata_,
    )


@router.post("/readers/{reader_id}/handoff", response_model=ReaderResponse)
async def handoff_reader(
    reader_id: str,
    request: Request,
    data: ReaderHandoffRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalReader
    
    query = select(TerminalReader).where(TerminalReader.id == reader_id)
    result = await session.execute(query)
    reader = result.scalar_one_or_none()
    
    if not reader:
        raise NotFoundError(f"Reader {reader_id} not found")
    
    if data.location_id:
        reader.location_id = data.location_id
    if data.configuration_id:
        reader.configuration_id = data.configuration_id
    
    await session.flush()
    
    return ReaderResponse(
        id=reader.id,
        account_id=reader.account_id,
        device_type=reader.device_type.value,
        device_sw_version=reader.device_sw_version,
        location_id=reader.location_id,
        status=reader.status.value,
        label=reader.label,
        serial_number=reader.serial_number,
        ip_address=reader.ip_address,
        last_seen_at=reader.last_seen_at,
        is_active=reader.is_active,
        firmware_version=reader.firmware_version,
        capabilities=reader.capabilities,
        configuration_id=reader.configuration_id,
        offline_mode_enabled=reader.offline_mode_enabled,
        offline_transaction_limit=reader.offline_transaction_limit,
        offline_amount_limit=reader.offline_amount_limit,
        created=reader.created,
        metadata=reader.metadata_,
    )


@router.delete("/readers/{reader_id}")
async def unregister_reader(
    reader_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select, delete
    from payment_platform.backend.domain.terminal import TerminalReader
    
    query = select(TerminalReader).where(TerminalReader.id == reader_id)
    result = await session.execute(query)
    reader = result.scalar_one_or_none()
    
    if not reader:
        raise NotFoundError(f"Reader {reader_id} not found")
    
    reader.is_active = False
    reader.status = "offline"
    
    await session.flush()
    
    return {"deleted": True, "id": reader_id}


@router.post("/readers/{reader_id}/heartbeat")
async def reader_heartbeat(
    reader_id: str,
    request: Request,
    data: HeartbeatRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalReader, ReaderStatus
    
    query = select(TerminalReader).where(TerminalReader.id == reader_id)
    result = await session.execute(query)
    reader = result.scalar_one_or_none()
    
    if not reader:
        raise NotFoundError(f"Reader {reader_id} not found")
    
    timestamp = _get_timestamp()
    reader.last_seen_at = timestamp
    reader.last_heartbeat_at = timestamp
    
    if data.status:
        status_map = {
            "online": ReaderStatus.ONLINE,
            "offline": ReaderStatus.OFFLINE,
            "busy": ReaderStatus.BUSY,
            "unavailable": ReaderStatus.UNAVAILABLE,
            "updating": ReaderStatus.UPDATING,
        }
        if data.status in status_map:
            reader.status = status_map[data.status]
    if data.ip_address:
        reader.ip_address = data.ip_address
    if data.firmware_version:
        reader.firmware_version = data.firmware_version
    
    await session.flush()
    
    return {
        "status": "acknowledged",
        "reader_id": reader_id,
        "timestamp": timestamp,
    }


@router.post("/connection_tokens", response_model=ConnectionTokenResponse, status_code=201)
async def create_connection_token(
    request: Request,
    data: ConnectionTokenCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.terminal import (
        TerminalConnectionToken, ConnectionTokenStatus
    )
    
    token_id = _generate_id("tct")
    timestamp = _get_timestamp()
    expires_at = timestamp + 3600
    token = _generate_token()
    
    connection_token = TerminalConnectionToken(
        id=token_id,
        reader_id=data.reader_id,
        token=token,
        expires_at=expires_at,
        status=ConnectionTokenStatus.ACTIVE,
        created=timestamp,
    )
    
    session.add(connection_token)
    await session.flush()
    
    return ConnectionTokenResponse(
        id=connection_token.id,
        reader_id=connection_token.reader_id,
        token=connection_token.token,
        expires_at=connection_token.expires_at,
        status=connection_token.status.value,
        created=connection_token.created,
    )


@router.post("/locations", response_model=LocationResponse, status_code=201)
async def create_location(
    request: Request,
    data: LocationCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.terminal import TerminalLocation
    
    account_id = _get_account_id(request)
    
    location_id = _generate_id("tml")
    timestamp = _get_timestamp()
    
    location = TerminalLocation(
        id=location_id,
        account_id=account_id,
        display_name=data.display_name,
        address_line1=data.address_line1,
        address_line2=data.address_line2,
        city=data.city,
        state=data.state,
        postal_code=data.postal_code,
        country=data.country.upper(),
        configuration_id=data.configuration_id,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(location)
    await session.flush()
    
    return LocationResponse(
        id=location.id,
        account_id=location.account_id,
        display_name=location.display_name,
        address_line1=location.address_line1,
        address_line2=location.address_line2,
        city=location.city,
        state=location.state,
        postal_code=location.postal_code,
        country=location.country,
        configuration_id=location.configuration_id,
        geolocation=location.geolocation,
        is_active=location.is_active,
        created=location.created,
        metadata=location.metadata_,
    )


@router.get("/locations", response_model=PaginatedResponse[LocationResponse])
async def list_locations(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    country: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalLocation
    
    account_id = _get_account_id(request)
    
    query = select(TerminalLocation)
    if account_id:
        query = query.where(TerminalLocation.account_id == account_id)
    if country:
        query = query.where(TerminalLocation.country == country.upper())
    if starting_after:
        query = query.where(TerminalLocation.id > starting_after)
    
    query = query.order_by(TerminalLocation.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    locations = list(result.scalars().all())
    
    has_more = len(locations) > limit
    if has_more:
        locations = locations[:limit]
    
    data = [
        LocationResponse(
            id=loc.id,
            account_id=loc.account_id,
            display_name=loc.display_name,
            address_line1=loc.address_line1,
            address_line2=loc.address_line2,
            city=loc.city,
            state=loc.state,
            postal_code=loc.postal_code,
            country=loc.country,
            configuration_id=loc.configuration_id,
            geolocation=loc.geolocation,
            is_active=loc.is_active,
            created=loc.created,
            metadata=loc.metadata_,
        )
        for loc in locations
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/locations/{location_id}", response_model=LocationResponse)
async def get_location(
    location_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalLocation
    
    query = select(TerminalLocation).where(TerminalLocation.id == location_id)
    result = await session.execute(query)
    location = result.scalar_one_or_none()
    
    if not location:
        raise NotFoundError(f"Location {location_id} not found")
    
    return LocationResponse(
        id=location.id,
        account_id=location.account_id,
        display_name=location.display_name,
        address_line1=location.address_line1,
        address_line2=location.address_line2,
        city=location.city,
        state=location.state,
        postal_code=location.postal_code,
        country=location.country,
        configuration_id=location.configuration_id,
        geolocation=location.geolocation,
        is_active=location.is_active,
        created=location.created,
        metadata=location.metadata_,
    )


@router.post("/payment_intents", response_model=TerminalPaymentIntentResponse, status_code=201)
async def create_terminal_payment(
    request: Request,
    data: TerminalPaymentIntentCreateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import (
        TerminalPayment, TerminalReader, TerminalPaymentStatus, CaptureMethod, ReaderStatus
    )
    
    reader_query = select(TerminalReader).where(TerminalReader.id == data.reader_id)
    reader_result = await session.execute(reader_query)
    reader = reader_result.scalar_one_or_none()
    
    if not reader:
        raise NotFoundError(f"Reader {data.reader_id} not found")
    
    if reader.status != ReaderStatus.ONLINE:
        raise TerminalError(f"Reader {data.reader_id} is not online", reader_id=data.reader_id)
    
    payment_id = _generate_id("tpi")
    timestamp = _get_timestamp()
    
    capture_method = CaptureMethod.AUTOMATIC
    if data.capture_method == "manual":
        capture_method = CaptureMethod.MANUAL
    
    payment = TerminalPayment(
        id=payment_id,
        reader_id=data.reader_id,
        amount=data.amount,
        currency=data.currency.lower(),
        status=TerminalPaymentStatus.PENDING,
        capture_method=capture_method,
        statement_descriptor=data.statement_descriptor,
        description=data.description,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    reader.status = ReaderStatus.BUSY
    
    session.add(payment)
    await session.flush()
    
    return TerminalPaymentIntentResponse(
        id=payment.id,
        reader_id=payment.reader_id,
        payment_intent_id=payment.payment_intent_id,
        amount=payment.amount,
        amount_capturable=payment.amount_capturable,
        amount_received=payment.amount_received,
        currency=payment.currency,
        status=payment.status.value,
        capture_method=payment.capture_method.value,
        statement_descriptor=payment.statement_descriptor,
        description=payment.description,
        receipt_number=payment.receipt_number,
        receipt_url=payment.receipt_url,
        tip_amount=payment.tip_amount,
        signature_collected=payment.signature_collected,
        offline=payment.offline,
        offline_id=payment.offline_id,
        processed_at=payment.processed_at,
        failed_at=payment.failed_at,
        canceled_at=payment.canceled_at,
        failure_code=payment.failure_code,
        failure_message=payment.failure_message,
        created=payment.created,
        metadata=payment.metadata_,
    )


@router.post("/payment_intents/{payment_id}/capture", response_model=TerminalPaymentIntentResponse)
async def capture_payment(
    payment_id: str,
    request: Request,
    data: TerminalPaymentCaptureRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import (
        TerminalPayment, TerminalReader, TerminalPaymentStatus, CaptureMethod
    )
    
    query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
    result = await session.execute(query)
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Payment {payment_id} not found")
    
    if payment.status != TerminalPaymentStatus.SUCCEEDED:
        raise TerminalError(f"Payment {payment_id} cannot be captured in current status", payment_id=payment_id)
    
    if payment.capture_method != CaptureMethod.MANUAL:
        raise TerminalError(f"Payment {payment_id} is automatic capture", payment_id=payment_id)
    
    capture_amount = data.amount if data.amount else payment.amount_capturable
    timestamp = _get_timestamp()
    
    payment.amount_received = capture_amount
    payment.amount_capturable = 0
    payment.processed_at = timestamp
    
    reader_query = select(TerminalReader).where(TerminalReader.id == payment.reader_id)
    reader_result = await session.execute(reader_query)
    reader = reader_result.scalar_one_or_none()
    if reader:
        reader.status = "online"
    
    await session.flush()
    
    return TerminalPaymentIntentResponse(
        id=payment.id,
        reader_id=payment.reader_id,
        payment_intent_id=payment.payment_intent_id,
        amount=payment.amount,
        amount_capturable=payment.amount_capturable,
        amount_received=payment.amount_received,
        currency=payment.currency,
        status=payment.status.value,
        capture_method=payment.capture_method.value,
        statement_descriptor=payment.statement_descriptor,
        description=payment.description,
        receipt_number=payment.receipt_number,
        receipt_url=payment.receipt_url,
        tip_amount=payment.tip_amount,
        signature_collected=payment.signature_collected,
        offline=payment.offline,
        offline_id=payment.offline_id,
        processed_at=payment.processed_at,
        failed_at=payment.failed_at,
        canceled_at=payment.canceled_at,
        failure_code=payment.failure_code,
        failure_message=payment.failure_message,
        created=payment.created,
        metadata=payment.metadata_,
    )


@router.post("/payment_intents/{payment_id}/cancel", response_model=TerminalPaymentIntentResponse)
async def cancel_payment(
    payment_id: str,
    request: Request,
    data: TerminalPaymentCancelRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import (
        TerminalPayment, TerminalReader, TerminalPaymentStatus
    )
    
    query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
    result = await session.execute(query)
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Payment {payment_id} not found")
    
    if payment.status not in [TerminalPaymentStatus.PENDING, TerminalPaymentStatus.IN_PROGRESS]:
        raise TerminalError(f"Payment {payment_id} cannot be canceled in current status", payment_id=payment_id)
    
    timestamp = _get_timestamp()
    payment.status = TerminalPaymentStatus.CANCELED
    payment.canceled_at = timestamp
    if data.reason:
        payment.failure_message = data.reason
    
    reader_query = select(TerminalReader).where(TerminalReader.id == payment.reader_id)
    reader_result = await session.execute(reader_query)
    reader = reader_result.scalar_one_or_none()
    if reader:
        reader.status = "online"
    
    await session.flush()
    
    return TerminalPaymentIntentResponse(
        id=payment.id,
        reader_id=payment.reader_id,
        payment_intent_id=payment.payment_intent_id,
        amount=payment.amount,
        amount_capturable=payment.amount_capturable,
        amount_received=payment.amount_received,
        currency=payment.currency,
        status=payment.status.value,
        capture_method=payment.capture_method.value,
        statement_descriptor=payment.statement_descriptor,
        description=payment.description,
        receipt_number=payment.receipt_number,
        receipt_url=payment.receipt_url,
        tip_amount=payment.tip_amount,
        signature_collected=payment.signature_collected,
        offline=payment.offline,
        offline_id=payment.offline_id,
        processed_at=payment.processed_at,
        failed_at=payment.failed_at,
        canceled_at=payment.canceled_at,
        failure_code=payment.failure_code,
        failure_message=payment.failure_message,
        created=payment.created,
        metadata=payment.metadata_,
    )


@router.post("/configurations", response_model=ConfigurationResponse, status_code=201)
async def create_configuration(
    request: Request,
    data: ConfigurationCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.terminal import TerminalConfiguration
    
    account_id = _get_account_id(request)
    
    config_id = _generate_id("tmc")
    timestamp = _get_timestamp()
    
    configuration = TerminalConfiguration(
        id=config_id,
        account_id=account_id,
        tipping_enabled=data.tipping_enabled if data.tipping_enabled is not None else True,
        tipping_percentages=data.tipping_percentages,
        tipping_fixed_amounts=data.tipping_fixed_amounts,
        collect_signature=data.collect_signature if data.collect_signature is not None else False,
        collect_name=data.collect_name if data.collect_name is not None else False,
        show_amount_confirmation=data.show_amount_confirmation if data.show_amount_confirmation is not None else True,
        timeout_seconds=data.timeout_seconds if data.timeout_seconds is not None else 120,
        ui_language=data.ui_language,
        receipt_language=data.receipt_language,
        receipt_header=data.receipt_header,
        receipt_footer=data.receipt_footer,
        offline_mode_enabled=data.offline_mode_enabled if data.offline_mode_enabled is not None else False,
        offline_transaction_limit=data.offline_transaction_limit if data.offline_transaction_limit is not None else 50000,
        offline_amount_limit=data.offline_amount_limit if data.offline_amount_limit is not None else 1000000,
        branding_logo_url=data.branding_logo_url,
        branding_primary_color=data.branding_primary_color,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(configuration)
    await session.flush()
    
    return ConfigurationResponse(
        id=configuration.id,
        account_id=configuration.account_id,
        tipping_enabled=configuration.tipping_enabled,
        tipping_percentages=configuration.tipping_percentages,
        tipping_fixed_amounts=configuration.tipping_fixed_amounts,
        collect_signature=configuration.collect_signature,
        collect_name=configuration.collect_name,
        show_amount_confirmation=configuration.show_amount_confirmation,
        timeout_seconds=configuration.timeout_seconds,
        idle_timeout_seconds=configuration.idle_timeout_seconds,
        verification_timeout_seconds=configuration.verification_timeout_seconds,
        ui_language=configuration.ui_language,
        receipt_language=configuration.receipt_language,
        receipt_email_enabled=configuration.receipt_email_enabled,
        receipt_sms_enabled=configuration.receipt_sms_enabled,
        receipt_header=configuration.receipt_header,
        receipt_footer=configuration.receipt_footer,
        offline_mode_enabled=configuration.offline_mode_enabled,
        offline_transaction_limit=configuration.offline_transaction_limit,
        offline_amount_limit=configuration.offline_amount_limit,
        offline_allow_charged_cards=configuration.offline_allow_charged_cards,
        offline_max_stored_transactions=configuration.offline_max_stored_transactions,
        branding_logo_url=configuration.branding_logo_url,
        branding_primary_color=configuration.branding_primary_color,
        branding_secondary_color=configuration.branding_secondary_color,
        is_default=configuration.is_default,
        is_active=configuration.is_active,
        created=configuration.created,
        metadata=configuration.metadata_,
    )


@router.get("/configurations", response_model=PaginatedResponse[ConfigurationResponse])
async def list_configurations(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    is_default: Optional[bool] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalConfiguration
    
    account_id = _get_account_id(request)
    
    query = select(TerminalConfiguration)
    if account_id:
        query = query.where(TerminalConfiguration.account_id == account_id)
    if is_default is not None:
        query = query.where(TerminalConfiguration.is_default == is_default)
    if starting_after:
        query = query.where(TerminalConfiguration.id > starting_after)
    
    query = query.order_by(TerminalConfiguration.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    configurations = list(result.scalars().all())
    
    has_more = len(configurations) > limit
    if has_more:
        configurations = configurations[:limit]
    
    data = [
        ConfigurationResponse(
            id=c.id,
            account_id=c.account_id,
            tipping_enabled=c.tipping_enabled,
            tipping_percentages=c.tipping_percentages,
            tipping_fixed_amounts=c.tipping_fixed_amounts,
            collect_signature=c.collect_signature,
            collect_name=c.collect_name,
            show_amount_confirmation=c.show_amount_confirmation,
            timeout_seconds=c.timeout_seconds,
            idle_timeout_seconds=c.idle_timeout_seconds,
            verification_timeout_seconds=c.verification_timeout_seconds,
            ui_language=c.ui_language,
            receipt_language=c.receipt_language,
            receipt_email_enabled=c.receipt_email_enabled,
            receipt_sms_enabled=c.receipt_sms_enabled,
            receipt_header=c.receipt_header,
            receipt_footer=c.receipt_footer,
            offline_mode_enabled=c.offline_mode_enabled,
            offline_transaction_limit=c.offline_transaction_limit,
            offline_amount_limit=c.offline_amount_limit,
            offline_allow_charged_cards=c.offline_allow_charged_cards,
            offline_max_stored_transactions=c.offline_max_stored_transactions,
            branding_logo_url=c.branding_logo_url,
            branding_primary_color=c.branding_primary_color,
            branding_secondary_color=c.branding_secondary_color,
            is_default=c.is_default,
            is_active=c.is_active,
            created=c.created,
            metadata=c.metadata_,
        )
        for c in configurations
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/actions", response_model=ActionResponse, status_code=201)
async def send_action(
    request: Request,
    data: ActionCreateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import (
        TerminalAction, TerminalReader, ActionType, ActionStatus, ReaderStatus
    )
    
    reader_query = select(TerminalReader).where(TerminalReader.id == data.reader_id)
    reader_result = await session.execute(reader_query)
    reader = reader_result.scalar_one_or_none()
    
    if not reader:
        raise NotFoundError(f"Reader {data.reader_id} not found")
    
    if reader.status != ReaderStatus.ONLINE:
        raise TerminalError(f"Reader {data.reader_id} is not online", reader_id=data.reader_id)
    
    action_type_map = {
        "display": ActionType.DISPLAY,
        "prompt": ActionType.PROMPT,
        "set_branding": ActionType.SET_BRANDING,
        "collect_signature": ActionType.COLLECT_SIGNATURE,
        "collect_tip": ActionType.COLLECT_TIP,
        "confirm_payment": ActionType.CONFIRM_PAYMENT,
        "refund": ActionType.REFUND,
    }
    
    if data.type not in action_type_map:
        raise ValidationError(f"Invalid action type: {data.type}")
    
    action_id = _generate_id("tac")
    timestamp = _get_timestamp()
    
    action = TerminalAction(
        id=action_id,
        reader_id=data.reader_id,
        type=action_type_map[data.type],
        status=ActionStatus.PENDING,
        request_data=data.request_data,
        timeout_seconds=data.timeout_seconds if data.timeout_seconds else 120,
        sent_at=timestamp,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(action)
    await session.flush()
    
    return ActionResponse(
        id=action.id,
        reader_id=action.reader_id,
        type=action.type.value,
        status=action.status.value,
        request_data=action.request_data,
        response_data=action.response_data,
        error_code=action.error_code,
        error_message=action.error_message,
        sent_at=action.sent_at,
        completed_at=action.completed_at,
        timeout_seconds=action.timeout_seconds,
        created=action.created,
        metadata=action.metadata_,
    )


@router.post("/actions/{action_id}/response", response_model=ActionResponse)
async def handle_action_response(
    action_id: str,
    request: Request,
    response_data: Dict[str, Any],
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalAction, ActionStatus
    
    query = select(TerminalAction).where(TerminalAction.id == action_id)
    result = await session.execute(query)
    action = result.scalar_one_or_none()
    
    if not action:
        raise NotFoundError(f"Action {action_id} not found")
    
    timestamp = _get_timestamp()
    action.status = ActionStatus.COMPLETED
    action.response_data = response_data
    action.completed_at = timestamp
    
    await session.flush()
    
    return ActionResponse(
        id=action.id,
        reader_id=action.reader_id,
        type=action.type.value,
        status=action.status.value,
        request_data=action.request_data,
        response_data=action.response_data,
        error_code=action.error_code,
        error_message=action.error_message,
        sent_at=action.sent_at,
        completed_at=action.completed_at,
        timeout_seconds=action.timeout_seconds,
        created=action.created,
        metadata=action.metadata_,
    )


@router.post("/payments/{payment_id}/receipt/email")
async def email_receipt(
    payment_id: str,
    request: Request,
    data: ReceiptEmailRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalPayment, TerminalReceipt
    
    payment_query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
    payment_result = await session.execute(payment_query)
    payment = payment_result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Payment {payment_id} not found")
    
    timestamp = _get_timestamp()
    receipt_id = _generate_id("trc")
    
    receipt = TerminalReceipt(
        id=receipt_id,
        payment_id=payment_id,
        reader_id=payment.reader_id,
        receipt_type="email",
        receipt_number=f"RE-{payment_id[-8:].upper()}",
        receipt_data=_generate_receipt_data(payment),
        email_sent=True,
        email_sent_at=timestamp,
        email_address=data.email,
        created=timestamp,
    )
    
    session.add(receipt)
    await session.flush()
    
    return {
        "sent": True,
        "payment_id": payment_id,
        "email": data.email,
        "receipt_id": receipt_id,
    }


@router.post("/payments/{payment_id}/receipt/sms")
async def sms_receipt(
    payment_id: str,
    request: Request,
    data: ReceiptSmsRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalPayment, TerminalReceipt
    
    payment_query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
    payment_result = await session.execute(payment_query)
    payment = payment_result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Payment {payment_id} not found")
    
    timestamp = _get_timestamp()
    receipt_id = _generate_id("trc")
    
    receipt = TerminalReceipt(
        id=receipt_id,
        payment_id=payment_id,
        reader_id=payment.reader_id,
        receipt_type="sms",
        receipt_number=f"RE-{payment_id[-8:].upper()}",
        receipt_data=_generate_receipt_data(payment),
        sms_sent=True,
        sms_sent_at=timestamp,
        phone_number=data.phone_number,
        created=timestamp,
    )
    
    session.add(receipt)
    await session.flush()
    
    return {
        "sent": True,
        "payment_id": payment_id,
        "phone_number": data.phone_number,
        "receipt_id": receipt_id,
    }


@router.get("/payments/{payment_id}/receipt")
async def get_receipt(
    payment_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalPayment, TerminalReceipt
    
    payment_query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
    payment_result = await session.execute(payment_query)
    payment = payment_result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Payment {payment_id} not found")
    
    receipt_query = select(TerminalReceipt).where(TerminalReceipt.payment_id == payment_id)
    receipt_result = await session.execute(receipt_query)
    receipts = list(receipt_result.scalars().all())
    
    return {
        "payment_id": payment_id,
        "receipt_number": f"RE-{payment_id[-8:].upper()}",
        "receipt_data": _generate_receipt_data(payment),
        "receipts": [
            {
                "id": r.id,
                "type": r.receipt_type,
                "sent_at": r.email_sent_at or r.sms_sent_at,
            }
            for r in receipts
        ],
    }


@router.post("/payments/{payment_id}/signature")
async def collect_signature(
    payment_id: str,
    request: Request,
    signature_data: Dict[str, Any],
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalPayment, TerminalSignature
    
    query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
    result = await session.execute(query)
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Payment {payment_id} not found")
    
    timestamp = _get_timestamp()
    signature_id = _generate_id("tsg")
    
    signature = TerminalSignature(
        id=signature_id,
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
    
    session.add(signature)
    await session.flush()
    
    return {
        "collected": True,
        "payment_id": payment_id,
        "signature_id": signature_id,
    }


@router.post("/payments/{payment_id}/tip")
async def collect_tip(
    payment_id: str,
    request: Request,
    tip_data: Dict[str, Any],
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.terminal import TerminalPayment
    
    query = select(TerminalPayment).where(TerminalPayment.id == payment_id)
    result = await session.execute(query)
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundError(f"Payment {payment_id} not found")
    
    timestamp = _get_timestamp()
    tip_amount = tip_data.get("amount", 0)
    
    payment.tip_amount = tip_amount
    payment.tip_collected_at = timestamp
    
    await session.flush()
    
    return {
        "collected": True,
        "payment_id": payment_id,
        "tip_amount": tip_amount,
        "total_amount": payment.amount + tip_amount,
    }


def _get_device_capabilities(device_type: str) -> Dict[str, Any]:
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


def _generate_receipt_data(payment) -> Dict[str, Any]:
    return {
        "payment_id": payment.id,
        "amount": payment.amount,
        "currency": payment.currency.upper(),
        "tip_amount": payment.tip_amount,
        "total_amount": payment.amount + (payment.tip_amount or 0),
        "created": payment.created,
        "status": payment.status,
    }
