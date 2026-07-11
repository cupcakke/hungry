from datetime import datetime, timedelta, timezone
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional, Type, TypeVar

from sqlalchemy import ARRAY, JSON, and_, delete, func, inspect, or_, select, update
from sqlalchemy.exc import IntegrityError
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
from payment_platform.shared.utils.secrets import (
    generate_api_key_hash,
    generate_webhook_secret,
)

T = TypeVar("T")


class BaseRepository:
    def __init__(self, session: AsyncSession, model: Type[T]) -> None:
        self.session = session
        self.model = model
        self.mapper = inspect(model)
        if "id" not in self.mapper.column_attrs:
            raise TypeError(f"{model.__name__} must define a mapped id column")
        self.id_column = getattr(model, "id")

    def _mapped_attribute_names(self) -> set[str]:
        return set(self.mapper.attrs.keys())

    def _mapped_column_names(self) -> set[str]:
        return set(self.mapper.column_attrs.keys())

    def _relationship_names(self) -> set[str]:
        return set(self.mapper.relationships.keys())

    def _validate_column_name(self, field: str) -> None:
        if field not in self._mapped_column_names():
            raise ValueError(
                f"{field!r} is not a mapped column of {self.model.__name__}"
            )

    def _validate_relationship_name(self, field: str) -> None:
        if field not in self._relationship_names():
            raise ValueError(
                f"{field!r} is not a mapped relationship of "
                f"{self.model.__name__}"
            )

    def _validate_create_values(self, values: Dict[str, Any]) -> None:
        unknown_fields = set(values) - self._mapped_attribute_names()
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(
                f"Unknown mapped attributes for {self.model.__name__}: {fields}"
            )

    def _validate_update_values(self, values: Dict[str, Any]) -> None:
        column_names = self._mapped_column_names()
        unknown_fields = set(values) - column_names
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(
                f"Unknown or non-column attributes for "
                f"{self.model.__name__}: {fields}"
            )
        primary_key_names = {
            attribute.key
            for attribute in self.mapper.column_attrs
            if any(column.primary_key for column in attribute.columns)
        }
        immutable_fields = set(values) & primary_key_names
        if immutable_fields:
            fields = ", ".join(sorted(immutable_fields))
            raise ValueError(f"Primary-key fields cannot be updated: {fields}")

    def _validate_pagination(self, limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if isinstance(offset, bool) or not isinstance(offset, int):
            raise TypeError("offset must be an integer")
        if limit < 0:
            raise ValueError("limit cannot be negative")
        if offset < 0:
            raise ValueError("offset cannot be negative")

    def _merge_create_values(
        self,
        explicit_values: Dict[str, Any],
        extra_values: Dict[str, Any],
    ) -> Dict[str, Any]:
        values = dict(extra_values)
        values.update(explicit_values)
        return values

    def _active_condition(self) -> Optional[Any]:
        if "deleted_at" in self._mapped_column_names():
            return getattr(self.model, "deleted_at").is_(None)
        return None

    def _base_conditions(
        self,
        include_deleted: bool = False,
    ) -> List[Any]:
        conditions: List[Any] = []
        if not include_deleted:
            active_condition = self._active_condition()
            if active_condition is not None:
                conditions.append(active_condition)
        return conditions

    def _filter_expression(self, field: str, value: Any) -> Any:
        self._validate_column_name(field)
        column = getattr(self.model, field)
        if value is None:
            return column.is_(None)
        mapped_column = self.mapper.column_attrs[field].columns[0]
        if isinstance(mapped_column.type, (JSON, ARRAY)):
            return column == value
        if isinstance(value, (list, tuple, set, frozenset)):
            return column.in_(list(value))
        return column == value

    def _apply_loader_options(
        self,
        query: Any,
        joinedload_fields: Optional[List[str]],
        selectinload_fields: Optional[List[str]],
    ) -> Any:
        joined_fields = joinedload_fields or []
        selectin_fields = selectinload_fields or []
        duplicate_fields = set(joined_fields) & set(selectin_fields)
        if duplicate_fields:
            fields = ", ".join(sorted(duplicate_fields))
            raise ValueError(
                f"Relationships cannot use both joinedload and "
                f"selectinload: {fields}"
            )
        for field in joined_fields:
            self._validate_relationship_name(field)
            query = query.options(joinedload(getattr(self.model, field)))
        for field in selectin_fields:
            self._validate_relationship_name(field)
            query = query.options(selectinload(getattr(self.model, field)))
        return query

    async def create(self, **kwargs: Any) -> T:
        self._validate_create_values(kwargs)
        instance = self.model(**kwargs)
        self.session.add(instance)
        return instance

    async def get_by_id(
        self,
        id: str,
        include_deleted: bool = False,
        for_update: bool = False,
        joinedload_fields: Optional[List[str]] = None,
        selectinload_fields: Optional[List[str]] = None,
    ) -> Optional[T]:
        conditions = [self.id_column == id]
        conditions.extend(self._base_conditions(include_deleted))
        query = select(self.model).where(and_(*conditions))
        query = self._apply_loader_options(
            query,
            joinedload_fields,
            selectinload_fields,
        )
        if for_update:
            query = query.with_for_update()
        result = await self.session.execute(query)
        return result.unique().scalar_one_or_none()

    async def get_by_field(
        self,
        field: str,
        value: Any,
        include_deleted: bool = False,
        joinedload_fields: Optional[List[str]] = None,
        selectinload_fields: Optional[List[str]] = None,
    ) -> Optional[T]:
        conditions = [self._filter_expression(field, value)]
        conditions.extend(self._base_conditions(include_deleted))
        query = (
            select(self.model)
            .where(and_(*conditions))
            .order_by(self.id_column.asc())
            .limit(1)
        )
        query = self._apply_loader_options(
            query,
            joinedload_fields,
            selectinload_fields,
        )
        result = await self.session.execute(query)
        return result.unique().scalar_one_or_none()

    async def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
        order_by: Optional[str] = None,
        order_desc: bool = True,
        include_deleted: bool = False,
        joinedload_fields: Optional[List[str]] = None,
        selectinload_fields: Optional[List[str]] = None,
    ) -> List[T]:
        self._validate_pagination(limit, offset)
        conditions = self._base_conditions(include_deleted)
        if filters:
            conditions.extend(
                self._filter_expression(key, value)
                for key, value in filters.items()
            )
        query = select(self.model)
        if conditions:
            query = query.where(and_(*conditions))
        query = self._apply_loader_options(
            query,
            joinedload_fields,
            selectinload_fields,
        )
        if order_by is not None:
            self._validate_column_name(order_by)
            order_column = getattr(self.model, order_by)
            query = query.order_by(
                order_column.desc() if order_desc else order_column.asc()
            )
            if order_by != "id":
                query = query.order_by(self.id_column.asc())
        else:
            query = query.order_by(self.id_column.asc())
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.unique().scalars().all())

    async def count(
        self,
        filters: Optional[Dict[str, Any]] = None,
        include_deleted: bool = False,
    ) -> int:
        conditions = self._base_conditions(include_deleted)
        if filters:
            conditions.extend(
                self._filter_expression(key, value)
                for key, value in filters.items()
            )
        query = select(func.count()).select_from(self.model)
        if conditions:
            query = query.where(and_(*conditions))
        result = await self.session.execute(query)
        value = result.scalar_one()
        return int(value)

    async def update(self, id: str, **kwargs: Any) -> Optional[T]:
        self._validate_update_values(kwargs)
        instance = await self.get_by_id(id, for_update=True)
        if instance is None:
            return None
        if not kwargs:
            return instance
        conditions = [self.id_column == id]
        active_condition = self._active_condition()
        if active_condition is not None:
            conditions.append(active_condition)
        statement = (
            update(self.model)
            .where(and_(*conditions))
            .values(**kwargs)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(statement)
        return instance

    async def delete(self, id: str) -> bool:
        instance = await self.get_by_id(
            id,
            include_deleted=True,
            for_update=True,
        )
        if instance is None:
            return False
        await self.session.delete(instance)
        return True

    async def soft_delete(self, id: str) -> Optional[T]:
        if "deleted_at" not in self._mapped_column_names():
            raise TypeError(
                f"{self.model.__name__} does not support soft deletion"
            )
        instance = await self.get_by_id(
            id,
            include_deleted=True,
            for_update=True,
        )
        if instance is None:
            return None
        if getattr(instance, "deleted_at") is None:
            setattr(instance, "deleted_at", datetime.now(timezone.utc))
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
        values = self._merge_create_values(
            {
                "id": generate_customer_id(),
                "account_id": account_id,
                "email": email.lower() if email is not None else None,
                "name": name,
                "phone": phone,
                "description": description,
                "metadata_": metadata or {},
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_by_email(
        self,
        email: str,
        account_id: Optional[str] = None,
    ) -> Optional[Customer]:
        query = (
            select(Customer)
            .where(Customer.email == email.lower())
            .where(Customer.account_id == account_id)
            .where(Customer.deleted_at.is_(None))
            .order_by(Customer.id.asc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_account(
        self,
        account_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Customer]:
        self._validate_pagination(limit, offset)
        query = (
            select(Customer)
            .where(Customer.account_id == account_id)
            .where(Customer.deleted_at.is_(None))
            .order_by(Customer.created_at.desc(), Customer.id.asc())
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
        payment_intent_id = generate_payment_intent_id()
        client_secret = (
            f"{payment_intent_id}_secret_{secrets.token_urlsafe(24)}"
        )
        values = self._merge_create_values(
            {
                "id": payment_intent_id,
                "amount": amount,
                "currency": currency.lower(),
                "account_id": account_id,
                "customer_id": customer_id,
                "payment_method_types": payment_method_types or ["card"],
                "capture_method": capture_method,
                "confirmation_method": confirmation_method,
                "client_secret": client_secret,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_by_client_secret(
        self,
        client_secret: str,
    ) -> Optional[PaymentIntent]:
        query = (
            select(PaymentIntent)
            .where(PaymentIntent.client_secret == client_secret)
            .order_by(PaymentIntent.id.asc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        payment_intent_id: str,
        status: str,
        amount_received: Any = ...,
        latest_charge: Any = ...,
    ) -> Optional[PaymentIntent]:
        updates: Dict[str, Any] = {"status": status}
        if amount_received is not ...:
            updates["amount_received"] = amount_received
        if latest_charge is not ...:
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
        values = self._merge_create_values(
            {
                "id": generate_charge_id(),
                "amount": amount,
                "currency": currency.lower(),
                "payment_intent_id": payment_intent_id,
                "customer_id": customer_id,
                "account_id": account_id,
                "description": description,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_by_payment_intent(
        self,
        payment_intent_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Charge]:
        self._validate_pagination(limit, offset)
        query = (
            select(Charge)
            .where(Charge.payment_intent_id == payment_intent_id)
            .order_by(Charge.created_at.desc(), Charge.id.asc())
            .limit(limit)
            .offset(offset)
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
        values = self._merge_create_values(
            {
                "id": generate_refund_id(),
                "charge_id": charge_id,
                "amount": amount,
                "currency": currency.lower(),
                "reason": reason,
                "account_id": account_id,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_by_charge(
        self,
        charge_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Refund]:
        self._validate_pagination(limit, offset)
        query = (
            select(Refund)
            .where(Refund.charge_id == charge_id)
            .order_by(Refund.created_at.desc(), Refund.id.asc())
            .limit(limit)
            .offset(offset)
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
        items: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Subscription:
        current_period_start = int(time.time())
        values = self._merge_create_values(
            {
                "id": generate_subscription_id(),
                "customer_id": customer_id,
                "currency": currency.lower(),
                "billing_cycle_anchor": billing_cycle_anchor,
                "current_period_start": current_period_start,
                "current_period_end": billing_cycle_anchor,
                "account_id": account_id,
                "items": items or [],
                "metadata_": metadata or {},
                "created": current_period_start,
                "start_date": current_period_start,
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_active_by_customer(
        self,
        customer_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Subscription]:
        self._validate_pagination(limit, offset)
        query = (
            select(Subscription)
            .where(Subscription.customer_id == customer_id)
            .where(
                Subscription.status.in_(
                    ["active", "trialing", "past_due"]
                )
            )
            .where(Subscription.deleted_at.is_(None))
            .order_by(
                Subscription.created_at.desc(),
                Subscription.id.asc(),
            )
            .limit(limit)
            .offset(offset)
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
        created = int(time.time())
        values = self._merge_create_values(
            {
                "id": generate_invoice_id(),
                "customer_id": customer_id,
                "currency": currency.lower(),
                "account_id": account_id,
                "subscription_id": subscription_id,
                "metadata_": metadata or {},
                "created": created,
                "period_start": created,
                "period_end": created,
                "amount_due": 0,
                "amount_remaining": 0,
                "subtotal": 0,
                "total": 0,
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_pending_by_customer(
        self,
        customer_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Invoice]:
        self._validate_pagination(limit, offset)
        query = (
            select(Invoice)
            .where(Invoice.customer_id == customer_id)
            .where(Invoice.status.in_(["draft", "open"]))
            .where(Invoice.deleted_at.is_(None))
            .order_by(Invoice.created_at.desc(), Invoice.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class InvoiceItemRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, InvoiceItem)


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
        line_items: Optional[List[Dict[str, Any]]] = None,
        payment_method_types: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> CheckoutSession:
        created = int(time.time())
        checkout_session_id = generate_checkout_session_id()
        client_secret = (
            f"{checkout_session_id}_secret_{secrets.token_urlsafe(24)}"
        )
        values = self._merge_create_values(
            {
                "id": checkout_session_id,
                "mode": mode,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "account_id": account_id,
                "customer_id": customer_id,
                "customer_email": (
                    customer_email.lower()
                    if customer_email is not None
                    else None
                ),
                "line_items": line_items or [],
                "payment_method_types": payment_method_types or ["card"],
                "metadata_": metadata or {},
                "created": created,
                "expires_at": created + 86400,
                "client_secret": client_secret,
            },
            kwargs,
        )
        return await self.create(**values)


class PaymentMethodRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PaymentMethod)

    async def create_payment_method(
        self,
        type: str,
        customer_id: Optional[str] = None,
        account_id: Optional[str] = None,
        card: Optional[Dict[str, Any]] = None,
        billing_details: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> PaymentMethod:
        values = self._merge_create_values(
            {
                "id": generate_payment_method_id(),
                "type": type,
                "customer_id": customer_id,
                "account_id": account_id,
                "card": card,
                "billing_details": billing_details,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_by_customer(
        self,
        customer_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[PaymentMethod]:
        self._validate_pagination(limit, offset)
        query = (
            select(PaymentMethod)
            .where(PaymentMethod.customer_id == customer_id)
            .order_by(
                PaymentMethod.created_at.desc(),
                PaymentMethod.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class BalanceRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Balance)

    async def get_or_create_for_account(self, account_id: str) -> Balance:
        balance = await self.get_by_field("account_id", account_id)
        if balance is not None:
            return balance
        try:
            async with self.session.begin_nested():
                balance = await self.create(
                    id=f"bal_{account_id}",
                    account_id=account_id,
                    available=[],
                    pending=[],
                )
                await self.session.flush()
            return balance
        except IntegrityError:
            balance = await self.get_by_field("account_id", account_id)
            if balance is None:
                raise
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
        created = int(time.time())
        values = self._merge_create_values(
            {
                "id": generate_balance_transaction_id(),
                "amount": amount,
                "currency": currency.lower(),
                "type": type,
                "account_id": account_id,
                "source": source,
                "description": description,
                "metadata_": metadata or {},
                "created": created,
                "available_on": created + 172800,
                "net": amount,
            },
            kwargs,
        )
        return await self.create(**values)


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
        values = self._merge_create_values(
            {
                "id": generate_webhook_endpoint_id(),
                "url": url,
                "enabled_events": enabled_events,
                "account_id": account_id,
                "description": description,
                "secret": generate_webhook_secret(),
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_enabled_for_account(
        self,
        account_id: Optional[str],
        limit: int = 100,
        offset: int = 0,
    ) -> List[WebhookEndpoint]:
        self._validate_pagination(limit, offset)
        query = (
            select(WebhookEndpoint)
            .where(WebhookEndpoint.status == "enabled")
            .where(WebhookEndpoint.account_id == account_id)
            .order_by(
                WebhookEndpoint.created_at.desc(),
                WebhookEndpoint.id.asc(),
            )
            .limit(limit)
            .offset(offset)
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
        return await self.create(
            id=generate_event_id(),
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
        return await self.create(
            id=f"evd_{uuid.uuid4().hex[:24]}",
            event_id=event_id,
            webhook_endpoint_id=webhook_endpoint_id,
            webhook_url=webhook_url,
            account_id=account_id,
            status="pending",
            attempt_number=1,
        )

    async def get_pending_deliveries(
        self,
        limit: int = 100,
    ) -> List[EventDelivery]:
        self._validate_pagination(limit, 0)
        query = (
            select(EventDelivery)
            .where(EventDelivery.status == "pending")
            .where(
                or_(
                    EventDelivery.next_retry_at.is_(None),
                    EventDelivery.next_retry_at
                    <= datetime.now(timezone.utc),
                )
            )
            .order_by(
                EventDelivery.created_at.asc(),
                EventDelivery.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(query)
        deliveries = list(result.scalars().all())
        for delivery in deliveries:
            delivery.status = "processing"
        if deliveries:
            await self.session.flush()
        return deliveries


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
        api_key_id = generate_api_key_id(test=not livemode)
        raw_key, key_hash = generate_api_key_hash()
        api_key = await self.create(
            id=api_key_id,
            account_id=account_id,
            name=name,
            description=description,
            key_hash=key_hash,
            key_prefix=raw_key[:13],
            livemode=livemode,
            created=int(time.time()),
        )
        return api_key, raw_key

    async def get_by_key_hash(
        self,
        key_hash: str,
    ) -> Optional[APIKey]:
        query = (
            select(APIKey)
            .where(APIKey.key_hash == key_hash)
            .order_by(APIKey.id.asc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()


class RestrictedAPIKeyRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RestrictedAPIKey)


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
        values = self._merge_create_values(
            {
                "id": generate_account_id(),
                "country": country.upper(),
                "account_type": account_type,
                "email": email.lower() if email is not None else None,
                "business_type": business_type,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)


class AccountCapabilityRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AccountCapability)


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
        created = int(time.time())
        values = self._merge_create_values(
            {
                "id": generate_product_id(),
                "name": name,
                "account_id": account_id,
                "description": description,
                "active": active,
                "type": type,
                "metadata_": metadata or {},
                "created": created,
                "updated": created,
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_active(
        self,
        account_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Product]:
        self._validate_pagination(limit, offset)
        conditions = [Product.active.is_(True)]
        if account_id is not None:
            conditions.append(Product.account_id == account_id)
        query = (
            select(Product)
            .where(and_(*conditions))
            .order_by(Product.created_at.desc(), Product.id.asc())
            .limit(limit)
            .offset(offset)
        )
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
        values = self._merge_create_values(
            {
                "id": generate_price_id(),
                "product_id": product_id,
                "currency": currency.lower(),
                "unit_amount": unit_amount,
                "recurring_interval": recurring_interval,
                "recurring_interval_count": recurring_interval_count,
                "account_id": account_id,
                "active": active,
                "type": type,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)

    async def get_by_product(
        self,
        product_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Price]:
        self._validate_pagination(limit, offset)
        query = (
            select(Price)
            .where(Price.product_id == product_id)
            .where(Price.active.is_(True))
            .order_by(Price.created_at.desc(), Price.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class CouponRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Coupon)

    async def create_coupon(
        self,
        **kwargs: Any,
    ) -> Coupon:
        values = dict(kwargs)
        values["id"] = generate_coupon_id()
        return await self.create(**values)


class PromotionCodeRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PromotionCode)

    async def create_promotion_code(
        self,
        **kwargs: Any,
    ) -> PromotionCode:
        values = dict(kwargs)
        values["id"] = generate_promotion_code_id()
        return await self.create(**values)


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
        values = self._merge_create_values(
            {
                "id": generate_dispute_id(),
                "charge_id": charge_id,
                "amount": amount,
                "currency": currency.lower(),
                "reason": reason,
                "account_id": account_id,
                "payment_intent_id": payment_intent_id,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)


class DisputeEvidenceRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DisputeEvidence)


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
        created = int(time.time())
        values = self._merge_create_values(
            {
                "id": generate_payout_id(),
                "amount": amount,
                "currency": currency.lower(),
                "destination": destination,
                "account_id": account_id,
                "description": description,
                "metadata_": metadata or {},
                "created": created,
                "arrival_date": created + 172800,
            },
            kwargs,
        )
        return await self.create(**values)


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
        values = self._merge_create_values(
            {
                "id": generate_transfer_id(),
                "amount": amount,
                "currency": currency.lower(),
                "destination": destination,
                "account_id": account_id,
                "description": description,
                "transfer_group": transfer_group,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)


class TaxRateRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TaxRate)


class TaxIdRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TaxId)


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
        setup_intent_id = generate_setup_intent_id()
        client_secret = (
            f"{setup_intent_id}_secret_{secrets.token_urlsafe(24)}"
        )
        values = self._merge_create_values(
            {
                "id": setup_intent_id,
                "customer_id": customer_id,
                "account_id": account_id,
                "payment_method_types": payment_method_types or ["card"],
                "usage": usage,
                "client_secret": client_secret,
                "metadata_": metadata or {},
                "created": int(time.time()),
            },
            kwargs,
        )
        return await self.create(**values)


class MandateRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Mandate)

    async def create_mandate(
        self,
        payment_method: str,
        type: str,
        account_id: Optional[str] = None,
        customer_acceptance: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Mandate:
        values = self._merge_create_values(
            {
                "id": generate_mandate_id(),
                "payment_method": payment_method,
                "type": type,
                "account_id": account_id,
                "customer_acceptance": customer_acceptance,
                "metadata_": metadata or {},
            },
            kwargs,
        )
        return await self.create(**values)


class CreditNoteRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CreditNote)

    async def create_credit_note(
        self,
        **kwargs: Any,
    ) -> CreditNote:
        values = dict(kwargs)
        values["id"] = generate_credit_note_id()
        return await self.create(**values)


class ApplicationFeeRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ApplicationFee)


class FileRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, File)


class ReportRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Report)


class ReportRunRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ReportRun)


class TerminalReaderRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TerminalReader)


class LocationRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Location)


class CardholderRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Cardholder)


class IssuingCardRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IssuingCard)


class IssuingAuthorizationRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IssuingAuthorization)


class IssuingTransactionRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IssuingTransaction)


class FinancialAccountRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, FinancialAccount)


class TreasuryTransactionRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TreasuryTransaction)


class CapitalOfferRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CapitalOffer)


class VerificationSessionRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, VerificationSession)


class ReviewRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Review)


class OrderRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Order)


class OrderItemRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OrderItem)


class SubscriptionItemRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SubscriptionItem)


class UsageRecordRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UsageRecord)


class IdempotencyKeyRepository(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IdempotencyKey)

    async def create_key(
        self,
        id: str,
        request_path: str,
        request_method: str,
        request_params_hash: str,
        request_raw_params: Optional[Dict[str, Any]] = None,
        account_id: Optional[str] = None,
    ) -> IdempotencyKey:
        return await self.create(
            id=id,
            request_path=request_path,
            request_method=request_method,
            request_params_hash=request_params_hash,
            request_raw_params=request_raw_params,
            account_id=account_id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

    async def get_valid_key(
        self,
        id: str,
    ) -> Optional[IdempotencyKey]:
        query = (
            select(IdempotencyKey)
            .where(IdempotencyKey.id == id)
            .where(
                IdempotencyKey.expires_at > datetime.now(timezone.utc)
            )
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def cleanup_expired(
        self,
        batch_size: int = 1000,
    ) -> int:
        if isinstance(batch_size, bool) or not isinstance(batch_size, int):
            raise TypeError("batch_size must be an integer")
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        deleted_count = 0
        while True:
            id_query = (
                select(IdempotencyKey.id)
                .where(
                    IdempotencyKey.expires_at
                    <= datetime.now(timezone.utc)
                )
                .order_by(IdempotencyKey.id.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            result = await self.session.execute(id_query)
            ids = list(result.scalars().all())
            if not ids:
                break
            statement = delete(IdempotencyKey).where(
                IdempotencyKey.id.in_(ids)
            )
            await self.session.execute(statement)
            deleted_count += len(ids)
            if len(ids) < batch_size:
                break
        return deleted_count


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
        changes: Optional[Dict[str, Any]] = None,
        status: str = "success",
    ) -> AuditLog:
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

    async def get_by_resource(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLog]:
        self._validate_pagination(limit, offset)
        query = (
            select(AuditLog)
            .where(AuditLog.resource_type == resource_type)
            .where(AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
