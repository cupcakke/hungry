from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio

from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.treasury import (
    TreasuryFinancialAccount,
    InboundTransfer,
    OutboundTransfer,
    OutboundPayment,
    ReceivedCredit,
    ReceivedDebit,
    TransactionEntry,
    CreditBalance,
    FinancialAccountType,
    FinancialAccountStatus,
    InboundTransferStatus,
    OutboundTransferStatus,
    OutboundPaymentStatus,
    TransferNetwork,
    TransactionFlowType,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    TreasuryError,
    InsufficientBalanceError,
)
from payment_platform.shared.utils.identifiers import generate_id


@dataclass
class BalanceInfo:
    available: int
    pending: int
    reserved: int
    currency: str


@dataclass
class TransferResult:
    transfer_id: str
    status: str
    amount: int
    currency: str
    fee: int


class FinancialAccountService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_account(
        self,
        account_id: str,
        account_type: str,
        currency: str,
        features: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TreasuryFinancialAccount:
        fa_type = FinancialAccountType.CHECKING
        if account_type.lower() == "savings":
            fa_type = FinancialAccountType.SAVINGS

        currency = currency.lower()
        timestamp = int(datetime.now(timezone.utc).timestamp())

        financial_account = TreasuryFinancialAccount(
            id=self._generate_id("fa"),
            account_id=account_id,
            account_type=fa_type,
            currency=currency,
            balance=0,
            available_balance=0,
            pending_balance=0,
            reserved_balance=0,
            status=FinancialAccountStatus.OPEN,
            features=self._get_default_features(features),
            active_features=features or ["inbound_transfers", "outbound_transfers"],
            routing_numbers=self._generate_routing_numbers(currency),
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(financial_account)
        await self.session.flush()

        credit_balance = CreditBalance(
            id=self._generate_id("cb"),
            financial_account_id=financial_account.id,
            available=0,
            pending=0,
            reserved=0,
            currency=currency,
        )
        self.session.add(credit_balance)

        return financial_account

    async def get_account(self, account_id: str) -> Optional[TreasuryFinancialAccount]:
        query = select(TreasuryFinancialAccount).where(
            TreasuryFinancialAccount.id == account_id
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_accounts(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        currency: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TreasuryFinancialAccount]:
        query = select(TreasuryFinancialAccount)
        
        if account_id:
            query = query.where(TreasuryFinancialAccount.account_id == account_id)
        if status:
            query = query.where(TreasuryFinancialAccount.status == status)
        if currency:
            query = query.where(TreasuryFinancialAccount.currency == currency.lower())

        query = query.order_by(TreasuryFinancialAccount.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_features(self, financial_account_id: str) -> Dict[str, Any]:
        account = await self.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        return {
            "financial_account_id": account.id,
            "active_features": account.active_features or [],
            "pending_features": account.pending_features or [],
            "restricted_features": account.restricted_features or [],
            "status": {
                "inbound_transfers": "active" if "inbound_transfers" in (account.active_features or []) else "inactive",
                "outbound_transfers": "active" if "outbound_transfers" in (account.active_features or []) else "inactive",
                "financial_addresses": "active" if "financial_addresses" in (account.active_features or []) else "inactive",
            },
        }

    async def close_account(self, financial_account_id: str) -> TreasuryFinancialAccount:
        account = await self.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        if account.balance != 0:
            raise TreasuryError(
                "Cannot close account with non-zero balance",
                financial_account_id=financial_account_id,
            )

        account.status = FinancialAccountStatus.CLOSED
        await self.session.flush()
        return account

    async def update_balance(
        self,
        financial_account_id: str,
        available_delta: int = 0,
        pending_delta: int = 0,
        reserved_delta: int = 0,
    ) -> TreasuryFinancialAccount:
        account = await self.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        new_available = account.available_balance + available_delta
        new_pending = account.pending_balance + pending_delta
        new_reserved = account.reserved_balance + reserved_delta
        new_balance = new_available + new_pending + new_reserved

        if new_available < 0:
            raise InsufficientBalanceError(
                available_amount=account.available_balance,
                requested_amount=abs(available_delta),
                currency=account.currency,
            )

        account.available_balance = new_available
        account.pending_balance = new_pending
        account.reserved_balance = new_reserved
        account.balance = new_balance

        await self.session.flush()
        return account

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"

    def _get_default_features(self, features: Optional[List[str]]) -> Dict[str, Any]:
        default = {
            "inbound_transfers": {"ach": True, "wire": True},
            "outbound_transfers": {"ach": True, "wire": True, "sepa": True},
            "financial_addresses": {"aba": True, "iban": True},
        }
        if features:
            for feature in features:
                if feature not in default:
                    default[feature] = True
        return default

    def _generate_routing_numbers(self, currency: str) -> Dict[str, Any]:
        import secrets
        if currency == "usd":
            return {
                "ach": {
                    "routing_number": "021000021",
                    "account_number": f"****{secrets.token_hex(4).upper()}",
                },
                "wire": {
                    "routing_number": "021000021",
                    "account_number": f"****{secrets.token_hex(4).upper()}",
                },
            }
        elif currency == "eur":
            return {
                "sepa": {
                    "iban": f"DE89370400440532013000",
                    "bic": "COBADEFFXXX",
                },
            }
        return {}


class InboundTransferService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.account_service = FinancialAccountService(session)

    async def create_transfer(
        self,
        financial_account_id: str,
        amount: int,
        currency: str,
        network: str,
        origin_payment_method: Optional[str] = None,
        statement_descriptor: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> InboundTransfer:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        if currency.lower() != account.currency:
            raise ValidationError(
                f"Currency mismatch. Expected {account.currency}, got {currency}",
                param="currency",
            )

        network_enum = self._parse_network(network)
        timestamp = int(datetime.now(timezone.utc).timestamp())
        expected_arrival = self._calculate_expected_arrival(network_enum, timestamp)

        transfer = InboundTransfer(
            id=self._generate_id("ibt"),
            financial_account_id=financial_account_id,
            amount=amount,
            currency=currency.lower(),
            status=InboundTransferStatus.PENDING,
            origin_payment_method=origin_payment_method,
            network=network_enum,
            statement_descriptor=statement_descriptor,
            expected_arrival_date=expected_arrival,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(transfer)
        await self.account_service.update_balance(
            financial_account_id,
            pending_delta=amount,
        )

        return transfer

    async def get_transfer(self, transfer_id: str) -> Optional[InboundTransfer]:
        query = select(InboundTransfer).where(InboundTransfer.id == transfer_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_transfers(
        self,
        financial_account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[InboundTransfer]:
        query = select(InboundTransfer)

        if financial_account_id:
            query = query.where(InboundTransfer.financial_account_id == financial_account_id)
        if status:
            query = query.where(InboundTransfer.status == status)

        query = query.order_by(InboundTransfer.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def process_transfer(self, transfer_id: str) -> InboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Inbound transfer {transfer_id} not found")

        if transfer.status != InboundTransferStatus.PENDING:
            raise TreasuryError(
                f"Transfer {transfer_id} is not in pending status",
                financial_account_id=transfer.financial_account_id,
            )

        transfer.status = InboundTransferStatus.PROCESSING
        await self.session.flush()
        return transfer

    async def complete_transfer(self, transfer_id: str) -> InboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Inbound transfer {transfer_id} not found")

        if transfer.status != InboundTransferStatus.PROCESSING:
            raise TreasuryError(
                f"Transfer {transfer_id} is not in processing status",
                financial_account_id=transfer.financial_account_id,
            )

        timestamp = int(datetime.now(timezone.utc).timestamp())
        transfer.status = InboundTransferStatus.SUCCEEDED
        transfer.arrived_at = timestamp

        await self.account_service.update_balance(
            transfer.financial_account_id,
            available_delta=transfer.amount,
            pending_delta=-transfer.amount,
        )

        transaction_entry = TransactionEntry(
            id=self._generate_id("te"),
            financial_account_id=transfer.financial_account_id,
            flow_type=TransactionFlowType.CREDIT,
            flow_id=transfer.id,
            amount=transfer.amount,
            currency=transfer.currency,
            balance_after=0,
            available_balance_after=0,
            pending_balance_after=0,
            effective_at=timestamp,
            created=timestamp,
        )
        self.session.add(transaction_entry)

        await self.session.flush()
        return transfer

    async def fail_transfer(
        self,
        transfer_id: str,
        failure_code: str,
        failure_message: str,
    ) -> InboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Inbound transfer {transfer_id} not found")

        transfer.status = InboundTransferStatus.FAILED
        transfer.failure_code = failure_code
        transfer.failure_message = failure_message

        await self.account_service.update_balance(
            transfer.financial_account_id,
            pending_delta=-transfer.amount,
        )

        await self.session.flush()
        return transfer

    async def cancel_transfer(self, transfer_id: str) -> InboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Inbound transfer {transfer_id} not found")

        if transfer.status not in [InboundTransferStatus.PENDING]:
            raise TreasuryError(
                f"Transfer {transfer_id} cannot be canceled",
                financial_account_id=transfer.financial_account_id,
            )

        transfer.status = InboundTransferStatus.CANCELED

        await self.account_service.update_balance(
            transfer.financial_account_id,
            pending_delta=-transfer.amount,
        )

        await self.session.flush()
        return transfer

    def _parse_network(self, network: str) -> TransferNetwork:
        network_map = {
            "ach": TransferNetwork.ACH,
            "wire": TransferNetwork.WIRE,
            "sepa": TransferNetwork.SEPA,
        }
        if network.lower() not in network_map:
            raise ValidationError(f"Invalid network: {network}", param="network")
        return network_map[network.lower()]

    def _calculate_expected_arrival(self, network: TransferNetwork, created: int) -> int:
        if network == TransferNetwork.ACH:
            return created + 86400 * 2
        elif network == TransferNetwork.WIRE:
            return created + 86400
        elif network == TransferNetwork.SEPA:
            return created + 86400
        return created + 86400 * 2

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class OutboundTransferService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.account_service = FinancialAccountService(session)

    async def create_transfer(
        self,
        financial_account_id: str,
        amount: int,
        currency: str,
        network: str,
        destination_payment_method: Optional[str] = None,
        statement_descriptor: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OutboundTransfer:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        if currency.lower() != account.currency:
            raise ValidationError(
                f"Currency mismatch. Expected {account.currency}, got {currency}",
                param="currency",
            )

        if account.available_balance < amount:
            raise InsufficientBalanceError(
                available_amount=account.available_balance,
                requested_amount=amount,
                currency=account.currency,
            )

        network_enum = self._parse_network(network)
        timestamp = int(datetime.now(timezone.utc).timestamp())
        expected_arrival = self._calculate_expected_arrival(network_enum, timestamp)

        transfer = OutboundTransfer(
            id=self._generate_id("obt"),
            financial_account_id=financial_account_id,
            amount=amount,
            currency=currency.lower(),
            status=OutboundTransferStatus.PENDING,
            destination_payment_method=destination_payment_method,
            network=network_enum,
            statement_descriptor=statement_descriptor,
            expected_arrival_date=expected_arrival,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(transfer)
        await self.account_service.update_balance(
            financial_account_id,
            available_delta=-amount,
            pending_delta=amount,
        )

        return transfer

    async def get_transfer(self, transfer_id: str) -> Optional[OutboundTransfer]:
        query = select(OutboundTransfer).where(OutboundTransfer.id == transfer_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_transfers(
        self,
        financial_account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[OutboundTransfer]:
        query = select(OutboundTransfer)

        if financial_account_id:
            query = query.where(OutboundTransfer.financial_account_id == financial_account_id)
        if status:
            query = query.where(OutboundTransfer.status == status)

        query = query.order_by(OutboundTransfer.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def process_transfer(self, transfer_id: str) -> OutboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Outbound transfer {transfer_id} not found")

        transfer.status = OutboundTransferStatus.PROCESSING
        await self.session.flush()
        return transfer

    async def post_transfer(self, transfer_id: str) -> OutboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Outbound transfer {transfer_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        transfer.status = OutboundTransferStatus.POSTED
        transfer.posted_at = timestamp

        await self.account_service.update_balance(
            transfer.financial_account_id,
            pending_delta=-transfer.amount,
        )

        transaction_entry = TransactionEntry(
            id=self._generate_id("te"),
            financial_account_id=transfer.financial_account_id,
            flow_type=TransactionFlowType.TRANSFER,
            flow_id=transfer.id,
            amount=-transfer.amount,
            currency=transfer.currency,
            balance_after=0,
            available_balance_after=0,
            pending_balance_after=0,
            effective_at=timestamp,
            created=timestamp,
        )
        self.session.add(transaction_entry)

        await self.session.flush()
        return transfer

    async def return_transfer(
        self,
        transfer_id: str,
        return_reason: str,
        return_details: Optional[Dict[str, Any]] = None,
    ) -> OutboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Outbound transfer {transfer_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        transfer.status = OutboundTransferStatus.RETURNED
        transfer.returned_at = timestamp
        transfer.returned_details = {
            "reason": return_reason,
            **(return_details or {}),
        }

        await self.account_service.update_balance(
            transfer.financial_account_id,
            available_delta=transfer.amount,
            pending_delta=-transfer.amount,
        )

        await self.session.flush()
        return transfer

    async def fail_transfer(
        self,
        transfer_id: str,
        failure_code: str,
        failure_message: str,
    ) -> OutboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Outbound transfer {transfer_id} not found")

        transfer.status = OutboundTransferStatus.FAILED
        transfer.failure_code = failure_code
        transfer.failure_message = failure_message

        await self.account_service.update_balance(
            transfer.financial_account_id,
            available_delta=transfer.amount,
            pending_delta=-transfer.amount,
        )

        await self.session.flush()
        return transfer

    async def cancel_transfer(self, transfer_id: str) -> OutboundTransfer:
        transfer = await self.get_transfer(transfer_id)
        if not transfer:
            raise NotFoundError(f"Outbound transfer {transfer_id} not found")

        transfer.status = OutboundTransferStatus.CANCELED

        await self.account_service.update_balance(
            transfer.financial_account_id,
            available_delta=transfer.amount,
            pending_delta=-transfer.amount,
        )

        await self.session.flush()
        return transfer

    def _parse_network(self, network: str) -> TransferNetwork:
        network_map = {
            "ach": TransferNetwork.ACH,
            "wire": TransferNetwork.WIRE,
            "sepa": TransferNetwork.SEPA,
        }
        if network.lower() not in network_map:
            raise ValidationError(f"Invalid network: {network}", param="network")
        return network_map[network.lower()]

    def _calculate_expected_arrival(self, network: TransferNetwork, created: int) -> int:
        if network == TransferNetwork.ACH:
            return created + 86400 * 2
        elif network == TransferNetwork.WIRE:
            return created + 86400
        elif network == TransferNetwork.SEPA:
            return created + 86400
        return created + 86400 * 2

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class OutboundPaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.account_service = FinancialAccountService(session)

    async def create_payment(
        self,
        financial_account_id: str,
        amount: int,
        currency: str,
        recipient_payment_method: Optional[str] = None,
        statement_descriptor: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OutboundPayment:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        if currency.lower() != account.currency:
            raise ValidationError(
                f"Currency mismatch. Expected {account.currency}, got {currency}",
                param="currency",
            )

        if account.available_balance < amount:
            raise InsufficientBalanceError(
                available_amount=account.available_balance,
                requested_amount=amount,
                currency=account.currency,
            )

        timestamp = int(datetime.now(timezone.utc).timestamp())
        expected_arrival = timestamp + 86400 * 3

        payment = OutboundPayment(
            id=self._generate_id("obp"),
            financial_account_id=financial_account_id,
            amount=amount,
            currency=currency.lower(),
            status=OutboundPaymentStatus.PENDING,
            recipient_payment_method=recipient_payment_method,
            statement_descriptor=statement_descriptor,
            expected_arrival_date=expected_arrival,
            cancelable=True,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(payment)
        await self.account_service.update_balance(
            financial_account_id,
            available_delta=-amount,
            pending_delta=amount,
        )

        return payment

    async def get_payment(self, payment_id: str) -> Optional[OutboundPayment]:
        query = select(OutboundPayment).where(OutboundPayment.id == payment_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_payments(
        self,
        financial_account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[OutboundPayment]:
        query = select(OutboundPayment)

        if financial_account_id:
            query = query.where(OutboundPayment.financial_account_id == financial_account_id)
        if status:
            query = query.where(OutboundPayment.status == status)

        query = query.order_by(OutboundPayment.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def cancel_payment(self, payment_id: str) -> OutboundPayment:
        payment = await self.get_payment(payment_id)
        if not payment:
            raise NotFoundError(f"Outbound payment {payment_id} not found")

        if not payment.cancelable or payment.status not in [OutboundPaymentStatus.PENDING]:
            raise TreasuryError(
                f"Payment {payment_id} cannot be canceled",
                financial_account_id=payment.financial_account_id,
            )

        payment.status = OutboundPaymentStatus.CANCELED
        payment.cancelable = False

        await self.account_service.update_balance(
            payment.financial_account_id,
            available_delta=payment.amount,
            pending_delta=-payment.amount,
        )

        await self.session.flush()
        return payment

    async def process_payment(self, payment_id: str) -> OutboundPayment:
        payment = await self.get_payment(payment_id)
        if not payment:
            raise NotFoundError(f"Outbound payment {payment_id} not found")

        payment.status = OutboundPaymentStatus.PROCESSING
        payment.cancelable = False
        await self.session.flush()
        return payment

    async def post_payment(self, payment_id: str) -> OutboundPayment:
        payment = await self.get_payment(payment_id)
        if not payment:
            raise NotFoundError(f"Outbound payment {payment_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.status = OutboundPaymentStatus.POSTED
        payment.posted_at = timestamp

        await self.account_service.update_balance(
            payment.financial_account_id,
            pending_delta=-payment.amount,
        )

        await self.session.flush()
        return payment

    async def return_payment(
        self,
        payment_id: str,
        return_reason: str,
        return_details: Optional[Dict[str, Any]] = None,
    ) -> OutboundPayment:
        payment = await self.get_payment(payment_id)
        if not payment:
            raise NotFoundError(f"Outbound payment {payment_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        payment.status = OutboundPaymentStatus.RETURNED
        payment.returned_at = timestamp
        payment.returned_details = {
            "reason": return_reason,
            **(return_details or {}),
        }

        await self.account_service.update_balance(
            payment.financial_account_id,
            available_delta=payment.amount,
            pending_delta=-payment.amount,
        )

        await self.session.flush()
        return payment

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class BalanceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.account_service = FinancialAccountService(session)

    async def get_balance(self, financial_account_id: str) -> BalanceInfo:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        return BalanceInfo(
            available=account.available_balance,
            pending=account.pending_balance,
            reserved=account.reserved_balance,
            currency=account.currency,
        )

    async def get_credit_balance(self, financial_account_id: str) -> CreditBalance:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        query = select(CreditBalance).where(
            CreditBalance.financial_account_id == financial_account_id
        )
        result = await self.session.execute(query)
        balance = result.scalar_one_or_none()

        if not balance:
            balance = CreditBalance(
                id=self._generate_id("cb"),
                financial_account_id=financial_account_id,
                available=account.available_balance,
                pending=account.pending_balance,
                reserved=account.reserved_balance,
                currency=account.currency,
            )
            self.session.add(balance)
            await self.session.flush()

        return balance

    async def refresh_balance(self, financial_account_id: str) -> CreditBalance:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        balance = await self.get_credit_balance(financial_account_id)

        balance.available = account.available_balance
        balance.pending = account.pending_balance
        balance.reserved = account.reserved_balance

        await self.session.flush()
        return balance

    async def reserve_funds(
        self,
        financial_account_id: str,
        amount: int,
        reference: Optional[str] = None,
    ) -> BalanceInfo:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        if account.available_balance < amount:
            raise InsufficientBalanceError(
                available_amount=account.available_balance,
                requested_amount=amount,
                currency=account.currency,
            )

        await self.account_service.update_balance(
            financial_account_id,
            available_delta=-amount,
            reserved_delta=amount,
        )

        return await self.get_balance(financial_account_id)

    async def release_reserved_funds(
        self,
        financial_account_id: str,
        amount: int,
        reference: Optional[str] = None,
    ) -> BalanceInfo:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        if account.reserved_balance < amount:
            raise TreasuryError(
                f"Insufficient reserved balance. Available: {account.reserved_balance}",
                financial_account_id=financial_account_id,
            )

        await self.account_service.update_balance(
            financial_account_id,
            available_delta=amount,
            reserved_delta=-amount,
        )

        return await self.get_balance(financial_account_id)

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class TransactionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.account_service = FinancialAccountService(session)

    async def create_entry(
        self,
        financial_account_id: str,
        flow_type: TransactionFlowType,
        amount: int,
        currency: str,
        flow_id: Optional[str] = None,
        flow_details: Optional[Dict[str, Any]] = None,
    ) -> TransactionEntry:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        entry = TransactionEntry(
            id=self._generate_id("te"),
            financial_account_id=financial_account_id,
            flow_type=flow_type,
            flow_id=flow_id,
            flow_details=flow_details,
            amount=amount,
            currency=currency.lower(),
            balance_after=account.balance,
            available_balance_after=account.available_balance,
            pending_balance_after=account.pending_balance,
            effective_at=timestamp,
            created=timestamp,
        )

        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_entries(
        self,
        financial_account_id: Optional[str] = None,
        flow_type: Optional[str] = None,
        start_date: Optional[int] = None,
        end_date: Optional[int] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[TransactionEntry]:
        query = select(TransactionEntry)

        if financial_account_id:
            query = query.where(TransactionEntry.financial_account_id == financial_account_id)
        if flow_type:
            query = query.where(TransactionEntry.flow_type == flow_type)
        if start_date:
            query = query.where(TransactionEntry.effective_at >= start_date)
        if end_date:
            query = query.where(TransactionEntry.effective_at <= end_date)

        query = query.order_by(TransactionEntry.effective_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_entry(self, entry_id: str) -> Optional[TransactionEntry]:
        query = select(TransactionEntry).where(TransactionEntry.id == entry_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_transactions_by_flow(
        self,
        flow_type: TransactionFlowType,
        flow_id: str,
    ) -> List[TransactionEntry]:
        query = select(TransactionEntry).where(
            and_(
                TransactionEntry.flow_type == flow_type,
                TransactionEntry.flow_id == flow_id,
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ReconciliationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.account_service = FinancialAccountService(session)
        self.balance_service = BalanceService(session)
        self.transaction_service = TransactionService(session)

    async def reconcile_account(
        self,
        financial_account_id: str,
    ) -> Dict[str, Any]:
        account = await self.account_service.get_account(financial_account_id)
        if not account:
            raise NotFoundError(f"Financial account {financial_account_id} not found")

        entries = await self.transaction_service.list_entries(
            financial_account_id=financial_account_id,
            limit=10000,
        )

        calculated_balance = sum(e.amount for e in entries)

        query = select(func.count()).select_from(TransactionEntry).where(
            TransactionEntry.financial_account_id == financial_account_id
        )
        result = await self.session.execute(query)
        entry_count = result.scalar() or 0

        balance = await self.balance_service.get_balance(financial_account_id)

        is_reconciled = (
            calculated_balance == account.balance
            and balance.available == account.available_balance
            and balance.pending == account.pending_balance
            and balance.reserved == account.reserved_balance
        )

        return {
            "financial_account_id": financial_account_id,
            "is_reconciled": is_reconciled,
            "calculated_balance": calculated_balance,
            "stored_balance": account.balance,
            "available_balance": account.available_balance,
            "pending_balance": account.pending_balance,
            "reserved_balance": account.reserved_balance,
            "entry_count": entry_count,
            "reconciled_at": int(datetime.now(timezone.utc).timestamp()),
        }

    async def reconcile_pending_transfers(
        self,
        financial_account_id: str,
    ) -> Dict[str, Any]:
        inbound_query = select(InboundTransfer).where(
            and_(
                InboundTransfer.financial_account_id == financial_account_id,
                InboundTransfer.status.in_([
                    InboundTransferStatus.PENDING,
                    InboundTransferStatus.PROCESSING,
                ]),
            )
        )
        inbound_result = await self.session.execute(inbound_query)
        pending_inbound = list(inbound_result.scalars().all())

        outbound_query = select(OutboundTransfer).where(
            and_(
                OutboundTransfer.financial_account_id == financial_account_id,
                OutboundTransfer.status.in_([
                    OutboundTransferStatus.PENDING,
                    OutboundTransferStatus.PROCESSING,
                ]),
            )
        )
        outbound_result = await self.session.execute(outbound_query)
        pending_outbound = list(outbound_result.scalars().all())

        payments_query = select(OutboundPayment).where(
            and_(
                OutboundPayment.financial_account_id == financial_account_id,
                OutboundPayment.status.in_([
                    OutboundPaymentStatus.PENDING,
                    OutboundPaymentStatus.PROCESSING,
                ]),
            )
        )
        payments_result = await self.session.execute(payments_query)
        pending_payments = list(payments_result.scalars().all())

        inbound_total = sum(t.amount for t in pending_inbound)
        outbound_total = sum(t.amount for t in pending_outbound)
        payments_total = sum(p.amount for p in pending_payments)

        return {
            "financial_account_id": financial_account_id,
            "pending_inbound_transfers": len(pending_inbound),
            "pending_inbound_amount": inbound_total,
            "pending_outbound_transfers": len(pending_outbound),
            "pending_outbound_amount": outbound_total,
            "pending_outbound_payments": len(pending_payments),
            "pending_payments_amount": payments_total,
            "total_pending_debit": outbound_total + payments_total,
            "total_pending_credit": inbound_total,
            "reconciled_at": int(datetime.now(timezone.utc).timestamp()),
        }

    async def auto_complete_transfers(
        self,
        financial_account_id: str,
        max_age_hours: int = 72,
    ) -> Dict[str, Any]:
        from payment_platform.backend.application.services.treasury_service import (
            InboundTransferService,
            OutboundTransferService,
            OutboundPaymentService,
        )

        inbound_service = InboundTransferService(self.session)
        outbound_service = OutboundTransferService(self.session)
        payment_service = OutboundPaymentService(self.session)

        cutoff_time = int(datetime.now(timezone.utc).timestamp()) - (max_age_hours * 3600)

        completed_inbound = 0
        failed_inbound = 0

        inbound_query = select(InboundTransfer).where(
            and_(
                InboundTransfer.financial_account_id == financial_account_id,
                InboundTransfer.status == InboundTransferStatus.PROCESSING,
                InboundTransfer.created < cutoff_time,
            )
        )
        inbound_result = await self.session.execute(inbound_query)
        for transfer in inbound_result.scalars().all():
            try:
                await inbound_service.complete_transfer(transfer.id)
                completed_inbound += 1
            except Exception:
                failed_inbound += 1

        completed_outbound = 0
        failed_outbound = 0

        outbound_query = select(OutboundTransfer).where(
            and_(
                OutboundTransfer.financial_account_id == financial_account_id,
                OutboundTransfer.status == OutboundTransferStatus.PROCESSING,
                OutboundTransfer.created < cutoff_time,
            )
        )
        outbound_result = await self.session.execute(outbound_query)
        for transfer in outbound_result.scalars().all():
            try:
                await outbound_service.post_transfer(transfer.id)
                completed_outbound += 1
            except Exception:
                failed_outbound += 1

        completed_payments = 0
        failed_payments = 0

        payments_query = select(OutboundPayment).where(
            and_(
                OutboundPayment.financial_account_id == financial_account_id,
                OutboundPayment.status == OutboundPaymentStatus.PROCESSING,
                OutboundPayment.created < cutoff_time,
            )
        )
        payments_result = await self.session.execute(payments_query)
        for payment in payments_result.scalars().all():
            try:
                await payment_service.post_payment(payment.id)
                completed_payments += 1
            except Exception:
                failed_payments += 1

        return {
            "financial_account_id": financial_account_id,
            "completed_inbound_transfers": completed_inbound,
            "failed_inbound_transfers": failed_inbound,
            "completed_outbound_transfers": completed_outbound,
            "failed_outbound_transfers": failed_outbound,
            "completed_outbound_payments": completed_payments,
            "failed_outbound_payments": failed_payments,
            "processed_at": int(datetime.now(timezone.utc).timestamp()),
        }

    async def get_daily_summary(
        self,
        financial_account_id: str,
        date: Optional[int] = None,
    ) -> Dict[str, Any]:
        if date is None:
            date = int(datetime.now(timezone.utc).timestamp())

        start_of_day = date - (date % 86400)
        end_of_day = start_of_day + 86400

        inbound_query = select(InboundTransfer).where(
            and_(
                InboundTransfer.financial_account_id == financial_account_id,
                InboundTransfer.created >= start_of_day,
                InboundTransfer.created < end_of_day,
            )
        )
        inbound_result = await self.session.execute(inbound_query)
        inbound_transfers = list(inbound_result.scalars().all())

        outbound_query = select(OutboundTransfer).where(
            and_(
                OutboundTransfer.financial_account_id == financial_account_id,
                OutboundTransfer.created >= start_of_day,
                OutboundTransfer.created < end_of_day,
            )
        )
        outbound_result = await self.session.execute(outbound_query)
        outbound_transfers = list(outbound_result.scalars().all())

        payments_query = select(OutboundPayment).where(
            and_(
                OutboundPayment.financial_account_id == financial_account_id,
                OutboundPayment.created >= start_of_day,
                OutboundPayment.created < end_of_day,
            )
        )
        payments_result = await self.session.execute(payments_query)
        outbound_payments = list(payments_result.scalars().all())

        balance = await self.balance_service.get_balance(financial_account_id)

        return {
            "financial_account_id": financial_account_id,
            "date": start_of_day,
            "inbound_transfers_count": len(inbound_transfers),
            "inbound_transfers_total": sum(t.amount for t in inbound_transfers),
            "outbound_transfers_count": len(outbound_transfers),
            "outbound_transfers_total": sum(t.amount for t in outbound_transfers),
            "outbound_payments_count": len(outbound_payments),
            "outbound_payments_total": sum(p.amount for p in outbound_payments),
            "net_flow": sum(t.amount for t in inbound_transfers)
                        - sum(t.amount for t in outbound_transfers)
                        - sum(p.amount for p in outbound_payments),
            "closing_balance": {
                "available": balance.available,
                "pending": balance.pending,
                "reserved": balance.reserved,
                "currency": balance.currency,
            },
        }
