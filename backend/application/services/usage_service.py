from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio

from sqlalchemy import select, update, and_, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.usage import (
    UsageRecord,
    UsageRecordSummary,
    Meter,
    MeterEvent,
    MeterEventAdjustment,
    MeterPriceTier,
    UsageAlert,
    UsageReport,
    UsageRecordAction,
    UsageRecordStatus,
    AggregationType,
    ResetPeriod,
    MeterEventAdjustmentType,
    UsageAlertStatus,
    UsageReportStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    UsageError,
)
from payment_platform.shared.utils.identifiers import generate_id


@dataclass
class UsageSummary:
    subscription_item_id: str
    period_start: int
    period_end: int
    total_usage: int
    period_count: int
    aggregation_type: str


@dataclass
class TieredPriceResult:
    total_amount: Decimal
    tiers_used: List[Dict[str, Any]]
    usage_quantity: int


@dataclass
class MeterUsageInfo:
    meter_id: str
    customer_id: Optional[str]
    period_start: int
    period_end: int
    total_value: Decimal
    event_count: int
    aggregated_value: Decimal
    aggregation_type: str


class UsageRecordService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        subscription_item_id: str,
        quantity: int,
        action: str = "increment",
        timestamp: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        period_start: Optional[int] = None,
        period_end: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UsageRecord:
        if idempotency_key:
            existing = await self._get_by_idempotency_key(idempotency_key)
            if existing:
                return existing

        ts = timestamp or int(datetime.now(timezone.utc).timestamp())
        p_start = period_start or ts
        p_end = period_end or (ts + 2592000)

        action_enum = UsageRecordAction.INCREMENT
        if action.lower() == "set":
            action_enum = UsageRecordAction.SET

        record = UsageRecord(
            id=self._generate_id("ur"),
            subscription_item_id=subscription_item_id,
            quantity=quantity,
            timestamp=ts,
            action=action_enum,
            idempotency_key=idempotency_key,
            period_start=p_start,
            period_end=p_end,
            status=UsageRecordStatus.PENDING,
            created=int(datetime.now(timezone.utc).timestamp()),
            metadata_=metadata or {},
        )

        self.session.add(record)
        await self.session.flush()
        return record

    async def list(
        self,
        subscription_item_id: Optional[str] = None,
        status: Optional[str] = None,
        period_start: Optional[int] = None,
        period_end: Optional[int] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[UsageRecord]:
        query = select(UsageRecord)

        if subscription_item_id:
            query = query.where(UsageRecord.subscription_item_id == subscription_item_id)
        if status:
            query = query.where(UsageRecord.status == status)
        if period_start:
            query = query.where(UsageRecord.period_start >= period_start)
        if period_end:
            query = query.where(UsageRecord.period_end <= period_end)

        query = query.order_by(UsageRecord.timestamp.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def delete(self, usage_record_id: str) -> UsageRecord:
        record = await self.get(usage_record_id)
        if not record:
            raise NotFoundError(f"Usage record {usage_record_id} not found")

        if record.status == UsageRecordStatus.INVOICED:
            raise UsageError(
                "Cannot delete usage record that has been invoiced",
                usage_record_id=usage_record_id,
            )

        record.status = UsageRecordStatus.CANCELED
        await self.session.flush()
        return record

    async def get(self, usage_record_id: str) -> Optional[UsageRecord]:
        query = select(UsageRecord).where(UsageRecord.id == usage_record_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def validate_period(
        self,
        subscription_item_id: str,
        period_start: int,
        period_end: int,
    ) -> bool:
        if period_start >= period_end:
            raise ValidationError(
                "Period start must be before period end",
                param="period_start",
            )

        query = select(UsageRecord).where(
            and_(
                UsageRecord.subscription_item_id == subscription_item_id,
                UsageRecord.status != UsageRecordStatus.CANCELED,
                or_(
                    and_(
                        UsageRecord.period_start <= period_start,
                        UsageRecord.period_end >= period_start,
                    ),
                    and_(
                        UsageRecord.period_start <= period_end,
                        UsageRecord.period_end >= period_end,
                    ),
                    and_(
                        UsageRecord.period_start >= period_start,
                        UsageRecord.period_end <= period_end,
                    ),
                ),
            )
        )

        result = await self.session.execute(query.limit(1))
        overlapping = result.scalar_one_or_none()
        return overlapping is None

    async def mark_invoiced(
        self,
        usage_record_id: str,
        invoice_id: str,
    ) -> UsageRecord:
        record = await self.get(usage_record_id)
        if not record:
            raise NotFoundError(f"Usage record {usage_record_id} not found")

        record.status = UsageRecordStatus.INVOICED
        record.invoice_id = invoice_id
        await self.session.flush()
        return record

    async def _get_by_idempotency_key(self, key: str) -> Optional[UsageRecord]:
        query = select(UsageRecord).where(UsageRecord.idempotency_key == key)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class UsageSummaryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.record_service = UsageRecordService(session)

    async def calculate_summary(
        self,
        subscription_item_id: str,
        period_start: int,
        period_end: int,
        aggregation_type: str = "sum",
    ) -> UsageRecordSummary:
        query = select(UsageRecord).where(
            and_(
                UsageRecord.subscription_item_id == subscription_item_id,
                UsageRecord.period_start >= period_start,
                UsageRecord.period_end <= period_end,
                UsageRecord.status != UsageRecordStatus.CANCELED,
            )
        )

        result = await self.session.execute(query)
        records = list(result.scalars().all())

        total_usage, aggregated_values = self.aggregate_usage(
            records, aggregation_type
        )

        existing_summary = await self._get_existing_summary(
            subscription_item_id, period_start, period_end
        )

        if existing_summary:
            existing_summary.total_usage = total_usage
            existing_summary.period_count = len(records)
            existing_summary.aggregated_values = aggregated_values
            if records:
                existing_summary.last_usage_record_id = records[-1].id
            await self.session.flush()
            return existing_summary

        summary = UsageRecordSummary(
            id=self._generate_id("urs"),
            subscription_item_id=subscription_item_id,
            period_start=period_start,
            period_end=period_end,
            total_usage=total_usage,
            invoice_usage=0,
            period_count=len(records),
            last_usage_record_id=records[-1].id if records else None,
            aggregated_values=aggregated_values,
            created=int(datetime.now(timezone.utc).timestamp()),
        )

        self.session.add(summary)
        await self.session.flush()
        return summary

    async def get_period_usage(
        self,
        subscription_item_id: str,
        period_start: int,
        period_end: int,
    ) -> int:
        query = select(func.sum(UsageRecord.quantity)).where(
            and_(
                UsageRecord.subscription_item_id == subscription_item_id,
                UsageRecord.period_start >= period_start,
                UsageRecord.period_end <= period_end,
                UsageRecord.status != UsageRecordStatus.CANCELED,
            )
        )

        result = await self.session.execute(query)
        total = result.scalar()
        return total or 0

    def aggregate_usage(
        self,
        records: List[UsageRecord],
        aggregation_type: str,
    ) -> Tuple[int, Dict[str, Any]]:
        if not records:
            return 0, {}

        if aggregation_type == "sum":
            total = sum(r.quantity for r in records)
            return total, {"sum": total}

        elif aggregation_type == "max":
            max_val = max(r.quantity for r in records)
            return max_val, {"max": max_val, "count": len(records)}

        elif aggregation_type == "last":
            sorted_records = sorted(records, key=lambda r: r.timestamp)
            last_val = sorted_records[-1].quantity if sorted_records else 0
            return last_val, {"last": last_val, "timestamp": sorted_records[-1].timestamp if sorted_records else None}

        return sum(r.quantity for r in records), {"sum": sum(r.quantity for r in records)}

    async def get_or_create_summary(
        self,
        subscription_item_id: str,
        period_start: int,
        period_end: int,
    ) -> UsageRecordSummary:
        existing = await self._get_existing_summary(
            subscription_item_id, period_start, period_end
        )
        if existing:
            return existing

        return await self.calculate_summary(
            subscription_item_id, period_start, period_end
        )

    async def _get_existing_summary(
        self,
        subscription_item_id: str,
        period_start: int,
        period_end: int,
    ) -> Optional[UsageRecordSummary]:
        query = select(UsageRecordSummary).where(
            and_(
                UsageRecordSummary.subscription_item_id == subscription_item_id,
                UsageRecordSummary.period_start == period_start,
                UsageRecordSummary.period_end == period_end,
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class MeterService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        name: str,
        aggregation_type: str = "sum",
        reset_period: str = "monthly",
        display_name: Optional[str] = None,
        unit_label: Optional[str] = None,
        default_price_per_unit: Optional[Decimal] = None,
        event_name: Optional[str] = None,
        value_property: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Meter:
        agg_type = self._parse_aggregation_type(aggregation_type)
        reset = self._parse_reset_period(reset_period)

        meter = Meter(
            id=self._generate_id("meter"),
            account_id=account_id,
            name=name,
            display_name=display_name,
            aggregation_type=agg_type,
            unit_label=unit_label,
            reset_period=reset,
            default_price_per_unit=default_price_per_unit,
            event_name=event_name,
            value_property=value_property,
            status="active",
            created=int(datetime.now(timezone.utc).timestamp()),
            metadata_=metadata or {},
        )

        self.session.add(meter)
        await self.session.flush()
        return meter

    async def update(
        self,
        meter_id: str,
        display_name: Optional[str] = None,
        default_price_per_unit: Optional[Decimal] = None,
        status: Optional[str] = None,
    ) -> Meter:
        meter = await self.get(meter_id)
        if not meter:
            raise NotFoundError(f"Meter {meter_id} not found")

        if display_name is not None:
            meter.display_name = display_name
        if default_price_per_unit is not None:
            meter.default_price_per_unit = default_price_per_unit
        if status is not None:
            meter.status = status

        await self.session.flush()
        return meter

    async def get(self, meter_id: str) -> Optional[Meter]:
        query = select(Meter).where(Meter.id == meter_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Meter]:
        query = select(Meter)

        if account_id:
            query = query.where(Meter.account_id == account_id)
        if status:
            query = query.where(Meter.status == status)

        query = query.order_by(Meter.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def track_event(
        self,
        meter_id: str,
        value: Decimal,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        event_name: Optional[str] = None,
        timestamp: Optional[int] = None,
        properties: Optional[Dict[str, Any]] = None,
        identifier: Optional[str] = None,
    ) -> MeterEvent:
        meter = await self.get(meter_id)
        if not meter:
            raise NotFoundError(f"Meter {meter_id} not found")

        if identifier:
            existing = await self._get_event_by_identifier(identifier)
            if existing:
                return existing

        ts = timestamp or int(datetime.now(timezone.utc).timestamp())

        event = MeterEvent(
            id=self._generate_id("me"),
            meter_id=meter_id,
            customer_id=customer_id,
            subscription_id=subscription_id,
            value=value,
            timestamp=ts,
            event_name=event_name or meter.event_name,
            properties=properties,
            identifier=identifier,
            status="processed",
            processed_at=int(datetime.now(timezone.utc).timestamp()),
            created=int(datetime.now(timezone.utc).timestamp()),
        )

        self.session.add(event)
        await self.session.flush()
        return event

    async def calculate_usage(
        self,
        meter_id: str,
        period_start: int,
        period_end: int,
        customer_id: Optional[str] = None,
    ) -> MeterUsageInfo:
        meter = await self.get(meter_id)
        if not meter:
            raise NotFoundError(f"Meter {meter_id} not found")

        query = select(
            func.sum(MeterEvent.value).label("total_value"),
            func.count(MeterEvent.id).label("event_count"),
        ).where(
            and_(
                MeterEvent.meter_id == meter_id,
                MeterEvent.timestamp >= period_start,
                MeterEvent.timestamp <= period_end,
            )
        )

        if customer_id:
            query = query.where(MeterEvent.customer_id == customer_id)

        result = await self.session.execute(query)
        row = result.one()

        total_value = row.total_value or Decimal("0")
        event_count = row.event_count or 0

        aggregated_value = await self._aggregate_by_type(
            meter, period_start, period_end, customer_id
        )

        return MeterUsageInfo(
            meter_id=meter_id,
            customer_id=customer_id,
            period_start=period_start,
            period_end=period_end,
            total_value=total_value,
            event_count=event_count,
            aggregated_value=aggregated_value,
            aggregation_type=meter.aggregation_type.value,
        )

    async def _aggregate_by_type(
        self,
        meter: Meter,
        period_start: int,
        period_end: int,
        customer_id: Optional[str] = None,
    ) -> Decimal:
        query = select(MeterEvent).where(
            and_(
                MeterEvent.meter_id == meter.id,
                MeterEvent.timestamp >= period_start,
                MeterEvent.timestamp <= period_end,
            )
        )

        if customer_id:
            query = query.where(MeterEvent.customer_id == customer_id)

        result = await self.session.execute(query)
        events = list(result.scalars().all())

        if not events:
            return Decimal("0")

        if meter.aggregation_type == AggregationType.SUM:
            return sum(e.value for e in events)
        elif meter.aggregation_type == AggregationType.MAX:
            return max(e.value for e in events)
        elif meter.aggregation_type == AggregationType.LAST:
            sorted_events = sorted(events, key=lambda e: e.timestamp)
            return sorted_events[-1].value if sorted_events else Decimal("0")

        return sum(e.value for e in events)

    async def _get_event_by_identifier(self, identifier: str) -> Optional[MeterEvent]:
        query = select(MeterEvent).where(MeterEvent.identifier == identifier)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def _parse_aggregation_type(self, agg_type: str) -> AggregationType:
        mapping = {
            "sum": AggregationType.SUM,
            "max": AggregationType.MAX,
            "last": AggregationType.LAST,
        }
        if agg_type.lower() not in mapping:
            raise ValidationError(f"Invalid aggregation type: {agg_type}", param="aggregation_type")
        return mapping[agg_type.lower()]

    def _parse_reset_period(self, reset: str) -> ResetPeriod:
        mapping = {
            "never": ResetPeriod.NEVER,
            "daily": ResetPeriod.DAILY,
            "weekly": ResetPeriod.WEEKLY,
            "monthly": ResetPeriod.MONTHLY,
            "yearly": ResetPeriod.YEARLY,
        }
        if reset.lower() not in mapping:
            raise ValidationError(f"Invalid reset period: {reset}", param="reset_period")
        return mapping[reset.lower()]

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class MeterEventService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.meter_service = MeterService(session)

    async def create_event(
        self,
        meter_id: str,
        value: Decimal,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        event_name: Optional[str] = None,
        timestamp: Optional[int] = None,
        properties: Optional[Dict[str, Any]] = None,
        identifier: Optional[str] = None,
        backfill: bool = False,
    ) -> MeterEvent:
        return await self.meter_service.track_event(
            meter_id=meter_id,
            value=value,
            customer_id=customer_id,
            subscription_id=subscription_id,
            event_name=event_name,
            timestamp=timestamp,
            properties=properties,
            identifier=identifier,
        )

    async def apply_adjustment(
        self,
        meter_event_id: str,
        adjustment_type: str,
        amount: Decimal,
        reason: Optional[str] = None,
    ) -> MeterEventAdjustment:
        event = await self.get_event(meter_event_id)
        if not event:
            raise NotFoundError(f"Meter event {meter_event_id} not found")

        adj_type = MeterEventAdjustmentType.CREDIT
        if adjustment_type.lower() == "debit":
            adj_type = MeterEventAdjustmentType.DEBIT

        adjustment = MeterEventAdjustment(
            id=self._generate_id("mea"),
            meter_event_id=meter_event_id,
            adjustment_type=adj_type,
            amount=amount,
            reason=reason,
            created=int(datetime.now(timezone.utc).timestamp()),
        )

        self.session.add(adjustment)
        await self.session.flush()
        return adjustment

    async def list_events(
        self,
        meter_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[MeterEvent]:
        query = select(MeterEvent)

        if meter_id:
            query = query.where(MeterEvent.meter_id == meter_id)
        if customer_id:
            query = query.where(MeterEvent.customer_id == customer_id)
        if subscription_id:
            query = query.where(MeterEvent.subscription_id == subscription_id)
        if start_time:
            query = query.where(MeterEvent.timestamp >= start_time)
        if end_time:
            query = query.where(MeterEvent.timestamp <= end_time)

        query = query.order_by(MeterEvent.timestamp.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_event(self, event_id: str) -> Optional[MeterEvent]:
        query = select(MeterEvent).where(MeterEvent.id == event_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class PricingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def calculate_tiered_price(
        self,
        meter_id: str,
        usage_quantity: int,
        price_id: Optional[str] = None,
    ) -> TieredPriceResult:
        query = select(MeterPriceTier).where(
            MeterPriceTier.meter_id == meter_id
        )

        if price_id:
            query = query.where(MeterPriceTier.price_id == price_id)

        query = query.order_by(MeterPriceTier.up_to.nulls_last())

        result = await self.session.execute(query)
        tiers = list(result.scalars().all())

        if not tiers:
            meter_query = select(Meter).where(Meter.id == meter_id)
            meter_result = await self.session.execute(meter_query)
            meter = meter_result.scalar_one_or_none()

            if meter and meter.default_price_per_unit:
                total = Decimal(str(usage_quantity)) * meter.default_price_per_unit
                return TieredPriceResult(
                    total_amount=total,
                    tiers_used=[{
                        "unit_amount": float(meter.default_price_per_unit),
                        "quantity": usage_quantity,
                    }],
                    usage_quantity=usage_quantity,
                )

            raise ValidationError(f"No price tiers found for meter {meter_id}")

        total_amount = Decimal("0")
        remaining = usage_quantity
        tiers_used = []

        for i, tier in enumerate(tiers):
            tier_limit = tier.up_to if tier.up_to else float("inf")

            if remaining <= 0:
                break

            prev_limit = 0
            if i > 0 and tiers[i - 1].up_to:
                prev_limit = tiers[i - 1].up_to

            tier_capacity = tier_limit - prev_limit
            usage_in_tier = min(remaining, int(tier_capacity))

            if tier.tier_type == "volume":
                if usage_quantity > prev_limit and (tier.up_to is None or usage_quantity <= tier.up_to):
                    tier_total = Decimal(str(usage_quantity)) * tier.unit_amount
                    if tier.flat_amount:
                        tier_total += Decimal(str(tier.flat_amount))
                    total_amount = tier_total
                    tiers_used = [{
                        "tier_id": tier.id,
                        "up_to": tier.up_to,
                        "unit_amount": float(tier.unit_amount),
                        "flat_amount": tier.flat_amount,
                        "quantity": usage_quantity,
                    }]
                    break
            else:
                if usage_in_tier > 0:
                    tier_total = Decimal(str(usage_in_tier)) * tier.unit_amount
                    if tier.flat_amount and i == 0:
                        tier_total += Decimal(str(tier.flat_amount))
                    total_amount += tier_total
                    tiers_used.append({
                        "tier_id": tier.id,
                        "up_to": tier.up_to,
                        "unit_amount": float(tier.unit_amount),
                        "quantity": usage_in_tier,
                    })
                    remaining -= usage_in_tier

        return TieredPriceResult(
            total_amount=total_amount,
            tiers_used=tiers_used,
            usage_quantity=usage_quantity,
        )

    async def calculate_overage(
        self,
        meter_id: str,
        included_quantity: int,
        actual_usage: int,
    ) -> Tuple[int, Decimal]:
        if actual_usage <= included_quantity:
            return 0, Decimal("0")

        overage = actual_usage - included_quantity

        meter_query = select(Meter).where(Meter.id == meter_id)
        meter_result = await self.session.execute(meter_query)
        meter = meter_result.scalar_one_or_none()

        if not meter:
            raise NotFoundError(f"Meter {meter_id} not found")

        price = await self.calculate_tiered_price(meter_id, overage)
        return overage, price.total_amount

    async def get_tiers_for_meter(
        self,
        meter_id: str,
        price_id: Optional[str] = None,
    ) -> List[MeterPriceTier]:
        query = select(MeterPriceTier).where(
            MeterPriceTier.meter_id == meter_id
        )

        if price_id:
            query = query.where(MeterPriceTier.price_id == price_id)

        query = query.order_by(MeterPriceTier.up_to.nulls_last())

        result = await self.session.execute(query)
        return list(result.scalars().all())


class UsageAlertService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_alert(
        self,
        subscription_item_id: str,
        threshold: int,
        notification_emails: Optional[List[str]] = None,
        webhook_url: Optional[str] = None,
    ) -> UsageAlert:
        alert = UsageAlert(
            id=self._generate_id("ual"),
            subscription_item_id=subscription_item_id,
            threshold=threshold,
            notification_emails=notification_emails,
            webhook_url=webhook_url,
            status=UsageAlertStatus.ACTIVE,
            current_usage=0,
            created=int(datetime.now(timezone.utc).timestamp()),
        )

        self.session.add(alert)
        await self.session.flush()
        return alert

    async def check_thresholds(
        self,
        subscription_item_id: str,
        current_usage: int,
    ) -> List[UsageAlert]:
        query = select(UsageAlert).where(
            and_(
                UsageAlert.subscription_item_id == subscription_item_id,
                UsageAlert.status == UsageAlertStatus.ACTIVE,
                UsageAlert.threshold <= current_usage,
            )
        )

        result = await self.session.execute(query)
        triggered_alerts = list(result.scalars().all())

        for alert in triggered_alerts:
            alert.status = UsageAlertStatus.TRIGGERED
            alert.triggered_at = int(datetime.now(timezone.utc).timestamp())
            alert.current_usage = current_usage

        await self.session.flush()
        return triggered_alerts

    async def notify(
        self,
        alert: UsageAlert,
        current_usage: int,
    ) -> Dict[str, Any]:
        notification_results = {
            "alert_id": alert.id,
            "threshold": alert.threshold,
            "current_usage": current_usage,
            "emails_sent": [],
            "webhook_sent": False,
        }

        if alert.notification_emails:
            for email in alert.notification_emails:
                notification_results["emails_sent"].append({
                    "email": email,
                    "status": "sent",
                })

        if alert.webhook_url:
            notification_results["webhook_sent"] = True

        return notification_results

    async def list_alerts(
        self,
        subscription_item_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[UsageAlert]:
        query = select(UsageAlert)

        if subscription_item_id:
            query = query.where(UsageAlert.subscription_item_id == subscription_item_id)
        if status:
            query = query.where(UsageAlert.status == status)

        query = query.order_by(UsageAlert.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def delete_alert(self, alert_id: str) -> bool:
        query = select(UsageAlert).where(UsageAlert.id == alert_id)
        result = await self.session.execute(query)
        alert = result.scalar_one_or_none()

        if not alert:
            return False

        await self.session.delete(alert)
        await self.session.flush()
        return True

    async def update_usage(
        self,
        subscription_item_id: str,
        current_usage: int,
    ) -> List[UsageAlert]:
        query = select(UsageAlert).where(
            and_(
                UsageAlert.subscription_item_id == subscription_item_id,
                UsageAlert.status == UsageAlertStatus.ACTIVE,
            )
        )

        result = await self.session.execute(query)
        alerts = list(result.scalars().all())

        for alert in alerts:
            alert.current_usage = current_usage

        await self.session.flush()

        triggered = []
        for alert in alerts:
            if current_usage >= alert.threshold:
                alert.status = UsageAlertStatus.TRIGGERED
                alert.triggered_at = int(datetime.now(timezone.utc).timestamp())
                triggered.append(alert)

        await self.session.flush()
        return triggered

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class UsageReportService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.summary_service = UsageSummaryService(session)
        self.pricing_service = PricingService(session)

    async def generate_report(
        self,
        subscription_id: str,
        period_start: int,
        period_end: int,
        currency: str = "usd",
    ) -> UsageReport:
        existing = await self._get_existing_report(
            subscription_id, period_start, period_end
        )
        if existing and existing.status == UsageReportStatus.COMPLETED:
            return existing

        if existing:
            report = existing
            report.status = UsageReportStatus.GENERATING
        else:
            report = UsageReport(
                id=self._generate_id("urpt"),
                subscription_id=subscription_id,
                period_start=period_start,
                period_end=period_end,
                currency=currency,
                status=UsageReportStatus.GENERATING,
                created=int(datetime.now(timezone.utc).timestamp()),
            )
            self.session.add(report)

        await self.session.flush()

        try:
            usage_summary = await self._collect_usage_data(
                subscription_id, period_start, period_end
            )

            line_items, total_usage, total_amount = await self._build_line_items(
                usage_summary
            )

            report.usage_summary = usage_summary
            report.line_items = line_items
            report.total_usage = total_usage
            report.total_amount = total_amount
            report.status = UsageReportStatus.COMPLETED
            report.generated_at = int(datetime.now(timezone.utc).timestamp())

        except Exception as e:
            report.status = UsageReportStatus.FAILED
            report.usage_summary = {"error": str(e)}

        await self.session.flush()
        return report

    async def calculate_period_totals(
        self,
        subscription_id: str,
        period_start: int,
        period_end: int,
    ) -> Dict[str, Any]:
        report = await self.generate_report(
            subscription_id, period_start, period_end
        )

        return {
            "subscription_id": subscription_id,
            "period_start": period_start,
            "period_end": period_end,
            "total_usage": report.total_usage,
            "total_amount": report.total_amount,
            "currency": report.currency,
            "status": report.status.value,
            "generated_at": report.generated_at,
        }

    async def list_reports(
        self,
        subscription_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[UsageReport]:
        query = select(UsageReport)

        if subscription_id:
            query = query.where(UsageReport.subscription_id == subscription_id)
        if status:
            query = query.where(UsageReport.status == status)

        query = query.order_by(UsageReport.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_report(self, report_id: str) -> Optional[UsageReport]:
        query = select(UsageReport).where(UsageReport.id == report_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _collect_usage_data(
        self,
        subscription_id: str,
        period_start: int,
        period_end: int,
    ) -> Dict[str, Any]:
        meter_query = select(MeterEvent).where(
            and_(
                MeterEvent.subscription_id == subscription_id,
                MeterEvent.timestamp >= period_start,
                MeterEvent.timestamp <= period_end,
            )
        )

        result = await self.session.execute(meter_query)
        events = list(result.scalars().all())

        meter_totals = {}
        for event in events:
            if event.meter_id not in meter_totals:
                meter_totals[event.meter_id] = {
                    "total_value": Decimal("0"),
                    "event_count": 0,
                    "customer_ids": set(),
                }
            meter_totals[event.meter_id]["total_value"] += event.value
            meter_totals[event.meter_id]["event_count"] += 1
            if event.customer_id:
                meter_totals[event.meter_id]["customer_ids"].add(event.customer_id)

        return {
            "subscription_id": subscription_id,
            "period_start": period_start,
            "period_end": period_end,
            "meters": {
                k: {
                    "total_value": float(v["total_value"]),
                    "event_count": v["event_count"],
                    "unique_customers": len(v["customer_ids"]),
                }
                for k, v in meter_totals.items()
            },
            "total_events": len(events),
        }

    async def _build_line_items(
        self,
        usage_summary: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        line_items = []
        total_usage = 0
        total_amount = 0

        for meter_id, meter_data in usage_summary.get("meters", {}).items():
            try:
                usage_qty = int(meter_data.get("total_value", 0))
                price_result = await self.pricing_service.calculate_tiered_price(
                    meter_id, usage_qty
                )

                line_item = {
                    "meter_id": meter_id,
                    "quantity": usage_qty,
                    "amount": int(price_result.total_amount * 100),
                    "tiers": price_result.tiers_used,
                }

                line_items.append(line_item)
                total_usage += usage_qty
                total_amount += int(price_result.total_amount * 100)

            except Exception:
                line_items.append({
                    "meter_id": meter_id,
                    "quantity": meter_data.get("total_value", 0),
                    "amount": 0,
                    "error": "Unable to calculate price",
                })

        return line_items, total_usage, total_amount

    async def _get_existing_report(
        self,
        subscription_id: str,
        period_start: int,
        period_end: int,
    ) -> Optional[UsageReport]:
        query = select(UsageReport).where(
            and_(
                UsageReport.subscription_id == subscription_id,
                UsageReport.period_start == period_start,
                UsageReport.period_end == period_end,
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
