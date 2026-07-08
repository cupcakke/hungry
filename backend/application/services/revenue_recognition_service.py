from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import calendar

from sqlalchemy import select, update, and_, or_, func, sum as sql_sum
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.revenue_recognition import (
    RecognitionSchedule,
    RecognitionPeriod,
    DeferredRevenue,
    RevenueAllocation,
    RecognitionTransaction,
    RecognitionRule,
    RecognitionMilestone,
    RecognitionMethod,
    RecognitionTrigger,
    ScheduleStatus,
    PeriodStatus,
    DeferredRevenueStatus,
    TransactionType,
    MilestoneStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    TreasuryError,
)
from payment_platform.shared.utils.identifiers import generate_id


@dataclass
class RecognitionResult:
    schedule_id: str
    amount_recognized: int
    total_recognized: int
    remaining_deferred: int
    period_id: str
    journal_entry_id: Optional[str]


@dataclass
class AllocationResult:
    transaction_id: str
    total_amount: int
    allocations: List[Dict[str, Any]]


@dataclass
class DeferredBalanceReport:
    account_id: str
    currency: str
    total_deferred: int
    total_recognized: int
    pending_recognition: int
    by_period: List[Dict[str, Any]]
    by_source: List[Dict[str, Any]]


class ScheduleService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        transaction_id: str,
        total_amount: int,
        currency: str,
        start_date: date,
        end_date: date,
        recognition_method: str = "straight_line",
        account_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        contract_id: Optional[str] = None,
        performance_obligation_id: Optional[str] = None,
        performance_obligation_description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RecognitionSchedule:
        if end_date < start_date:
            raise ValidationError("End date must be after start date", param="end_date")

        if total_amount <= 0:
            raise ValidationError("Total amount must be positive", param="total_amount")

        method = RecognitionMethod.STRAIGHT_LINE
        if recognition_method == "performance":
            method = RecognitionMethod.PERFORMANCE
        elif recognition_method == "usage":
            method = RecognitionMethod.USAGE

        schedule = RecognitionSchedule(
            id=self._generate_id("rs"),
            transaction_id=transaction_id,
            account_id=account_id,
            customer_id=customer_id,
            total_amount=total_amount,
            currency=currency.lower(),
            recognized_amount=0,
            deferred_amount=total_amount,
            start_date=start_date,
            end_date=end_date,
            status=ScheduleStatus.PENDING,
            recognition_method=method,
            contract_id=contract_id,
            performance_obligation_id=performance_obligation_id,
            performance_obligation_description=performance_obligation_description,
            total_periods=0,
            recognized_periods=0,
            metadata_=metadata or {},
        )

        self.session.add(schedule)
        await self.session.flush()

        return schedule

    async def get(self, schedule_id: str) -> Optional[RecognitionSchedule]:
        query = select(RecognitionSchedule).where(RecognitionSchedule.id == schedule_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        account_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
        contract_id: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[RecognitionSchedule]:
        query = select(RecognitionSchedule)

        if account_id:
            query = query.where(RecognitionSchedule.account_id == account_id)
        if transaction_id:
            query = query.where(RecognitionSchedule.transaction_id == transaction_id)
        if contract_id:
            query = query.where(RecognitionSchedule.contract_id == contract_id)
        if status:
            query = query.where(RecognitionSchedule.status == status)
        if start_date:
            query = query.where(RecognitionSchedule.start_date >= start_date)
        if end_date:
            query = query.where(RecognitionSchedule.end_date <= end_date)

        query = query.order_by(RecognitionSchedule.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def adjust(
        self,
        schedule_id: str,
        adjustment_amount: int,
        reason: str,
        new_end_date: Optional[date] = None,
    ) -> RecognitionSchedule:
        schedule = await self.get(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {schedule_id} not found")

        if schedule.status == ScheduleStatus.COMPLETED:
            raise ValidationError("Cannot adjust completed schedule", param="schedule_id")

        old_amount = schedule.total_amount
        new_total = schedule.total_amount + adjustment_amount

        if new_total < schedule.recognized_amount:
            raise ValidationError(
                "New total cannot be less than already recognized amount",
                param="adjustment_amount",
            )

        schedule.total_amount = new_total
        schedule.deferred_amount = new_total - schedule.recognized_amount
        schedule.adjustment_count += 1
        schedule.status = ScheduleStatus.ADJUSTED

        if new_end_date:
            if new_end_date < schedule.start_date:
                raise ValidationError("New end date must be after start date", param="new_end_date")
            schedule.end_date = new_end_date

        adjustment_transaction = RecognitionTransaction(
            id=self._generate_id("rt"),
            schedule_id=schedule_id,
            amount=adjustment_amount,
            currency=schedule.currency,
            transaction_type=TransactionType.ADJUSTMENT,
            timestamp=datetime.now(timezone.utc),
            description=f"Adjustment: {reason}. Old amount: {old_amount}, New amount: {new_total}",
        )
        self.session.add(adjustment_transaction)

        await self.session.flush()
        return schedule

    async def recognize(
        self,
        schedule_id: str,
        amount: int,
        period_id: Optional[str] = None,
        journal_entry_id: Optional[str] = None,
    ) -> RecognitionResult:
        schedule = await self.get(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {schedule_id} not found")

        if schedule.status == ScheduleStatus.COMPLETED:
            raise ValidationError("Schedule is already completed", param="schedule_id")

        if schedule.status == ScheduleStatus.CANCELED:
            raise ValidationError("Cannot recognize on canceled schedule", param="schedule_id")

        if amount > schedule.deferred_amount:
            raise ValidationError(
                f"Amount {amount} exceeds deferred amount {schedule.deferred_amount}",
                param="amount",
            )

        period = None
        if period_id:
            period_query = select(RecognitionPeriod).where(RecognitionPeriod.id == period_id)
            period_result = await self.session.execute(period_query)
            period = period_result.scalar_one_or_none()
            if not period:
                raise NotFoundError(f"Period {period_id} not found")

        schedule.recognized_amount += amount
        schedule.deferred_amount -= amount
        schedule.last_recognition_at = datetime.now(timezone.utc)

        if schedule.deferred_amount == 0:
            schedule.status = ScheduleStatus.COMPLETED
            schedule.completed_at = datetime.now(timezone.utc)

        if schedule.status == ScheduleStatus.PENDING:
            schedule.status = ScheduleStatus.ACTIVE

        transaction = RecognitionTransaction(
            id=self._generate_id("rt"),
            schedule_id=schedule_id,
            period_id=period_id,
            amount=amount,
            currency=schedule.currency,
            transaction_type=TransactionType.RECOGNITION,
            timestamp=datetime.now(timezone.utc),
            journal_entry_id=journal_entry_id,
        )
        self.session.add(transaction)

        if period:
            period.recognized_amount += amount
            if period.recognized_amount >= period.amount_to_recognize:
                period.status = PeriodStatus.RECOGNIZED
                period.recognized_at = datetime.now(timezone.utc)
                schedule.recognized_periods += 1
            else:
                period.status = PeriodStatus.PARTIAL

        await self.session.flush()

        return RecognitionResult(
            schedule_id=schedule_id,
            amount_recognized=amount,
            total_recognized=schedule.recognized_amount,
            remaining_deferred=schedule.deferred_amount,
            period_id=period_id or "",
            journal_entry_id=journal_entry_id,
        )

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class PeriodService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.schedule_service = ScheduleService(session)

    async def create_periods(
        self,
        schedule_id: str,
        frequency: str = "monthly",
    ) -> List[RecognitionPeriod]:
        schedule = await self.schedule_service.get(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {schedule_id} not found")

        existing_query = select(RecognitionPeriod).where(
            RecognitionPeriod.schedule_id == schedule_id
        )
        existing_result = await self.session.execute(existing_query)
        existing_periods = existing_result.scalars().all()
        if existing_periods:
            raise ValidationError("Periods already exist for this schedule", param="schedule_id")

        periods = []
        start_date = schedule.start_date
        end_date = schedule.end_date
        total_days = (end_date - start_date).days + 1

        if schedule.recognition_method == RecognitionMethod.STRAIGHT_LINE:
            if frequency == "monthly":
                periods = self._create_monthly_periods(schedule, start_date, end_date)
            elif frequency == "quarterly":
                periods = self._create_quarterly_periods(schedule, start_date, end_date)
            elif frequency == "yearly":
                periods = self._create_yearly_periods(schedule, start_date, end_date)
            else:
                periods = self._create_daily_periods(schedule, start_date, end_date, total_days)
        elif schedule.recognition_method == RecognitionMethod.PERFORMANCE:
            periods = self._create_performance_periods(schedule)
        else:
            periods = self._create_usage_periods(schedule)

        for period in periods:
            self.session.add(period)

        schedule.total_periods = len(periods)
        await self.session.flush()

        return periods

    def _create_monthly_periods(
        self,
        schedule: RecognitionSchedule,
        start_date: date,
        end_date: date,
    ) -> List[RecognitionPeriod]:
        periods = []
        current_start = start_date
        period_number = 1
        total_months = self._count_months(start_date, end_date)
        base_amount = schedule.total_amount // total_months
        remainder = schedule.total_amount % total_months

        while current_start <= end_date:
            year = current_start.year
            month = current_start.month
            last_day = calendar.monthrange(year, month)[1]
            current_end = date(year, month, last_day)
            if current_end > end_date:
                current_end = end_date

            amount = base_amount
            if period_number == total_months:
                amount = base_amount + remainder

            period = RecognitionPeriod(
                id=self._generate_id("rp"),
                schedule_id=schedule.id,
                period_number=period_number,
                period_start=current_start,
                period_end=current_end,
                amount_to_recognize=amount,
                recognized_amount=0,
                status=PeriodStatus.PENDING,
                livemode=schedule.livemode,
            )
            periods.append(period)

            period_number += 1
            if month == 12:
                current_start = date(year + 1, 1, 1)
            else:
                current_start = date(year, month + 1, 1)

        return periods

    def _create_quarterly_periods(
        self,
        schedule: RecognitionSchedule,
        start_date: date,
        end_date: date,
    ) -> List[RecognitionPeriod]:
        periods = []
        current_start = start_date
        period_number = 1
        total_quarters = max(1, ((end_date.year - start_date.year) * 4 + 
                                 (end_date.month - start_date.month)) // 3 + 1)
        base_amount = schedule.total_amount // total_quarters
        remainder = schedule.total_amount % total_quarters

        while current_start <= end_date:
            quarter = (current_start.month - 1) // 3
            quarter_end_month = (quarter + 1) * 3
            last_day = calendar.monthrange(current_start.year, quarter_end_month)[1]
            current_end = date(current_start.year, quarter_end_month, last_day)
            if current_end > end_date:
                current_end = end_date

            amount = base_amount
            if period_number == total_quarters:
                amount = base_amount + remainder

            period = RecognitionPeriod(
                id=self._generate_id("rp"),
                schedule_id=schedule.id,
                period_number=period_number,
                period_start=current_start,
                period_end=current_end,
                amount_to_recognize=amount,
                recognized_amount=0,
                status=PeriodStatus.PENDING,
                livemode=schedule.livemode,
            )
            periods.append(period)

            period_number += 1
            next_quarter_start_month = quarter_end_month + 1
            if next_quarter_start_month > 12:
                current_start = date(current_start.year + 1, 1, 1)
            else:
                current_start = date(current_start.year, next_quarter_start_month, 1)

        return periods

    def _create_yearly_periods(
        self,
        schedule: RecognitionSchedule,
        start_date: date,
        end_date: date,
    ) -> List[RecognitionPeriod]:
        periods = []
        current_start = start_date
        period_number = 1
        total_years = max(1, end_date.year - start_date.year + 1)
        base_amount = schedule.total_amount // total_years
        remainder = schedule.total_amount % total_years

        while current_start <= end_date:
            current_end = date(current_start.year, 12, 31)
            if current_end > end_date:
                current_end = end_date

            amount = base_amount
            if period_number == total_years:
                amount = base_amount + remainder

            period = RecognitionPeriod(
                id=self._generate_id("rp"),
                schedule_id=schedule.id,
                period_number=period_number,
                period_start=current_start,
                period_end=current_end,
                amount_to_recognize=amount,
                recognized_amount=0,
                status=PeriodStatus.PENDING,
                livemode=schedule.livemode,
            )
            periods.append(period)

            period_number += 1
            current_start = date(current_start.year + 1, 1, 1)

        return periods

    def _create_daily_periods(
        self,
        schedule: RecognitionSchedule,
        start_date: date,
        end_date: date,
        total_days: int,
    ) -> List[RecognitionPeriod]:
        periods = []
        base_amount = schedule.total_amount // total_days
        remainder = schedule.total_amount % total_days
        current_date = start_date
        period_number = 1

        while current_date <= end_date:
            amount = base_amount
            if period_number == total_days:
                amount = base_amount + remainder

            period = RecognitionPeriod(
                id=self._generate_id("rp"),
                schedule_id=schedule.id,
                period_number=period_number,
                period_start=current_date,
                period_end=current_date,
                amount_to_recognize=amount,
                recognized_amount=0,
                status=PeriodStatus.PENDING,
                livemode=schedule.livemode,
            )
            periods.append(period)

            period_number += 1
            current_date = current_date + timedelta(days=1)

        return periods

    def _create_performance_periods(
        self,
        schedule: RecognitionSchedule,
    ) -> List[RecognitionPeriod]:
        periods = []
        period = RecognitionPeriod(
            id=self._generate_id("rp"),
            schedule_id=schedule.id,
            period_number=1,
            period_start=schedule.start_date,
            period_end=schedule.end_date,
            amount_to_recognize=schedule.total_amount,
            recognized_amount=0,
            status=PeriodStatus.PENDING,
            livemode=schedule.livemode,
        )
        periods.append(period)
        return periods

    def _create_usage_periods(
        self,
        schedule: RecognitionSchedule,
    ) -> List[RecognitionPeriod]:
        periods = []
        period = RecognitionPeriod(
            id=self._generate_id("rp"),
            schedule_id=schedule.id,
            period_number=1,
            period_start=schedule.start_date,
            period_end=schedule.end_date,
            amount_to_recognize=0,
            recognized_amount=0,
            status=PeriodStatus.PENDING,
            livemode=schedule.livemode,
        )
        periods.append(period)
        return periods

    def _count_months(self, start_date: date, end_date: date) -> int:
        return (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1

    async def recognize_period(
        self,
        period_id: str,
        amount: Optional[int] = None,
        journal_entry_id: Optional[str] = None,
    ) -> RecognitionPeriod:
        query = select(RecognitionPeriod).where(RecognitionPeriod.id == period_id)
        result = await self.session.execute(query)
        period = result.scalar_one_or_none()

        if not period:
            raise NotFoundError(f"Period {period_id} not found")

        if period.status == PeriodStatus.RECOGNIZED:
            raise ValidationError("Period is already recognized", param="period_id")

        recognition_amount = amount or period.amount_to_recognize - period.recognized_amount
        if recognition_amount <= 0:
            raise ValidationError("Amount must be positive", param="amount")

        if period.recognized_amount + recognition_amount > period.amount_to_recognize:
            raise ValidationError("Amount exceeds period amount to recognize", param="amount")

        await self.schedule_service.recognize(
            schedule_id=period.schedule_id,
            amount=recognition_amount,
            period_id=period_id,
            journal_entry_id=journal_entry_id,
        )

        await self.session.flush()
        return period

    async def auto_recognize(
        self,
        as_of_date: Optional[date] = None,
        account_id: Optional[str] = None,
    ) -> List[RecognitionResult]:
        if as_of_date is None:
            as_of_date = date.today()

        results = []

        query = select(RecognitionPeriod).join(RecognitionSchedule).where(
            and_(
                RecognitionPeriod.status == PeriodStatus.PENDING,
                RecognitionPeriod.period_end <= as_of_date,
                RecognitionSchedule.status.in_([
                    ScheduleStatus.ACTIVE,
                    ScheduleStatus.PENDING,
                    ScheduleStatus.ADJUSTED,
                ]),
            )
        )

        if account_id:
            query = query.where(RecognitionSchedule.account_id == account_id)

        result = await self.session.execute(query)
        periods = result.scalars().all()

        for period in periods:
            try:
                recognition_result = await self.recognize_period(period.id)
                results.append(recognition_result)
            except ValidationError:
                continue

        await self.session.flush()
        return results

    async def list(
        self,
        schedule_id: Optional[str] = None,
        status: Optional[str] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[RecognitionPeriod]:
        query = select(RecognitionPeriod)

        if schedule_id:
            query = query.where(RecognitionPeriod.schedule_id == schedule_id)
        if status:
            query = query.where(RecognitionPeriod.status == status)
        if period_start:
            query = query.where(RecognitionPeriod.period_start >= period_start)
        if period_end:
            query = query.where(RecognitionPeriod.period_end <= period_end)

        query = query.order_by(RecognitionPeriod.period_number)
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class DeferredRevenueService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def track(
        self,
        account_id: str,
        amount: int,
        currency: str,
        source_type: str,
        source_id: str,
        expected_recognition_date: Optional[date] = None,
        schedule_id: Optional[str] = None,
        contract_liability_account: Optional[str] = None,
        contract_asset_account: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DeferredRevenue:
        deferred = DeferredRevenue(
            id=self._generate_id("dr"),
            account_id=account_id,
            amount=amount,
            original_amount=amount,
            currency=currency.lower(),
            source_type=source_type,
            source_id=source_id,
            schedule_id=schedule_id,
            expected_recognition_date=expected_recognition_date,
            status=DeferredRevenueStatus.PENDING,
            recognized_amount=0,
            remaining_amount=amount,
            contract_liability_account=contract_liability_account,
            contract_asset_account=contract_asset_account,
            metadata_=metadata or {},
        )

        self.session.add(deferred)
        await self.session.flush()

        return deferred

    async def release(
        self,
        deferred_id: str,
        amount: int,
        journal_entry_id: Optional[str] = None,
    ) -> DeferredRevenue:
        query = select(DeferredRevenue).where(DeferredRevenue.id == deferred_id)
        result = await self.session.execute(query)
        deferred = result.scalar_one_or_none()

        if not deferred:
            raise NotFoundError(f"Deferred revenue {deferred_id} not found")

        if deferred.status == DeferredRevenueStatus.RECOGNIZED:
            raise ValidationError("Deferred revenue is already fully recognized", param="deferred_id")

        if amount > deferred.remaining_amount:
            raise ValidationError(
                f"Amount {amount} exceeds remaining amount {deferred.remaining_amount}",
                param="amount",
            )

        deferred.recognized_amount += amount
        deferred.remaining_amount -= amount
        deferred.amount = deferred.remaining_amount

        if deferred.remaining_amount == 0:
            deferred.status = DeferredRevenueStatus.RECOGNIZED
            deferred.actual_recognition_date = date.today()
        else:
            deferred.status = DeferredRevenueStatus.RECOGNIZING

        await self.session.flush()
        return deferred

    async def report(
        self,
        account_id: str,
        currency: Optional[str] = None,
        as_of_date: Optional[date] = None,
    ) -> DeferredBalanceReport:
        if as_of_date is None:
            as_of_date = date.today()

        query = select(DeferredRevenue).where(
            DeferredRevenue.account_id == account_id
        )

        if currency:
            query = query.where(DeferredRevenue.currency == currency.lower())

        result = await self.session.execute(query)
        deferred_items = result.scalars().all()

        total_deferred = sum(d.remaining_amount for d in deferred_items)
        total_recognized = sum(d.recognized_amount for d in deferred_items)
        pending_recognition = sum(
            d.remaining_amount for d in deferred_items
            if d.status in [DeferredRevenueStatus.PENDING, DeferredRevenueStatus.RECOGNIZING]
        )

        by_period = []
        period_aggregation = {}
        for item in deferred_items:
            month_key = item.expected_recognition_date.strftime("%Y-%m") if item.expected_recognition_date else "unknown"
            if month_key not in period_aggregation:
                period_aggregation[month_key] = {"amount": 0, "count": 0}
            period_aggregation[month_key]["amount"] += item.remaining_amount
            period_aggregation[month_key]["count"] += 1

        for period_key, data in sorted(period_aggregation.items()):
            by_period.append({
                "period": period_key,
                "amount": data["amount"],
                "count": data["count"],
            })

        by_source = []
        source_aggregation = {}
        for item in deferred_items:
            source_key = f"{item.source_type}:{item.source_id}"
            if source_key not in source_aggregation:
                source_aggregation[source_key] = {
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "amount": 0,
                    "count": 0,
                }
            source_aggregation[source_key]["amount"] += item.remaining_amount
            source_aggregation[source_key]["count"] += 1

        for source_data in source_aggregation.values():
            by_source.append(source_data)

        return DeferredBalanceReport(
            account_id=account_id,
            currency=currency or "usd",
            total_deferred=total_deferred,
            total_recognized=total_recognized,
            pending_recognition=pending_recognition,
            by_period=by_period,
            by_source=by_source,
        )

    async def list(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        expected_before: Optional[date] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[DeferredRevenue]:
        query = select(DeferredRevenue)

        if account_id:
            query = query.where(DeferredRevenue.account_id == account_id)
        if status:
            query = query.where(DeferredRevenue.status == status)
        if source_type:
            query = query.where(DeferredRevenue.source_type == source_type)
        if expected_before:
            query = query.where(DeferredRevenue.expected_recognition_date <= expected_before)

        query = query.order_by(DeferredRevenue.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class AllocationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def allocate_transaction(
        self,
        transaction_id: str,
        total_amount: int,
        currency: str,
        products: List[Dict[str, Any]],
        bundle_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        allocation_method: str = "standalone_price",
    ) -> AllocationResult:
        if not products:
            raise ValidationError("Products list cannot be empty", param="products")

        total_standalone = sum(p.get("standalone_price", 0) for p in products)
        if total_standalone == 0:
            raise ValidationError("Total standalone price cannot be zero", param="products")

        allocations = []
        total_allocated = 0

        for i, product in enumerate(products):
            product_id = product.get("product_id")
            standalone_price = product.get("standalone_price", 0)
            fair_value = product.get("fair_value", standalone_price)

            if standalone_price == 0:
                allocation_pct = Decimal("0")
                allocated_amount = 0
            else:
                allocation_pct = Decimal(str(standalone_price)) / Decimal(str(total_standalone))
                allocated_amount = int(total_amount * allocation_pct)

            if i == len(products) - 1:
                allocated_amount = total_amount - total_allocated

            discount = standalone_price - allocated_amount if standalone_price > allocated_amount else 0

            allocation = RevenueAllocation(
                id=self._generate_id("ra"),
                transaction_id=transaction_id,
                schedule_id=schedule_id,
                product_id=product_id,
                performance_obligation_id=product.get("performance_obligation_id"),
                allocated_amount=allocated_amount,
                fair_value=fair_value,
                standalone_price=standalone_price,
                discount_allocation=discount,
                allocation_percentage=allocation_pct,
                allocation_method=allocation_method,
                currency=currency.lower(),
                bundle_id=bundle_id,
            )

            self.session.add(allocation)
            allocations.append({
                "allocation_id": allocation.id,
                "product_id": product_id,
                "allocated_amount": allocated_amount,
                "standalone_price": standalone_price,
                "fair_value": fair_value,
                "allocation_percentage": float(allocation_pct),
                "discount_allocation": discount,
            })

            total_allocated += allocated_amount

        await self.session.flush()

        return AllocationResult(
            transaction_id=transaction_id,
            total_amount=total_amount,
            allocations=allocations,
        )

    async def fair_value_calc(
        self,
        product_id: str,
        standalone_price: int,
        market_prices: Optional[List[int]] = None,
        cost_plus_margin: Optional[Decimal] = None,
    ) -> int:
        if market_prices and len(market_prices) > 0:
            avg_market = sum(market_prices) / len(market_prices)
            return int((standalone_price + avg_market) / 2)

        if cost_plus_margin:
            return int(standalone_price * (1 + cost_plus_margin))

        return standalone_price

    async def list(
        self,
        transaction_id: Optional[str] = None,
        product_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        bundle_id: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[RevenueAllocation]:
        query = select(RevenueAllocation)

        if transaction_id:
            query = query.where(RevenueAllocation.transaction_id == transaction_id)
        if product_id:
            query = query.where(RevenueAllocation.product_id == product_id)
        if schedule_id:
            query = query.where(RevenueAllocation.schedule_id == schedule_id)
        if bundle_id:
            query = query.where(RevenueAllocation.bundle_id == bundle_id)

        query = query.order_by(RevenueAllocation.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ReportingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate_recognition_report(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        schedules_query = select(RecognitionSchedule).where(
            and_(
                RecognitionSchedule.account_id == account_id,
                RecognitionSchedule.start_date >= start_date,
                RecognitionSchedule.end_date <= end_date,
            )
        )

        if currency:
            schedules_query = schedules_query.where(RecognitionSchedule.currency == currency.lower())

        schedules_result = await self.session.execute(schedules_query)
        schedules = schedules_result.scalars().all()

        transactions_query = select(RecognitionTransaction).join(RecognitionSchedule).where(
            and_(
                RecognitionSchedule.account_id == account_id,
                RecognitionTransaction.timestamp >= datetime.combine(start_date, datetime.min.time()),
                RecognitionTransaction.timestamp <= datetime.combine(end_date, datetime.max.time()),
            )
        )

        if currency:
            transactions_query = transactions_query.where(RecognitionSchedule.currency == currency.lower())

        transactions_result = await self.session.execute(transactions_query)
        transactions = transactions_result.scalars().all()

        total_recognized = sum(t.amount for t in transactions if t.transaction_type == TransactionType.RECOGNITION)
        total_adjustments = sum(t.amount for t in transactions if t.transaction_type == TransactionType.ADJUSTMENT)
        total_reversals = sum(abs(t.amount) for t in transactions if t.transaction_type == TransactionType.REVERSAL)

        by_method = {}
        for schedule in schedules:
            method = schedule.recognition_method.value
            if method not in by_method:
                by_method[method] = {
                    "total_amount": 0,
                    "recognized_amount": 0,
                    "deferred_amount": 0,
                    "schedule_count": 0,
                }
            by_method[method]["total_amount"] += schedule.total_amount
            by_method[method]["recognized_amount"] += schedule.recognized_amount
            by_method[method]["deferred_amount"] += schedule.deferred_amount
            by_method[method]["schedule_count"] += 1

        by_status = {}
        for schedule in schedules:
            status = schedule.status.value
            if status not in by_status:
                by_status[status] = {"count": 0, "amount": 0}
            by_status[status]["count"] += 1
            by_status[status]["amount"] += schedule.total_amount

        return {
            "account_id": account_id,
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "currency": currency or "usd",
            "summary": {
                "total_schedules": len(schedules),
                "total_transactions": len(transactions),
                "total_recognized": total_recognized,
                "total_adjustments": total_adjustments,
                "total_reversals": total_reversals,
            },
            "by_method": by_method,
            "by_status": by_status,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def deferred_balance_report(
        self,
        account_id: str,
        as_of_date: Optional[date] = None,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        if as_of_date is None:
            as_of_date = date.today()

        deferred_service = DeferredRevenueService(self.session)
        report = await deferred_service.report(account_id, currency, as_of_date)

        schedules_query = select(RecognitionSchedule).where(
            RecognitionSchedule.account_id == account_id
        )

        if currency:
            schedules_query = schedules_query.where(RecognitionSchedule.currency == currency.lower())

        schedules_result = await self.session.execute(schedules_query)
        schedules = schedules_result.scalars().all()

        contract_assets = sum(s.recognized_amount - s.total_amount for s in schedules if s.recognized_amount > s.total_amount)
        contract_liabilities = sum(s.deferred_amount for s in schedules)

        return {
            "account_id": account_id,
            "as_of_date": as_of_date.isoformat(),
            "currency": currency or "usd",
            "totals": {
                "total_deferred": report.total_deferred,
                "total_recognized": report.total_recognized,
                "pending_recognition": report.pending_recognition,
                "contract_assets": contract_assets,
                "contract_liabilities": contract_liabilities,
            },
            "by_period": report.by_period,
            "by_source": report.by_source,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class MilestoneService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.schedule_service = ScheduleService(session)

    async def create(
        self,
        schedule_id: str,
        name: str,
        amount: int,
        due_date: Optional[date] = None,
        description: Optional[str] = None,
        sequence: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RecognitionMilestone:
        schedule = await self.schedule_service.get(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {schedule_id} not found")

        if schedule.recognition_method != RecognitionMethod.PERFORMANCE:
            raise ValidationError(
                "Milestones can only be created for performance-based schedules",
                param="schedule_id",
            )

        if sequence == 0:
            max_seq_query = select(func.max(RecognitionMilestone.sequence)).where(
                RecognitionMilestone.schedule_id == schedule_id
            )
            max_seq_result = await self.session.execute(max_seq_query)
            max_seq = max_seq_result.scalar() or 0
            sequence = max_seq + 1

        milestone = RecognitionMilestone(
            id=self._generate_id("rm"),
            schedule_id=schedule_id,
            name=name,
            description=description,
            amount=amount,
            due_date=due_date,
            status=MilestoneStatus.PENDING,
            sequence=sequence,
            metadata_=metadata or {},
        )

        self.session.add(milestone)
        await self.session.flush()

        return milestone

    async def complete(
        self,
        milestone_id: str,
        journal_entry_id: Optional[str] = None,
    ) -> RecognitionMilestone:
        query = select(RecognitionMilestone).where(RecognitionMilestone.id == milestone_id)
        result = await self.session.execute(query)
        milestone = result.scalar_one_or_none()

        if not milestone:
            raise NotFoundError(f"Milestone {milestone_id} not found")

        if milestone.status == MilestoneStatus.COMPLETED:
            raise ValidationError("Milestone is already completed", param="milestone_id")

        if milestone.status == MilestoneStatus.CANCELED:
            raise ValidationError("Cannot complete canceled milestone", param="milestone_id")

        schedule = await self.schedule_service.get(milestone.schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {milestone.schedule_id} not found")

        milestone.status = MilestoneStatus.COMPLETED
        milestone.completed_at = datetime.now(timezone.utc)
        milestone.journal_entry_id = journal_entry_id

        await self.schedule_service.recognize(
            schedule_id=milestone.schedule_id,
            amount=milestone.amount,
            journal_entry_id=journal_entry_id,
        )

        await self.session.flush()
        return milestone

    async def track_progress(
        self,
        schedule_id: str,
    ) -> Dict[str, Any]:
        schedule = await self.schedule_service.get(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {schedule_id} not found")

        query = select(RecognitionMilestone).where(
            RecognitionMilestone.schedule_id == schedule_id
        ).order_by(RecognitionMilestone.sequence)
        result = await self.session.execute(query)
        milestones = result.scalars().all()

        total_milestones = len(milestones)
        completed = sum(1 for m in milestones if m.status == MilestoneStatus.COMPLETED)
        pending = sum(1 for m in milestones if m.status == MilestoneStatus.PENDING)
        canceled = sum(1 for m in milestones if m.status == MilestoneStatus.CANCELED)

        total_amount = sum(m.amount for m in milestones)
        completed_amount = sum(m.amount for m in milestones if m.status == MilestoneStatus.COMPLETED)

        progress_percentage = (completed_amount / total_amount * 100) if total_amount > 0 else 0

        next_milestone = None
        for m in milestones:
            if m.status == MilestoneStatus.PENDING:
                next_milestone = m
                break

        return {
            "schedule_id": schedule_id,
            "total_milestones": total_milestones,
            "completed_milestones": completed,
            "pending_milestones": pending,
            "canceled_milestones": canceled,
            "total_amount": total_amount,
            "completed_amount": completed_amount,
            "remaining_amount": total_amount - completed_amount,
            "progress_percentage": round(progress_percentage, 2),
            "next_milestone": {
                "id": next_milestone.id,
                "name": next_milestone.name,
                "amount": next_milestone.amount,
                "due_date": next_milestone.due_date.isoformat() if next_milestone.due_date else None,
            } if next_milestone else None,
        }

    async def list(
        self,
        schedule_id: str,
        status: Optional[str] = None,
    ) -> List[RecognitionMilestone]:
        query = select(RecognitionMilestone).where(
            RecognitionMilestone.schedule_id == schedule_id
        )

        if status:
            query = query.where(RecognitionMilestone.status == status)

        query = query.order_by(RecognitionMilestone.sequence)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
