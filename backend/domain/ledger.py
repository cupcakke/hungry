from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Type
from sqlalchemy import (
    String, Integer, BigInteger, Numeric, Boolean, DateTime, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Enum as SQLEnum,
    event, func, select, update,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, deferred
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import JSONB
import enum
import uuid

from payment_platform.backend.infrastructure.database import Base, get_session
from payment_platform.shared.models.enums import (
    LedgerAccountType, LedgerEntryStatus, ReferenceType,
)
from payment_platform.shared.exceptions import (
    ValidationError, NotFoundError, BalanceError, InsufficientBalanceError,
)
from payment_platform.shared.utils.identifiers import (
    generate_ledger_account_id, generate_ledger_entry_id, generate_journal_entry_id,
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MetadataMixin:
    metadata_: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=dict,
    )


class LedgerAccount(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "ledger_accounts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="ledger_account", nullable=False)
    account_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pending_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    parent_account_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("ledger_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system_account: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_negative: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    parent: Mapped[Optional["LedgerAccount"]] = relationship(
        "LedgerAccount", remote_side=[id], backref="child_accounts"
    )
    entries: Mapped[List["LedgerEntry"]] = relationship(
        "LedgerEntry", back_populates="account", foreign_keys="LedgerEntry.account_id"
    )

    __table_args__ = (
        Index("ix_ledger_accounts_code", "account_code"),
        Index("ix_ledger_accounts_type_currency", "account_type", "currency"),
        Index("ix_ledger_accounts_parent", "parent_account_id"),
        Index("ix_ledger_accounts_active", "is_active"),
        CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')",
            name="ck_ledger_account_type",
        ),
    )

    def debit(self, amount: int) -> None:
        if self.account_type in ("asset", "expense"):
            self.balance += amount
        else:
            self.balance -= amount

    def credit(self, amount: int) -> None:
        if self.account_type in ("asset", "expense"):
            self.balance -= amount
        else:
            self.balance += amount

    def get_normal_balance(self) -> int:
        if self.account_type in ("asset", "expense"):
            return self.balance
        return -self.balance

    def can_debit(self, amount: int) -> bool:
        if self.allow_negative:
            return True
        if self.account_type in ("asset", "expense"):
            return True
        new_balance = self.balance + amount
        return new_balance >= 0

    def can_credit(self, amount: int) -> bool:
        if self.allow_negative:
            return True
        if self.account_type in ("liability", "equity", "revenue"):
            return True
        new_balance = self.balance - amount
        return new_balance >= 0


class LedgerEntry(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "ledger_entries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="ledger_entry", nullable=False)
    journal_entry_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("ledger_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="posted", nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_entry_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    account_balance_before: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    account_balance_after: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    account: Mapped["LedgerAccount"] = relationship(
        "LedgerAccount", back_populates="entries", foreign_keys=[account_id]
    )

    __table_args__ = (
        Index("ix_ledger_entries_journal", "journal_entry_id"),
        Index("ix_ledger_entries_account_date", "account_id", "created_at"),
        Index("ix_ledger_entries_reference", "reference_type", "reference_id"),
        Index("ix_ledger_entries_status", "status"),
        CheckConstraint(
            "entry_type IN ('debit', 'credit')",
            name="ck_ledger_entry_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'posted', 'reversed', 'canceled')",
            name="ck_ledger_entry_status",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_ledger_entry_amount_positive",
        ),
    )


class JournalEntry(Base, TimestampMixin, MetadataMixin):
    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    object: Mapped[str] = mapped_column(String(20), default="journal_entry", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    external_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    entries: Mapped[List["LedgerEntry"]] = relationship(
        "LedgerEntry", backref="journal_entry_obj", foreign_keys="LedgerEntry.journal_entry_id"
    )

    __table_args__ = (
        Index("ix_journal_entries_status", "status"),
        Index("ix_journal_entries_reference", "reference_type", "reference_id"),
        Index("ix_journal_entries_posted", "posted_at"),
        CheckConstraint(
            "status IN ('pending', 'posted', 'reversed', 'canceled')",
            name="ck_journal_entry_status",
        ),
    )


class BalanceAssertion(Base, TimestampMixin):
    __tablename__ = "balance_assertions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("ledger_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expected_balance: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_balance: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    assertion_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discrepancy: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_balance_assertions_account_date", "account_id", "assertion_date"),
    )


async def post_ledger_entry(
    session: AsyncSession,
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
    if amount <= 0:
        raise ValidationError("Amount must be positive", param="amount")

    debit_account = await session.execute(
        select(LedgerAccount).where(LedgerAccount.account_code == debit_account_code)
    )
    debit_account = debit_account.scalar_one_or_none()
    if not debit_account:
        raise NotFoundError(f"Debit account {debit_account_code} not found")

    credit_account = await session.execute(
        select(LedgerAccount).where(LedgerAccount.account_code == credit_account_code)
    )
    credit_account = credit_account.scalar_one_or_none()
    if not credit_account:
        raise NotFoundError(f"Credit account {credit_account_code} not found")

    if debit_account.currency != currency:
        raise ValidationError(
            f"Debit account currency {debit_account.currency} does not match {currency}",
            param="currency"
        )
    if credit_account.currency != currency:
        raise ValidationError(
            f"Credit account currency {credit_account.currency} does not match {currency}",
            param="currency"
        )

    if not debit_account.is_active:
        raise ValidationError(f"Debit account {debit_account_code} is not active")
    if not credit_account.is_active:
        raise ValidationError(f"Credit account {credit_account_code} is not active")

    journal_entry_id = generate_journal_entry_id()
    journal_entry = JournalEntry(
        id=journal_entry_id,
        description=description,
        status="posted",
        reference_type=reference_type,
        reference_id=reference_id,
        posted_at=datetime.now(timezone.utc),
        posted_by=created_by,
        metadata_=metadata or {},
        livemode=livemode,
        account_id=account_id,
    )
    session.add(journal_entry)

    now = datetime.now(timezone.utc)

    debit_balance_before = debit_account.balance
    debit_account.debit(amount)
    debit_balance_after = debit_account.balance

    credit_balance_before = credit_account.balance
    credit_account.credit(amount)
    credit_balance_after = credit_account.balance

    debit_entry = LedgerEntry(
        id=generate_ledger_entry_id(),
        journal_entry_id=journal_entry_id,
        account_id=debit_account.id,
        entry_type="debit",
        amount=amount,
        currency=currency,
        status="posted",
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        posted_at=now,
        account_balance_before=debit_balance_before,
        account_balance_after=debit_balance_after,
        metadata_=metadata or {},
        livemode=livemode,
        created_by=created_by,
    )
    session.add(debit_entry)

    credit_entry = LedgerEntry(
        id=generate_ledger_entry_id(),
        journal_entry_id=journal_entry_id,
        account_id=credit_account.id,
        entry_type="credit",
        amount=amount,
        currency=currency,
        status="posted",
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        posted_at=now,
        account_balance_before=credit_balance_before,
        account_balance_after=credit_balance_after,
        metadata_=metadata or {},
        livemode=livemode,
        created_by=created_by,
    )
    session.add(credit_entry)

    await session.flush()
    return journal_entry


async def get_account_balance(
    session: AsyncSession,
    account_code: str,
    include_pending: bool = False,
) -> Dict[str, Any]:
    result = await session.execute(
        select(LedgerAccount).where(LedgerAccount.account_code == account_code)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise NotFoundError(f"Account {account_code} not found")

    balance = account.balance
    if include_pending:
        pending_query = await session.execute(
            select(func.sum(LedgerEntry.amount)).where(
                LedgerEntry.account_id == account.id,
                LedgerEntry.status == "pending"
            )
        )
        pending_amount = pending_query.scalar() or 0
        balance += pending_amount

    return {
        "account_id": account.id,
        "account_code": account.account_code,
        "account_name": account.name,
        "account_type": account.account_type,
        "currency": account.currency,
        "balance": balance,
        "pending_balance": account.pending_balance,
        "normal_balance": account.get_normal_balance(),
        "is_active": account.is_active,
    }


async def get_trial_balance(
    session: AsyncSession,
    as_of_date: Optional[datetime] = None,
    currency: Optional[str] = None,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    query = select(LedgerAccount).where(LedgerAccount.is_active == True)
    
    if currency:
        query = query.where(LedgerAccount.currency == currency)
    if account_id:
        query = query.where(LedgerAccount.account_id == account_id)

    result = await session.execute(query)
    accounts = result.scalars().all()

    trial_balance = {
        "accounts": [],
        "total_debits": 0,
        "total_credits": 0,
        "is_balanced": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "currency": currency,
    }

    total_debits = 0
    total_credits = 0

    for account in accounts:
        normal_balance = account.get_normal_balance()
        
        if account.account_type in ("asset", "expense"):
            debit_balance = abs(account.balance) if account.balance > 0 else 0
            credit_balance = abs(account.balance) if account.balance < 0 else 0
            total_debits += debit_balance
            total_credits += credit_balance
        else:
            credit_balance = abs(account.balance) if account.balance > 0 else 0
            debit_balance = abs(account.balance) if account.balance < 0 else 0
            total_credits += credit_balance
            total_debits += debit_balance

        trial_balance["accounts"].append({
            "account_id": account.id,
            "account_code": account.account_code,
            "account_name": account.name,
            "account_type": account.account_type,
            "currency": account.currency,
            "debit_balance": debit_balance,
            "credit_balance": credit_balance,
            "balance": account.balance,
        })

    trial_balance["total_debits"] = total_debits
    trial_balance["total_credits"] = total_credits
    trial_balance["is_balanced"] = total_debits == total_credits

    return trial_balance


async def get_balance_sheet(
    session: AsyncSession,
    as_of_date: Optional[datetime] = None,
    currency: Optional[str] = None,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    query = select(LedgerAccount).where(
        LedgerAccount.is_active == True,
        LedgerAccount.account_type.in_(["asset", "liability", "equity"])
    )

    if currency:
        query = query.where(LedgerAccount.currency == currency)
    if account_id:
        query = query.where(LedgerAccount.account_id == account_id)

    result = await session.execute(query)
    accounts = result.scalars().all()

    balance_sheet = {
        "assets": {
            "current": [],
            "fixed": [],
            "total": 0,
        },
        "liabilities": {
            "current": [],
            "long_term": [],
            "total": 0,
        },
        "equity": {
            "accounts": [],
            "total": 0,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "currency": currency,
    }

    for account in accounts:
        account_data = {
            "account_id": account.id,
            "account_code": account.account_code,
            "account_name": account.name,
            "currency": account.currency,
            "balance": account.balance,
        }

        if account.account_type == "asset":
            if account.account_code.startswith("1"):
                balance_sheet["assets"]["current"].append(account_data)
            else:
                balance_sheet["assets"]["fixed"].append(account_data)
            balance_sheet["assets"]["total"] += account.balance
        elif account.account_type == "liability":
            if account.account_code.startswith("2"):
                balance_sheet["liabilities"]["current"].append(account_data)
            else:
                balance_sheet["liabilities"]["long_term"].append(account_data)
            balance_sheet["liabilities"]["total"] += account.balance
        elif account.account_type == "equity":
            balance_sheet["equity"]["accounts"].append(account_data)
            balance_sheet["equity"]["total"] += account.balance

    return balance_sheet


async def get_income_statement(
    session: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    currency: Optional[str] = None,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    query = select(LedgerAccount).where(
        LedgerAccount.is_active == True,
        LedgerAccount.account_type.in_(["revenue", "expense"])
    )

    if currency:
        query = query.where(LedgerAccount.currency == currency)
    if account_id:
        query = query.where(LedgerAccount.account_id == account_id)

    result = await session.execute(query)
    accounts = result.scalars().all()

    income_statement = {
        "revenue": {
            "accounts": [],
            "total": 0,
        },
        "expenses": {
            "accounts": [],
            "total": 0,
        },
        "net_income": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "currency": currency,
    }

    total_revenue = 0
    total_expenses = 0

    for account in accounts:
        account_data = {
            "account_id": account.id,
            "account_code": account.account_code,
            "account_name": account.name,
            "currency": account.currency,
            "balance": abs(account.balance),
        }

        if account.account_type == "revenue":
            income_statement["revenue"]["accounts"].append(account_data)
            total_revenue += abs(account.balance)
        elif account.account_type == "expense":
            income_statement["expenses"]["accounts"].append(account_data)
            total_expenses += abs(account.balance)

    income_statement["revenue"]["total"] = total_revenue
    income_statement["expenses"]["total"] = total_expenses
    income_statement["net_income"] = total_revenue - total_expenses

    return income_statement


async def create_balance_assertion(
    session: AsyncSession,
    account_code: str,
    expected_balance: int,
    notes: Optional[str] = None,
    created_by: Optional[str] = None,
) -> BalanceAssertion:
    result = await session.execute(
        select(LedgerAccount).where(LedgerAccount.account_code == account_code)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise NotFoundError(f"Account {account_code} not found")

    actual_balance = account.balance
    is_valid = actual_balance == expected_balance
    discrepancy = actual_balance - expected_balance

    assertion = BalanceAssertion(
        id=f"ba_{uuid.uuid4().hex[:22]}",
        account_id=account.id,
        expected_balance=expected_balance,
        actual_balance=actual_balance,
        currency=account.currency,
        assertion_date=datetime.now(timezone.utc),
        is_valid=is_valid,
        discrepancy=discrepancy,
        notes=notes,
        created_by=created_by,
    )
    session.add(assertion)
    await session.flush()

    return assertion


async def reverse_journal_entry(
    session: AsyncSession,
    journal_entry_id: str,
    reason: Optional[str] = None,
    reversed_by: Optional[str] = None,
) -> JournalEntry:
    result = await session.execute(
        select(JournalEntry).where(JournalEntry.id == journal_entry_id)
    )
    original_entry = result.scalar_one_or_none()
    if not original_entry:
        raise NotFoundError(f"Journal entry {journal_entry_id} not found")

    if original_entry.status == "reversed":
        raise ValidationError(f"Journal entry {journal_entry_id} is already reversed")

    if original_entry.status == "canceled":
        raise ValidationError(f"Journal entry {journal_entry_id} is canceled")

    entries_result = await session.execute(
        select(LedgerEntry).where(LedgerEntry.journal_entry_id == journal_entry_id)
    )
    original_entries = entries_result.scalars().all()

    reversal_id = generate_journal_entry_id()
    reversal_entry = JournalEntry(
        id=reversal_id,
        description=f"Reversal of {journal_entry_id}: {reason or 'No reason provided'}",
        status="posted",
        reference_type="reversal",
        reference_id=journal_entry_id,
        posted_at=datetime.now(timezone.utc),
        posted_by=reversed_by,
        metadata_={"original_entry_id": journal_entry_id, "reason": reason},
        livemode=original_entry.livemode,
        account_id=original_entry.account_id,
    )
    session.add(reversal_entry)

    now = datetime.now(timezone.utc)

    for original in original_entries:
        account_result = await session.execute(
            select(LedgerAccount).where(LedgerAccount.id == original.account_id)
        )
        account = account_result.scalar_one()

        balance_before = account.balance

        if original.entry_type == "debit":
            account.credit(original.amount)
        else:
            account.debit(original.amount)

        balance_after = account.balance

        reversal_ledger_entry = LedgerEntry(
            id=generate_ledger_entry_id(),
            journal_entry_id=reversal_id,
            account_id=original.account_id,
            entry_type="credit" if original.entry_type == "debit" else "debit",
            amount=original.amount,
            currency=original.currency,
            status="posted",
            reference_type="reversal",
            reference_id=journal_entry_id,
            description=f"Reversal: {original.description or ''}",
            posted_at=now,
            account_balance_before=balance_before,
            account_balance_after=balance_after,
            metadata_={"original_entry_id": original.id},
            livemode=original.livemode,
            created_by=reversed_by,
        )
        session.add(reversal_ledger_entry)

        original.status = "reversed"
        original.reversed_at = now

    original_entry.status = "reversed"
    await session.flush()

    return reversal_entry


async def get_chart_of_accounts(
    session: AsyncSession,
    account_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    currency: Optional[str] = None,
    account_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    query = select(LedgerAccount).order_by(LedgerAccount.account_code)

    if account_type:
        query = query.where(LedgerAccount.account_type == account_type)
    if is_active is not None:
        query = query.where(LedgerAccount.is_active == is_active)
    if currency:
        query = query.where(LedgerAccount.currency == currency)
    if account_id:
        query = query.where(LedgerAccount.account_id == account_id)

    result = await session.execute(query)
    accounts = result.scalars().all()

    chart = []
    for account in accounts:
        account_dict = {
            "id": account.id,
            "account_code": account.account_code,
            "name": account.name,
            "account_type": account.account_type,
            "currency": account.currency,
            "balance": account.balance,
            "is_active": account.is_active,
            "is_system_account": account.is_system_account,
            "allow_negative": account.allow_negative,
            "parent_account_id": account.parent_account_id,
            "description": account.description,
            "created_at": account.created_at.isoformat(),
            "updated_at": account.updated_at.isoformat(),
        }
        chart.append(account_dict)

    return chart


async def validate_double_entry(
    session: AsyncSession,
    journal_entry_id: str,
) -> Dict[str, Any]:
    result = await session.execute(
        select(LedgerEntry).where(LedgerEntry.journal_entry_id == journal_entry_id)
    )
    entries = result.scalars().all()

    if not entries:
        return {
            "is_valid": False,
            "error": "No entries found for journal entry",
            "journal_entry_id": journal_entry_id,
        }

    total_debits = sum(e.amount for e in entries if e.entry_type == "debit")
    total_credits = sum(e.amount for e in entries if e.entry_type == "credit")

    is_balanced = total_debits == total_credits

    return {
        "is_valid": is_balanced,
        "journal_entry_id": journal_entry_id,
        "total_debits": total_debits,
        "total_credits": total_credits,
        "difference": abs(total_debits - total_credits),
        "entry_count": len(entries),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
