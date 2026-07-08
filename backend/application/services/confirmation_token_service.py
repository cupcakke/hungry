from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import secrets
import hashlib
import json
import re
import time

from sqlalchemy import select, update, and_, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.confirmation_tokens import (
    ConfirmationToken,
    ConfirmationSession,
    ConfirmationChallenge,
    ThreeDSecureData,
    OTPVerification,
    BiometricChallenge,
    AppRedirectData,
    ChallengeTimeoutConfig,
    LiabilityShiftRecord,
    ConfirmationTokenType,
    ConfirmationTokenStatus,
    ConfirmationSessionStatus,
    ChallengeType,
    ChallengeStatus,
    ThreeDSVersion,
    AuthenticationType,
    LiabilityShift,
    OTPDeliveryMethod,
    BiometricType,
    AppRedirectStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    ConfirmationError,
)
from payment_platform.shared.utils.identifiers import generate_id


@dataclass
class TokenCreateResult:
    token_id: str
    client_secret: str
    status: str
    expires_at: int


@dataclass
class ChallengeResult:
    challenge_id: str
    challenge_type: str
    status: str
    challenge_data: Dict[str, Any]
    expires_at: int


@dataclass
class OTPSendResult:
    otp_id: str
    delivery_method: str
    destination: str
    expires_at: int
    attempts_remaining: int


@dataclass
class ThreeDSAuthResult:
    three_d_secure_id: str
    version: str
    acs_url: Optional[str]
    pareq: Optional[str]
    status: str
    liability_shift: Optional[str]


