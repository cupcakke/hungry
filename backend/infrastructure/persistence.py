from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type, TypeVar
from sqlalchemy import select, update, delete, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from payment_platform.backend.domain.models import (
    Customer, PaymentIntent, Charge, Refund, Subscription, Invoice,
    InvoiceItem, CheckoutSession, PaymentMethod, Balance, BalanceTransaction,
    WebhookEndpoint, Event, EventDelivery, APIKey, RestrictedAPIKey, Account,
    AccountCapability, Product, Price, Coupon, PromotionCode, Dispute,
    DisputeEvidence, Payout, Transfer, TaxRate, TaxId, SetupIntent, Mandate,
    CreditNote, ApplicationFee, File, Report, ReportRun, TerminalReader,
    Location, Cardholder, IssuingCard, IssuingAuthorization, IssuingTransaction,
    FinancialAccount, TreasuryTransaction, CapitalOffer, VerificationSession,
    Review, Order, OrderItem, SubscriptionItem, UsageRecord, IdempotencyKey,
    AuditLog,
)
from payment_platform.shared.utils.identifiers import (
    generate_customer_id, generate_payment_intent_id, generate_charge_id,
    generate_refund_id, generate_subscription_id, generate_invoice_id,
    generate_checkout_session_id, generate_payment_method_id, generate_event_id,
    generate_webhook_endpoint_id, generate_api_key_id, generate_account_id,
    generate_product_id, generate_price_id, generate_coupon_id,
    generate_promotion_code_id, generate_dispute_id, generate_payout_id,
    generate_transfer_id, generate_setup_intent_id, generate_mandate_id,
    generate_credit_note_id, generate_balance_transaction_id,
)

T = TypeVar("T")


class BaseRepository:
    def __init__(self, session: AsyncSession, model: Type[T]) -> None:
        self.session = session
        self.model = model

    async def create(self, **kwargs: Any) -> T:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def get_by_id(self, id: str) -> Optional[T]:
        query = select(self.model).where(self.model.id == id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_field(self, field: str, value: Any) -> Optional[T]:
        query = select(self.model).where(getattr(self.model, field) == value)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
        order_by: Optional[str] = None,
        order_desc: bool = True,
    ) -> List[T]:
        query = select(self.model)
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    if value is None:
                        query = query.where(getattr(self.model, key).is_(None))
                    elif isinstance(value, list):
                        query = query.where(getattr(self.model, key).in_(value))
                    else:
                        query = query.where(getattr(self.model, key) == value)
        if order_by and hasattr(self.model, order_by):
            column = getattr(self.model, order_by)
            if order_desc:
                query = query.order_by(column.desc())
            else:
                query = query.order_by(column.asc())
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        query = select(func.count()).select_from(self.model)
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def update(self, id: str, **kwargs: Any) -> Optional[T]:
        instance = await self.get_by_id(id)
        if instance:
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            await self.session.flush()
        return instance

    async def delete(self, id: str) -> bool:
        instance = await self.get_by_id(id)
        if instance:
            await self.session.delete(instance)
            await self.session.flush()
            return True
        return False

    async def soft_delete(self, id: str) -> Optional[T]:
        instance = await self.get_by_id(id)
        if instance and hasattr(instance, "deleted_at"):
            instance.deleted_at = datetime.now(timezone.utc)
            await self.session.flush()
        return instance


class CustomerRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Customer)

    async def create_customer(
        self,
        account_id: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Customer:
        customer_id = generate_customer_id()
        return await self.create(
            id=customer_id,
            account_id=account_id,
            email=email,
            name=name,
            phone=phone,
            description=description,
            metadata_=metadata or {},
            **kwargs,
        )

    async def get_by_email(self, email: str, account_id: Optional[str] = None) -> Optional[Customer]:
        query = select(Customer).where(Customer.email == email.lower())
        if account_id:
            query = query.where(Customer.account_id == account_id)
        query = query.where(Customer.deleted_at.is_(None))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_account(
        self,
        account_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Customer]:
        query = (
            select(Customer)
            .where(Customer.account_id == account_id)
            .where(Customer.deleted_at.is_(None))
            .order_by(Customer.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class PaymentIntentRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PaymentIntent)

    async def create_payment_intent(
        self,
        amount: int,
        currency: str,
        account_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        payment_method_types: Optional[List[str]] = None,
        capture_method: str = "automatic",
        confirmation_method: str = "automatic",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PaymentIntent:
        import time
        import secrets
        payment_intent_id = generate_payment_intent_id()
        client_secret = f"{payment_intent_id}_secret_{secrets.token_urlsafe(24)}"
        return await self.create(
            id=payment_intent_id,
            amount=amount,
            currency=currency.lower(),
            account_id=account_id,
            customer_id=customer_id,
            payment_method_types=payment_method_types or ["card"],
            capture_method=capture_method,
            confirmation_method=confirmation_method,
            client_secret=client_secret,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )

    async def get_by_client_secret(self, client_secret: str) -> Optional[PaymentIntent]:
        query = select(PaymentIntent).where(PaymentIntent.client_secret == client_secret)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        payment_intent_id: str,
        status: str,
        amount_received: Optional[int] = None,
        latest_charge: Optional[str] = None,
    ) -> Optional[PaymentIntent]:
        updates = {"status": status}
        if amount_received is not None:
            updates["amount_received"] = amount_received
        if latest_charge is not None:
            updates["latest_charge"] = latest_charge
        return await self.update(payment_intent_id, **updates)


class ChargeRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Charge)

    async def create_charge(
        self,
        amount: int,
        currency: str,
        payment_intent_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        account_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Charge:
        import time
        charge_id = generate_charge_id()
        return await self.create(
            id=charge_id,
            amount=amount,
            currency=currency.lower(),
            payment_intent_id=payment_intent_id,
            customer_id=customer_id,
            account_id=account_id,
            description=description,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )

    async def get_by_payment_intent(self, payment_intent_id: str) -> List[Charge]:
        query = (
            select(Charge)
            .where(Charge.payment_intent_id == payment_intent_id)
            .order_by(Charge.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class RefundRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Refund)

    async def create_refund(
        self,
        charge_id: str,
        amount: int,
        currency: str,
        reason: Optional[str] = None,
        account_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Refund:
        import time
        refund_id = generate_refund_id()
        return await self.create(
            id=refund_id,
            charge_id=charge_id,
            amount=amount,
            currency=currency.lower(),
            reason=reason,
            account_id=account_id,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )

    async def get_by_charge(self, charge_id: str) -> List[Refund]:
        query = (
            select(Refund)
            .where(Refund.charge_id == charge_id)
            .order_by(Refund.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class SubscriptionRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Subscription)

    async def create_subscription(
        self,
        customer_id: str,
        currency: str,
        billing_cycle_anchor: int,
        account_id: Optional[str] = None,
        items: Optional[List[Dict]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Subscription:
        import time
        subscription_id = generate_subscription_id()
        current_period_start = int(time.time())
        return await self.create(
            id=subscription_id,
            customer_id=customer_id,
            currency=currency.lower(),
            billing_cycle_anchor=billing_cycle_anchor,
            current_period_start=current_period_start,
            current_period_end=billing_cycle_anchor,
            account_id=account_id,
            items=items or [],
            metadata_=metadata or {},
            created=int(time.time()),
            start_date=current_period_start,
            **kwargs,
        )

    async def get_active_by_customer(self, customer_id: str) -> List[Subscription]:
        query = (
            select(Subscription)
            .where(Subscription.customer_id == customer_id)
            .where(Subscription.status.in_(["active", "trialing", "past_due"]))
            .where(Subscription.deleted_at.is_(None))
            .order_by(Subscription.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class InvoiceRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Invoice)

    async def create_invoice(
        self,
        customer_id: str,
        currency: str,
        account_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Invoice:
        import time
        invoice_id = generate_invoice_id()
        return await self.create(
            id=invoice_id,
            customer_id=customer_id,
            currency=currency.lower(),
            account_id=account_id,
            subscription_id=subscription_id,
            metadata_=metadata or {},
            created=int(time.time()),
            period_start=int(time.time()),
            period_end=int(time.time()),
            amount_due=0,
            amount_remaining=0,
            subtotal=0,
            total=0,
            **kwargs,
        )

    async def get_pending_by_customer(self, customer_id: str) -> List[Invoice]:
        query = (
            select(Invoice)
            .where(Invoice.customer_id == customer_id)
            .where(Invoice.status.in_(["draft", "open"]))
            .where(Invoice.deleted_at.is_(None))
            .order_by(Invoice.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class CheckoutSessionRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CheckoutSession)

    async def create_checkout_session(
        self,
        mode: str,
        success_url: str,
        cancel_url: Optional[str] = None,
        account_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        customer_email: Optional[str] = None,
        line_items: Optional[List[Dict]] = None,
        payment_method_types: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> CheckoutSession:
        import time
        import secrets
        checkout_session_id = generate_checkout_session_id()
        client_secret = f"{checkout_session_id}_secret_{secrets.token_urlsafe(24)}"
        expires_at = int(time.time()) + 86400
        return await self.create(
            id=checkout_session_id,
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            account_id=account_id,
            customer_id=customer_id,
            customer_email=customer_email,
            line_items=line_items or [],
            payment_method_types=payment_method_types or ["card"],
            metadata_=metadata or {},
            created=int(time.time()),
            expires_at=expires_at,
            client_secret=client_secret,
            **kwargs,
        )


class PaymentMethodRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PaymentMethod)

    async def create_payment_method(
        self,
        type: str,
        customer_id: Optional[str] = None,
        account_id: Optional[str] = None,
        card: Optional[Dict] = None,
        billing_details: Optional[Dict] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PaymentMethod:
        import time
        payment_method_id = generate_payment_method_id()
        return await self.create(
            id=payment_method_id,
            type=type,
            customer_id=customer_id,
            account_id=account_id,
            card=card,
            billing_details=billing_details,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )

    async def get_by_customer(self, customer_id: str) -> List[PaymentMethod]:
        query = (
            select(PaymentMethod)
            .where(PaymentMethod.customer_id == customer_id)
            .order_by(PaymentMethod.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class BalanceRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Balance)

    async def get_or_create_for_account(self, account_id: str) -> Balance:
        balance = await self.get_by_field("account_id", account_id)
        if not balance:
            balance = await self.create(
                id=f"bal_{account_id}",
                account_id=account_id,
                available=[],
                pending=[],
            )
        return balance


class BalanceTransactionRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, BalanceTransaction)

    async def create_transaction(
        self,
        amount: int,
        currency: str,
        type: str,
        account_id: Optional[str] = None,
        source: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> BalanceTransaction:
        import time
        transaction_id = generate_balance_transaction_id()
        return await self.create(
            id=transaction_id,
            amount=amount,
            currency=currency.lower(),
            type=type,
            account_id=account_id,
            source=source,
            description=description,
            metadata_=metadata or {},
            created=int(time.time()),
            available_on=int(time.time()) + 86400 * 2,
            net=amount,
            **kwargs,
        )


class WebhookEndpointRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WebhookEndpoint)

    async def create_endpoint(
        self,
        url: str,
        enabled_events: List[str],
        account_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> WebhookEndpoint:
        import time
        from payment_platform.shared.utils.secrets import generate_webhook_secret
        endpoint_id = generate_webhook_endpoint_id()
        secret = generate_webhook_secret()
        return await self.create(
            id=endpoint_id,
            url=url,
            enabled_events=enabled_events,
            account_id=account_id,
            description=description,
            secret=secret,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )

    async def get_enabled_for_account(self, account_id: Optional[str]) -> List[WebhookEndpoint]:
        query = (
            select(WebhookEndpoint)
            .where(WebhookEndpoint.status == "enabled")
            .where(WebhookEndpoint.account_id == account_id if account_id else WebhookEndpoint.account_id.is_(None))
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class EventRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Event)

    async def create_event(
        self,
        type: str,
        data: Dict[str, Any],
        account_id: Optional[str] = None,
        api_version: str = "2024-01-01",
    ) -> Event:
        import time
        event_id = generate_event_id()
        return await self.create(
            id=event_id,
            type=type,
            data=data,
            account_id=account_id,
            api_version=api_version,
            created=int(time.time()),
        )


class EventDeliveryRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EventDelivery)

    async def create_delivery(
        self,
        event_id: str,
        webhook_endpoint_id: str,
        webhook_url: str,
        account_id: Optional[str] = None,
    ) -> EventDelivery:
        import time
        import uuid
        return await self.create(
            id=f"evd_{uuid.uuid4().hex[:24]}",
            event_id=event_id,
            webhook_endpoint_id=webhook_endpoint_id,
            webhook_url=webhook_url,
            account_id=account_id,
            status="pending",
            attempt_number=1,
        )

    async def get_pending_deliveries(self, limit: int = 100) -> List[EventDelivery]:
        query = (
            select(EventDelivery)
            .where(EventDelivery.status == "pending")
            .where(
                or_(
                    EventDelivery.next_retry_at.is_(None),
                    EventDelivery.next_retry_at <= datetime.now(timezone.utc),
                )
            )
            .order_by(EventDelivery.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class APIKeyRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, APIKey)

    async def create_api_key(
        self,
        account_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        livemode: bool = False,
    ) -> tuple[APIKey, str]:
        import time
        from payment_platform.shared.utils.secrets import generate_api_key_hash
        from payment_platform.shared.utils.identifiers import generate_api_key_id
        api_key_id = generate_api_key_id(test=not livemode)
        raw_key, key_hash = generate_api_key_hash()
        key_prefix = raw_key[:13]
        api_key = await self.create(
            id=api_key_id,
            account_id=account_id,
            name=name,
            description=description,
            key_hash=key_hash,
            key_prefix=key_prefix,
            livemode=livemode,
            created=int(time.time()),
        )
        return api_key, raw_key

    async def get_by_key_hash(self, key_hash: str) -> Optional[APIKey]:
        query = select(APIKey).where(APIKey.key_hash == key_hash)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


class AccountRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Account)

    async def create_account(
        self,
        country: str,
        account_type: str = "standard",
        email: Optional[str] = None,
        business_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Account:
        import time
        account_id = generate_account_id()
        return await self.create(
            id=account_id,
            country=country.upper(),
            account_type=account_type,
            email=email,
            business_type=business_type,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )


class ProductRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Product)

    async def create_product(
        self,
        name: str,
        account_id: Optional[str] = None,
        description: Optional[str] = None,
        active: bool = True,
        type: str = "service",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Product:
        import time
        product_id = generate_product_id()
        return await self.create(
            id=product_id,
            name=name,
            account_id=account_id,
            description=description,
            active=active,
            type=type,
            metadata_=metadata or {},
            created=int(time.time()),
            updated=int(time.time()),
            **kwargs,
        )

    async def get_active(self, account_id: Optional[str] = None) -> List[Product]:
        query = select(Product).where(Product.active == True)
        if account_id:
            query = query.where(Product.account_id == account_id)
        query = query.order_by(Product.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())


class PriceRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Price)

    async def create_price(
        self,
        product_id: str,
        currency: str,
        unit_amount: Optional[int] = None,
        recurring_interval: Optional[str] = None,
        recurring_interval_count: int = 1,
        account_id: Optional[str] = None,
        active: bool = True,
        type: str = "recurring",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Price:
        import time
        price_id = generate_price_id()
        return await self.create(
            id=price_id,
            product_id=product_id,
            currency=currency.lower(),
            unit_amount=unit_amount,
            recurring_interval=recurring_interval,
            recurring_interval_count=recurring_interval_count,
            account_id=account_id,
            active=active,
            type=type,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )

    async def get_by_product(self, product_id: str) -> List[Price]:
        query = (
            select(Price)
            .where(Price.product_id == product_id)
            .where(Price.active == True)
            .order_by(Price.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class DisputeRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Dispute)

    async def create_dispute(
        self,
        charge_id: str,
        amount: int,
        currency: str,
        reason: str,
        account_id: Optional[str] = None,
        payment_intent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dispute:
        import time
        dispute_id = generate_dispute_id()
        return await self.create(
            id=dispute_id,
            charge_id=charge_id,
            amount=amount,
            currency=currency.lower(),
            reason=reason,
            account_id=account_id,
            payment_intent_id=payment_intent_id,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )


class PayoutRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Payout)

    async def create_payout(
        self,
        amount: int,
        currency: str,
        destination: Optional[str] = None,
        account_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Payout:
        import time
        payout_id = generate_payout_id()
        return await self.create(
            id=payout_id,
            amount=amount,
            currency=currency.lower(),
            destination=destination,
            account_id=account_id,
            description=description,
            metadata_=metadata or {},
            created=int(time.time()),
            arrival_date=int(time.time()) + 86400 * 2,
            **kwargs,
        )


class TransferRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Transfer)

    async def create_transfer(
        self,
        amount: int,
        currency: str,
        destination: str,
        account_id: Optional[str] = None,
        description: Optional[str] = None,
        transfer_group: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Transfer:
        import time
        transfer_id = generate_transfer_id()
        return await self.create(
            id=transfer_id,
            amount=amount,
            currency=currency.lower(),
            destination=destination,
            account_id=account_id,
            description=description,
            transfer_group=transfer_group,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )


class SetupIntentRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SetupIntent)

    async def create_setup_intent(
        self,
        customer_id: Optional[str] = None,
        account_id: Optional[str] = None,
        payment_method_types: Optional[List[str]] = None,
        usage: str = "off_session",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> SetupIntent:
        import time
        import secrets
        setup_intent_id = generate_setup_intent_id()
        client_secret = f"{setup_intent_id}_secret_{secrets.token_urlsafe(24)}"
        return await self.create(
            id=setup_intent_id,
            customer_id=customer_id,
            account_id=account_id,
            payment_method_types=payment_method_types or ["card"],
            usage=usage,
            client_secret=client_secret,
            metadata_=metadata or {},
            created=int(time.time()),
            **kwargs,
        )


class MandateRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Mandate)

    async def create_mandate(
        self,
        payment_method: str,
        type: str,
        account_id: Optional[str] = None,
        customer_acceptance: Optional[Dict] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Mandate:
        mandate_id = generate_mandate_id()
        return await self.create(
            id=mandate_id,
            payment_method=payment_method,
            type=type,
            account_id=account_id,
            customer_acceptance=customer_acceptance,
            metadata_=metadata or {},
            **kwargs,
        )


class IdempotencyKeyRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IdempotencyKey)

    async def create_key(
        self,
        id: str,
        request_path: str,
        request_method: str,
        request_params_hash: str,
        request_raw_params: Optional[Dict] = None,
        account_id: Optional[str] = None,
    ) -> IdempotencyKey:
        from datetime import timedelta
        return await self.create(
            id=id,
            request_path=request_path,
            request_method=request_method,
            request_params_hash=request_params_hash,
            request_raw_params=request_raw_params,
            account_id=account_id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

    async def get_valid_key(self, id: str) -> Optional[IdempotencyKey]:
        query = (
            select(IdempotencyKey)
            .where(IdempotencyKey.id == id)
            .where(IdempotencyKey.expires_at > datetime.now(timezone.utc))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def cleanup_expired(self) -> int:
        query = delete(IdempotencyKey).where(
            IdempotencyKey.expires_at < datetime.now(timezone.utc)
        )
        result = await self.session.execute(query)
        return result.rowcount


class AuditLogRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)

    async def create_log(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        actor_id: Optional[str] = None,
        actor_type: str = "user",
        actor_ip_address: Optional[str] = None,
        actor_user_agent: Optional[str] = None,
        account_id: Optional[str] = None,
        changes: Optional[Dict] = None,
        status: str = "success",
    ) -> AuditLog:
        import uuid
        return await self.create(
            id=f"aud_{uuid.uuid4().hex[:24]}",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_ip_address=actor_ip_address,
            actor_user_agent=actor_user_agent,
            account_id=account_id,
            changes=changes,
            status=status,
        )

    async def get_by_resource(self, resource_type: str, resource_id: str) -> List[AuditLog]:
        query = (
            select(AuditLog)
            .where(AuditLog.resource_type == resource_type)
            .where(AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
