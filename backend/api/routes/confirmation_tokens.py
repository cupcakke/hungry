from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, ConfirmationError

router = APIRouter()


class ConfirmationTokenCreateRequest(BaseModel):
    type: str = Field(..., description="Token type: payment or setup")
    payment_intent_id: Optional[str] = Field(default=None, description="Payment intent ID")
    setup_intent_id: Optional[str] = Field(default=None, description="Setup intent ID")
    payment_method_types: Optional[List[str]] = Field(default=None, description="Allowed payment method types")
    return_url: Optional[str] = Field(default=None, description="Return URL after confirmation")
    expires_in_seconds: Optional[int] = Field(default=3600, description="Token expiration time in seconds")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ConfirmationTokenResponse(BaseModel):
    id: str
    object: str = "confirmation.token"
    account_id: Optional[str] = None
    payment_intent_id: Optional[str] = None
    setup_intent_id: Optional[str] = None
    type: str
    status: str
    client_secret: str
    expires_at: int
    confirmed_at: Optional[int] = None
    used_at: Optional[int] = None
    payment_method_id: Optional[str] = None
    payment_method_types: Optional[List[str]] = None
    return_url: Optional[str] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ConfirmationTokenConfirmRequest(BaseModel):
    payment_method_id: str = Field(..., description="Payment method ID to confirm with")


class ConfirmationTokenCancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Cancellation reason")


class ChallengeResponse(BaseModel):
    id: str
    object: str = "confirmation.challenge"
    confirmation_token_id: str
    confirmation_session_id: Optional[str] = None
    challenge_type: str
    challenge_data: Optional[Dict[str, Any]] = None
    status: str
    timeout_seconds: int
    expires_at: int
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    attempt_count: int
    max_attempts: int
    created: int


class ChallengeCompleteRequest(BaseModel):
    challenge_data: Optional[Dict[str, Any]] = Field(default=None, description="Challenge result data")
    success: bool = Field(..., description="Whether challenge was successful")
    failure_reason: Optional[str] = Field(default=None, description="Failure reason if unsuccessful")


class OTPSendRequest(BaseModel):
    delivery_method: str = Field(..., description="Delivery method: sms, email, or voice")
    phone_number: Optional[str] = Field(default=None, description="Phone number for SMS/voice")
    email: Optional[str] = Field(default=None, description="Email address for email delivery")
    code_length: Optional[int] = Field(default=6, description="OTP code length")
    expires_in_seconds: Optional[int] = Field(default=300, description="OTP expiration time")


class OTPSendResponse(BaseModel):
    id: str
    object: str = "otp.verification"
    confirmation_token_id: str
    delivery_method: str
    destination: str
    expires_at: int
    attempts_remaining: int
    resend_count: int
    max_resends: int
    created: int


class OTPVerifyRequest(BaseModel):
    code: str = Field(..., description="OTP code to verify")


class OTPVerifyResponse(BaseModel):
    id: str
    object: str = "otp.verification"
    confirmation_token_id: str
    delivery_method: str
    verified: bool
    verified_at: Optional[int] = None
    attempts_remaining: int
    created: int


class ThreeDSecureDataResponse(BaseModel):
    id: str
    object: str = "three_d_secure"
    confirmation_token_id: str
    version: str
    acs_url: Optional[str] = None
    pareq: Optional[str] = None
    md: Optional[str] = None
    cres: Optional[str] = None
    authentication_type: Optional[str] = None
    liability_shift: Optional[str] = None
    cavv: Optional[str] = None
    eci: Optional[str] = None
    xid: Optional[str] = None
    status: Optional[str] = None
    authenticated_at: Optional[int] = None
    created: int


class ThreeDSAuthenticateRequest(BaseModel):
    cres: Optional[str] = Field(default=None, description="CRES response from ACS")
    pares: Optional[str] = Field(default=None, description="PARES response for 3DS v1")
    md: Optional[str] = Field(default=None, description="MD value for 3DS v1")


