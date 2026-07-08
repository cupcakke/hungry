from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.ledger import (
    LedgerAccount,
    LedgerEntry,
    JournalEntry,
    BalanceAssertion,
    post_ledger_entry,
    get_account_balance,
    get_trial_balance,
    get_balance_sheet,
    get_income_statement,
    create_balance_assertion,
    reverse_journal_entry,
    get_chart_of_accounts,
    validate_double_entry,
)
from payment_platform.shared.exceptions import (
    ValidationError, NotFoundError, ConflictError, BalanceError,
)
from payment_platform.shared.utils.identifiers import generate_ledger_account_id


class CreateAccountService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_account(
        self,
        account_code: str,
        name: str,
        account_type: str,
        currency: str,
        description: Optional[str] = None,
        parent_account_code: Optional[str] = None,
        allow_negative: bool = False,
        is_system_account: bool = False,
        initial_balance: int = 0,
        account_id: Optional[str] = None,
        livemode: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LedgerAccount:
        valid_types = ["asset", "liability", "equity", "revenue", "expense"]
        if account_type.lower() not in valid_types:
            raise ValidationError(
                f"Invalid account type: {account_type}. Must be one of {valid_types}",
                param="account_type"
            )

        existing = await self.session.execute(
            select(LedgerAccount).where(LedgerAccount.account_code == account_code)
        )
        if existing.scalar_one_or_none():
            raise ConflictError(
                f"Account with code {account_code} already exists",
                code="account_exists"
            )

        parent_account_id = None
        if parent_account_code:
            parent = await self.session.execute(
                select(LedgerAccount).where(LedgerAccount.account_code == parent_account_code)
            )
            parent = parent.scalar_one_or_none()
            if not parent:
                raise NotFoundError(f"Parent account {parent_account_code} not found")
            parent_account_id = parent.id
            if parent.account_type != account_type:
                raise ValidationError(
                    f"Parent account type {parent.account_type} does not match {account_type}",
                    param="account_type"
                )

        if len(currency) != 3:
            raise ValidationError("Currency must be a 3-letter code", param="currency")

        account = LedgerAccount(
            id=generate_ledger_account_id(),
            account_code=account_code,
            name=name,
            account_type=account_type.lower(),
            currency=currency.upper(),
            balance=initial_balance,
            description=description,
            parent_account_id=parent_account_id,
            allow_negative=allow_negative,
            is_system_account=is_system_account,
            is_active=True,
            account_id=account_id,
            livemode=livemode,
            metadata_=metadata or {},
        )
        self.session.add(account)
        await self.session.flush()

        return account

    async def update_account(
        self,
        account_code: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        allow_negative: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LedgerAccount:
        result = await self.session.execute(
            select(LedgerAccount).where(LedgerAccount.account_code == account_code)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise NotFoundError(f"Account {account_code} not found")

        if account.is_system_account:
            raise ValidationError(
                f"System account {account_code} cannot be modified",
                code="system_account"
            )

        if name is not None:
            account.name = name
        if description is not None:
            account.description = description
        if is_active is not None:
            account.is_active = is_active
        if allow_negative is not None:
            account.allow_negative = allow_negative
        if metadata is not None:
            account.metadata_ = {**(account.metadata_ or {}), **metadata}

        await self.session.flush()
        return account

    async def deactivate_account(self, account_code: str) -> LedgerAccount:
        result = await self.session.execute(
            select(LedgerAccount).where(LedgerAccount.account_code == account_code)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise NotFoundError(f"Account {account_code} not found")

        if account.balance != 0:
            raise ValidationError(
                f"Cannot deactivate account {account_code} with non-zero balance",
                code="non_zero_balance"
            )

        account.is_active = False
        await self.session.flush()
        return account


class PostEntryService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def post_entry(
        self,
        debit_account_code: str,
        credit_account_code: str,
        amount: int,
        currency: str,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        account_id: Optional[str] = None,
        livemode: bool = False,
        created_by: Optional[str] = None,
    ) -> JournalEntry:
        valid_reference_types = [
            "payment_intent", "charge", "refund", "payout", "transfer",
            "dispute", "adjustment", "fee", "reversal", "manual"
        ]
        if reference_type and reference_type not in valid_reference_types:
            raise ValidationError(
                f"Invalid reference type: {reference_type}",
                param="reference_type"
            )

        return await post_ledger_entry(
            session=self.session,
            debit_account_code=debit_account_code,
            credit_account_code=credit_account_code,
            amount=amount,
            currency=currency,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            metadata=metadata,
            account_id=account_id,
            livemode=livemode,
            created_by=created_by,
        )

    async def post_compound_entry(
        self,
        entries: List[Dict[str, Any]],
        currency: str,
        description: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        account_id: Optional[str] = None,
        livemode: bool = False,
        created_by: Optional[str] = None,
    ) -> JournalEntry:
        total_debits = sum(e.get("amount", 0) for e in entries if e.get("entry_type") == "debit")
        total_credits = sum(e.get("amount", 0) for e in entries if e.get("entry_type") == "credit")

        if total_debits != total_credits:
            raise ValidationError(
                f"Double-entry violation: debits ({total_debits}) != credits ({total_credits})",
                code="unbalanced_entry"
            )

        if not entries:
            raise ValidationError("No entries provided", param="entries")

        journal_entry_id = None
        for entry in entries:
            if entry.get("entry_type") == "debit":
                for other in entries:
                    if other.get("entry_type") == "credit":
                        journal = await self.post_entry(
                            debit_account_code=entry["account_code"],
                            credit_account_code=other["account_code"],
                            amount=entry["amount"],
                            currency=currency,
                            reference_type=reference_type,
                            reference_id=reference_id,
                            description=description,
                            account_id=account_id,
                            livemode=livemode,
                            created_by=created_by,
                        )
                        journal_entry_id = journal.id
                        break
                break

        result = await self.session.execute(
            select(JournalEntry).where(JournalEntry.id == journal_entry_id)
        )
        return result.scalar_one()

    async def reverse_entry(
        self,
        journal_entry_id: str,
        reason: Optional[str] = None,
        reversed_by: Optional[str] = None,
    ) -> JournalEntry:
        return await reverse_journal_entry(
            session=self.session,
            journal_entry_id=journal_entry_id,
            reason=reason,
            reversed_by=reversed_by,
        )


class BalanceQueryService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_balance(
        self,
        account_code: str,
        include_pending: bool = False,
    ) -> Dict[str, Any]:
        return await get_account_balance(
            session=self.session,
            account_code=account_code,
            include_pending=include_pending,
        )

    async def get_trial_balance(
        self,
        as_of_date: Optional[datetime] = None,
        currency: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await get_trial_balance(
            session=self.session,
            as_of_date=as_of_date,
            currency=currency,
            account_id=account_id,
        )

    async def get_balance_sheet(
        self,
        as_of_date: Optional[datetime] = None,
        currency: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await get_balance_sheet(
            session=self.session,
            as_of_date=as_of_date,
            currency=currency,
            account_id=account_id,
        )

    async def get_income_statement(
        self,
        start_date: datetime,
        end_date: datetime,
        currency: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await get_income_statement(
            session=self.session,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            account_id=account_id,
        )

    async def get_account_history(
        self,
        account_code: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        result = await self.session.execute(
            select(LedgerAccount).where(LedgerAccount.account_code == account_code)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise NotFoundError(f"Account {account_code} not found")

        query = select(LedgerEntry).where(
            LedgerEntry.account_id == account.id
        ).order_by(LedgerEntry.created_at.desc())

        if start_date:
            query = query.where(LedgerEntry.created_at >= start_date)
        if end_date:
            query = query.where(LedgerEntry.created_at <= end_date)

        count_query = select(func.count()).select_from(query.subquery())
        total = await self.session.scalar(count_query)

        query = query.limit(limit).offset(offset)
        entries_result = await self.session.execute(query)
        entries = entries_result.scalars().all()

        return {
            "account_id": account.id,
            "account_code": account.account_code,
            "account_name": account.name,
            "currency": account.currency,
            "current_balance": account.balance,
            "entries": [
                {
                    "id": e.id,
                    "journal_entry_id": e.journal_entry_id,
                    "entry_type": e.entry_type,
                    "amount": e.amount,
                    "status": e.status,
                    "reference_type": e.reference_type,
                    "reference_id": e.reference_id,
                    "description": e.description,
                    "balance_before": e.account_balance_before,
                    "balance_after": e.account_balance_after,
                    "created_at": e.created_at.isoformat(),
                    "posted_at": e.posted_at.isoformat() if e.posted_at else None,
                }
                for e in entries
            ],
            "total_count": total,
            "limit": limit,
            "offset": offset,
        }

    async def get_chart_of_accounts(
        self,
        account_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        currency: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return await get_chart_of_accounts(
            session=self.session,
            account_type=account_type,
            is_active=is_active,
            currency=currency,
            account_id=account_id,
        )


class ReconciliationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_assertion(
        self,
        account_code: str,
        expected_balance: int,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> BalanceAssertion:
        return await create_balance_assertion(
            session=self.session,
            account_code=account_code,
            expected_balance=expected_balance,
            notes=notes,
            created_by=created_by,
        )

    async def get_assertions(
        self,
        account_code: Optional[str] = None,
        is_valid: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = select(BalanceAssertion).order_by(BalanceAssertion.assertion_date.desc())

        if account_code:
            account_result = await self.session.execute(
                select(LedgerAccount).where(LedgerAccount.account_code == account_code)
            )
            account = account_result.scalar_one_or_none()
            if account:
                query = query.where(BalanceAssertion.account_id == account.id)

        if is_valid is not None:
            query = query.where(BalanceAssertion.is_valid == is_valid)
        if start_date:
            query = query.where(BalanceAssertion.assertion_date >= start_date)
        if end_date:
            query = query.where(BalanceAssertion.assertion_date <= end_date)

        query = query.limit(limit)
        result = await self.session.execute(query)
        assertions = result.scalars().all()

        return [
            {
                "id": a.id,
                "account_id": a.account_id,
                "expected_balance": a.expected_balance,
                "actual_balance": a.actual_balance,
                "currency": a.currency,
                "assertion_date": a.assertion_date.isoformat(),
                "is_valid": a.is_valid,
                "discrepancy": a.discrepancy,
                "notes": a.notes,
                "created_by": a.created_by,
                "created_at": a.created_at.isoformat(),
            }
            for a in assertions
        ]

    async def validate_journal_entry(
        self,
        journal_entry_id: str,
    ) -> Dict[str, Any]:
        return await validate_double_entry(
            session=self.session,
            journal_entry_id=journal_entry_id,
        )

    async def get_audit_trail(
        self,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        account_code: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = select(LedgerEntry).order_by(LedgerEntry.created_at.desc())

        if reference_type:
            query = query.where(LedgerEntry.reference_type == reference_type)
        if reference_id:
            query = query.where(LedgerEntry.reference_id == reference_id)
        if start_date:
            query = query.where(LedgerEntry.created_at >= start_date)
        if end_date:
            query = query.where(LedgerEntry.created_at <= end_date)

        if account_code:
            account_result = await self.session.execute(
                select(LedgerAccount).where(LedgerAccount.account_code == account_code)
            )
            account = account_result.scalar_one_or_none()
            if account:
                query = query.where(LedgerEntry.account_id == account.id)

        query = query.limit(limit)
        result = await self.session.execute(query)
        entries = result.scalars().all()

        audit_trail = []
        for entry in entries:
            account_result = await self.session.execute(
                select(LedgerAccount).where(LedgerAccount.id == entry.account_id)
            )
            account = account_result.scalar_one()

            journal_result = await self.session.execute(
                select(JournalEntry).where(JournalEntry.id == entry.journal_entry_id)
            )
            journal = journal_result.scalar_one_or_none()

            audit_trail.append({
                "entry_id": entry.id,
                "journal_entry_id": entry.journal_entry_id,
                "account_code": account.account_code,
                "account_name": account.name,
                "account_type": account.account_type,
                "entry_type": entry.entry_type,
                "amount": entry.amount,
                "currency": entry.currency,
                "status": entry.status,
                "reference_type": entry.reference_type,
                "reference_id": entry.reference_id,
                "description": entry.description,
                "balance_before": entry.account_balance_before,
                "balance_after": entry.account_balance_after,
                "created_at": entry.created_at.isoformat(),
                "created_by": entry.created_by,
                "posted_at": entry.posted_at.isoformat() if entry.posted_at else None,
                "reversed_at": entry.reversed_at.isoformat() if entry.reversed_at else None,
                "journal_description": journal.description if journal else None,
            })

        return audit_trail

    async def reconcile_account(
        self,
        account_code: str,
        expected_balance: int,
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        assertion = await self.create_assertion(
            account_code=account_code,
            expected_balance=expected_balance,
            notes=notes,
            created_by=created_by,
        )

        balance_info = await get_account_balance(
            session=self.session,
            account_code=account_code,
        )

        return {
            "assertion_id": assertion.id,
            "account_code": account_code,
            "expected_balance": expected_balance,
            "actual_balance": assertion.actual_balance,
            "is_reconciled": assertion.is_valid,
            "discrepancy": assertion.discrepancy,
            "currency": assertion.currency,
            "reconciled_at": assertion.assertion_date.isoformat(),
            "notes": notes,
        }
