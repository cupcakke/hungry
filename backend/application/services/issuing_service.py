import time
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from payment_platform.backend.domain.models import Cardholder, IssuingCard, IssuingAuthorization, IssuingTransaction
from payment_platform.backend.domain.issuing import (
    CardholderVerification, SpendingLimit, IssuingDispute,
    CardToken, AuthorizationRequest, CardNetworkResponse, FraudScore,
    SpendingControlRule, CardholderStatus, CardholderType, CardType,
    IssuingCardStatus, AuthorizationStatus, SpendingLimitInterval,
)
from payment_platform.shared.utils.identifiers import (
    generate_cardholder_id, generate_issuing_card_id,
    generate_issuing_authorization_id, generate_issuing_transaction_id,
    generate_id,
)
from payment_platform.shared.utils.crypto import (
    encrypt_card_number, decrypt_card_number,
    generate_card_fingerprint, mask_card_number,
)
from payment_platform.shared.exceptions import NotFoundError, ValidationError


class CardholderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_cardholder(
        self,
        account_id: Optional[str],
        cardholder_type: str,
        name: str,
        billing_address: Dict[str, str],
        email: Optional[str] = None,
        phone_number: Optional[str] = None,
        individual: Optional[Dict] = None,
        company: Optional[Dict] = None,
        spending_controls: Optional[Dict] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Cardholder:
        if cardholder_type == "individual" and not individual:
            raise ValidationError("Individual details required for individual cardholder type")
        if cardholder_type == "company" and not company:
            raise ValidationError("Company details required for company cardholder type")
        cardholder_id = generate_cardholder_id()
        cardholder = Cardholder(
            id=cardholder_id,
            account_id=account_id,
            type=cardholder_type,
            name=name,
            email=email,
            phone_number=phone_number,
            billing_address_line1=billing_address.get("line1", ""),
            billing_address_line2=billing_address.get("line2"),
            billing_address_city=billing_address.get("city", ""),
            billing_address_state=billing_address.get("state"),
            billing_address_postal_code=billing_address.get("postal_code", ""),
            billing_address_country=billing_address.get("country", ""),
            individual=individual,
            company=company,
            spending_controls=spending_controls,
            metadata_=metadata or {},
            requirements={"disabled_reason": None, "past_due": []},
            status=CardholderStatus.PENDING.value,
            created=int(time.time()),
            livemode=False,
        )
        self.session.add(cardholder)
        await self.session.flush()
        if spending_controls and spending_controls.get("spending_limits"):
            for limit_data in spending_controls["spending_limits"]:
                limit = SpendingLimit(
                    id=generate_id("spl"),
                    amount=limit_data.get("amount", 0),
                    interval=limit_data.get("interval", "monthly"),
                    categories=limit_data.get("categories"),
                    cardholder_id=cardholder_id,
                    created=int(time.time()),
                    enforced=True,
                )
                self.session.add(limit)
        await self.session.flush()
        return cardholder

    async def verify_cardholder(
        self,
        cardholder_id: str,
        account_id: Optional[str],
        verification_type: str,
        document_type: Optional[str] = None,
        document_front_id: Optional[str] = None,
        document_back_id: Optional[str] = None,
    ) -> CardholderVerification:
        cardholder = await self._get_cardholder(cardholder_id)
        if not cardholder:
            raise NotFoundError(f"Cardholder {cardholder_id} not found")
        verification_id = generate_id("ver")
        verification = CardholderVerification(
            id=verification_id,
            cardholder_id=cardholder_id,
            account_id=account_id,
            status="pending",
            verification_type=verification_type,
            document_type=document_type,
            document_front_id=document_front_id,
            document_back_id=document_back_id,
            requirements={
                "disabled_reason": None,
                "past_due": [],
            },
            created=int(time.time()),
            livemode=False,
        )
        self.session.add(verification)
        await self.session.flush()
        cardholder.status = CardholderStatus.ACTIVE.value
        cardholder.requirements = {"disabled_reason": None, "past_due": []}
        await self.session.flush()
        return verification

    async def _get_cardholder(self, cardholder_id: str) -> Optional[Cardholder]:
        query = select(Cardholder).where(Cardholder.id == cardholder_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_cardholder(
        self,
        cardholder_id: str,
        **kwargs: Any,
    ) -> Cardholder:
        cardholder = await self._get_cardholder(cardholder_id)
        if not cardholder:
            raise NotFoundError(f"Cardholder {cardholder_id} not found")
        for key, value in kwargs.items():
            if hasattr(cardholder, key):
                setattr(cardholder, key, value)
        await self.session.flush()
        return cardholder


class CardService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_card(
        self,
        account_id: Optional[str],
        cardholder_id: str,
        card_type: str,
        currency: str,
        initial_status: str = "inactive",
        spending_controls: Optional[Dict] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> IssuingCard:
        cardholder = await self._get_cardholder(cardholder_id)
        if not cardholder:
            raise NotFoundError(f"Cardholder {cardholder_id} not found")
        if cardholder.status != CardholderStatus.ACTIVE.value:
            raise ValidationError(f"Cardholder {cardholder_id} is not active")
        card_id = generate_issuing_card_id()
        pan, cvc = self._generate_card_number()
        encrypted_pan = encrypt_card_number(pan)
        encrypted_cvc = encrypt_card_number(cvc)
        last4 = pan[-4:]
        exp_month, exp_year = self._calculate_expiry()
        brand = self._determine_brand()
        card = IssuingCard(
            id=card_id,
            account_id=account_id,
            cardholder_id=cardholder_id,
            type=card_type,
            status=initial_status or IssuingCardStatus.INACTIVE.value,
            brand=brand,
            currency=currency.lower(),
            last4=last4,
            exp_month=exp_month,
            exp_year=exp_year,
            spending_controls=spending_controls,
            metadata_=metadata or {},
            cvc_status="active",
            number_status="active",
            created=int(time.time()),
            livemode=False,
        )
        self.session.add(card)
        await self.session.flush()
        token = self._generate_token()
        card_token = CardToken(
            id=generate_id("tok"),
            card_id=card_id,
            account_id=account_id,
            token=token,
            encrypted_pan=encrypted_pan,
            encrypted_cvc=encrypted_cvc,
            token_type="pan_token",
            status="active",
            created=int(time.time()),
            livemode=False,
        )
        self.session.add(card_token)
        await self.session.flush()
        if spending_controls and spending_controls.get("spending_limits"):
            for limit_data in spending_controls["spending_limits"]:
                limit = SpendingLimit(
                    id=generate_id("spl"),
                    amount=limit_data.get("amount", 0),
                    interval=limit_data.get("interval", "monthly"),
                    categories=limit_data.get("categories"),
                    card_id=card_id,
                    created=int(time.time()),
                    enforced=True,
                )
                self.session.add(limit)
        await self.session.flush()
        return card

    def _generate_card_number(self) -> Tuple[str, str]:
        pan_prefix = "424242"
        pan_rest = "".join([str(secrets.randbelow(10)) for _ in range(9)])
        pan_base = f"{pan_prefix}{pan_rest}"
        checksum = self._calculate_luhn_checksum(pan_base)
        pan = f"{pan_base}{checksum}"
        cvc = "".join([str(secrets.randbelow(10)) for _ in range(3)])
        return pan, cvc

    def _calculate_luhn_checksum(self, number: str) -> int:
        digits = [int(d) for d in number]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        checksum = sum(odd_digits)
        for d in even_digits:
            doubled = d * 2
            checksum += doubled if doubled < 10 else doubled - 9
        return (10 - checksum % 10) % 10

    def _calculate_expiry(self) -> Tuple[int, int]:
        now = datetime.now(timezone.utc)
        exp_month = now.month
        exp_year = now.year + 4
        return exp_month, exp_year

    def _determine_brand(self) -> str:
        return "Visa"

    def _generate_token(self) -> str:
        return f"tok_issuing_{secrets.token_urlsafe(32)}"

    async def activate_card(self, card_id: str) -> IssuingCard:
        card = await self._get_card(card_id)
        if not card:
            raise NotFoundError(f"Card {card_id} not found")
        if card.status not in [IssuingCardStatus.INACTIVE.value, IssuingCardStatus.PENDING.value]:
            raise ValidationError(f"Card {card_id} cannot be activated from status {card.status}")
        card.status = IssuingCardStatus.ACTIVE.value
        await self.session.flush()
        return card

    async def deactivate_card(self, card_id: str) -> IssuingCard:
        card = await self._get_card(card_id)
        if not card:
            raise NotFoundError(f"Card {card_id} not found")
        if card.status == IssuingCardStatus.CANCELED.value:
            raise ValidationError(f"Card {card_id} is already canceled")
        card.status = IssuingCardStatus.INACTIVE.value
        await self.session.flush()
        return card

    async def get_card_details(self, card_id: str) -> Tuple[IssuingCard, str, str]:
        card = await self._get_card(card_id)
        if not card:
            raise NotFoundError(f"Card {card_id} not found")
        query = select(CardToken).where(
            and_(
                CardToken.card_id == card_id,
                CardToken.status == "active",
            )
        ).order_by(CardToken.created_at.desc())
        result = await self.session.execute(query)
        token = result.scalar_one_or_none()
        if not token:
            raise NotFoundError(f"No active token found for card {card_id}")
        pan = decrypt_card_number(token.encrypted_pan)
        cvc = decrypt_card_number(token.encrypted_cvc)
        token.last_accessed_at = int(time.time())
        await self.session.flush()
        return card, pan, cvc

    async def _get_card(self, card_id: str) -> Optional[IssuingCard]:
        query = select(IssuingCard).where(IssuingCard.id == card_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _get_cardholder(self, cardholder_id: str) -> Optional[Cardholder]:
        query = select(Cardholder).where(Cardholder.id == cardholder_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


class AuthorizationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.spending_control = SpendingControlService(session)
        self.network = CardNetworkIntegration(session)

    async def create_authorization(
        self,
        account_id: Optional[str],
        card_id: str,
        amount: int,
        currency: str,
        merchant_data: Dict[str, Any],
        authorization_method: str,
        verification_data: Optional[Dict] = None,
    ) -> IssuingAuthorization:
        card = await self._get_card(card_id)
        if not card:
            raise NotFoundError(f"Card {card_id} not found")
        if card.status != IssuingCardStatus.ACTIVE.value:
            raise ValidationError(f"Card {card_id} is not active")
        cardholder = await self._get_cardholder(card.cardholder_id)
        if not cardholder:
            raise NotFoundError(f"Cardholder {card.cardholder_id} not found")
        if cardholder.status != CardholderStatus.ACTIVE.value:
            raise ValidationError(f"Cardholder {cardholder.id} is not active")
        limits_ok, limit_reason = await self.spending_control.check_limits(
            card_id=card_id,
            cardholder_id=card.cardholder_id,
            amount=amount,
            currency=currency,
            merchant_category=merchant_data.get("category_code"),
        )
        fraud_score = await self._calculate_fraud_score(
            card_id=card_id,
            amount=amount,
            merchant_data=merchant_data,
        )
        authorization_id = generate_issuing_authorization_id()
        authorization = IssuingAuthorization(
            id=authorization_id,
            account_id=account_id,
            card_id=card_id,
            cardholder_id=card.cardholder_id,
            amount=amount,
            currency=currency.lower(),
            merchant_amount=amount,
            merchant_currency=currency.lower(),
            merchant_category=merchant_data.get("category_code", ""),
            merchant_data=merchant_data,
            merchant_name=merchant_data.get("name"),
            authorization_method=authorization_method,
            verification_data=verification_data,
            approved=limits_ok and fraud_score < 80,
            status=AuthorizationStatus.PENDING.value,
            network_risk_score=fraud_score,
            created=int(time.time()),
            livemode=False,
        )
        self.session.add(authorization)
        await self.session.flush()
        request = AuthorizationRequest(
            id=generate_id("auth_req"),
            authorization_id=authorization_id,
            account_id=account_id,
            amount=amount,
            currency=currency.lower(),
            merchant_amount=amount,
            merchant_currency=currency.lower(),
            merchant_data=merchant_data,
            authorization_method=authorization_method,
            verification_data=verification_data,
            created=int(time.time()),
            decision="approved" if authorization.approved else "pending",
            livemode=False,
        )
        self.session.add(request)
        await self.session.flush()
        if authorization.approved:
            network_response = await self.network.simulate_authorization(
                authorization_id=authorization_id,
                amount=amount,
                currency=currency,
            )
        return authorization

    async def approve_authorization(
        self,
        authorization_id: str,
        approved_amount: Optional[int] = None,
    ) -> IssuingAuthorization:
        authorization = await self._get_authorization(authorization_id)
        if not authorization:
            raise NotFoundError(f"Authorization {authorization_id} not found")
        if authorization.status != AuthorizationStatus.PENDING.value:
            raise ValidationError(f"Authorization {authorization_id} is not pending")
        authorization.approved = True
        authorization.status = AuthorizationStatus.CLOSED.value
        if approved_amount:
            authorization.amount = approved_amount
        await self.session.flush()
        await self._create_transaction(authorization)
        return authorization

    async def decline_authorization(
        self,
        authorization_id: str,
        decline_reason: str,
    ) -> IssuingAuthorization:
        authorization = await self._get_authorization(authorization_id)
        if not authorization:
            raise NotFoundError(f"Authorization {authorization_id} not found")
        if authorization.status != AuthorizationStatus.PENDING.value:
            raise ValidationError(f"Authorization {authorization_id} is not pending")
        authorization.approved = False
        authorization.status = AuthorizationStatus.DECLINED.value
        await self.session.flush()
        query = select(AuthorizationRequest).where(
            AuthorizationRequest.authorization_id == authorization_id
        )
        result = await self.session.execute(query)
        request = result.scalar_one_or_none()
        if request:
            request.decision = "declined"
            request.decline_reason = decline_reason
        await self.session.flush()
        return authorization

    async def _create_transaction(self, authorization: IssuingAuthorization) -> IssuingTransaction:
        transaction_id = generate_issuing_transaction_id()
        transaction = IssuingTransaction(
            id=transaction_id,
            account_id=authorization.account_id,
            authorization_id=authorization.id,
            card_id=authorization.card_id,
            cardholder_id=authorization.cardholder_id,
            amount=authorization.amount,
            currency=authorization.currency,
            merchant_amount=authorization.merchant_amount,
            merchant_currency=authorization.merchant_currency,
            merchant_category=authorization.merchant_category,
            merchant_data=authorization.merchant_data,
            merchant_name=authorization.merchant_name,
            type="capture",
            created=int(time.time()),
            livemode=False,
        )
        self.session.add(transaction)
        await self.session.flush()
        return transaction

    async def _calculate_fraud_score(
        self,
        card_id: str,
        amount: int,
        merchant_data: Dict[str, Any],
    ) -> int:
        base_score = 10
        if amount > 100000:
            base_score += 20
        elif amount > 10000:
            base_score += 10
        high_risk_categories = ["7995", "7273", "4814", "6012"]
        category = merchant_data.get("category_code", "")
        if category in high_risk_categories:
            base_score += 15
        score = min(100, max(0, base_score + secrets.randbelow(20)))
        fraud_score = FraudScore(
            id=generate_id("fs"),
            card_id=card_id,
            score=score,
            risk_level="elevated" if score > 50 else "normal",
            recommendation="approve" if score < 70 else "review",
            model_version="1.0.0",
            created=int(time.time()),
        )
        self.session.add(fraud_score)
        await self.session.flush()
        return score

    async def _get_authorization(self, authorization_id: str) -> Optional[IssuingAuthorization]:
        query = select(IssuingAuthorization).where(
            IssuingAuthorization.id == authorization_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _get_card(self, card_id: str) -> Optional[IssuingCard]:
        query = select(IssuingCard).where(IssuingCard.id == card_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _get_cardholder(self, cardholder_id: str) -> Optional[Cardholder]:
        query = select(Cardholder).where(Cardholder.id == cardholder_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


class SpendingControlService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_limits(
        self,
        card_id: str,
        cardholder_id: str,
        amount: int,
        currency: str,
        merchant_category: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        card_limits = await self._get_limits(card_id=card_id)
        cardholder_limits = await self._get_limits(cardholder_id=cardholder_id)
        all_limits = card_limits + cardholder_limits
        for limit in all_limits:
            if not limit.enforced:
                continue
            if limit.categories and merchant_category:
                if merchant_category not in limit.categories:
                    continue
            current_spending = await self._get_current_spending(
                limit_id=limit.id,
                interval=limit.interval,
                card_id=card_id,
                cardholder_id=cardholder_id,
            )
            if current_spending + amount > limit.amount:
                return False, f"Spending limit exceeded for interval {limit.interval}"
        return True, None

    async def update_limits(
        self,
        card_id: Optional[str] = None,
        cardholder_id: Optional[str] = None,
        limits: Optional[List[Dict]] = None,
    ) -> List[SpendingLimit]:
        existing_limits = await self._get_limits(card_id=card_id, cardholder_id=cardholder_id)
        for limit in existing_limits:
            await self.session.delete(limit)
        await self.session.flush()
        new_limits = []
        if limits:
            for limit_data in limits:
                limit = SpendingLimit(
                    id=generate_id("spl"),
                    amount=limit_data.get("amount", 0),
                    interval=limit_data.get("interval", "monthly"),
                    categories=limit_data.get("categories"),
                    card_id=card_id,
                    cardholder_id=cardholder_id,
                    created=int(time.time()),
                    enforced=True,
                )
                self.session.add(limit)
                new_limits.append(limit)
        await self.session.flush()
        return new_limits

    async def _get_limits(
        self,
        card_id: Optional[str] = None,
        cardholder_id: Optional[str] = None,
    ) -> List[SpendingLimit]:
        query = select(SpendingLimit)
        conditions = []
        if card_id:
            conditions.append(SpendingLimit.card_id == card_id)
        if cardholder_id:
            conditions.append(SpendingLimit.cardholder_id == cardholder_id)
        if conditions:
            query = query.where(or_(*conditions))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _get_current_spending(
        self,
        limit_id: str,
        interval: str,
        card_id: Optional[str] = None,
        cardholder_id: Optional[str] = None,
    ) -> int:
        now = datetime.now(timezone.utc)
        if interval == SpendingLimitInterval.PER_AUTHORIZATION.value:
            return 0
        elif interval == SpendingLimitInterval.DAILY.value:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif interval == SpendingLimitInterval.WEEKLY.value:
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        elif interval == SpendingLimitInterval.MONTHLY.value:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif interval == SpendingLimitInterval.YEARLY.value:
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = datetime(1970, 1, 1, tzinfo=timezone.utc)
        query = select(IssuingTransaction)
        conditions = [IssuingTransaction.created >= int(start.timestamp())]
        if card_id:
            conditions.append(IssuingTransaction.card_id == card_id)
        if cardholder_id:
            conditions.append(IssuingTransaction.cardholder_id == cardholder_id)
        query = query.where(and_(*conditions))
        result = await self.session.execute(query)
        transactions = list(result.scalars().all())
        return sum(t.amount for t in transactions)


class CardNetworkIntegration:
    VISA = "visa"
    MASTERCARD = "mastercard"

    def __init__(self, session: AsyncSession):
        self.session = session

    async def simulate_authorization(
        self,
        authorization_id: str,
        amount: int,
        currency: str,
        network: str = "visa",
    ) -> CardNetworkResponse:
        response_code = "00" if secrets.randbelow(100) < 95 else "05"
        approval_code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
        rrn = "".join([str(secrets.randbelow(10)) for _ in range(12)])
        stan = "".join([str(secrets.randbelow(10)) for _ in range(6)])
        response = CardNetworkResponse(
            id=generate_id("nr"),
            authorization_id=authorization_id,
            network=network,
            response_code=response_code,
            response_message="APPROVED" if response_code == "00" else "DECLINED",
            approval_code=approval_code if response_code == "00" else None,
            retrieval_reference_number=rrn,
            system_trace_audit_number=stan,
            created=int(time.time()),
            raw_response={
                "network": network,
                "response_code": response_code,
                "approval_code": approval_code,
            },
        )
        self.session.add(response)
        await self.session.flush()
        return response

    async def simulate_reversal(
        self,
        authorization_id: str,
        amount: int,
        reason: str = "cardholder_request",
    ) -> CardNetworkResponse:
        response = CardNetworkResponse(
            id=generate_id("nr"),
            authorization_id=authorization_id,
            network="visa",
            response_code="00",
            response_message="REVERSED",
            created=int(time.time()),
            raw_response={
                "reversal": True,
                "amount": amount,
                "reason": reason,
            },
        )
        self.session.add(response)
        await self.session.flush()
        return response


class DisputeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_dispute(
        self,
        account_id: Optional[str],
        transaction_id: str,
        amount: int,
        reason: str,
        evidence: Optional[Dict] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> IssuingDispute:
        transaction = await self._get_transaction(transaction_id)
        if not transaction:
            raise NotFoundError(f"Transaction {transaction_id} not found")
        dispute_id = generate_id("idp")
        dispute = IssuingDispute(
            id=dispute_id,
            account_id=account_id,
            transaction_id=transaction_id,
            amount=amount,
            currency=transaction.currency,
            reason=reason,
            status=IssuingDisputeStatus.SUBMITTED.value,
            evidence=evidence,
            metadata_=metadata or {},
            submitted_at=int(time.time()),
            created=int(time.time()),
            livemode=False,
        )
        self.session.add(dispute)
        transaction.dispute = dispute_id
        await self.session.flush()
        return dispute

    async def update_dispute(
        self,
        dispute_id: str,
        evidence: Optional[Dict] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> IssuingDispute:
        dispute = await self._get_dispute(dispute_id)
        if not dispute:
            raise NotFoundError(f"Dispute {dispute_id} not found")
        if evidence:
            dispute.evidence = evidence
        if metadata:
            dispute.metadata_ = metadata
        await self.session.flush()
        return dispute

    async def resolve_dispute(
        self,
        dispute_id: str,
        outcome: str,
    ) -> IssuingDispute:
        dispute = await self._get_dispute(dispute_id)
        if not dispute:
            raise NotFoundError(f"Dispute {dispute_id} not found")
        dispute.status = IssuingDisputeStatus.WON.value if outcome == "won" else IssuingDisputeStatus.LOST.value
        dispute.resolved_at = int(time.time())
        dispute.outcome = {
            "result": outcome,
            "resolved_at": dispute.resolved_at,
        }
        await self.session.flush()
        return dispute

    async def _get_dispute(self, dispute_id: str) -> Optional[IssuingDispute]:
        query = select(IssuingDispute).where(IssuingDispute.id == dispute_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _get_transaction(self, transaction_id: str) -> Optional[IssuingTransaction]:
        query = select(IssuingTransaction).where(IssuingTransaction.id == transaction_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