class ConfirmationTokenService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        token_type: str,
        payment_intent_id: Optional[str] = None,
        setup_intent_id: Optional[str] = None,
        payment_method_types: Optional[List[str]] = None,
        return_url: Optional[str] = None,
        expires_in_seconds: int = 3600,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConfirmationToken:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        client_secret = self._generate_client_secret()

        type_enum = ConfirmationTokenType.PAYMENT if token_type == "payment" else ConfirmationTokenType.SETUP

        token = ConfirmationToken(
            id=self._generate_id("ct"),
            account_id=account_id,
            payment_intent_id=payment_intent_id,
            setup_intent_id=setup_intent_id,
            type=type_enum,
            status=ConfirmationTokenStatus.PENDING,
            client_secret=client_secret,
            expires_at=timestamp + expires_in_seconds,
            payment_method_types=payment_method_types or ["card"],
            return_url=return_url,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(token)
        await self.session.flush()
        return token

    async def get(self, token_id: str) -> Optional[ConfirmationToken]:
        query = select(ConfirmationToken).where(ConfirmationToken.id == token_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_client_secret(self, client_secret: str) -> Optional[ConfirmationToken]:
        query = select(ConfirmationToken).where(ConfirmationToken.client_secret == client_secret)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        account_id: Optional[str] = None,
        payment_intent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[ConfirmationToken]:
        query = select(ConfirmationToken)

        if account_id:
            query = query.where(ConfirmationToken.account_id == account_id)
        if payment_intent_id:
            query = query.where(ConfirmationToken.payment_intent_id == payment_intent_id)
        if status:
            query = query.where(ConfirmationToken.status == status)

        query = query.order_by(ConfirmationToken.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def confirm(
        self,
        token_id: str,
        payment_method_id: str,
    ) -> ConfirmationToken:
        token = await self.get(token_id)
        if not token:
            raise NotFoundError(f"Confirmation token {token_id} not found")

        self._validate_token_status(token)

        timestamp = int(datetime.now(timezone.utc).timestamp())
        token.payment_method_id = payment_method_id
        token.status = ConfirmationTokenStatus.CONFIRMED
        token.confirmed_at = timestamp

        await self.session.flush()
        return token

    async def cancel(self, token_id: str) -> ConfirmationToken:
        token = await self.get(token_id)
        if not token:
            raise NotFoundError(f"Confirmation token {token_id} not found")

        if token.status not in [ConfirmationTokenStatus.PENDING, ConfirmationTokenStatus.CONFIRMED]:
            raise ConfirmationError(f"Token cannot be canceled in status {token.status}")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        token.status = ConfirmationTokenStatus.EXPIRED

        await self.session.flush()
        return token

    async def mark_used(self, token_id: str) -> ConfirmationToken:
        token = await self.get(token_id)
        if not token:
            raise NotFoundError(f"Confirmation token {token_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        token.status = ConfirmationTokenStatus.USED
        token.used_at = timestamp

        await self.session.flush()
        return token

    async def expire_tokens(self) -> int:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        query = (
            update(ConfirmationToken)
            .where(
                and_(
                    ConfirmationToken.status == ConfirmationTokenStatus.PENDING,
                    ConfirmationToken.expires_at < timestamp,
                )
            )
            .values(status=ConfirmationTokenStatus.EXPIRED)
        )
        result = await self.session.execute(query)
        await self.session.flush()
        return result.rowcount

    def _validate_token_status(self, token: ConfirmationToken):
        timestamp = int(datetime.now(timezone.utc).timestamp())

        if token.status == ConfirmationTokenStatus.EXPIRED:
            raise ConfirmationError("Token has expired")
        if token.status == ConfirmationTokenStatus.USED:
            raise ConfirmationError("Token has already been used")
        if token.status == ConfirmationTokenStatus.CONFIRMED:
            raise ConfirmationError("Token has already been confirmed")
        if token.expires_at < timestamp:
            raise ConfirmationError("Token has expired")

    def _generate_client_secret(self) -> str:
        return f"ct_secret_{secrets.token_urlsafe(32)}"

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ConfirmationSessionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.token_service = ConfirmationTokenService(session)

    async def create_session(
        self,
        confirmation_token_id: str,
        return_url: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        customer_id: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_name: Optional[str] = None,
        customer_phone: Optional[str] = None,
        billing_address: Optional[Dict[str, Any]] = None,
        shipping_address: Optional[Dict[str, Any]] = None,
        payment_method_options: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConfirmationSession:
        token = await self.token_service.get(confirmation_token_id)
        if not token:
            raise NotFoundError(f"Confirmation token {confirmation_token_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        session_obj = ConfirmationSession(
            id=self._generate_id("cs"),
            confirmation_token_id=confirmation_token_id,
            return_url=return_url or token.return_url,
            success_url=success_url,
            cancel_url=cancel_url,
            status=ConfirmationSessionStatus.PENDING,
            customer_id=customer_id,
            customer_email=customer_email,
            customer_name=customer_name,
            customer_phone=customer_phone,
            billing_address=billing_address,
            shipping_address=shipping_address,
            payment_method_options=payment_method_options,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(session_obj)
        await self.session.flush()
        return session_obj

    async def get(self, session_id: str) -> Optional[ConfirmationSession]:
        query = select(ConfirmationSession).where(ConfirmationSession.id == session_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_token(self, token_id: str) -> Optional[ConfirmationSession]:
        query = select(ConfirmationSession).where(ConfirmationSession.confirmation_token_id == token_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def handle_return(
        self,
        session_id: str,
        success: bool,
        redirect_url: Optional[str] = None,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> ConfirmationSession:
        session_obj = await self.get(session_id)
        if not session_obj:
            raise NotFoundError(f"Confirmation session {session_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if success:
            session_obj.status = ConfirmationSessionStatus.SUCCEEDED
            session_obj.completed_at = timestamp
            session_obj.redirect_url = redirect_url or session_obj.success_url
        else:
            session_obj.status = ConfirmationSessionStatus.FAILED
            session_obj.failed_at = timestamp
            session_obj.failure_code = failure_code
            session_obj.failure_message = failure_message
            session_obj.redirect_url = redirect_url or session_obj.cancel_url

        await self.session.flush()
        return session_obj

    async def update_next_action(
        self,
        session_id: str,
        next_action: Dict[str, Any],
    ) -> ConfirmationSession:
        session_obj = await self.get(session_id)
        if not session_obj:
            raise NotFoundError(f"Confirmation session {session_id} not found")

        session_obj.next_action = next_action
        await self.session.flush()
        return session_obj

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ChallengeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.token_service = ConfirmationTokenService(session)

    async def create_challenge(
        self,
        confirmation_token_id: str,
        challenge_type: str,
        confirmation_session_id: Optional[str] = None,
        challenge_data: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
        max_attempts: int = 3,
    ) -> ConfirmationChallenge:
        token = await self.token_service.get(confirmation_token_id)
        if not token:
            raise NotFoundError(f"Confirmation token {confirmation_token_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        type_map = {
            "3ds": ChallengeType.THREE_DS,
            "otp": ChallengeType.OTP,
            "biometric": ChallengeType.BIOMETRIC,
            "app_redirect": ChallengeType.APP_REDIRECT,
        }

        challenge_type_enum = type_map.get(challenge_type)
        if not challenge_type_enum:
            raise ValidationError(f"Invalid challenge type: {challenge_type}")

        challenge = ConfirmationChallenge(
            id=self._generate_id("ch"),
            confirmation_token_id=confirmation_token_id,
            confirmation_session_id=confirmation_session_id,
            challenge_type=challenge_type_enum,
            challenge_data=challenge_data,
            status=ChallengeStatus.PENDING,
            timeout_seconds=timeout_seconds,
            expires_at=timestamp + timeout_seconds,
            max_attempts=max_attempts,
            created=timestamp,
        )

        self.session.add(challenge)
        await self.session.flush()
        return challenge

    async def get(self, challenge_id: str) -> Optional[ConfirmationChallenge]:
        query = select(ConfirmationChallenge).where(ConfirmationChallenge.id == challenge_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_token(self, token_id: str) -> List[ConfirmationChallenge]:
        query = select(ConfirmationChallenge).where(
            ConfirmationChallenge.confirmation_token_id == token_id
        ).order_by(ConfirmationChallenge.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_challenge(self, token_id: str) -> Optional[ConfirmationChallenge]:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        query = select(ConfirmationChallenge).where(
            and_(
                ConfirmationChallenge.confirmation_token_id == token_id,
                ConfirmationChallenge.status.in_([ChallengeStatus.PENDING, ChallengeStatus.IN_PROGRESS]),
                ConfirmationChallenge.expires_at > timestamp,
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def start_challenge(self, challenge_id: str) -> ConfirmationChallenge:
        challenge = await self.get(challenge_id)
        if not challenge:
            raise NotFoundError(f"Challenge {challenge_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        challenge.status = ChallengeStatus.IN_PROGRESS
        challenge.started_at = timestamp

        await self.session.flush()
        return challenge

    async def complete_challenge(
        self,
        challenge_id: str,
        challenge_result: Optional[Dict[str, Any]] = None,
    ) -> ConfirmationChallenge:
        challenge = await self.get(challenge_id)
        if not challenge:
            raise NotFoundError(f"Challenge {challenge_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        challenge.status = ChallengeStatus.COMPLETED
        challenge.completed_at = timestamp

        if challenge_result:
            challenge.challenge_data = challenge_result

        await self.session.flush()
        return challenge

    async def fail_challenge(
        self,
        challenge_id: str,
        reason: str,
    ) -> ConfirmationChallenge:
        challenge = await self.get(challenge_id)
        if not challenge:
            raise NotFoundError(f"Challenge {challenge_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        challenge.status = ChallengeStatus.FAILED
        challenge.failed_at = timestamp
        challenge.failure_reason = reason

        await self.session.flush()
        return challenge

    async def increment_attempt(self, challenge_id: str) -> ConfirmationChallenge:
        challenge = await self.get(challenge_id)
        if not challenge:
            raise NotFoundError(f"Challenge {challenge_id} not found")

        challenge.attempt_count += 1

        if challenge.attempt_count >= challenge.max_attempts:
            await self.fail_challenge(challenge_id, "Maximum attempts exceeded")

        await self.session.flush()
        return challenge

    async def expire_challenges(self) -> int:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        query = (
            update(ConfirmationChallenge)
            .where(
                and_(
                    ConfirmationChallenge.status.in_([ChallengeStatus.PENDING, ChallengeStatus.IN_PROGRESS]),
                    ConfirmationChallenge.expires_at < timestamp,
                )
            )
            .values(status=ChallengeStatus.EXPIRED)
        )
        result = await self.session.execute(query)
        await self.session.flush()
        return result.rowcount

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ThreeDSecureService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.challenge_service = ChallengeService(session)
        self.token_service = ConfirmationTokenService(session)

    async def initiate_3ds(
        self,
        confirmation_token_id: str,
        card_brand: str,
        amount: int,
        currency: str,
        confirmation_session_id: Optional[str] = None,
        browser_info: Optional[Dict[str, Any]] = None,
        device_info: Optional[Dict[str, Any]] = None,
        return_url: Optional[str] = None,
    ) -> ThreeDSecureData:
        challenge = await self.challenge_service.create_challenge(
            confirmation_token_id=confirmation_token_id,
            challenge_type="3ds",
            confirmation_session_id=confirmation_session_id,
            timeout_seconds=600,
        )

        timestamp = int(datetime.now(timezone.utc).timestamp())
        version = self._determine_version(card_brand)

        three_ds_data = ThreeDSecureData(
            id=self._generate_id("3ds"),
            confirmation_token_id=confirmation_token_id,
            challenge_id=challenge.id,
            version=version,
            three_ds_requestor_url=return_url,
            browser_info=browser_info,
            device_info=device_info,
            status="initialized",
            created=timestamp,
        )

        if version != ThreeDSVersion.V1:
            three_ds_data.three_ds_server_trans_id = self._generate_server_trans_id()
            three_ds_data.three_ds_requestor_id = self._generate_requestor_id()

        self.session.add(three_ds_data)
        await self.challenge_service.start_challenge(challenge.id)
        await self.session.flush()

        return three_ds_data

    async def get(self, three_ds_id: str) -> Optional[ThreeDSecureData]:
        query = select(ThreeDSecureData).where(ThreeDSecureData.id == three_ds_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_token(self, token_id: str) -> Optional[ThreeDSecureData]:
        query = select(ThreeDSecureData).where(
            ThreeDSecureData.confirmation_token_id == token_id
        ).order_by(ThreeDSecureData.created_at.desc())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def process_3ds_callback(
        self,
        three_ds_id: str,
        cres: Optional[str] = None,
        pares: Optional[str] = None,
        md: Optional[str] = None,
    ) -> ThreeDSecureData:
        three_ds_data = await self.get(three_ds_id)
        if not three_ds_data:
            raise NotFoundError(f"3DS data {three_ds_id} not found")

        if cres:
            three_ds_data.cres = cres
            auth_result = self._parse_cres(cres)
            three_ds_data.authentication_type = auth_result.get("authentication_type")
            three_ds_data.liability_shift = auth_result.get("liability_shift")
            three_ds_data.eci = auth_result.get("eci")
            three_ds_data.cavv = auth_result.get("cavv")

        if pares:
            three_ds_data.pares = pares
            three_ds_data.md = md
            auth_result = self._parse_pares(pares)
            three_ds_data.authentication_type = auth_result.get("authentication_type")
            three_ds_data.liability_shift = auth_result.get("liability_shift")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        three_ds_data.authenticated_at = timestamp
        three_ds_data.status = "authenticated"

        if three_ds_data.challenge_id:
            await self.challenge_service.complete_challenge(three_ds_data.challenge_id)

        await self.session.flush()
        return three_ds_data

    async def verify_3ds(
        self,
        three_ds_id: str,
    ) -> Tuple[bool, Optional[str]]:
        three_ds_data = await self.get(three_ds_id)
        if not three_ds_data:
            raise NotFoundError(f"3DS data {three_ds_id} not found")

        if three_ds_data.status != "authenticated":
            return False, "Not authenticated"

        if three_ds_data.liability_shift == LiabilityShift.NO:
            return False, "No liability shift"

        return True, None

    async def prepare_challenge(
        self,
        three_ds_id: str,
        acs_url: str,
        acs_trans_id: str,
        acs_reference_number: str,
        challenge_window_size: str = "05",
    ) -> Dict[str, Any]:
        three_ds_data = await self.get(three_ds_id)
        if not three_ds_data:
            raise NotFoundError(f"3DS data {three_ds_id} not found")

        three_ds_data.acs_url = acs_url
        three_ds_data.acs_trans_id = acs_trans_id
        three_ds_data.acs_reference_number = acs_reference_number
        three_ds_data.challenge_window_size = challenge_window_size
        three_ds_data.status = "challenge_required"

        await self.session.flush()

        pareq = self._generate_pareq(
            three_ds_data.three_ds_server_trans_id,
            three_ds_data.acs_trans_id,
            three_ds_data.challenge_window_size,
        )

        return {
            "three_d_secure_id": three_ds_data.id,
            "acs_url": acs_url,
            "pareq": pareq,
            "md": three_ds_data.id,
            "challenge_window_size": challenge_window_size,
        }

    async def create_liability_shift_record(
        self,
        confirmation_token_id: str,
        three_ds_id: str,
        payment_intent_id: Optional[str] = None,
        charge_id: Optional[str] = None,
        card_brand: Optional[str] = None,
        card_fingerprint: Optional[str] = None,
    ) -> LiabilityShiftRecord:
        three_ds_data = await self.get(three_ds_id)
        if not three_ds_data:
            raise NotFoundError(f"3DS data {three_ds_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        record = LiabilityShiftRecord(
            id=self._generate_id("ls"),
            confirmation_token_id=confirmation_token_id,
            three_d_secure_id=three_ds_id,
            payment_intent_id=payment_intent_id,
            charge_id=charge_id,
            card_brand=card_brand,
            card_fingerprint=card_fingerprint,
            liability_shift=three_ds_data.liability_shift or LiabilityShift.UNKNOWN,
            authentication_type=three_ds_data.authentication_type,
            cavv=three_ds_data.cavv,
            eci=three_ds_data.eci,
            xid=three_ds_data.xid,
            ds_trans_id=three_ds_data.ds_trans_id,
            three_ds_version=three_ds_data.version.value,
            authenticated_at=three_ds_data.authenticated_at,
            created=timestamp,
        )

        self.session.add(record)
        await self.session.flush()
        return record

    def _determine_version(self, card_brand: str) -> ThreeDSVersion:
        version_map = {
            "visa": ThreeDSVersion.V2_2,
            "mastercard": ThreeDSVersion.V2_2,
            "amex": ThreeDSVersion.V2_1,
            "discover": ThreeDSVersion.V2_1,
            "jcb": ThreeDSVersion.V2_1,
        }
        return version_map.get(card_brand.lower(), ThreeDSVersion.V2_0)

    def _generate_server_trans_id(self) -> str:
        return f"3dss-{secrets.token_urlsafe(32)}"

    def _generate_requestor_id(self) -> str:
        return f"3dsr-{secrets.token_urlsafe(16)}"

    def _generate_pareq(self, server_trans_id: str, acs_trans_id: str, window_size: str) -> str:
        pareq_data = {
            "threeDSServerTransID": server_trans_id,
            "acsTransID": acs_trans_id,
            "challengeWindowSize": window_size,
            "messageType": "CReq",
            "messageVersion": "2.2.0",
        }
        import base64
        return base64.b64encode(json.dumps(pareq_data).encode()).decode()

    def _parse_cres(self, cres: str) -> Dict[str, Any]:
        import base64
        try:
            decoded = base64.b64decode(cres).decode()
            data = json.loads(decoded)
            return {
                "authentication_type": data.get("authenticationType"),
                "liability_shift": LiabilityShift.YES if data.get("transStatus") == "Y" else LiabilityShift.NO,
                "eci": data.get("eci"),
                "cavv": data.get(" cavv"),
            }
        except Exception:
            return {
                "authentication_type": None,
                "liability_shift": LiabilityShift.UNKNOWN,
            }

    def _parse_pares(self, pares: str) -> Dict[str, Any]:
        import base64
        try:
            decoded = base64.b64decode(pares).decode()
            data = json.loads(decoded)
            return {
                "authentication_type": "challenge",
                "liability_shift": LiabilityShift.YES if data.get("status") == "Y" else LiabilityShift.NO,
            }
        except Exception:
            return {
                "authentication_type": None,
                "liability_shift": LiabilityShift.UNKNOWN,
            }

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class OTPService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.challenge_service = ChallengeService(session)
        self.token_service = ConfirmationTokenService(session)

    async def generate_otp(
        self,
        confirmation_token_id: str,
        delivery_method: str,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
        code_length: int = 6,
        expires_in_seconds: int = 300,
        max_attempts: int = 3,
        max_resends: int = 3,
    ) -> OTPVerification:
        method_map = {
            "sms": OTPDeliveryMethod.SMS,
            "email": OTPDeliveryMethod.EMAIL,
            "voice": OTPDeliveryMethod.VOICE,
        }

        delivery_enum = method_map.get(delivery_method)
        if not delivery_enum:
            raise ValidationError(f"Invalid delivery method: {delivery_method}")

        if delivery_enum == OTPDeliveryMethod.SMS and not phone_number:
            raise ValidationError("Phone number required for SMS delivery")

        if delivery_enum == OTPDeliveryMethod.EMAIL and not email:
            raise ValidationError("Email required for email delivery")

        challenge = await self.challenge_service.create_challenge(
            confirmation_token_id=confirmation_token_id,
            challenge_type="otp",
            timeout_seconds=expires_in_seconds,
            max_attempts=max_attempts,
        )

        timestamp = int(datetime.now(timezone.utc).timestamp())
        code = self._generate_code(code_length)
        code_hash = self._hash_code(code)

        otp = OTPVerification(
            id=self._generate_id("otp"),
            confirmation_token_id=confirmation_token_id,
            challenge_id=challenge.id,
            delivery_method=delivery_enum,
            phone_number=phone_number,
            email=email,
            code_hash=code_hash,
            code_length=code_length,
            attempts_remaining=max_attempts,
            max_attempts=max_attempts,
            max_resends=max_resends,
            expires_at=timestamp + expires_in_seconds,
            created=timestamp,
        )

        self.session.add(otp)
        await self.session.flush()

        return otp

    async def get(self, otp_id: str) -> Optional[OTPVerification]:
        query = select(OTPVerification).where(OTPVerification.id == otp_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_token(self, token_id: str) -> Optional[OTPVerification]:
        query = select(OTPVerification).where(
            OTPVerification.confirmation_token_id == token_id
        ).order_by(OTPVerification.created_at.desc())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def send_otp(
        self,
        otp_id: str,
    ) -> OTPSendResult:
        otp = await self.get(otp_id)
        if not otp:
            raise NotFoundError(f"OTP verification {otp_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if otp.expires_at < timestamp:
            raise ConfirmationError("OTP has expired")

        otp.sent_at = timestamp

        if otp.challenge_id:
            await self.challenge_service.start_challenge(otp.challenge_id)

        await self.session.flush()

        destination = otp.phone_number if otp.delivery_method == OTPDeliveryMethod.SMS else otp.email

        return OTPSendResult(
            otp_id=otp.id,
            delivery_method=otp.delivery_method.value,
            destination=self._mask_destination(destination),
            expires_at=otp.expires_at,
            attempts_remaining=otp.attempts_remaining,
        )

    async def resend_otp(
        self,
        otp_id: str,
    ) -> OTPVerification:
        otp = await self.get(otp_id)
        if not otp:
            raise NotFoundError(f"OTP verification {otp_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if otp.resend_count >= otp.max_resends:
            raise ConfirmationError("Maximum resend attempts exceeded")

        if otp.last_resend_at:
            cooldown_end = otp.last_resend_at + otp.resend_cooldown_seconds
            if timestamp < cooldown_end:
                raise ConfirmationError(f"Resend cooldown active")

        new_code = self._generate_code(otp.code_length)
        otp.code_hash = self._hash_code(new_code)
        otp.resend_count += 1
        otp.last_resend_at = timestamp
        otp.sent_at = timestamp
        otp.attempts_remaining = otp.max_attempts

        await self.session.flush()
        return otp

    async def verify_otp(
        self,
        otp_id: str,
        code: str,
    ) -> Tuple[bool, OTPVerification]:
        otp = await self.get(otp_id)
        if not otp:
            raise NotFoundError(f"OTP verification {otp_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if otp.expires_at < timestamp:
            otp.failed_at = timestamp
            otp.failure_reason = "OTP expired"
            await self.session.flush()
            return False, otp

        if otp.attempts_remaining <= 0:
            otp.failed_at = timestamp
            otp.failure_reason = "No attempts remaining"
            await self.session.flush()
            return False, otp

        if otp.verified_at:
            return True, otp

        if not self._verify_code(code, otp.code_hash):
            otp.attempts_remaining -= 1
            await self.session.flush()

            if otp.challenge_id:
                await self.challenge_service.increment_attempt(otp.challenge_id)

            return False, otp

        otp.verified_at = timestamp
        otp.attempts_remaining = otp.max_attempts

        if otp.challenge_id:
            await self.challenge_service.complete_challenge(otp.challenge_id)

        await self.session.flush()
        return True, otp

    def _generate_code(self, length: int) -> str:
        return "".join(secrets.choice("0123456789") for _ in range(length))

    def _hash_code(self, code: str) -> str:
        salt = secrets.token_hex(16)
        hash_value = hashlib.sha256(f"{salt}{code}".encode()).hexdigest()
        return f"{salt}:{hash_value}"

    def _verify_code(self, code: str, stored_hash: str) -> bool:
        try:
            salt, hash_value = stored_hash.split(":")
            computed_hash = hashlib.sha256(f"{salt}{code}".encode()).hexdigest()
            return secrets.compare_digest(hash_value, computed_hash)
        except ValueError:
            return False

    def _mask_destination(self, destination: str) -> str:
        if "@" in destination:
            parts = destination.split("@")
            local = parts[0]
            if len(local) <= 2:
                return f"{'*' * len(local)}@{parts[1]}"
            return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{parts[1]}"
        else:
            if len(destination) <= 4:
                return "*" * len(destination)
            return f"{'*' * (len(destination) - 4)}{destination[-4:]}"

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class BiometricService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.challenge_service = ChallengeService(session)
        self.token_service = ConfirmationTokenService(session)

    async def create_challenge(
        self,
        confirmation_token_id: str,
        biometric_type: str,
        device_id: Optional[str] = None,
        device_info: Optional[Dict[str, Any]] = None,
        confidence_threshold: Decimal = Decimal("0.9000"),
        expires_in_seconds: int = 300,
    ) -> BiometricChallenge:
        type_map = {
            "fingerprint": BiometricType.FINGERPRINT,
            "face": BiometricType.FACE,
            "voice": BiometricType.VOICE,
            "iris": BiometricType.IRIS,
        }

        biometric_enum = type_map.get(biometric_type)
        if not biometric_enum:
            raise ValidationError(f"Invalid biometric type: {biometric_type}")

        challenge = await self.challenge_service.create_challenge(
            confirmation_token_id=confirmation_token_id,
            challenge_type="biometric",
            timeout_seconds=expires_in_seconds,
        )

        timestamp = int(datetime.now(timezone.utc).timestamp())
        challenge_token = self._generate_challenge_token()

        biometric = BiometricChallenge(
            id=self._generate_id("bio"),
            confirmation_token_id=confirmation_token_id,
            challenge_id=challenge.id,
            biometric_type=biometric_enum,
            challenge_token=challenge_token,
            device_id=device_id,
            device_info=device_info,
            confidence_threshold=confidence_threshold,
            expires_at=timestamp + expires_in_seconds,
            created=timestamp,
        )

        self.session.add(biometric)
        await self.session.flush()

        return biometric

    async def get(self, biometric_id: str) -> Optional[BiometricChallenge]:
        query = select(BiometricChallenge).where(BiometricChallenge.id == biometric_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_token(self, token_id: str) -> Optional[BiometricChallenge]:
        query = select(BiometricChallenge).where(
            BiometricChallenge.confirmation_token_id == token_id
        ).order_by(BiometricChallenge.created_at.desc())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_challenge_token(self, challenge_token: str) -> Optional[BiometricChallenge]:
        query = select(BiometricChallenge).where(BiometricChallenge.challenge_token == challenge_token)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def verify_biometric(
        self,
        biometric_id: str,
        verification_data: Dict[str, Any],
        confidence_score: Decimal,
        liveness_score: Optional[Decimal] = None,
        liveness_check_passed: Optional[bool] = None,
    ) -> Tuple[bool, BiometricChallenge]:
        biometric = await self.get(biometric_id)
        if not biometric:
            raise NotFoundError(f"Biometric challenge {biometric_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if biometric.expires_at < timestamp:
            biometric.failed_at = timestamp
            biometric.failure_reason = "Challenge expired"
            await self.session.flush()
            return False, biometric

        if biometric.verified_at:
            return True, biometric

        biometric.verification_data = verification_data
        biometric.confidence_score = confidence_score
        biometric.liveness_score = liveness_score
        biometric.liveness_check_passed = liveness_check_passed

        passed = confidence_score >= biometric.confidence_threshold

        if liveness_check_passed is False:
            passed = False
            biometric.failure_reason = "Liveness check failed"

        if passed:
            biometric.verified_at = timestamp

            if biometric.challenge_id:
                await self.challenge_service.complete_challenge(biometric.challenge_id)
        else:
            if biometric.challenge_id:
                await self.challenge_service.increment_attempt(biometric.challenge_id)

        await self.session.flush()
        return passed, biometric

    async def fail_challenge(
        self,
        biometric_id: str,
        reason: str,
    ) -> BiometricChallenge:
        biometric = await self.get(biometric_id)
        if not biometric:
            raise NotFoundError(f"Biometric challenge {biometric_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        biometric.failed_at = timestamp
        biometric.failure_reason = reason

        if biometric.challenge_id:
            await self.challenge_service.fail_challenge(biometric.challenge_id, reason)

        await self.session.flush()
        return biometric

    def _generate_challenge_token(self) -> str:
        return f"bio_{secrets.token_urlsafe(48)}"

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class AppRedirectService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.challenge_service = ChallengeService(session)
        self.token_service = ConfirmationTokenService(session)

    async def generate_redirect(
        self,
        confirmation_token_id: str,
        app_url: str,
        fallback_url: Optional[str] = None,
        package_name: Optional[str] = None,
        android_package_name: Optional[str] = None,
        ios_bundle_id: Optional[str] = None,
        universal_link: Optional[str] = None,
        app_link: Optional[str] = None,
        deep_link_config: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
    ) -> AppRedirectData:
        challenge = await self.challenge_service.create_challenge(
            confirmation_token_id=confirmation_token_id,
            challenge_type="app_redirect",
            timeout_seconds=timeout_seconds,
        )

        timestamp = int(datetime.now(timezone.utc).timestamp())

        redirect = AppRedirectData(
            id=self._generate_id("ar"),
            confirmation_token_id=confirmation_token_id,
            challenge_id=challenge.id,
            app_url=app_url,
            fallback_url=fallback_url,
            package_name=package_name,
            android_package_name=android_package_name,
            ios_bundle_id=ios_bundle_id,
            universal_link=universal_link,
            app_link=app_link,
            deep_link_config=deep_link_config,
            status=AppRedirectStatus.PENDING,
            timeout_seconds=timeout_seconds,
            expires_at=timestamp + timeout_seconds,
            created=timestamp,
        )

        self.session.add(redirect)
        await self.session.flush()

        return redirect

    async def get(self, redirect_id: str) -> Optional[AppRedirectData]:
        query = select(AppRedirectData).where(AppRedirectData.id == redirect_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_token(self, token_id: str) -> Optional[AppRedirectData]:
        query = select(AppRedirectData).where(
            AppRedirectData.confirmation_token_id == token_id
        ).order_by(AppRedirectData.created_at.desc())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def mark_launched(self, redirect_id: str) -> AppRedirectData:
        redirect = await self.get(redirect_id)
        if not redirect:
            raise NotFoundError(f"App redirect {redirect_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        redirect.status = AppRedirectStatus.LAUNCHED
        redirect.launched_at = timestamp

        if redirect.challenge_id:
            await self.challenge_service.start_challenge(redirect.challenge_id)

        await self.session.flush()
        return redirect

    async def handle_return(
        self,
        redirect_id: str,
        success: bool,
        return_intent: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> AppRedirectData:
        redirect = await self.get(redirect_id)
        if not redirect:
            raise NotFoundError(f"App redirect {redirect_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if success:
            redirect.status = AppRedirectStatus.COMPLETED
            redirect.completed_at = timestamp
            redirect.return_intent = return_intent

            if redirect.challenge_id:
                await self.challenge_service.complete_challenge(redirect.challenge_id)
        else:
            redirect.status = AppRedirectStatus.FAILED
            redirect.failed_at = timestamp

            if redirect.challenge_id:
                await self.challenge_service.fail_challenge(
                    redirect.challenge_id,
                    error_message or "App redirect failed",
                )

        await self.session.flush()
        return redirect

    async def check_timeout(self, redirect_id: str) -> Optional[AppRedirectData]:
        redirect = await self.get(redirect_id)
        if not redirect:
            return None

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if redirect.status in [AppRedirectStatus.PENDING, AppRedirectStatus.LAUNCHED]:
            if redirect.expires_at < timestamp:
                redirect.status = AppRedirectStatus.TIMED_OUT
                redirect.failed_at = timestamp

                if redirect.challenge_id:
                    await self.challenge_service.fail_challenge(
                        redirect.challenge_id,
                        "App redirect timed out",
                    )

                await self.session.flush()
                return redirect

        return None

    async def get_fallback_url(self, redirect_id: str) -> Optional[str]:
        redirect = await self.get(redirect_id)
        if not redirect:
            return None
        return redirect.fallback_url

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
