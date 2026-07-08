from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
import secrets

from payment_platform.backend.domain.capital import (
    FinancingOffer, Financing, RepaymentSchedule, Repayment,
    FinancingTransaction, OfferEligibility, CollectionPlan,
    RepaymentMethod, InterestType, FinancingStatus,
    FinancingTransactionType, DelinquencyStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError, ValidationError, CapitalError,
    InsufficientBalanceError, AuthorizationError,
)
from payment_platform.shared.utils.identifiers import (
    generate_id, generate_capital_financing_id,
)


class OfferService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        amount: int,
        currency: str,
        interest_rate: Decimal,
        term_months: int,
        repayment_method: str,
        interest_type: str = "simple",
        revenue_share_percentage: Optional[Decimal] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_in_days: int = 30,
    ) -> FinancingOffer:
        eligibility = await self.evaluate_eligibility(account_id)
        if not eligibility.eligible:
            raise ValidationError(
                f"Account not eligible for financing: {', '.join(eligibility.reason_codes or [])}"
            )
        if amount > (eligibility.max_amount or 0):
            raise ValidationError(
                f"Requested amount {amount} exceeds maximum eligible amount {eligibility.max_amount}"
            )
        terms = await self.calculate_terms(
            amount=amount,
            interest_rate=interest_rate,
            term_months=term_months,
            repayment_method=repayment_method,
            interest_type=interest_type,
            revenue_share_percentage=revenue_share_percentage,
        )
        offer_id = generate_capital_financing_id()
        offer = FinancingOffer(
            id=offer_id,
            account_id=account_id,
            amount=amount,
            currency=currency.lower(),
            interest_rate=interest_rate,
            interest_type=interest_type,
            term_months=term_months,
            repayment_method=repayment_method,
            revenue_share_percentage=revenue_share_percentage,
            total_repayment_amount=terms["total_repayment"],
            status="pending",
            expires_at=datetime.utcnow() + timedelta(days=expires_in_days),
            risk_score=eligibility.risk_score,
            risk_tier=eligibility.risk_tier,
            metadata_=metadata or {},
        )
        self.session.add(offer)
        await self.session.flush()
        return offer

    async def evaluate_eligibility(self, account_id: str) -> OfferEligibility:
        existing = await self.session.execute(
            select(OfferEligibility).where(OfferEligibility.account_id == account_id)
        )
        eligibility = existing.scalar_one_or_none()
        if eligibility and (datetime.utcnow() - eligibility.evaluated_at) < timedelta(hours=24):
            return eligibility
        risk_score = Decimal(str(secrets.randbelow(100))) / Decimal("100")
        risk_tier = self._determine_risk_tier(risk_score)
        processing_volume = secrets.randbelow(10000000) + 100000
        monthly_revenue = processing_volume // 3
        max_amount = int(monthly_revenue * Decimal("2.5"))
        eligible = risk_score < Decimal("0.85") and processing_volume > 50000
        reason_codes = []
        if risk_score >= Decimal("0.85"):
            reason_codes.append("high_risk_score")
        if processing_volume <= 50000:
            reason_codes.append("insufficient_processing_volume")
        if not eligible:
            max_amount = 0
        eligibility = OfferEligibility(
            id=generate_id("elig"),
            account_id=account_id,
            eligible=eligible,
            max_amount=max_amount if eligible else None,
            currency="usd",
            reason_codes=reason_codes if not eligible else None,
            risk_score=risk_score,
            risk_tier=risk_tier,
            monthly_revenue=monthly_revenue,
            processing_volume_90d=processing_volume,
            evaluated_at=datetime.utcnow(),
        )
        self.session.add(eligibility)
        await self.session.flush()
        return eligibility

    async def calculate_terms(
        self,
        amount: int,
        interest_rate: Decimal,
        term_months: int,
        repayment_method: str,
        interest_type: str = "simple",
        revenue_share_percentage: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        annual_rate = interest_rate / Decimal("100")
        monthly_rate = annual_rate / Decimal("12")
        if interest_type == "compound":
            total_interest = amount * ((Decimal("1") + monthly_rate) ** term_months - Decimal("1"))
        else:
            total_interest = amount * monthly_rate * term_months
        total_interest = int(total_interest.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total_repayment = amount + total_interest
        terms = {
            "principal": amount,
            "interest_rate": float(interest_rate),
            "interest_type": interest_type,
            "term_months": term_months,
            "total_interest": total_interest,
            "total_repayment": total_repayment,
            "monthly_rate": float(monthly_rate),
        }
        if repayment_method == "fixed":
            monthly_payment = total_repayment // term_months
            terms["monthly_payment"] = monthly_payment
            terms["fixed_payment_amount"] = monthly_payment
        elif repayment_method == "revenue_share":
            if revenue_share_percentage is None:
                raise ValidationError("revenue_share_percentage required for revenue share method")
            terms["revenue_share_percentage"] = float(revenue_share_percentage)
            terms["estimated_months_to_repay"] = self._estimate_revenue_share_months(
                amount, revenue_share_percentage, total_repayment
            )
        return terms

    async def get_by_id(self, offer_id: str) -> Optional[FinancingOffer]:
        result = await self.session.execute(
            select(FinancingOffer).where(FinancingOffer.id == offer_id)
        )
        return result.scalar_one_or_none()

    async def get_by_account(
        self,
        account_id: str,
        status: Optional[str] = None,
    ) -> List[FinancingOffer]:
        query = select(FinancingOffer).where(FinancingOffer.account_id == account_id)
        if status:
            query = query.where(FinancingOffer.status == status)
        query = query.order_by(FinancingOffer.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def accept(self, offer_id: str) -> FinancingOffer:
        offer = await self.get_by_id(offer_id)
        if not offer:
            raise NotFoundError(f"Offer {offer_id} not found")
        if offer.status != "pending":
            raise ValidationError(f"Offer cannot be accepted in status {offer.status}")
        if offer.expires_at < datetime.utcnow():
            raise ValidationError("Offer has expired")
        offer.status = "accepted"
        offer.accepted_at = datetime.utcnow()
        await self.session.flush()
        return offer

    async def decline(self, offer_id: str) -> FinancingOffer:
        offer = await self.get_by_id(offer_id)
        if not offer:
            raise NotFoundError(f"Offer {offer_id} not found")
        if offer.status != "pending":
            raise ValidationError(f"Offer cannot be declined in status {offer.status}")
        offer.status = "declined"
        offer.declined_at = datetime.utcnow()
        await self.session.flush()
        return offer

    def _determine_risk_tier(self, risk_score: Decimal) -> str:
        if risk_score < Decimal("0.25"):
            return "prime"
        elif risk_score < Decimal("0.50"):
            return "near_prime"
        elif risk_score < Decimal("0.75"):
            return "subprime"
        else:
            return "high_risk"

    def _estimate_revenue_share_months(
        self,
        amount: int,
        percentage: Decimal,
        total_repayment: int,
    ) -> int:
        estimated_monthly_revenue = amount // 3
        estimated_monthly_payment = int(estimated_monthly_revenue * percentage / Decimal("100"))
        if estimated_monthly_payment <= 0:
            return 999
        return (total_repayment + estimated_monthly_payment - 1) // estimated_monthly_payment


class FinancingService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def disburse(
        self,
        offer_id: str,
        disbursement_destination: Optional[str] = None,
    ) -> Financing:
        offer_service = OfferService(self.session)
        offer = await offer_service.get_by_id(offer_id)
        if not offer:
            raise NotFoundError(f"Offer {offer_id} not found")
        if offer.status != "accepted":
            raise ValidationError(f"Offer must be accepted before disbursement")
        financing_id = generate_capital_financing_id()
        terms = {
            "interest_rate": float(offer.interest_rate),
            "interest_type": offer.interest_type,
            "term_months": offer.term_months,
            "repayment_method": offer.repayment_method,
            "revenue_share_percentage": float(offer.revenue_share_percentage) if offer.revenue_share_percentage else None,
            "total_repayment": offer.total_repayment_amount,
        }
        financing = Financing(
            id=financing_id,
            account_id=offer.account_id,
            offer_id=offer_id,
            amount=offer.amount,
            currency=offer.currency,
            interest_rate=offer.interest_rate,
            interest_type=offer.interest_type,
            term_months=offer.term_months,
            repayment_method=offer.repayment_method,
            revenue_share_percentage=offer.revenue_share_percentage,
            status="active",
            outstanding_principal=offer.amount,
            outstanding_interest=0,
            outstanding_balance=offer.amount,
            disbursed_at=datetime.utcnow(),
            terms=terms,
        )
        self.session.add(financing)
        offer.status = "disbursed"
        await self.session.flush()
        await self._create_disbursement_transaction(financing)
        await self._create_repayment_schedule(financing)
        return financing

    async def _create_disbursement_transaction(self, financing: Financing) -> None:
        transaction = FinancingTransaction(
            id=generate_id("fintrx"),
            financing_id=financing.id,
            account_id=financing.account_id,
            type="disbursement",
            amount=financing.amount,
            balance_before=0,
            balance_after=financing.amount,
            timestamp=datetime.utcnow(),
            description="Initial disbursement",
        )
        self.session.add(transaction)
        await self.session.flush()

    async def _create_repayment_schedule(self, financing: Financing) -> Financing:
        schedule = await self._generate_schedule(financing)
        repayment_schedule = RepaymentSchedule(
            id=generate_id("rsched"),
            financing_id=financing.id,
            installments=schedule,
            total_installments=len(schedule),
            completed_installments=0,
            next_payment_date=schedule[0]["due_date"] if schedule else None,
            next_payment_amount=schedule[0]["amount"] if schedule else None,
            total_remaining=financing.terms.get("total_repayment", financing.amount),
            total_paid=0,
        )
        self.session.add(repayment_schedule)
        financing.next_payment_date = schedule[0]["due_date"] if schedule else None
        financing.next_payment_amount = schedule[0]["amount"] if schedule else None
        await self.session.flush()
        return financing

    async def _generate_schedule(self, financing: Financing) -> List[Dict[str, Any]]:
        installments = []
        remaining_principal = financing.amount
        remaining_total = financing.terms.get("total_repayment", financing.amount)
        monthly_rate = float(financing.interest_rate) / 100 / 12
        if financing.repayment_method == "fixed":
            monthly_payment = remaining_total // financing.term_months
            remainder = remaining_total % financing.term_months
            for i in range(financing.term_months):
                payment = monthly_payment + (1 if i < remainder else 0)
                interest_portion = int(remaining_principal * monthly_rate)
                principal_portion = payment - interest_portion
                if i == financing.term_months - 1:
                    principal_portion = remaining_principal
                    payment = principal_portion + interest_portion
                due_date = date.today() + timedelta(days=30 * (i + 1))
                installments.append({
                    "number": i + 1,
                    "due_date": due_date.isoformat(),
                    "amount": payment,
                    "principal": principal_portion,
                    "interest": interest_portion,
                    "status": "pending",
                    "remaining_balance": remaining_principal - principal_portion,
                })
                remaining_principal -= principal_portion
        else:
            for i in range(financing.term_months):
                due_date = date.today() + timedelta(days=30 * (i + 1))
                installments.append({
                    "number": i + 1,
                    "due_date": due_date.isoformat(),
                    "amount": None,
                    "principal": None,
                    "interest": None,
                    "status": "pending",
                    "remaining_balance": remaining_principal,
                })
        return installments

    async def get_by_id(self, financing_id: str) -> Optional[Financing]:
        result = await self.session.execute(
            select(Financing).where(Financing.id == financing_id)
        )
        return result.scalar_one_or_none()

    async def get_by_account(
        self,
        account_id: str,
        status: Optional[str] = None,
    ) -> List[Financing]:
        query = select(Financing).where(Financing.account_id == account_id)
        if status:
            query = query.where(Financing.status == status)
        query = query.order_by(Financing.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def track_balance(self, financing_id: str) -> Dict[str, Any]:
        financing = await self.get_by_id(financing_id)
        if not financing:
            raise NotFoundError(f"Financing {financing_id} not found")
        return {
            "financing_id": financing.id,
            "original_amount": financing.amount,
            "outstanding_principal": financing.outstanding_principal,
            "outstanding_interest": financing.outstanding_interest,
            "outstanding_balance": financing.outstanding_balance,
            "total_paid": financing.total_principal_paid + financing.total_interest_paid + financing.total_fees_paid,
            "principal_paid": financing.total_principal_paid,
            "interest_paid": financing.total_interest_paid,
            "fees_paid": financing.total_fees_paid,
            "status": financing.status,
        }

    async def calculate_payoff(
        self,
        financing_id: str,
        payoff_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        financing = await self.get_by_id(financing_id)
        if not financing:
            raise NotFoundError(f"Financing {financing_id} not found")
        payoff_date = payoff_date or date.today()
        outstanding_principal = financing.outstanding_principal
        outstanding_interest = financing.outstanding_interest
        if financing.interest_type == "simple":
            days_since_disbursement = (payoff_date - financing.disbursed_at.date()).days if financing.disbursed_at else 0
            daily_rate = float(financing.interest_rate) / 100 / 365
            accrued_interest = int(outstanding_principal * daily_rate * days_since_disbursement)
        else:
            monthly_rate = Decimal(str(financing.interest_rate)) / Decimal("100") / Decimal("12")
            months_since_disbursement = ((payoff_date.year - financing.disbursed_at.year) * 12 + payoff_date.month - financing.disbursed_at.month) if financing.disbursed_at else 0
            accrued_interest = int(outstanding_principal * ((Decimal("1") + monthly_rate) ** months_since_disbursement - Decimal("1")))
        total_payoff = outstanding_principal + outstanding_interest + accrued_interest
        return {
            "financing_id": financing.id,
            "payoff_date": payoff_date.isoformat(),
            "outstanding_principal": outstanding_principal,
            "outstanding_interest": outstanding_interest,
            "accrued_interest": accrued_interest,
            "total_payoff_amount": total_payoff,
            "currency": financing.currency,
        }

    async def get_repayment_schedule(self, financing_id: str) -> Optional[RepaymentSchedule]:
        result = await self.session.execute(
            select(RepaymentSchedule).where(RepaymentSchedule.financing_id == financing_id)
        )
        return result.scalar_one_or_none()

    async def get_summary(self, financing_id: str) -> Dict[str, Any]:
        financing = await self.get_by_id(financing_id)
        if not financing:
            raise NotFoundError(f"Financing {financing_id} not found")
        schedule = await self.get_repayment_schedule(financing_id)
        payoff = await self.calculate_payoff(financing_id)
        return {
            "id": financing.id,
            "object": "financing_summary",
            "account_id": financing.account_id,
            "amount": financing.amount,
            "currency": financing.currency,
            "status": financing.status,
            "disbursed_at": financing.disbursed_at.isoformat() if financing.disbursed_at else None,
            "outstanding_balance": financing.outstanding_balance,
            "outstanding_principal": financing.outstanding_principal,
            "outstanding_interest": financing.outstanding_interest,
            "total_principal_paid": financing.total_principal_paid,
            "total_interest_paid": financing.total_interest_paid,
            "total_fees_paid": financing.total_fees_paid,
            "next_payment_date": financing.next_payment_date.isoformat() if financing.next_payment_date else None,
            "next_payment_amount": financing.next_payment_amount,
            "delinquency_status": financing.delinquency_status,
            "payoff_amount": payoff["total_payoff_amount"],
            "progress_percentage": round((financing.total_principal_paid / financing.amount) * 100, 2) if financing.amount > 0 else 0,
            "installments_completed": schedule.completed_installments if schedule else 0,
            "installments_total": schedule.total_installments if schedule else 0,
        }


class RepaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def process_repayment(
        self,
        financing_id: str,
        amount: int,
        source: Optional[str] = None,
        source_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Repayment:
        financing_service = FinancingService(self.session)
        financing = await financing_service.get_by_id(financing_id)
        if not financing:
            raise NotFoundError(f"Financing {financing_id} not found")
        if financing.status not in ["active"]:
            raise ValidationError(f"Cannot make repayment on financing with status {financing.status}")
        if amount <= 0:
            raise ValidationError("Repayment amount must be positive")
        allocation = self._allocate_payment(
            amount=amount,
            outstanding_principal=financing.outstanding_principal,
            outstanding_interest=financing.outstanding_interest,
        )
        repayment_id = generate_id("repay")
        repayment = Repayment(
            id=repayment_id,
            financing_id=financing_id,
            account_id=financing.account_id,
            amount=amount,
            applied_to_principal=allocation["principal"],
            applied_to_interest=allocation["interest"],
            applied_to_fees=allocation["fees"],
            paid_at=datetime.utcnow(),
            status="completed",
            source=source,
            source_type=source_type,
            metadata_=metadata or {},
        )
        self.session.add(repayment)
        financing.outstanding_principal -= allocation["principal"]
        financing.outstanding_interest -= allocation["interest"]
        financing.outstanding_balance = financing.outstanding_principal + financing.outstanding_interest
        financing.total_principal_paid += allocation["principal"]
        financing.total_interest_paid += allocation["interest"]
        financing.total_fees_paid += allocation["fees"]
        if financing.outstanding_balance <= 0:
            financing.status = "paid"
            financing.outstanding_balance = 0
            financing.outstanding_principal = 0
            financing.outstanding_interest = 0
        await self._create_repayment_transaction(financing, repayment, allocation)
        await self.apply_to_schedule(financing_id, repayment)
        await self.session.flush()
        return repayment

    def _allocate_payment(
        self,
        amount: int,
        outstanding_principal: int,
        outstanding_interest: int,
    ) -> Dict[str, int]:
        remaining = amount
        interest_payment = min(remaining, outstanding_interest)
        remaining -= interest_payment
        principal_payment = min(remaining, outstanding_principal)
        remaining -= principal_payment
        fees_payment = remaining
        return {
            "principal": principal_payment,
            "interest": interest_payment,
            "fees": fees_payment,
        }

    async def _create_repayment_transaction(
        self,
        financing: Financing,
        repayment: Repayment,
        allocation: Dict[str, int],
    ) -> None:
        balance_before = financing.outstanding_balance + allocation["principal"] + allocation["interest"] + allocation["fees"]
        transaction = FinancingTransaction(
            id=generate_id("fintrx"),
            financing_id=financing.id,
            account_id=financing.account_id,
            type="repayment",
            amount=repayment.amount,
            balance_before=balance_before,
            balance_after=financing.outstanding_balance,
            timestamp=datetime.utcnow(),
            description=f"Repayment - Principal: {allocation['principal']}, Interest: {allocation['interest']}",
            reference_id=repayment.id,
            reference_type="repayment",
        )
        self.session.add(transaction)
        await self.session.flush()

    async def apply_to_schedule(
        self,
        financing_id: str,
        repayment: Repayment,
    ) -> None:
        result = await self.session.execute(
            select(RepaymentSchedule).where(RepaymentSchedule.financing_id == financing_id)
        )
        schedule = result.scalar_one_or_none()
        if not schedule:
            return
        installments = schedule.installments
        remaining_amount = repayment.applied_to_principal + repayment.applied_to_interest
        for installment in installments:
            if installment["status"] == "pending" and remaining_amount > 0:
                installment_amount = installment.get("amount", 0) or remaining_amount
                if remaining_amount >= installment_amount:
                    installment["status"] = "paid"
                    installment["paid_at"] = repayment.paid_at.isoformat()
                    schedule.completed_installments += 1
                    remaining_amount -= installment_amount
                else:
                    installment["status"] = "partial"
                    installment["paid_amount"] = remaining_amount
                    remaining_amount = 0
        schedule.total_paid += repayment.amount
        schedule.total_remaining = max(0, schedule.total_remaining - repayment.amount)
        next_pending = next((i for i in installments if i["status"] == "pending"), None)
        if next_pending:
            schedule.next_payment_date = date.fromisoformat(next_pending["due_date"])
            schedule.next_payment_amount = next_pending.get("amount")
        else:
            schedule.next_payment_date = None
            schedule.next_payment_amount = None
        await self.session.flush()

    async def process_automatic_repayment(
        self,
        account_id: str,
        processing_revenue: int,
    ) -> List[Repayment]:
        result = await self.session.execute(
            select(Financing).where(
                Financing.account_id == account_id,
                Financing.status == "active",
                Financing.repayment_method == "revenue_share",
            )
        )
        financings = list(result.scalars().all())
        repayments = []
        for financing in financings:
            if financing.revenue_share_percentage:
                payment_amount = int(processing_revenue * float(financing.revenue_share_percentage) / 100)
                if payment_amount > 0:
                    repayment = await self.process_repayment(
                        financing_id=financing.id,
                        amount=payment_amount,
                        source="automatic",
                        source_type="processing_revenue",
                    )
                    repayments.append(repayment)
        return repayments

    async def get_by_financing(
        self,
        financing_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Repayment]:
        query = (
            select(Repayment)
            .where(Repayment.financing_id == financing_id)
            .order_by(Repayment.paid_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class RiskAssessmentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def evaluate_account(self, account_id: str) -> Dict[str, Any]:
        eligibility_result = await self.session.execute(
            select(OfferEligibility).where(OfferEligibility.account_id == account_id)
        )
        eligibility = eligibility_result.scalar_one_or_none()
        if eligibility and (datetime.utcnow() - eligibility.evaluated_at) < timedelta(hours=24):
            return {
                "account_id": account_id,
                "eligible": eligibility.eligible,
                "max_amount": eligibility.max_amount,
                "risk_score": float(eligibility.risk_score) if eligibility.risk_score else None,
                "risk_tier": eligibility.risk_tier,
                "reason_codes": eligibility.reason_codes,
            }
        risk_score = Decimal(str(secrets.randbelow(100))) / Decimal("100")
        risk_tier = self._determine_risk_tier(risk_score)
        eligible = risk_score < Decimal("0.85")
        max_amount = int(secrets.randbelow(1000000) + 10000) if eligible else 0
        return {
            "account_id": account_id,
            "eligible": eligible,
            "max_amount": max_amount,
            "risk_score": float(risk_score),
            "risk_tier": risk_tier,
            "reason_codes": [] if eligible else ["high_risk_score"],
        }

    async def determine_rate(
        self,
        account_id: str,
        amount: int,
        term_months: int,
    ) -> Dict[str, Any]:
        evaluation = await self.evaluate_account(account_id)
        risk_tier = evaluation.get("risk_tier", "near_prime")
        base_rates = {
            "prime": Decimal("8.0"),
            "near_prime": Decimal("12.0"),
            "subprime": Decimal("18.0"),
            "high_risk": Decimal("25.0"),
        }
        base_rate = base_rates.get(risk_tier, Decimal("15.0"))
        term_adjustment = Decimal("0.5") * (term_months // 12)
        final_rate = base_rate + term_adjustment
        return {
            "account_id": account_id,
            "risk_tier": risk_tier,
            "base_rate": float(base_rate),
            "term_adjustment": float(term_adjustment),
            "final_rate": float(final_rate),
            "rate_type": "annual_percentage_rate",
        }

    def _determine_risk_tier(self, risk_score: Decimal) -> str:
        if risk_score < Decimal("0.25"):
            return "prime"
        elif risk_score < Decimal("0.50"):
            return "near_prime"
        elif risk_score < Decimal("0.75"):
            return "subprime"
        else:
            return "high_risk"

    async def get_eligibility(self, account_id: str) -> Optional[OfferEligibility]:
        result = await self.session.execute(
            select(OfferEligibility).where(OfferEligibility.account_id == account_id)
        )
        return result.scalar_one_or_none()


class CollectionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def handle_delinquency(self, financing_id: str) -> Financing:
        financing_service = FinancingService(self.session)
        financing = await financing_service.get_by_id(financing_id)
        if not financing:
            raise NotFoundError(f"Financing {financing_id} not found")
        days_past_due = self._calculate_days_past_due(financing)
        new_delinquency_status = self._determine_delinquency_status(days_past_due)
        if new_delinquency_status != financing.delinquency_status:
            financing.delinquency_status = new_delinquency_status
            if new_delinquency_status != "current" and not financing.delinquent_since:
                financing.delinquent_since = datetime.utcnow()
            if new_delinquency_status == "default":
                financing.status = "defaulted"
            await self._apply_late_fee_if_needed(financing, days_past_due)
        await self.session.flush()
        return financing

    def _calculate_days_past_due(self, financing: Financing) -> int:
        if not financing.next_payment_date:
            return 0
        today = date.today()
        if today <= financing.next_payment_date:
            return 0
        return (today - financing.next_payment_date).days

    def _determine_delinquency_status(self, days_past_due: int) -> str:
        if days_past_due < 1:
            return "current"
        elif days_past_due < 30:
            return "current"
        elif days_past_due < 60:
            return "delinquent_30"
        elif days_past_due < 90:
            return "delinquent_60"
        elif days_past_due < 120:
            return "delinquent_90"
        else:
            return "default"

    async def _apply_late_fee_if_needed(self, financing: Financing, days_past_due: int) -> None:
        if days_past_due >= 30 and days_past_due % 30 == 0:
            late_fee = int(financing.outstanding_balance * Decimal("0.05"))
            financing.outstanding_balance += late_fee
            transaction = FinancingTransaction(
                id=generate_id("fintrx"),
                financing_id=financing.id,
                account_id=financing.account_id,
                type="late_fee",
                amount=late_fee,
                balance_before=financing.outstanding_balance - late_fee,
                balance_after=financing.outstanding_balance,
                timestamp=datetime.utcnow(),
                description=f"Late fee applied - {days_past_due} days past due",
            )
            self.session.add(transaction)

    async def set_up_plan(
        self,
        financing_id: str,
        plan_type: str,
        modified_payment_amount: Optional[int] = None,
        payment_frequency: str = "monthly",
        duration_months: Optional[int] = None,
        waive_late_fees: bool = False,
        freeze_interest: bool = False,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> CollectionPlan:
        financing_service = FinancingService(self.session)
        financing = await financing_service.get_by_id(financing_id)
        if not financing:
            raise NotFoundError(f"Financing {financing_id} not found")
        if financing.status not in ["active", "defaulted"]:
            raise ValidationError(f"Cannot set up collection plan for financing with status {financing.status}")
        plan_id = generate_id("collplan")
        start_date = date.today()
        end_date = start_date + timedelta(days=30 * duration_months) if duration_months else None
        plan = CollectionPlan(
            id=plan_id,
            financing_id=financing_id,
            account_id=financing.account_id,
            status="active",
            plan_type=plan_type,
            original_payment_amount=financing.next_payment_amount or financing.outstanding_balance,
            modified_payment_amount=modified_payment_amount,
            payment_frequency=payment_frequency,
            start_date=start_date,
            end_date=end_date,
            interest_frozen=freeze_interest,
            notes=notes,
            created_by=created_by,
        )
        self.session.add(plan)
        if waive_late_fees:
            plan.late_fees_waived = 0
        if modified_payment_amount:
            financing.next_payment_amount = modified_payment_amount
        await self.session.flush()
        return plan

    async def get_plan(self, financing_id: str) -> Optional[CollectionPlan]:
        result = await self.session.execute(
            select(CollectionPlan).where(
                CollectionPlan.financing_id == financing_id,
                CollectionPlan.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def cancel_plan(self, plan_id: str) -> CollectionPlan:
        result = await self.session.execute(
            select(CollectionPlan).where(CollectionPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()
        if not plan:
            raise NotFoundError(f"Collection plan {plan_id} not found")
        plan.status = "canceled"
        await self.session.flush()
        return plan

    async def get_delinquent_financings(
        self,
        min_days_past_due: int = 30,
        limit: int = 100,
    ) -> List[Financing]:
        today = date.today()
        cutoff_date = today - timedelta(days=min_days_past_due)
        query = (
            select(Financing)
            .where(
                Financing.status == "active",
                Financing.next_payment_date < cutoff_date,
            )
            .order_by(Financing.next_payment_date.asc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


class FinancingTransactionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_financing(
        self,
        financing_id: str,
        limit: int = 25,
        offset: int = 0,
    ) -> List[FinancingTransaction]:
        query = (
            select(FinancingTransaction)
            .where(FinancingTransaction.financing_id == financing_id)
            .order_by(FinancingTransaction.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_account(
        self,
        account_id: str,
        transaction_type: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> List[FinancingTransaction]:
        query = select(FinancingTransaction).where(
            FinancingTransaction.account_id == account_id
        )
        if transaction_type:
            query = query.where(FinancingTransaction.type == transaction_type)
        query = query.order_by(FinancingTransaction.timestamp.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create_interest_accrual(
        self,
        financing_id: str,
        amount: int,
    ) -> FinancingTransaction:
        financing_service = FinancingService(self.session)
        financing = await financing_service.get_by_id(financing_id)
        if not financing:
            raise NotFoundError(f"Financing {financing_id} not found")
        balance_before = financing.outstanding_balance
        financing.outstanding_interest += amount
        financing.outstanding_balance += amount
        transaction = FinancingTransaction(
            id=generate_id("fintrx"),
            financing_id=financing_id,
            account_id=financing.account_id,
            type="interest_accrual",
            amount=amount,
            balance_before=balance_before,
            balance_after=financing.outstanding_balance,
            timestamp=datetime.utcnow(),
            description="Monthly interest accrual",
        )
        self.session.add(transaction)
        await self.session.flush()
        return transaction