class ThreeDSAuthenticateResponse(BaseModel):
    id: str
    object: str = "three_d_secure"
    confirmation_token_id: str
    version: str
    status: str
    liability_shift: Optional[str] = None
    authentication_type: Optional[str] = None
    authenticated_at: Optional[int] = None
    created: int


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


def _generate_client_secret() -> str:
    import secrets
    return f"ct_secret_{secrets.token_urlsafe(32)}"


@router.post("", response_model=ConfirmationTokenResponse, status_code=201)
async def create_confirmation_token(
    request: Request,
    data: ConfirmationTokenCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ConfirmationTokenType, ConfirmationTokenStatus
    )

    account_id = _get_account_id(request)

    type_enum = ConfirmationTokenType.PAYMENT if data.type == "payment" else ConfirmationTokenType.SETUP

    token_id = _generate_id("ct")
    timestamp = _get_timestamp()
    client_secret = _generate_client_secret()

    token = ConfirmationToken(
        id=token_id,
        account_id=account_id,
        payment_intent_id=data.payment_intent_id,
        setup_intent_id=data.setup_intent_id,
        type=type_enum,
        status=ConfirmationTokenStatus.PENDING,
        client_secret=client_secret,
        expires_at=timestamp + (data.expires_in_seconds or 3600),
        payment_method_types=data.payment_method_types or ["card"],
        return_url=data.return_url,
        created=timestamp,
        metadata_=data.metadata,
    )

    session.add(token)
    await session.flush()

    return ConfirmationTokenResponse(
        id=token.id,
        account_id=token.account_id,
        payment_intent_id=token.payment_intent_id,
        setup_intent_id=token.setup_intent_id,
        type=token.type.value,
        status=token.status.value,
        client_secret=token.client_secret,
        expires_at=token.expires_at,
        confirmed_at=token.confirmed_at,
        used_at=token.used_at,
        payment_method_id=token.payment_method_id,
        payment_method_types=token.payment_method_types,
        return_url=token.return_url,
        created=token.created,
        metadata=token.metadata_,
    )


