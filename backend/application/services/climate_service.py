from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio

from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.climate import (
    ClimateProduct,
    ClimateOrder,
    CarbonCredit,
    ClimateImpact,
    ProjectVerification,
    ClimateReport,
    CarbonLedgerEntry,
    ClimateProductType,
    ClimateOrderStatus,
    CarbonCreditStatus,
    VerificationStandard,
    ClimateReportStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    InsufficientBalanceError,
)
from payment_platform.backend.domain.ledger import post_ledger_entry


@dataclass
class PricingResult:
    metric_tons: Decimal
    unit_price: int
    total_amount: int
    currency: str
    fee: int


@dataclass
class ImpactSummary:
    total_metric_tons: Decimal
    total_amount: int
    currency: str
    contributions_count: int
    carbon_removal_tons: Decimal
    carbon_avoidance_tons: Decimal
    projects_supported: List[str]


class ProductService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_available(
        self,
        product_type: Optional[str] = None,
        verification_standard: Optional[str] = None,
        min_metric_tons: Optional[Decimal] = None,
        max_price_per_ton: Optional[int] = None,
        project_location: Optional[str] = None,
        active_only: bool = True,
        limit: int = 10,
        offset: int = 0,
    ) -> List[ClimateProduct]:
        query = select(ClimateProduct)

        if active_only:
            query = query.where(ClimateProduct.active == True)

        if product_type:
            if product_type == "carbon_removal":
                query = query.where(ClimateProduct.type == ClimateProductType.CARBON_REMOVAL)
            elif product_type == "carbon_avoidance":
                query = query.where(ClimateProduct.type == ClimateProductType.CARBON_AVOIDANCE)

        if verification_standard:
            query = query.where(ClimateProduct.verification_standard == verification_standard)

        if min_metric_tons is not None:
            query = query.where(ClimateProduct.metric_tons_available >= min_metric_tons)

        if max_price_per_ton is not None:
            query = query.where(ClimateProduct.price_per_ton <= max_price_per_ton)

        if project_location:
            query = query.where(ClimateProduct.project_location.ilike(f"%{project_location}%"))

        query = query.order_by(ClimateProduct.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_product(self, product_id: str) -> Optional[ClimateProduct]:
        query = select(ClimateProduct).where(ClimateProduct.id == product_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def calculate_pricing(
        self,
        product_id: str,
        metric_tons: Decimal,
        currency: str = "usd",
    ) -> PricingResult:
        product = await self.get_product(product_id)
        if not product:
            raise NotFoundError(f"Climate product {product_id} not found")

        if product.metric_tons_available < metric_tons:
            raise ValidationError(
                f"Insufficient credits available. Requested: {metric_tons}, Available: {product.metric_tons_available}",
                param="metric_tons",
            )

        total_amount = int(metric_tons * Decimal(product.price_per_ton))
        fee = int(total_amount * Decimal("0.025"))

        return PricingResult(
            metric_tons=metric_tons,
            unit_price=product.price_per_ton,
            total_amount=total_amount + fee,
            currency=currency.lower(),
            fee=fee,
        )

    async def check_availability(
        self,
        product_id: str,
        metric_tons: Decimal,
    ) -> bool:
        product = await self.get_product(product_id)
        if not product:
            return False
        return product.metric_tons_available >= metric_tons

    async def update_availability(
        self,
        product_id: str,
        metric_tons_delta: Decimal,
    ) -> ClimateProduct:
        product = await self.get_product(product_id)
        if not product:
            raise NotFoundError(f"Climate product {product_id} not found")

        new_availability = product.metric_tons_available + metric_tons_delta
        if new_availability < 0:
            raise ValidationError(
                "Insufficient credits available",
                param="metric_tons",
            )

        product.metric_tons_available = new_availability
        await self.session.flush()
        return product

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class OrderService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.product_service = ProductService(session)

    async def create(
        self,
        account_id: str,
        product_id: str,
        metric_tons: Decimal,
        currency: str = "usd",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ClimateOrder:
        product = await self.product_service.get_product(product_id)
        if not product:
            raise NotFoundError(f"Climate product {product_id} not found")

        if not product.active:
            raise ValidationError(
                f"Climate product {product_id} is not active",
                param="product_id",
            )

        pricing = await self.product_service.calculate_pricing(product_id, metric_tons, currency)

        timestamp = int(datetime.now(timezone.utc).timestamp())

        order = ClimateOrder(
            id=self._generate_id("clord"),
            account_id=account_id,
            product_id=product_id,
            amount=pricing.total_amount,
            currency=currency.lower(),
            metric_tons=metric_tons,
            status=ClimateOrderStatus.PENDING,
            metadata_=metadata or {},
            created=timestamp,
        )

        self.session.add(order)
        await self.session.flush()

        return order

    async def process(self, order_id: str, payment_intent_id: Optional[str] = None) -> ClimateOrder:
        order = await self.get_order(order_id)
        if not order:
            raise NotFoundError(f"Climate order {order_id} not found")

        if order.status != ClimateOrderStatus.PENDING:
            raise ValidationError(
                f"Order {order_id} is not in pending status",
                param="order_id",
            )

        order.status = ClimateOrderStatus.PROCESSING
        if payment_intent_id:
            order.payment_intent_id = payment_intent_id
            order.payment_status = "processing"

        await self.product_service.update_availability(
            order.product_id,
            -order.metric_tons,
        )

        await self.session.flush()
        return order

    async def fulfill(self, order_id: str) -> ClimateOrder:
        order = await self.get_order(order_id)
        if not order:
            raise NotFoundError(f"Climate order {order_id} not found")

        if order.status != ClimateOrderStatus.PROCESSING:
            raise ValidationError(
                f"Order {order_id} is not in processing status",
                param="order_id",
            )

        timestamp = int(datetime.now(timezone.utc).timestamp())

        order.status = ClimateOrderStatus.FULFILLED
        order.fulfilled_at = timestamp
        order.payment_status = "succeeded"

        product = await self.product_service.get_product(order.product_id)

        credit = CarbonCredit(
            id=self._generate_id("cc"),
            order_id=order.id,
            metric_tons=order.metric_tons,
            serial_number=self._generate_serial_number(order, product),
            vintage_year=product.vintage_year or datetime.now().year,
            verification_standard=product.verification_standard,
            project_id=product.project_id or self._generate_id("proj"),
            status=CarbonCreditStatus.ACTIVE,
            issued_at=timestamp,
            created=timestamp,
        )
        self.session.add(credit)

        await self._record_ledger_entry(
            account_id=order.account_id,
            credit_id=credit.id,
            order_id=order.id,
            entry_type="issuance",
            metric_tons=order.metric_tons,
            reference_type="climate_order",
            reference_id=order.id,
            description=f"Carbon credit issuance for order {order.id}",
        )

        await self._update_impact(order)

        await self.session.flush()
        return order

    async def cancel(self, order_id: str, reason: Optional[str] = None) -> ClimateOrder:
        order = await self.get_order(order_id)
        if not order:
            raise NotFoundError(f"Climate order {order_id} not found")

        if order.status not in [ClimateOrderStatus.PENDING, ClimateOrderStatus.PROCESSING]:
            raise ValidationError(
                f"Order {order_id} cannot be canceled",
                param="order_id",
            )

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if order.status == ClimateOrderStatus.PROCESSING:
            await self.product_service.update_availability(
                order.product_id,
                order.metric_tons,
            )

        order.status = ClimateOrderStatus.CANCELED
        order.canceled_at = timestamp
        order.cancellation_reason = reason

        await self.session.flush()
        return order

    async def get_order(self, order_id: str) -> Optional[ClimateOrder]:
        query = select(ClimateOrder).where(ClimateOrder.id == order_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_orders(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        product_id: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[ClimateOrder]:
        query = select(ClimateOrder)

        if account_id:
            query = query.where(ClimateOrder.account_id == account_id)
        if status:
            query = query.where(ClimateOrder.status == status)
        if product_id:
            query = query.where(ClimateOrder.product_id == product_id)

        query = query.order_by(ClimateOrder.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _record_ledger_entry(
        self,
        account_id: str,
        entry_type: str,
        metric_tons: Decimal,
        credit_id: Optional[str] = None,
        order_id: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> CarbonLedgerEntry:
        timestamp = int(datetime.now(timezone.utc).timestamp())

        current_balance = await self._get_current_balance(account_id)

        if entry_type in ["issuance", "transfer_in", "adjustment"]:
            balance_after = current_balance + metric_tons
        else:
            balance_after = current_balance - metric_tons

        entry = CarbonLedgerEntry(
            id=self._generate_id("cle"),
            account_id=account_id,
            credit_id=credit_id,
            order_id=order_id,
            entry_type=entry_type,
            metric_tons=metric_tons,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            effective_at=timestamp,
            created=timestamp,
        )

        self.session.add(entry)
        return entry

    async def _get_current_balance(self, account_id: str) -> Decimal:
        query = select(CarbonLedgerEntry).where(
            CarbonLedgerEntry.account_id == account_id
        ).order_by(CarbonLedgerEntry.effective_at.desc()).limit(1)
        result = await self.session.execute(query)
        entry = result.scalar_one_or_none()
        if entry:
            return entry.balance_after
        return Decimal("0")

    async def _update_impact(self, order: ClimateOrder) -> None:
        year = datetime.now().year

        query = select(ClimateImpact).where(
            and_(
                ClimateImpact.account_id == order.account_id,
                ClimateImpact.year == year,
            )
        )
        result = await self.session.execute(query)
        impact = result.scalar_one_or_none()

        product = await self.product_service.get_product(order.product_id)

        if not impact:
            impact = ClimateImpact(
                id=self._generate_id("ci"),
                account_id=order.account_id,
                year=year,
                total_metric_tons=Decimal("0"),
                total_amount=0,
                currency=order.currency,
                contributions_count=0,
                carbon_removal_tons=Decimal("0"),
                carbon_avoidance_tons=Decimal("0"),
                projects_supported=[],
                co2_equivalent_kg=Decimal("0"),
            )
            self.session.add(impact)

        impact.total_metric_tons += order.metric_tons
        impact.total_amount += order.amount
        impact.contributions_count += 1

        if product.type == ClimateProductType.CARBON_REMOVAL:
            impact.carbon_removal_tons += order.metric_tons
        else:
            impact.carbon_avoidance_tons += order.metric_tons

        impact.co2_equivalent_kg += order.metric_tons * Decimal("1000")

        if product.project_id:
            if not impact.projects_supported:
                impact.projects_supported = []
            if product.project_id not in impact.projects_supported:
                impact.projects_supported.append(product.project_id)

    def _generate_serial_number(self, order: ClimateOrder, product: ClimateProduct) -> str:
        import hashlib
        timestamp = int(datetime.now(timezone.utc).timestamp())
        data = f"{order.id}-{product.id}-{timestamp}"
        hash_part = hashlib.sha256(data.encode()).hexdigest()[:16].upper()
        year = product.vintage_year or datetime.now().year
        standard_prefix = product.verification_standard.value[:3].upper()
        return f"{standard_prefix}-{year}-{hash_part}"

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class CreditService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.order_service = OrderService(session)

    async def issue(
        self,
        order_id: str,
        metric_tons: Decimal,
        project_id: str,
        vintage_year: int,
        verification_standard: VerificationStandard,
    ) -> CarbonCredit:
        order = await self.order_service.get_order(order_id)
        if not order:
            raise NotFoundError(f"Climate order {order_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        credit = CarbonCredit(
            id=self._generate_id("cc"),
            order_id=order_id,
            metric_tons=metric_tons,
            serial_number=self._generate_serial_number(),
            vintage_year=vintage_year,
            verification_standard=verification_standard,
            project_id=project_id,
            status=CarbonCreditStatus.ACTIVE,
            issued_at=timestamp,
            created=timestamp,
        )

        self.session.add(credit)
        await self.session.flush()
        return credit

    async def retire(
        self,
        credit_id: str,
        beneficiary: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> CarbonCredit:
        credit = await self.get_credit(credit_id)
        if not credit:
            raise NotFoundError(f"Carbon credit {credit_id} not found")

        if credit.status != CarbonCreditStatus.ACTIVE:
            raise ValidationError(
                f"Credit {credit_id} is not in active status",
                param="credit_id",
            )

        timestamp = int(datetime.now(timezone.utc).timestamp())

        credit.status = CarbonCreditStatus.RETIRED
        credit.retired_at = timestamp
        credit.retirement_beneficiary = beneficiary
        credit.retirement_reason = reason

        order = await self.order_service.get_order(credit.order_id)
        if order:
            await self._record_ledger_entry(
                account_id=order.account_id,
                credit_id=credit_id,
                order_id=order.id,
                entry_type="retirement",
                metric_tons=credit.metric_tons,
                reference_type="retirement",
                reference_id=credit_id,
                description=f"Carbon credit retirement for {beneficiary or 'N/A'}",
            )

        await self.session.flush()
        return credit

    async def transfer(
        self,
        credit_id: str,
        to_account_id: str,
    ) -> CarbonCredit:
        credit = await self.get_credit(credit_id)
        if not credit:
            raise NotFoundError(f"Carbon credit {credit_id} not found")

        if credit.status != CarbonCreditStatus.ACTIVE:
            raise ValidationError(
                f"Credit {credit_id} is not in active status",
                param="credit_id",
            )

        timestamp = int(datetime.now(timezone.utc).timestamp())

        credit.status = CarbonCreditStatus.TRANSFERRED
        credit.transferred_at = timestamp
        credit.transferred_to = to_account_id

        order = await self.order_service.get_order(credit.order_id)
        if order:
            await self._record_ledger_entry(
                account_id=order.account_id,
                credit_id=credit_id,
                order_id=order.id,
                entry_type="transfer_out",
                metric_tons=credit.metric_tons,
                reference_type="transfer",
                reference_id=to_account_id,
                description=f"Carbon credit transfer to account {to_account_id}",
            )

            await self._record_ledger_entry(
                account_id=to_account_id,
                credit_id=credit_id,
                order_id=order.id,
                entry_type="transfer_in",
                metric_tons=credit.metric_tons,
                reference_type="transfer",
                reference_id=order.account_id,
                description=f"Carbon credit received from account {order.account_id}",
            )

        await self.session.flush()
        return credit

    async def get_credit(self, credit_id: str) -> Optional[CarbonCredit]:
        query = select(CarbonCredit).where(CarbonCredit.id == credit_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_credits(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        verification_standard: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[CarbonCredit]:
        query = select(CarbonCredit)

        if status:
            query = query.where(CarbonCredit.status == status)
        if verification_standard:
            query = query.where(CarbonCredit.verification_standard == verification_standard)

        if account_id:
            order_query = select(ClimateOrder.id).where(ClimateOrder.account_id == account_id)
            query = query.where(CarbonCredit.order_id.in_(order_query))

        query = query.order_by(CarbonCredit.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def generate_certificate(self, credit_id: str) -> Dict[str, Any]:
        credit = await self.get_credit(credit_id)
        if not credit:
            raise NotFoundError(f"Carbon credit {credit_id} not found")

        order = await self.order_service.get_order(credit.order_id)
        product = None
        if order:
            from payment_platform.backend.application.services.climate_service import ProductService
            product_service = ProductService(self.session)
            product = await product_service.get_product(order.product_id)

        certificate = {
            "certificate_id": f"cert_{credit_id}",
            "serial_number": credit.serial_number,
            "metric_tons": float(credit.metric_tons),
            "vintage_year": credit.vintage_year,
            "verification_standard": credit.verification_standard.value,
            "project_id": credit.project_id,
            "status": credit.status.value,
            "issued_at": credit.issued_at,
            "retired_at": credit.retired_at,
            "retirement_beneficiary": credit.retirement_beneficiary,
            "retirement_reason": credit.retirement_reason,
        }

        if order:
            certificate["order_id"] = order.id
            certificate["account_id"] = order.account_id
            certificate["amount"] = order.amount
            certificate["currency"] = order.currency

        if product:
            certificate["product_name"] = product.name
            certificate["product_type"] = product.type.value
            certificate["project_location"] = product.project_location

        return certificate

    async def _record_ledger_entry(
        self,
        account_id: str,
        entry_type: str,
        metric_tons: Decimal,
        credit_id: Optional[str] = None,
        order_id: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> CarbonLedgerEntry:
        timestamp = int(datetime.now(timezone.utc).timestamp())

        current_balance = Decimal("0")
        query = select(CarbonLedgerEntry).where(
            CarbonLedgerEntry.account_id == account_id
        ).order_by(CarbonLedgerEntry.effective_at.desc()).limit(1)
        result = await self.session.execute(query)
        entry = result.scalar_one_or_none()
        if entry:
            current_balance = entry.balance_after

        if entry_type in ["issuance", "transfer_in", "adjustment"]:
            balance_after = current_balance + metric_tons
        else:
            balance_after = current_balance - metric_tons

        ledger_entry = CarbonLedgerEntry(
            id=self._generate_id("cle"),
            account_id=account_id,
            credit_id=credit_id,
            order_id=order_id,
            entry_type=entry_type,
            metric_tons=metric_tons,
            balance_after=balance_after,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            effective_at=timestamp,
            created=timestamp,
        )

        self.session.add(ledger_entry)
        return ledger_entry

    def _generate_serial_number(self) -> str:
        import hashlib
        import secrets
        timestamp = int(datetime.now(timezone.utc).timestamp())
        random_data = secrets.token_hex(8)
        data = f"{timestamp}-{random_data}"
        hash_part = hashlib.sha256(data.encode()).hexdigest()[:16].upper()
        return f"CC-{datetime.now().year}-{hash_part}"

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ImpactService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def calculate_impact(
        self,
        account_id: str,
        year: Optional[int] = None,
    ) -> ImpactSummary:
        if year is None:
            year = datetime.now().year

        query = select(ClimateImpact).where(
            and_(
                ClimateImpact.account_id == account_id,
                ClimateImpact.year == year,
            )
        )
        result = await self.session.execute(query)
        impact = result.scalar_one_or_none()

        if impact:
            return ImpactSummary(
                total_metric_tons=impact.total_metric_tons,
                total_amount=impact.total_amount,
                currency=impact.currency,
                contributions_count=impact.contributions_count,
                carbon_removal_tons=impact.carbon_removal_tons,
                carbon_avoidance_tons=impact.carbon_avoidance_tons,
                projects_supported=impact.projects_supported or [],
            )

        return ImpactSummary(
            total_metric_tons=Decimal("0"),
            total_amount=0,
            currency="usd",
            contributions_count=0,
            carbon_removal_tons=Decimal("0"),
            carbon_avoidance_tons=Decimal("0"),
            projects_supported=[],
        )

    async def generate_summary(
        self,
        account_id: str,
        include_yearly_breakdown: bool = True,
    ) -> Dict[str, Any]:
        current_year = datetime.now().year
        current_impact = await self.calculate_impact(account_id, current_year)

        total_query = select(
            func.sum(ClimateImpact.total_metric_tons).label("total_tons"),
            func.sum(ClimateImpact.total_amount).label("total_amount"),
            func.sum(ClimateImpact.contributions_count).label("total_contributions"),
        ).where(ClimateImpact.account_id == account_id)
        total_result = await self.session.execute(total_query)
        total_row = total_result.one()

        summary = {
            "account_id": account_id,
            "current_year": current_year,
            "current_year_impact": {
                "total_metric_tons": float(current_impact.total_metric_tons),
                "total_amount": current_impact.total_amount,
                "currency": current_impact.currency,
                "contributions_count": current_impact.contributions_count,
                "carbon_removal_tons": float(current_impact.carbon_removal_tons),
                "carbon_avoidance_tons": float(current_impact.carbon_avoidance_tons),
                "projects_supported": current_impact.projects_supported,
            },
            "lifetime_impact": {
                "total_metric_tons": float(total_row.total_tons or Decimal("0")),
                "total_amount": total_row.total_amount or 0,
                "total_contributions": total_row.total_contributions or 0,
            },
            "co2_equivalent": {
                "kg": float(current_impact.total_metric_tons * Decimal("1000")),
                "tons": float(current_impact.total_metric_tons),
                "cars_removed_annually": float(current_impact.total_metric_tons / Decimal("4.6")),
                "trees_planted_equivalent": float(current_impact.total_metric_tons * Decimal("45")),
            },
        }

        if include_yearly_breakdown:
            yearly_query = select(ClimateImpact).where(
                ClimateImpact.account_id == account_id
            ).order_by(ClimateImpact.year.desc())
            yearly_result = await self.session.execute(yearly_query)
            yearly_impacts = yearly_result.scalars().all()

            summary["yearly_breakdown"] = [
                {
                    "year": impact.year,
                    "total_metric_tons": float(impact.total_metric_tons),
                    "total_amount": impact.total_amount,
                    "contributions_count": impact.contributions_count,
                }
                for impact in yearly_impacts
            ]

        return summary

    async def get_impact_by_project(
        self,
        account_id: str,
    ) -> List[Dict[str, Any]]:
        query = select(ClimateImpact).where(
            ClimateImpact.account_id == account_id
        ).order_by(ClimateImpact.year.desc())
        result = await self.session.execute(query)
        impacts = result.scalars().all()

        project_impacts = {}

        for impact in impacts:
            if impact.projects_supported:
                for project_id in impact.projects_supported:
                    if project_id not in project_impacts:
                        project_impacts[project_id] = {
                            "project_id": project_id,
                            "total_metric_tons": Decimal("0"),
                            "contributions_count": 0,
                        }
                    project_impacts[project_id]["total_metric_tons"] += impact.total_metric_tons
                    project_impacts[project_id]["contributions_count"] += impact.contributions_count

        return [
            {
                "project_id": data["project_id"],
                "total_metric_tons": float(data["total_metric_tons"]),
                "contributions_count": data["contributions_count"],
            }
            for data in project_impacts.values()
        ]

    async def recalculate_impact(
        self,
        account_id: str,
        year: int,
    ) -> ClimateImpact:
        orders_query = select(ClimateOrder).where(
            and_(
                ClimateOrder.account_id == account_id,
                ClimateOrder.status == ClimateOrderStatus.FULFILLED,
                func.extract("year", func.to_timestamp(ClimateOrder.created)) == year,
            )
        )
        orders_result = await self.session.execute(orders_query)
        orders = orders_result.scalars().all()

        total_metric_tons = Decimal("0")
        total_amount = 0
        contributions_count = len(orders)
        carbon_removal_tons = Decimal("0")
        carbon_avoidance_tons = Decimal("0")
        projects = []

        for order in orders:
            total_metric_tons += order.metric_tons
            total_amount += order.amount

            product_query = select(ClimateProduct).where(ClimateProduct.id == order.product_id)
            product_result = await self.session.execute(product_query)
            product = product_result.scalar_one_or_none()

            if product:
                if product.type == ClimateProductType.CARBON_REMOVAL:
                    carbon_removal_tons += order.metric_tons
                else:
                    carbon_avoidance_tons += order.metric_tons

                if product.project_id and product.project_id not in projects:
                    projects.append(product.project_id)

        impact_query = select(ClimateImpact).where(
            and_(
                ClimateImpact.account_id == account_id,
                ClimateImpact.year == year,
            )
        )
        impact_result = await self.session.execute(impact_query)
        impact = impact_result.scalar_one_or_none()

        if not impact:
            impact = ClimateImpact(
                id=f"ci_{account_id[:10]}_{year}",
                account_id=account_id,
                year=year,
            )
            self.session.add(impact)

        impact.total_metric_tons = total_metric_tons
        impact.total_amount = total_amount
        impact.contributions_count = contributions_count
        impact.carbon_removal_tons = carbon_removal_tons
        impact.carbon_avoidance_tons = carbon_avoidance_tons
        impact.projects_supported = projects
        impact.co2_equivalent_kg = total_metric_tons * Decimal("1000")

        await self.session.flush()
        return impact


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.impact_service = ImpactService(session)

    async def generate_monthly(
        self,
        account_id: str,
        year: int,
        month: int,
    ) -> ClimateReport:
        from calendar import monthrange
        start_date = datetime(year, month, 1)
        end_day = monthrange(year, month)[1]
        end_date = datetime(year, month, end_day, 23, 59, 59)

        period_start = int(start_date.timestamp())
        period_end = int(end_date.timestamp())

        existing_query = select(ClimateReport).where(
            and_(
                ClimateReport.account_id == account_id,
                ClimateReport.period_start == period_start,
                ClimateReport.period_end == period_end,
                ClimateReport.report_type == "monthly",
            )
        )
        existing_result = await self.session.execute(existing_query)
        existing_report = existing_result.scalar_one_or_none()

        if existing_report:
            return existing_report

        report = ClimateReport(
            id=self._generate_id("clr"),
            account_id=account_id,
            period_start=period_start,
            period_end=period_end,
            report_type="monthly",
            status=ClimateReportStatus.GENERATING,
            created=int(datetime.now(timezone.utc).timestamp()),
        )
        self.session.add(report)
        await self.session.flush()

        orders = await self._get_orders_in_period(account_id, period_start, period_end)
        credits = await self._get_credits_in_period(account_id, period_start, period_end)

        total_offset = sum(float(o.metric_tons) for o in orders)
        total_amount = sum(o.amount for o in orders)

        report.total_offset = Decimal(str(total_offset))
        report.total_amount = total_amount
        report.certificates_count = len(credits)
        report.certificates = [
            {
                "credit_id": c.id,
                "serial_number": c.serial_number,
                "metric_tons": float(c.metric_tons),
                "vintage_year": c.vintage_year,
            }
            for c in credits
        ]
        report.projects = await self._get_project_summary(orders)
        report.status = ClimateReportStatus.COMPLETED
        report.generated_at = int(datetime.now(timezone.utc).timestamp())

        await self.session.flush()
        return report

    async def generate_annual(
        self,
        account_id: str,
        year: int,
    ) -> ClimateReport:
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)

        period_start = int(start_date.timestamp())
        period_end = int(end_date.timestamp())

        existing_query = select(ClimateReport).where(
            and_(
                ClimateReport.account_id == account_id,
                ClimateReport.period_start == period_start,
                ClimateReport.period_end == period_end,
                ClimateReport.report_type == "annual",
            )
        )
        existing_result = await self.session.execute(existing_query)
        existing_report = existing_result.scalar_one_or_none()

        if existing_report:
            return existing_report

        report = ClimateReport(
            id=self._generate_id("clr"),
            account_id=account_id,
            period_start=period_start,
            period_end=period_end,
            report_type="annual",
            status=ClimateReportStatus.GENERATING,
            created=int(datetime.now(timezone.utc).timestamp()),
        )
        self.session.add(report)
        await self.session.flush()

        orders = await self._get_orders_in_period(account_id, period_start, period_end)
        credits = await self._get_credits_in_period(account_id, period_start, period_end)
        impact = await self.impact_service.calculate_impact(account_id, year)

        report.total_offset = impact.total_metric_tons
        report.total_amount = impact.total_amount
        report.certificates_count = len(credits)
        report.certificates = [
            {
                "credit_id": c.id,
                "serial_number": c.serial_number,
                "metric_tons": float(c.metric_tons),
                "vintage_year": c.vintage_year,
            }
            for c in credits
        ]
        report.projects = await self._get_project_summary(orders)
        report.status = ClimateReportStatus.COMPLETED
        report.generated_at = int(datetime.now(timezone.utc).timestamp())

        await self.session.flush()
        return report

    async def get_report(self, report_id: str) -> Optional[ClimateReport]:
        query = select(ClimateReport).where(ClimateReport.id == report_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_reports(
        self,
        account_id: str,
        report_type: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[ClimateReport]:
        query = select(ClimateReport).where(ClimateReport.account_id == account_id)

        if report_type:
            query = query.where(ClimateReport.report_type == report_type)

        query = query.order_by(ClimateReport.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _get_orders_in_period(
        self,
        account_id: str,
        period_start: int,
        period_end: int,
    ) -> List[ClimateOrder]:
        query = select(ClimateOrder).where(
            and_(
                ClimateOrder.account_id == account_id,
                ClimateOrder.status == ClimateOrderStatus.FULFILLED,
                ClimateOrder.created >= period_start,
                ClimateOrder.created <= period_end,
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _get_credits_in_period(
        self,
        account_id: str,
        period_start: int,
        period_end: int,
    ) -> List[CarbonCredit]:
        order_ids_query = select(ClimateOrder.id).where(
            ClimateOrder.account_id == account_id
        )
        query = select(CarbonCredit).where(
            and_(
                CarbonCredit.order_id.in_(order_ids_query),
                CarbonCredit.issued_at >= period_start,
                CarbonCredit.issued_at <= period_end,
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _get_project_summary(
        self,
        orders: List[ClimateOrder],
    ) -> List[Dict[str, Any]]:
        project_summary = {}

        for order in orders:
            product_query = select(ClimateProduct).where(ClimateProduct.id == order.product_id)
            product_result = await self.session.execute(product_query)
            product = product_result.scalar_one_or_none()

            if product and product.project_id:
                if product.project_id not in project_summary:
                    project_summary[product.project_id] = {
                        "project_id": product.project_id,
                        "project_name": product.project_name,
                        "project_location": product.project_location,
                        "total_metric_tons": Decimal("0"),
                        "contribution_count": 0,
                    }
                project_summary[product.project_id]["total_metric_tons"] += order.metric_tons
                project_summary[product.project_id]["contribution_count"] += 1

        return [
            {
                **data,
                "total_metric_tons": float(data["total_metric_tons"]),
            }
            for data in project_summary.values()
        ]

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class VerificationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def validate_credits(
        self,
        credit_ids: List[str],
    ) -> Dict[str, Any]:
        results = {
            "valid": [],
            "invalid": [],
            "pending_verification": [],
        }

        for credit_id in credit_ids:
            credit_query = select(CarbonCredit).where(CarbonCredit.id == credit_id)
            credit_result = await self.session.execute(credit_query)
            credit = credit_result.scalar_one_or_none()

            if not credit:
                results["invalid"].append({
                    "credit_id": credit_id,
                    "reason": "Credit not found",
                })
                continue

            if credit.status != CarbonCreditStatus.ACTIVE:
                results["invalid"].append({
                    "credit_id": credit_id,
                    "reason": f"Credit status is {credit.status.value}",
                })
                continue

            verification_query = select(ProjectVerification).where(
                and_(
                    ProjectVerification.project_id == credit.project_id,
                    ProjectVerification.standard == credit.verification_standard,
                    ProjectVerification.status == "active",
                )
            )
            verification_result = await self.session.execute(verification_query)
            verification = verification_result.scalar_one_or_none()

            if not verification:
                results["pending_verification"].append({
                    "credit_id": credit_id,
                    "project_id": credit.project_id,
                    "standard": credit.verification_standard.value,
                })
                continue

            current_time = int(datetime.now(timezone.utc).timestamp())
            if verification.valid_until and verification.valid_until < current_time:
                results["invalid"].append({
                    "credit_id": credit_id,
                    "reason": "Verification expired",
                })
                continue

            results["valid"].append({
                "credit_id": credit_id,
                "serial_number": credit.serial_number,
                "metric_tons": float(credit.metric_tons),
                "verification_standard": credit.verification_standard.value,
                "verification_id": verification.id,
                "certifier": verification.certifier,
            })

        return results

    async def track_certificates(
        self,
        project_id: str,
    ) -> Dict[str, Any]:
        verifications_query = select(ProjectVerification).where(
            ProjectVerification.project_id == project_id
        ).order_by(ProjectVerification.verification_date.desc())
        verifications_result = await self.session.execute(verifications_query)
        verifications = verifications_result.scalars().all()

        credits_query = select(CarbonCredit).where(
            CarbonCredit.project_id == project_id
        )
        credits_result = await self.session.execute(credits_query)
        credits = credits_result.scalars().all()

        total_credits = sum(c.metric_tons for c in credits)
        active_credits = sum(c.metric_tons for c in credits if c.status == CarbonCreditStatus.ACTIVE)
        retired_credits = sum(c.metric_tons for c in credits if c.status == CarbonCreditStatus.RETIRED)

        return {
            "project_id": project_id,
            "total_verifications": len(verifications),
            "verifications": [
                {
                    "verification_id": v.id,
                    "standard": v.standard.value,
                    "verification_date": v.verification_date,
                    "certifier": v.certifier,
                    "certificate_number": v.certificate_number,
                    "valid_until": v.valid_until,
                    "status": v.status,
                }
                for v in verifications
            ],
            "total_credits_issued": float(total_credits),
            "active_credits": float(active_credits),
            "retired_credits": float(retired_credits),
            "total_certificates": len(credits),
        }

    async def add_verification(
        self,
        project_id: str,
        standard: VerificationStandard,
        verification_date: int,
        certifier: str,
        certificate_number: Optional[str] = None,
        verification_body: Optional[str] = None,
        valid_from: Optional[int] = None,
        valid_until: Optional[int] = None,
        verification_url: Optional[str] = None,
    ) -> ProjectVerification:
        verification = ProjectVerification(
            id=self._generate_id("pv"),
            project_id=project_id,
            standard=standard,
            verification_date=verification_date,
            certifier=certifier,
            certificate_number=certificate_number,
            verification_body=verification_body,
            valid_from=valid_from,
            valid_until=valid_until,
            verification_url=verification_url,
            status="active",
            created=int(datetime.now(timezone.utc).timestamp()),
        )

        self.session.add(verification)
        await self.session.flush()
        return verification

    async def get_verification(self, verification_id: str) -> Optional[ProjectVerification]:
        query = select(ProjectVerification).where(ProjectVerification.id == verification_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_verifications(
        self,
        project_id: Optional[str] = None,
        standard: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[ProjectVerification]:
        query = select(ProjectVerification)

        if project_id:
            query = query.where(ProjectVerification.project_id == project_id)
        if standard:
            query = query.where(ProjectVerification.standard == standard)
        if status:
            query = query.where(ProjectVerification.status == status)

        query = query.order_by(ProjectVerification.verification_date.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
