from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re
import fnmatch

from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.payment_links import (
    PaymentLink,
    PaymentLinkLineItem,
    PaymentLinkPayment,
    PaymentLinkRestrictions,
    PaymentLinkCustomization,
    PaymentLinkAnalytics,
    PaymentLinkStatus,
    AfterCompletionType,
    PaymentLinkPaymentStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
)
import secrets
import string


@dataclass
class PaymentLinkInfo:
    id: str
    url: str
    name: Optional[str]
    active: bool
    total_amount: int
    currency: str


@dataclass
class AnalyticsStats:
    views: int
    unique_visitors: int
    started_checkouts: int
    completed_payments: int
    total_amount: int
    conversion_rate: float


@dataclass
class ValidationResult:
    valid: bool
    error_message: Optional[str] = None


class PaymentLinkService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        name: Optional[str] = None,
        payment_intent_data: Optional[Dict[str, Any]] = None,
        line_items: Optional[List[Dict[str, Any]]] = None,
        after_completion: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PaymentLink:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        url = self._generate_unique_url()
        
        payment_link = PaymentLink(
            id=self._generate_id("pl"),
            account_id=account_id,
            url=url,
            name=name,
            active=True,
            payment_intent_data=payment_intent_data,
            line_items=line_items,
            after_completion=after_completion,
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(payment_link)
        await self.session.flush()
        
        analytics = PaymentLinkAnalytics(
            id=self._generate_id("pla"),
            payment_link_id=payment_link.id,
            views=0,
            unique_visitors=0,
            started_checkouts=0,
            completed_payments=0,
            total_amount=0,
            currency=payment_intent_data.get("currency", "usd") if payment_intent_data else "usd",
            created=timestamp,
        )
        self.session.add(analytics)
        
        return payment_link

    async def get(self, payment_link_id: str) -> Optional[PaymentLink]:
        query = select(PaymentLink).where(PaymentLink.id == payment_link_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_url(self, url: str) -> Optional[PaymentLink]:
        query = select(PaymentLink).where(PaymentLink.url == url)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        account_id: Optional[str] = None,
        active: Optional[bool] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[PaymentLink]:
        query = select(PaymentLink)
        
        if account_id:
            query = query.where(PaymentLink.account_id == account_id)
        if active is not None:
            query = query.where(PaymentLink.active == active)
        
        query = query.order_by(PaymentLink.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update(
        self,
        payment_link_id: str,
        name: Optional[str] = None,
        payment_intent_data: Optional[Dict[str, Any]] = None,
        after_completion: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PaymentLink:
        payment_link = await self.get(payment_link_id)
        if not payment_link:
            raise NotFoundError(f"Payment link {payment_link_id} not found")
        
        if name is not None:
            payment_link.name = name
        if payment_intent_data is not None:
            payment_link.payment_intent_data = payment_intent_data
        if after_completion is not None:
            payment_link.after_completion = after_completion
        if metadata is not None:
            payment_link.metadata_ = metadata
        
        await self.session.flush()
        return payment_link

    async def activate(self, payment_link_id: str) -> PaymentLink:
        payment_link = await self.get(payment_link_id)
        if not payment_link:
            raise NotFoundError(f"Payment link {payment_link_id} not found")
        
        payment_link.active = True
        await self.session.flush()
        return payment_link

    async def deactivate(self, payment_link_id: str) -> PaymentLink:
        payment_link = await self.get(payment_link_id)
        if not payment_link:
            raise NotFoundError(f"Payment link {payment_link_id} not found")
        
        payment_link.active = False
        await self.session.flush()
        return payment_link

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"

    def _generate_unique_url(self) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(16))
        return f"https://pay.example.com/link/{random_part}"


class LineItemService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        payment_link_id: str,
        price_id: str,
        quantity: int = 1,
        adjustable_quantity: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PaymentLinkLineItem:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        line_item = PaymentLinkLineItem(
            id=self._generate_id("pli"),
            payment_link_id=payment_link_id,
            price_id=price_id,
            quantity=quantity,
            adjustable_quantity=adjustable_quantity,
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(line_item)
        await self.session.flush()
        return line_item

    async def get(self, line_item_id: str) -> Optional[PaymentLinkLineItem]:
        query = select(PaymentLinkLineItem).where(PaymentLinkLineItem.id == line_item_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(self, payment_link_id: str) -> List[PaymentLinkLineItem]:
        query = select(PaymentLinkLineItem).where(
            PaymentLinkLineItem.payment_link_id == payment_link_id
        ).order_by(PaymentLinkLineItem.created_at.asc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update(
        self,
        line_item_id: str,
        quantity: Optional[int] = None,
        adjustable_quantity: Optional[Dict[str, Any]] = None,
    ) -> PaymentLinkLineItem:
        line_item = await self.get(line_item_id)
        if not line_item:
            raise NotFoundError(f"Line item {line_item_id} not found")
        
        if quantity is not None:
            line_item.quantity = quantity
        if adjustable_quantity is not None:
            line_item.adjustable_quantity = adjustable_quantity
        
        await self.session.flush()
        return line_item

    async def remove(self, line_item_id: str) -> bool:
        line_item = await self.get(line_item_id)
        if not line_item:
            raise NotFoundError(f"Line item {line_item_id} not found")
        
        await self.session.delete(line_item)
        await self.session.flush()
        return True

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class RestrictionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def set(
        self,
        payment_link_id: str,
        max_uses: Optional[int] = None,
        expiry_date: Optional[int] = None,
        allowed_emails: Optional[List[str]] = None,
        require_customer: bool = False,
    ) -> PaymentLinkRestrictions:
        query = select(PaymentLinkRestrictions).where(
            PaymentLinkRestrictions.payment_link_id == payment_link_id
        )
        result = await self.session.execute(query)
        restrictions = result.scalar_one_or_none()
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        if not restrictions:
            restrictions = PaymentLinkRestrictions(
                id=self._generate_id("plr"),
                payment_link_id=payment_link_id,
                max_uses=max_uses,
                current_uses=0,
                expiry_date=expiry_date,
                allowed_emails=allowed_emails,
                require_customer=require_customer,
                created=timestamp,
            )
            self.session.add(restrictions)
        else:
            restrictions.max_uses = max_uses
            restrictions.expiry_date = expiry_date
            restrictions.allowed_emails = allowed_emails
            restrictions.require_customer = require_customer
        
        await self.session.flush()
        return restrictions

    async def get(self, payment_link_id: str) -> Optional[PaymentLinkRestrictions]:
        query = select(PaymentLinkRestrictions).where(
            PaymentLinkRestrictions.payment_link_id == payment_link_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def validate(self, payment_link_id: str, email: Optional[str] = None) -> ValidationResult:
        restrictions = await self.get(payment_link_id)
        
        if not restrictions:
            return ValidationResult(valid=True)
        
        if restrictions.max_uses is not None:
            if restrictions.current_uses >= restrictions.max_uses:
                return ValidationResult(
                    valid=False,
                    error_message="Payment link has reached maximum uses"
                )
        
        if restrictions.expiry_date is not None:
            current_time = int(datetime.now(timezone.utc).timestamp())
            if current_time > restrictions.expiry_date:
                return ValidationResult(
                    valid=False,
                    error_message="Payment link has expired"
                )
        
        if restrictions.allowed_emails and email:
            if not self._match_email_pattern(email, restrictions.allowed_emails):
                return ValidationResult(
                    valid=False,
                    error_message="Email is not allowed for this payment link"
                )
        
        return ValidationResult(valid=True)

    async def increment_use(self, payment_link_id: str) -> PaymentLinkRestrictions:
        restrictions = await self.get(payment_link_id)
        
        if not restrictions:
            restrictions = PaymentLinkRestrictions(
                id=self._generate_id("plr"),
                payment_link_id=payment_link_id,
                max_uses=None,
                current_uses=1,
                expiry_date=None,
                allowed_emails=None,
                require_customer=False,
                created=int(datetime.now(timezone.utc).timestamp()),
            )
            self.session.add(restrictions)
        else:
            restrictions.current_uses += 1
        
        await self.session.flush()
        return restrictions

    def _match_email(self, email: str, patterns: List[str]) -> bool:
        email_lower = email.lower()
        for pattern in patterns:
            pattern_lower = pattern.lower()
            if fnmatch.fnmatch(email_lower, pattern_lower):
                return True
            if email_lower == pattern_lower:
                return True
            if pattern_lower.startswith("@"):
                if email_lower.endswith(pattern_lower):
                    return True
        return False

    def _match_email_pattern(self, email: str, patterns: List[str]) -> bool:
        return self._match_email(email, patterns)

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class CustomizationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def apply_branding(
        self,
        payment_link_id: str,
        brand_color: Optional[str] = None,
        logo_url: Optional[str] = None,
        button_text: Optional[str] = None,
        custom_fields: Optional[List[Dict[str, Any]]] = None,
        terms_url: Optional[str] = None,
        privacy_url: Optional[str] = None,
    ) -> PaymentLinkCustomization:
        query = select(PaymentLinkCustomization).where(
            PaymentLinkCustomization.payment_link_id == payment_link_id
        )
        result = await self.session.execute(query)
        customization = result.scalar_one_or_none()
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        if not customization:
            customization = PaymentLinkCustomization(
                id=self._generate_id("plc"),
                payment_link_id=payment_link_id,
                brand_color=brand_color,
                logo_url=logo_url,
                button_text=button_text,
                custom_fields=custom_fields,
                terms_url=terms_url,
                privacy_url=privacy_url,
                created=timestamp,
            )
            self.session.add(customization)
        else:
            if brand_color is not None:
                customization.brand_color = brand_color
            if logo_url is not None:
                customization.logo_url = logo_url
            if button_text is not None:
                customization.button_text = button_text
            if custom_fields is not None:
                customization.custom_fields = custom_fields
            if terms_url is not None:
                customization.terms_url = terms_url
            if privacy_url is not None:
                customization.privacy_url = privacy_url
        
        await self.session.flush()
        return customization

    async def get(self, payment_link_id: str) -> Optional[PaymentLinkCustomization]:
        query = select(PaymentLinkCustomization).where(
            PaymentLinkCustomization.payment_link_id == payment_link_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def validate_assets(self, customization: PaymentLinkCustomization) -> ValidationResult:
        if customization.brand_color:
            if not re.match(r'^#[0-9A-Fa-f]{6}$', customization.brand_color):
                return ValidationResult(
                    valid=False,
                    error_message="Invalid brand color format. Expected hex color (e.g., #FF5733)"
                )
        
        if customization.logo_url:
            if not self._is_valid_url(customization.logo_url):
                return ValidationResult(
                    valid=False,
                    error_message="Invalid logo URL format"
                )
        
        if customization.terms_url:
            if not self._is_valid_url(customization.terms_url):
                return ValidationResult(
                    valid=False,
                    error_message="Invalid terms URL format"
                )
        
        if customization.privacy_url:
            if not self._is_valid_url(customization.privacy_url):
                return ValidationResult(
                    valid=False,
                    error_message="Invalid privacy URL format"
                )
        
        return ValidationResult(valid=True)

    def _is_valid_url(self, url: str) -> bool:
        url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        return bool(url_pattern.match(url))

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def track_view(self, payment_link_id: str, visitor_id: Optional[str] = None) -> PaymentLinkAnalytics:
        analytics = await self._get_or_create(payment_link_id)
        
        analytics.views += 1
        
        if visitor_id:
            analytics.unique_visitors += 1
        
        await self.session.flush()
        return analytics

    async def track_event(
        self,
        payment_link_id: str,
        event_type: str,
        amount: Optional[int] = None,
    ) -> PaymentLinkAnalytics:
        analytics = await self._get_or_create(payment_link_id)
        
        if event_type == "checkout_started":
            analytics.started_checkouts += 1
        elif event_type == "payment_completed":
            analytics.completed_payments += 1
            if amount:
                analytics.total_amount += amount
        
        await self.session.flush()
        return analytics

    async def get_stats(self, payment_link_id: str) -> AnalyticsStats:
        analytics = await self._get_or_create(payment_link_id)
        
        conversion_rate = 0.0
        if analytics.views > 0:
            conversion_rate = (analytics.completed_payments / analytics.views) * 100
        
        return AnalyticsStats(
            views=analytics.views,
            unique_visitors=analytics.unique_visitors,
            started_checkouts=analytics.started_checkouts,
            completed_payments=analytics.completed_payments,
            total_amount=analytics.total_amount,
            conversion_rate=round(conversion_rate, 2),
        )

    async def get(self, payment_link_id: str) -> Optional[PaymentLinkAnalytics]:
        query = select(PaymentLinkAnalytics).where(
            PaymentLinkAnalytics.payment_link_id == payment_link_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _get_or_create(self, payment_link_id: str) -> PaymentLinkAnalytics:
        analytics = await self.get(payment_link_id)
        
        if not analytics:
            timestamp = int(datetime.now(timezone.utc).timestamp())
            analytics = PaymentLinkAnalytics(
                id=self._generate_id("pla"),
                payment_link_id=payment_link_id,
                views=0,
                unique_visitors=0,
                started_checkouts=0,
                completed_payments=0,
                total_amount=0,
                currency="usd",
                created=timestamp,
            )
            self.session.add(analytics)
            await self.session.flush()
        
        return analytics

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class PaymentProcessingService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.analytics_service = AnalyticsService(session)
        self.restriction_service = RestrictionService(session)

    async def process_payment(
        self,
        payment_link_id: str,
        amount: int,
        currency: str,
        payment_intent_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PaymentLinkPayment:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        
        payment = PaymentLinkPayment(
            id=self._generate_id("plp"),
            payment_link_id=payment_link_id,
            payment_intent_id=payment_intent_id,
            customer_id=customer_id,
            amount=amount,
            currency=currency.lower(),
            status=PaymentLinkPaymentStatus.PENDING,
            created=timestamp,
            metadata_=metadata or {},
        )
        
        self.session.add(payment)
        await self.session.flush()
        
        return payment

    async def complete_payment(self, payment_id: str) -> PaymentLinkPayment:
        query = select(PaymentLinkPayment).where(PaymentLinkPayment.id == payment_id)
        result = await self.session.execute(query)
        payment = result.scalar_one_or_none()
        
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")
        
        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.status = PaymentLinkPaymentStatus.SUCCEEDED
        payment.paid_at = timestamp
        
        await self.analytics_service.track_event(
            payment.payment_link_id,
            "payment_completed",
            payment.amount
        )
        
        await self.restriction_service.increment_use(payment.payment_link_id)
        
        await self.session.flush()
        return payment

    async def fail_payment(self, payment_id: str) -> PaymentLinkPayment:
        query = select(PaymentLinkPayment).where(PaymentLinkPayment.id == payment_id)
        result = await self.session.execute(query)
        payment = result.scalar_one_or_none()
        
        if not payment:
            raise NotFoundError(f"Payment {payment_id} not found")
        
        payment.status = PaymentLinkPaymentStatus.FAILED
        await self.session.flush()
        return payment

    async def create_customer_if_needed(
        self,
        email: str,
        name: Optional[str] = None,
        payment_link_id: Optional[str] = None,
    ) -> str:
        customer_id = self._generate_id("cus")
        return customer_id

    async def get_payment(self, payment_id: str) -> Optional[PaymentLinkPayment]:
        query = select(PaymentLinkPayment).where(PaymentLinkPayment.id == payment_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_payments(
        self,
        payment_link_id: str,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[PaymentLinkPayment]:
        query = select(PaymentLinkPayment).where(
            PaymentLinkPayment.payment_link_id == payment_link_id
        )
        
        if status:
            query = query.where(PaymentLinkPayment.status == status)
        
        query = query.order_by(PaymentLinkPayment.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