@router.get("", response_model=PaginatedResponse[ConfirmationTokenResponse])
async def list_confirmation_tokens(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    payment_intent_id: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import ConfirmationToken

    account_id = _get_account_id(request)

    query = select(ConfirmationToken)
    if account_id:
        query = query.where(ConfirmationToken.account_id == account_id)
    if payment_intent_id:
        query = query.where(ConfirmationToken.payment_intent_id == payment_intent_id)
    if status:
        query = query.where(ConfirmationToken.status == status)
    if starting_after:
        query = query.where(ConfirmationToken.id > starting_after)

    query = query.order_by(ConfirmationToken.created_at.desc()).limit(limit + 1)

    result = await session.execute(query)
    tokens = list(result.scalars().all())

    has_more = len(tokens) > limit
    if has_more:
        tokens = tokens[:limit]

    data = [
        ConfirmationTokenResponse(
            id=t.id,
            account_id=t.account_id,
            payment_intent_id=t.payment_intent_id,
            setup_intent_id=t.setup_intent_id,
            type=t.type.value,
            status=t.status.value,
            client_secret=t.client_secret,
            expires_at=t.expires_at,
            confirmed_at=t.confirmed_at,
            used_at=t.used_at,
            payment_method_id=t.payment_method_id,
            payment_method_types=t.payment_method_types,
            return_url=t.return_url,
            created=t.created,
            metadata=t.metadata_,
        )
        for t in tokens
    ]

    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/{token_id}", response_model=ConfirmationTokenResponse)
async def get_confirmation_token(
    token_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import ConfirmationToken

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    return ConfirmationTokenResponse(
        id=token.id,
        account_id=token.account_id,
        payment_intent_id=token.payment_intent_id,
        setup_intent_id=token.setup_intent_id,
        type=token.type.value,
        status=token.status.value,
        client_secret=token.client_secret,
        expires_at=token.expires_at,
        confirmed_at=token.confirmed_at,
        used_at=token.used_at,
        payment_method_id=token.payment_method_id,
        payment_method_types=token.payment_method_types,
        return_url=token.return_url,
        created=token.created,
        metadata=token.metadata_,
    )


@router.post("/{token_id}/confirm", response_model=ConfirmationTokenResponse)
async def confirm_confirmation_token(
    token_id: str,
    request: Request,
    data: ConfirmationTokenConfirmRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ConfirmationTokenStatus
    )

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    timestamp = _get_timestamp()

    if token.status == ConfirmationTokenStatus.EXPIRED:
        raise ConfirmationError("Token has expired")
    if token.status == ConfirmationTokenStatus.USED:
        raise ConfirmationError("Token has already been used")
    if token.status == ConfirmationTokenStatus.CONFIRMED:
        raise ConfirmationError("Token has already been confirmed")
    if token.expires_at < timestamp:
        token.status = ConfirmationTokenStatus.EXPIRED
        await session.flush()
        raise ConfirmationError("Token has expired")

    token.payment_method_id = data.payment_method_id
    token.status = ConfirmationTokenStatus.CONFIRMED
    token.confirmed_at = timestamp

    await session.flush()

    return ConfirmationTokenResponse(
        id=token.id,
        account_id=token.account_id,
        payment_intent_id=token.payment_intent_id,
        setup_intent_id=token.setup_intent_id,
        type=token.type.value,
        status=token.status.value,
        client_secret=token.client_secret,
        expires_at=token.expires_at,
        confirmed_at=token.confirmed_at,
        used_at=token.used_at,
        payment_method_id=token.payment_method_id,
        payment_method_types=token.payment_method_types,
        return_url=token.return_url,
        created=token.created,
        metadata=token.metadata_,
    )


@router.post("/{token_id}/cancel", response_model=ConfirmationTokenResponse)
async def cancel_confirmation_token(
    token_id: str,
    request: Request,
    data: Optional[ConfirmationTokenCancelRequest] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ConfirmationTokenStatus
    )

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    if token.status not in [ConfirmationTokenStatus.PENDING, ConfirmationTokenStatus.CONFIRMED]:
        raise ConfirmationError(f"Token cannot be canceled in status {token.status}")

    token.status = ConfirmationTokenStatus.EXPIRED

    await session.flush()

    return ConfirmationTokenResponse(
        id=token.id,
        account_id=token.account_id,
        payment_intent_id=token.payment_intent_id,
        setup_intent_id=token.setup_intent_id,
        type=token.type.value,
        status=token.status.value,
        client_secret=token.client_secret,
        expires_at=token.expires_at,
        confirmed_at=token.confirmed_at,
        used_at=token.used_at,
        payment_method_id=token.payment_method_id,
        payment_method_types=token.payment_method_types,
        return_url=token.return_url,
        created=token.created,
        metadata=token.metadata_,
    )


@router.post("/{token_id}/challenge", response_model=ChallengeResponse, status_code=201)
async def get_challenge_data(
    token_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ConfirmationChallenge, ConfirmationTokenStatus, ChallengeStatus
    )

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    challenge_query = select(ConfirmationChallenge).where(
        ConfirmationChallenge.confirmation_token_id == token_id
    ).order_by(ConfirmationChallenge.created_at.desc())
    challenge_result = await session.execute(challenge_query)
    challenge = challenge_result.scalar_one_or_none()

    if not challenge:
        raise NotFoundError(f"No challenge found for token {token_id}")

    return ChallengeResponse(
        id=challenge.id,
        confirmation_token_id=challenge.confirmation_token_id,
        confirmation_session_id=challenge.confirmation_session_id,
        challenge_type=challenge.challenge_type.value,
        challenge_data=challenge.challenge_data,
        status=challenge.status.value,
        timeout_seconds=challenge.timeout_seconds,
        expires_at=challenge.expires_at,
        started_at=challenge.started_at,
        completed_at=challenge.completed_at,
        attempt_count=challenge.attempt_count,
        max_attempts=challenge.max_attempts,
        created=challenge.created,
    )


@router.post("/{token_id}/challenge/complete", response_model=ChallengeResponse)
async def complete_challenge(
    token_id: str,
    request: Request,
    data: ChallengeCompleteRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ConfirmationChallenge, ChallengeStatus
    )

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    challenge_query = select(ConfirmationChallenge).where(
        ConfirmationChallenge.confirmation_token_id == token_id
    ).order_by(ConfirmationChallenge.created_at.desc())
    challenge_result = await session.execute(challenge_query)
    challenge = challenge_result.scalar_one_or_none()

    if not challenge:
        raise NotFoundError(f"No challenge found for token {token_id}")

    timestamp = _get_timestamp()

    if data.success:
        challenge.status = ChallengeStatus.COMPLETED
        challenge.completed_at = timestamp
        if data.challenge_data:
            challenge.challenge_data = data.challenge_data
    else:
        challenge.status = ChallengeStatus.FAILED
        challenge.failed_at = timestamp
        challenge.failure_reason = data.failure_reason

    await session.flush()

    return ChallengeResponse(
        id=challenge.id,
        confirmation_token_id=challenge.confirmation_token_id,
        confirmation_session_id=challenge.confirmation_session_id,
        challenge_type=challenge.challenge_type.value,
        challenge_data=challenge.challenge_data,
        status=challenge.status.value,
        timeout_seconds=challenge.timeout_seconds,
        expires_at=challenge.expires_at,
        started_at=challenge.started_at,
        completed_at=challenge.completed_at,
        attempt_count=challenge.attempt_count,
        max_attempts=challenge.max_attempts,
        created=challenge.created,
    )


@router.post("/{token_id}/otp/send", response_model=OTPSendResponse, status_code=201)
async def send_otp(
    token_id: str,
    request: Request,
    data: OTPSendRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ConfirmationChallenge, OTPVerification,
        ConfirmationTokenStatus, ChallengeType, ChallengeStatus, OTPDeliveryMethod
    )
    import hashlib
    import secrets

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    if data.delivery_method == "sms" and not data.phone_number:
        raise ValidationError("Phone number required for SMS delivery")
    if data.delivery_method == "email" and not data.email:
        raise ValidationError("Email required for email delivery")

    timestamp = _get_timestamp()

    method_map = {
        "sms": OTPDeliveryMethod.SMS,
        "email": OTPDeliveryMethod.EMAIL,
        "voice": OTPDeliveryMethod.VOICE,
    }

    challenge = ConfirmationChallenge(
        id=_generate_id("ch"),
        confirmation_token_id=token_id,
        challenge_type=ChallengeType.OTP,
        status=ChallengeStatus.PENDING,
        timeout_seconds=data.expires_in_seconds or 300,
        expires_at=timestamp + (data.expires_in_seconds or 300),
        created=timestamp,
    )
    session.add(challenge)
    await session.flush()

    code = "".join(secrets.choice("0123456789") for _ in range(data.code_length or 6))
    salt = secrets.token_hex(16)
    hash_value = hashlib.sha256(f"{salt}{code}".encode()).hexdigest()
    code_hash = f"{salt}:{hash_value}"

    otp = OTPVerification(
        id=_generate_id("otp"),
        confirmation_token_id=token_id,
        challenge_id=challenge.id,
        delivery_method=method_map[data.delivery_method],
        phone_number=data.phone_number,
        email=data.email,
        code_hash=code_hash,
        code_length=data.code_length or 6,
        attempts_remaining=3,
        max_attempts=3,
        max_resends=3,
        expires_at=timestamp + (data.expires_in_seconds or 300),
        sent_at=timestamp,
        created=timestamp,
    )
    session.add(otp)
    await session.flush()

    destination = data.phone_number or data.email
    if destination:
        if "@" in destination:
            parts = destination.split("@")
            local = parts[0]
            if len(local) > 2:
                destination = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{parts[1]}"
        else:
            if len(destination) > 4:
                destination = f"{'*' * (len(destination) - 4)}{destination[-4:]}"

    return OTPSendResponse(
        id=otp.id,
        confirmation_token_id=otp.confirmation_token_id,
        delivery_method=otp.delivery_method.value,
        destination=destination,
        expires_at=otp.expires_at,
        attempts_remaining=otp.attempts_remaining,
        resend_count=otp.resend_count,
        max_resends=otp.max_resends,
        created=otp.created,
    )


@router.post("/{token_id}/otp/verify", response_model=OTPVerifyResponse)
async def verify_otp(
    token_id: str,
    request: Request,
    data: OTPVerifyRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, OTPVerification, ConfirmationChallenge, ChallengeStatus
    )
    import hashlib
    import secrets

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    otp_query = select(OTPVerification).where(
        OTPVerification.confirmation_token_id == token_id
    ).order_by(OTPVerification.created_at.desc())
    otp_result = await session.execute(otp_query)
    otp = otp_result.scalar_one_or_none()

    if not otp:
        raise NotFoundError(f"No OTP found for token {token_id}")

    timestamp = _get_timestamp()

    if otp.expires_at < timestamp:
        otp.failed_at = timestamp
        otp.failure_reason = "OTP expired"
        await session.flush()
        return OTPVerifyResponse(
            id=otp.id,
            confirmation_token_id=otp.confirmation_token_id,
            delivery_method=otp.delivery_method.value,
            verified=False,
            verified_at=otp.verified_at,
            attempts_remaining=otp.attempts_remaining,
            created=otp.created,
        )

    if otp.verified_at:
        return OTPVerifyResponse(
            id=otp.id,
            confirmation_token_id=otp.confirmation_token_id,
            delivery_method=otp.delivery_method.value,
            verified=True,
            verified_at=otp.verified_at,
            attempts_remaining=otp.attempts_remaining,
            created=otp.created,
        )

    try:
        salt, hash_value = otp.code_hash.split(":")
        computed_hash = hashlib.sha256(f"{salt}{data.code}".encode()).hexdigest()
        code_valid = secrets.compare_digest(hash_value, computed_hash)
    except ValueError:
        code_valid = False

    if not code_valid:
        otp.attempts_remaining -= 1
        await session.flush()
        return OTPVerifyResponse(
            id=otp.id,
            confirmation_token_id=otp.confirmation_token_id,
            delivery_method=otp.delivery_method.value,
            verified=False,
            verified_at=None,
            attempts_remaining=otp.attempts_remaining,
            created=otp.created,
        )

    otp.verified_at = timestamp
    otp.attempts_remaining = otp.max_attempts

    if otp.challenge_id:
        challenge_query = select(ConfirmationChallenge).where(
            ConfirmationChallenge.id == otp.challenge_id
        )
        challenge_result = await session.execute(challenge_query)
        challenge = challenge_result.scalar_one_or_none()
        if challenge:
            challenge.status = ChallengeStatus.COMPLETED
            challenge.completed_at = timestamp

    await session.flush()

    return OTPVerifyResponse(
        id=otp.id,
        confirmation_token_id=otp.confirmation_token_id,
        delivery_method=otp.delivery_method.value,
        verified=True,
        verified_at=otp.verified_at,
        attempts_remaining=otp.attempts_remaining,
        created=otp.created,
    )


@router.get("/{token_id}/3ds", response_model=ThreeDSecureDataResponse)
async def get_3ds_data(
    token_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ThreeDSecureData
    )

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    three_ds_query = select(ThreeDSecureData).where(
        ThreeDSecureData.confirmation_token_id == token_id
    ).order_by(ThreeDSecureData.created_at.desc())
    three_ds_result = await session.execute(three_ds_query)
    three_ds = three_ds_result.scalar_one_or_none()

    if not three_ds:
        raise NotFoundError(f"No 3DS data found for token {token_id}")

    return ThreeDSecureDataResponse(
        id=three_ds.id,
        confirmation_token_id=three_ds.confirmation_token_id,
        version=three_ds.version.value,
        acs_url=three_ds.acs_url,
        pareq=three_ds.pareq,
        md=three_ds.md,
        cres=three_ds.cres,
        authentication_type=three_ds.authentication_type.value if three_ds.authentication_type else None,
        liability_shift=three_ds.liability_shift.value if three_ds.liability_shift else None,
        cavv=three_ds.cavv,
        eci=three_ds.eci,
        xid=three_ds.xid,
        status=three_ds.status,
        authenticated_at=three_ds.authenticated_at,
        created=three_ds.created,
    )


@router.post("/{token_id}/3ds/authenticate", response_model=ThreeDSAuthenticateResponse)
async def complete_3ds_auth(
    token_id: str,
    request: Request,
    data: ThreeDSAuthenticateRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.confirmation_tokens import (
        ConfirmationToken, ThreeDSecureData, ConfirmationChallenge, ChallengeStatus, LiabilityShift
    )
    import base64
    import json

    query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
    result = await session.execute(query)
    token = result.scalar_one_or_none()

    if not token:
        raise NotFoundError(f"Confirmation token {token_id} not found")

    three_ds_query = select(ThreeDSecureData).where(
        ThreeDSecureData.confirmation_token_id == token_id
    ).order_by(ThreeDSecureData.created_at.desc())
    three_ds_result = await session.execute(three_ds_query)
    three_ds = three_ds_result.scalar_one_or_none()

    if not three_ds:
        raise NotFoundError(f"No 3DS data found for token {token_id}")

    timestamp = _get_timestamp()

    if data.cres:
        three_ds.cres = data.cres
        try:
            decoded = base64.b64decode(data.cres).decode()
            cres_data = json.loads(decoded)
            trans_status = cres_data.get("transStatus", "N")
            if trans_status == "Y":
                three_ds.liability_shift = LiabilityShift.YES
                three_ds.authentication_type = "challenge"
            else:
                three_ds.liability_shift = LiabilityShift.NO
            three_ds.eci = cres_data.get("eci")
            three_ds.cavv = cres_data.get("cavv")
        except Exception:
            three_ds.liability_shift = LiabilityShift.UNKNOWN

    if data.pares:
        three_ds.pares = data.pares
        three_ds.md = data.md
        three_ds.liability_shift = LiabilityShift.YES
        three_ds.authentication_type = "challenge"

    three_ds.authenticated_at = timestamp
    three_ds.status = "authenticated"

    if three_ds.challenge_id:
        challenge_query = select(ConfirmationChallenge).where(
            ConfirmationChallenge.id == three_ds.challenge_id
        )
        challenge_result = await session.execute(challenge_query)
        challenge = challenge_result.scalar_one_or_none()
        if challenge:
            challenge.status = ChallengeStatus.COMPLETED
            challenge.completed_at = timestamp

    await session.flush()

    return ThreeDSAuthenticateResponse(
        id=three_ds.id,
        confirmation_token_id=three_ds.confirmation_token_id,
        version=three_ds.version.value,
        status=three_ds.status,
        liability_shift=three_ds.liability_shift.value if three_ds.liability_shift else None,
        authentication_type=three_ds.authentication_type.value if three_ds.authentication_type else None,
        authenticated_at=three_ds.authenticated_at,
        created=three_ds.created,
    )
