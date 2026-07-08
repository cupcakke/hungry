from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import secrets
import json
import httpx

from sqlalchemy import select, update, and_, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.financial_connections import (
    FinancialConnection,
    LinkedAccount,
    AccountTransaction,
    Institution,
    AccountBalance,
    AccountOwnership,
    SyncStatus,
    RefreshToken,
    ConnectionSubscription,
    LinkSession,
    TransactionCategory,
    ConnectionStatus,
    ConnectionType,
    LinkedAccountType,
    LinkedAccountStatus,
    TransactionType,
    SyncStatusType,
    OwnershipType,
    CredentialsType,
    SubscriptionEventType,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    FinancialConnectionError,
)
from payment_platform.shared.utils.crypto import encrypt_data, decrypt_data


ENCRYPTION_KEY = "default_encryption_key_for_financial_connections"


@dataclass
class LinkSessionResult:
    session_id: str
    link_token: str
    oauth_url: Optional[str]
    expires_at: datetime


@dataclass
class ConnectionResult:
    connection_id: str
    status: str
    accounts_linked: int
    institution_name: str


@dataclass
class SyncResult:
    sync_id: str
    status: str
    items_synced: int
    items_failed: int
    has_more: bool


@dataclass
class TransactionCategorization:
    category: str
    subcategory: Optional[str]
    confidence: float


class ConnectionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._providers = {
            ConnectionType.PLAID: PlaidProvider(),
            ConnectionType.MX: MXProvider(),
            ConnectionType.YODLEE: YodleeProvider(),
            ConnectionType.FINICITY: FinicityProvider(),
            ConnectionType.TELLER: TellerProvider(),
        }

    async def create_session(
        self,
        account_id: str,
        connection_type: str,
        products: List[str],
        institution_id: Optional[str] = None,
        client_name: Optional[str] = None,
        webhook: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        country_codes: List[str] = None,
        language: str = "en",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LinkSessionResult:
        conn_type = self._parse_connection_type(connection_type)
        provider = self._providers.get(conn_type)
        
        if not provider:
            raise ValidationError(f"Unsupported connection type: {connection_type}")
        
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        
        link_session = LinkSession(
            id=self._generate_id("ls"),
            account_id=account_id,
            connection_type=conn_type,
            products=products,
            institution_id=institution_id,
            client_name=client_name,
            country_codes=country_codes or ["US"],
            language=language,
            webhook=webhook,
            redirect_uri=redirect_uri,
            status="pending",
            expires_at=expires_at,
            metadata_=metadata or {},
        )
        
        self.session.add(link_session)
        
        link_token, oauth_url = await provider.create_link_token(
            session_id=link_session.id,
            products=products,
            institution_id=institution_id,
            redirect_uri=redirect_uri,
        )
        
        link_session.oauth_state = link_token
        
        await self.session.flush()
        
        return LinkSessionResult(
            session_id=link_session.id,
            link_token=link_token,
            oauth_url=oauth_url,
            expires_at=expires_at,
        )

    async def connect(
        self,
        session_id: str,
        public_token: Optional[str] = None,
        institution_id: Optional[str] = None,
        institution_name: Optional[str] = None,
        accounts: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConnectionResult:
        query = select(LinkSession).where(LinkSession.id == session_id)
        result = await self.session.execute(query)
        link_session = result.scalar_one_or_none()
        
        if not link_session:
            raise NotFoundError(f"Link session {session_id} not found")
        
        if link_session.status != "pending":
            raise ValidationError(f"Link session {session_id} is not in pending state")
        
        if datetime.now(timezone.utc) > link_session.expires_at:
            raise ValidationError(f"Link session {session_id} has expired")
        
        provider = self._providers.get(link_session.connection_type)
        
        if not provider:
            raise ValidationError(f"Unsupported connection type: {link_session.connection_type}")
        
        external_connection_id = None
        access_token = None
        refresh_token = None
        
        if public_token:
            token_data = await provider.exchange_public_token(public_token)
            external_connection_id = token_data.get("connection_id")
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
        
        if not institution_id:
            institution_id = link_session.institution_id or "inst_default"
        if not institution_name:
            institution_name = "Connected Institution"
        
        connection = FinancialConnection(
            id=self._generate_id("fc"),
            account_id=link_session.account_id,
            institution_id=institution_id,
            institution_name=institution_name,
            status=ConnectionStatus.ACTIVE,
            connection_type=link_session.connection_type,
            products=link_session.products,
            external_connection_id=external_connection_id,
            link_session_id=session_id,
            metadata_=metadata or {},
        )
        
        self.session.add(connection)
        
        if access_token:
            encrypted_token = self._encrypt_token(access_token)
            encrypted_refresh = self._encrypt_token(refresh_token) if refresh_token else None
            
            refresh_token_record = RefreshToken(
                id=self._generate_id("rt"),
                connection_id=connection.id,
                token_encrypted=encrypted_token,
                token_hash=self._hash_token(access_token),
                access_token_encrypted=encrypted_token,
                refresh_token_encrypted=encrypted_refresh,
                is_valid=True,
            )
            self.session.add(refresh_token_record)
        
        accounts_linked = 0
        if accounts:
            for account_data in accounts:
                await self._create_linked_account(connection.id, account_data)
                accounts_linked += 1
        
        link_session.status = "completed"
        link_session.completed_at = datetime.now(timezone.utc)
        link_session.connection_id = connection.id
        
        await self.session.flush()
        
        return ConnectionResult(
            connection_id=connection.id,
            status=connection.status.value,
            accounts_linked=accounts_linked,
            institution_name=institution_name,
        )

    async def disconnect(self, connection_id: str) -> FinancialConnection:
        query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
        result = await self.session.execute(query)
        connection = result.scalar_one_or_none()
        
        if not connection:
            raise NotFoundError(f"Financial connection {connection_id} not found")
        
        provider = self._providers.get(connection.connection_type)
        
        if provider and connection.external_connection_id:
            try:
                await provider.disconnect(connection.external_connection_id)
            except Exception:
                pass
        
        connection.status = ConnectionStatus.DISCONNECTED
        
        token_query = select(RefreshToken).where(RefreshToken.connection_id == connection_id)
        token_result = await self.session.execute(token_query)
        tokens = token_result.scalars().all()
        for token in tokens:
            token.is_valid = False
        
        await self.session.flush()
        return connection

    async def refresh(self, connection_id: str) -> FinancialConnection:
        query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
        result = await self.session.execute(query)
        connection = result.scalar_one_or_none()
        
        if not connection:
            raise NotFoundError(f"Financial connection {connection_id} not found")
        
        if connection.status == ConnectionStatus.DISCONNECTED:
            raise ValidationError("Cannot refresh a disconnected connection")
        
        provider = self._providers.get(connection.connection_type)
        
        if not provider:
            raise ValidationError(f"Unsupported connection type: {connection.connection_type}")
        
        token_query = select(RefreshToken).where(
            and_(
                RefreshToken.connection_id == connection_id,
                RefreshToken.is_valid == True,
            )
        ).order_by(RefreshToken.created_at.desc())
        token_result = await self.session.execute(token_query)
        token_record = token_result.scalar_one_or_none()
        
        if not token_record:
            connection.status = ConnectionStatus.EXPIRED
            await self.session.flush()
            raise FinancialConnectionError("No valid refresh token found")
        
        access_token = self._decrypt_token(token_record.access_token_encrypted)
        refresh_token = None
        if token_record.refresh_token_encrypted:
            refresh_token = self._decrypt_token(token_record.refresh_token_encrypted)
        
        try:
            new_tokens = await provider.refresh_access_token(access_token, refresh_token)
            
            if new_tokens:
                encrypted_new_access = self._encrypt_token(new_tokens.get("access_token", access_token))
                token_record.access_token_encrypted = encrypted_new_access
                token_record.last_used_at = datetime.now(timezone.utc)
                
                if new_tokens.get("refresh_token"):
                    encrypted_new_refresh = self._encrypt_token(new_tokens["refresh_token"])
                    token_record.refresh_token_encrypted = encrypted_new_refresh
                
                connection.last_synced_at = datetime.now(timezone.utc)
                connection.status = ConnectionStatus.ACTIVE
                connection.error_code = None
                connection.error_message = None
            
        except Exception as e:
            connection.status = ConnectionStatus.ERROR
            connection.error_code = "REFRESH_FAILED"
            connection.error_message = str(e)
        
        await self.session.flush()
        return connection

    async def get_connection(self, connection_id: str) -> Optional[FinancialConnection]:
        query = select(FinancialConnection).where(FinancialConnection.id == connection_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_connections(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        connection_type: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[FinancialConnection]:
        query = select(FinancialConnection)
        
        if account_id:
            query = query.where(FinancialConnection.account_id == account_id)
        if status:
            query = query.where(FinancialConnection.status == status)
        if connection_type:
            query = query.where(FinancialConnection.connection_type == connection_type)
        
        query = query.order_by(FinancialConnection.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _create_linked_account(
        self,
        connection_id: str,
        account_data: Dict[str, Any],
    ) -> LinkedAccount:
        account_type = self._parse_account_type(account_data.get("type", "checking"))
        
        linked_account = LinkedAccount(
            id=self._generate_id("la"),
            connection_id=connection_id,
            external_account_id=account_data.get("id", self._generate_id("ext")),
            account_type=account_type,
            account_subtype=account_data.get("subtype"),
            account_name=account_data.get("name", "Account"),
            mask=account_data.get("mask"),
            official_name=account_data.get("official_name"),
            balance_available=account_data.get("balances", {}).get("available"),
            balance_current=account_data.get("balances", {}).get("current"),
            balance_limit=account_data.get("balances", {}).get("limit"),
            currency=account_data.get("currency", "USD").upper(),
            status=LinkedAccountStatus.ACTIVE,
            owner_name=account_data.get("owner_name"),
        )
        
        self.session.add(linked_account)
        await self.session.flush()
        return linked_account

    def _parse_connection_type(self, conn_type: str) -> ConnectionType:
        type_map = {
            "plaid": ConnectionType.PLAID,
            "mx": ConnectionType.MX,
            "yodlee": ConnectionType.YODLEE,
            "finicity": ConnectionType.FINICITY,
            "teller": ConnectionType.TELLER,
        }
        return type_map.get(conn_type.lower(), ConnectionType.PLAID)

    def _parse_account_type(self, acc_type: str) -> LinkedAccountType:
        type_map = {
            "checking": LinkedAccountType.CHECKING,
            "savings": LinkedAccountType.SAVINGS,
            "credit_card": LinkedAccountType.CREDIT_CARD,
            "credit": LinkedAccountType.CREDIT_CARD,
            "investment": LinkedAccountType.INVESTMENT,
            "loan": LinkedAccountType.LOAN,
            "mortgage": LinkedAccountType.MORTGAGE,
            "brokerage": LinkedAccountType.BROKERAGE,
            "retirement": LinkedAccountType.RETIREMENT,
        }
        return type_map.get(acc_type.lower(), LinkedAccountType.OTHER)

    def _encrypt_token(self, token: str) -> str:
        if not token:
            return ""
        return encrypt_data(token, ENCRYPTION_KEY)

    def _decrypt_token(self, encrypted: str) -> str:
        if not encrypted:
            return ""
        return decrypt_data(encrypted, ENCRYPTION_KEY)

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class LinkedAccountService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_accounts(
        self,
        connection_id: str,
        account_type: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[LinkedAccount]:
        query = select(LinkedAccount).where(LinkedAccount.connection_id == connection_id)
        
        if account_type:
            query = query.where(LinkedAccount.account_type == account_type)
        
        query = query.order_by(LinkedAccount.created_at.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_account(self, account_id: str) -> Optional[LinkedAccount]:
        query = select(LinkedAccount).where(LinkedAccount.id == account_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_balance(self, account_id: str) -> Optional[AccountBalance]:
        query = select(AccountBalance).where(
            AccountBalance.linked_account_id == account_id
        ).order_by(AccountBalance.as_of.desc())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_balance(
        self,
        account_id: str,
        available: Optional[int],
        current: Optional[int],
        limit: Optional[int],
        currency: str,
        source: Optional[str] = None,
    ) -> AccountBalance:
        account = await self.get_account(account_id)
        if not account:
            raise NotFoundError(f"Linked account {account_id} not found")
        
        now = datetime.now(timezone.utc)
        
        balance = AccountBalance(
            id=self._generate_id("bal"),
            linked_account_id=account_id,
            available=available,
            current=current,
            limit=limit,
            currency=currency.upper(),
            as_of=now,
            source=source,
        )
        
        self.session.add(balance)
        
        account.balance_available = available
        account.balance_current = current
        account.balance_limit = limit
        account.last_balance_update = now
        
        await self.session.flush()
        return balance

    async def sync_accounts(
        self,
        connection_id: str,
        accounts_data: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        synced = 0
        failed = 0
        
        for account_data in accounts_data:
            try:
                external_id = account_data.get("id")
                query = select(LinkedAccount).where(
                    and_(
                        LinkedAccount.connection_id == connection_id,
                        LinkedAccount.external_account_id == external_id,
                    )
                )
                result = await self.session.execute(query)
                existing = result.scalar_one_or_none()
                
                if existing:
                    balances = account_data.get("balances", {})
                    if balances:
                        await self.update_balance(
                            account_id=existing.id,
                            available=balances.get("available"),
                            current=balances.get("current"),
                            limit=balances.get("limit"),
                            currency=account_data.get("currency", "USD"),
                            source="sync",
                        )
                    synced += 1
                else:
                    await self._create_account(connection_id, account_data)
                    synced += 1
            except Exception:
                failed += 1
        
        await self.session.flush()
        return synced, failed

    async def _create_account(
        self,
        connection_id: str,
        account_data: Dict[str, Any],
    ) -> LinkedAccount:
        type_map = {
            "checking": LinkedAccountType.CHECKING,
            "savings": LinkedAccountType.SAVINGS,
            "credit_card": LinkedAccountType.CREDIT_CARD,
            "credit": LinkedAccountType.CREDIT_CARD,
            "investment": LinkedAccountType.INVESTMENT,
            "loan": LinkedAccountType.LOAN,
        }
        
        account_type = type_map.get(
            account_data.get("type", "checking").lower(),
            LinkedAccountType.OTHER
        )
        
        account = LinkedAccount(
            id=self._generate_id("la"),
            connection_id=connection_id,
            external_account_id=account_data.get("id", self._generate_id("ext")),
            account_type=account_type,
            account_subtype=account_data.get("subtype"),
            account_name=account_data.get("name", "Account"),
            mask=account_data.get("mask"),
            official_name=account_data.get("official_name"),
            balance_available=account_data.get("balances", {}).get("available"),
            balance_current=account_data.get("balances", {}).get("current"),
            balance_limit=account_data.get("balances", {}).get("limit"),
            currency=account_data.get("currency", "USD").upper(),
            status=LinkedAccountStatus.ACTIVE,
            owner_name=account_data.get("owner_name"),
        )
        
        self.session.add(account)
        return account

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class TransactionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self._category_keywords = self._build_category_keywords()

    async def sync_transactions(
        self,
        account_id: str,
        transactions_data: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        synced = 0
        failed = 0
        
        for tx_data in transactions_data:
            try:
                external_id = tx_data.get("transaction_id") or tx_data.get("id")
                
                query = select(AccountTransaction).where(
                    and_(
                        AccountTransaction.linked_account_id == account_id,
                        AccountTransaction.external_transaction_id == external_id,
                    )
                )
                result = await self.session.execute(query)
                existing = result.scalar_one_or_none()
                
                if existing:
                    existing.amount = tx_data.get("amount", existing.amount)
                    existing.pending = tx_data.get("pending", existing.pending)
                    existing.description = tx_data.get("description") or existing.description
                    
                    categorization = await self.categorize(existing.description or "")
                    existing.category = categorization.category
                    existing.subcategory = categorization.subcategory
                    synced += 1
                else:
                    await self._create_transaction(account_id, tx_data)
                    synced += 1
            except Exception:
                failed += 1
        
        account_query = select(LinkedAccount).where(LinkedAccount.id == account_id)
        account_result = await self.session.execute(account_query)
        account = account_result.scalar_one_or_none()
        if account:
            account.last_transaction_update = datetime.now(timezone.utc)
        
        await self.session.flush()
        return synced, failed

    async def categorize(
        self,
        description: str,
        merchant_name: Optional[str] = None,
        amount: Optional[int] = None,
    ) -> TransactionCategorization:
        text = f"{description or ''} {merchant_name or ''}".lower()
        
        best_category = "other"
        best_subcategory = None
        best_confidence = 0.0
        
        for category, keywords in self._category_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    confidence = len(keyword) / len(text) if text else 0
                    if confidence > best_confidence:
                        best_category = category
                        best_confidence = min(confidence * 2, 0.95)
                        break
        
        if best_category == "shopping":
            if any(w in text for w in ["grocery", "supermarket", "market"]):
                best_subcategory = "groceries"
            elif any(w in text for w in ["gas", "fuel", "station"]):
                best_subcategory = "gas"
            elif any(w in text for w in ["restaurant", "cafe", "coffee", "food"]):
                best_subcategory = "dining"
        elif best_category == "income":
            best_subcategory = "salary" if "payroll" in text or "salary" in text else "other"
        
        return TransactionCategorization(
            category=best_category,
            subcategory=best_subcategory,
            confidence=best_confidence,
        )

    async def search(
        self,
        account_id: str,
        query_text: Optional[str] = None,
        category: Optional[str] = None,
        min_amount: Optional[int] = None,
        max_amount: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AccountTransaction]:
        query = select(AccountTransaction).where(
            AccountTransaction.linked_account_id == account_id
        )
        
        if query_text:
            query = query.where(
                or_(
                    AccountTransaction.description.ilike(f"%{query_text}%"),
                    AccountTransaction.merchant_name.ilike(f"%{query_text}%"),
                )
            )
        
        if category:
            query = query.where(AccountTransaction.category == category)
        
        if min_amount is not None:
            query = query.where(AccountTransaction.amount >= min_amount)
        if max_amount is not None:
            query = query.where(AccountTransaction.amount <= max_amount)
        
        if start_date:
            query = query.where(AccountTransaction.date >= start_date.date())
        if end_date:
            query = query.where(AccountTransaction.date <= end_date.date())
        
        query = query.order_by(AccountTransaction.date.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_transactions(
        self,
        account_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AccountTransaction]:
        query = select(AccountTransaction).where(
            AccountTransaction.linked_account_id == account_id
        ).order_by(AccountTransaction.date.desc()).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _create_transaction(
        self,
        account_id: str,
        tx_data: Dict[str, Any],
    ) -> AccountTransaction:
        external_id = tx_data.get("transaction_id") or tx_data.get("id")
        description = tx_data.get("description") or tx_data.get("name", "")
        merchant_name = tx_data.get("merchant_name")
        
        categorization = await self.categorize(description, merchant_name, tx_data.get("amount"))
        
        tx_type = TransactionType.DEBIT
        amount = tx_data.get("amount", 0)
        if amount < 0:
            tx_type = TransactionType.CREDIT
        
        transaction = AccountTransaction(
            id=self._generate_id("tx"),
            linked_account_id=account_id,
            external_transaction_id=external_id,
            amount=abs(amount),
            currency=tx_data.get("currency", "USD").upper(),
            description=description,
            merchant_name=merchant_name,
            merchant_category_code=tx_data.get("merchant_category_code"),
            category=categorization.category,
            subcategory=categorization.subcategory,
            date=tx_data.get("date", datetime.now(timezone.utc).date()),
            authorized_date=tx_data.get("authorized_date"),
            pending=tx_data.get("pending", False),
            transaction_type=tx_type,
            payment_channel=tx_data.get("payment_channel"),
            location=tx_data.get("location"),
            metadata_=tx_data.get("metadata"),
        )
        
        self.session.add(transaction)
        return transaction

    def _build_category_keywords(self) -> Dict[str, List[str]]:
        return {
            "income": ["payroll", "salary", "deposit", "transfer in", "direct dep"],
            "shopping": ["amazon", "walmart", "target", "costco", "store", "shop"],
            "food": ["restaurant", "cafe", "coffee", "starbucks", "mcdonald", "pizza", "food"],
            "transport": ["uber", "lyft", "gas", "fuel", "parking", "transit"],
            "entertainment": ["netflix", "spotify", "movie", "theater", "gaming"],
            "utilities": ["electric", "water", "gas bill", "internet", "phone"],
            "healthcare": ["hospital", "pharmacy", "doctor", "medical", "dental"],
            "travel": ["airline", "hotel", "airbnb", "flight", "booking"],
            "finance": ["interest", "fee", "atm", "transfer", "payment"],
            "other": [],
        }

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class InstitutionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_supported(
        self,
        country: Optional[str] = None,
        product: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Institution]:
        query = select(Institution)
        
        if country:
            query = query.where(Institution.countries_supported.contains([country]))
        
        query = query.order_by(Institution.name).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        institutions = list(result.scalars().all())
        
        if not institutions:
            institutions = await self._seed_default_institutions()
        
        return institutions

    async def get_details(self, institution_id: str) -> Optional[Institution]:
        query = select(Institution).where(Institution.id == institution_id)
        result = await self.session.execute(query)
        institution = result.scalar_one_or_none()
        
        if not institution:
            institution = self._create_mock_institution(institution_id)
            self.session.add(institution)
            await self.session.flush()
        
        return institution

    async def search(
        self,
        query_text: str,
        country: Optional[str] = None,
        limit: int = 20,
    ) -> List[Institution]:
        query = select(Institution).where(
            Institution.name.ilike(f"%{query_text}%")
        )
        
        if country:
            query = query.where(Institution.countries_supported.contains([country]))
        
        query = query.limit(limit)
        
        result = await self.session.execute(query)
        institutions = list(result.scalars().all())
        
        if not institutions:
            mock_institution = self._create_mock_institution(
                f"inst_{query_text.lower().replace(' ', '_')}",
                name=query_text.title(),
            )
            institutions = [mock_institution]
        
        return institutions

    async def _seed_default_institutions(self) -> List[Institution]:
        default_institutions = [
            {"id": "ins_1", "name": "Bank of America", "countries": ["US"]},
            {"id": "ins_2", "name": "Chase", "countries": ["US"]},
            {"id": "ins_3", "name": "Wells Fargo", "countries": ["US"]},
            {"id": "ins_4", "name": "Citibank", "countries": ["US"]},
            {"id": "ins_5", "name": "Capital One", "countries": ["US"]},
        ]
        
        institutions = []
        for inst_data in default_institutions:
            institution = Institution(
                id=inst_data["id"],
                name=inst_data["name"],
                countries_supported=inst_data["countries"],
                credentials_type=CredentialsType.OAUTH,
                oauth_enabled=True,
                products=["transactions", "balance", "identity"],
            )
            self.session.add(institution)
            institutions.append(institution)
        
        await self.session.flush()
        return institutions

    def _create_mock_institution(
        self,
        institution_id: str,
        name: Optional[str] = None,
    ) -> Institution:
        return Institution(
            id=institution_id,
            name=name or f"Institution {institution_id}",
            countries_supported=["US"],
            credentials_type=CredentialsType.OAUTH,
            oauth_enabled=True,
            products=["transactions", "balance"],
        )


class SyncService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.account_service = LinkedAccountService(session)
        self.transaction_service = TransactionService(session)

    async def full_sync(
        self,
        connection_id: str,
    ) -> SyncResult:
        sync_status = await self._create_sync_status(connection_id, "full")
        
        try:
            connection_query = select(FinancialConnection).where(
                FinancialConnection.id == connection_id
            )
            connection_result = await self.session.execute(connection_query)
            connection = connection_result.scalar_one_or_none()
            
            if not connection:
                raise NotFoundError(f"Financial connection {connection_id} not found")
            
            accounts_data = await self._fetch_accounts_from_provider(connection)
            accounts_synced, accounts_failed = await self.account_service.sync_accounts(
                connection_id, accounts_data
            )
            
            accounts = await self.account_service.get_accounts(connection_id, limit=100)
            
            transactions_synced = 0
            transactions_failed = 0
            
            for account in accounts:
                tx_data = await self._fetch_transactions_from_provider(connection, account)
                synced, failed = await self.transaction_service.sync_transactions(
                    account.id, tx_data
                )
                transactions_synced += synced
                transactions_failed += failed
            
            sync_status.status = SyncStatusType.COMPLETED
            sync_status.items_synced = accounts_synced + transactions_synced
            sync_status.items_failed = accounts_failed + transactions_failed
            sync_status.completed_at = datetime.now(timezone.utc)
            
            connection.last_synced_at = datetime.now(timezone.utc)
            
        except Exception as e:
            sync_status.status = SyncStatusType.FAILED
            sync_status.error_code = "SYNC_FAILED"
            sync_status.error_message = str(e)
            sync_status.completed_at = datetime.now(timezone.utc)
        
        await self.session.flush()
        
        return SyncResult(
            sync_id=sync_status.id,
            status=sync_status.status.value,
            items_synced=sync_status.items_synced,
            items_failed=sync_status.items_failed,
            has_more=sync_status.has_more,
        )

    async def incremental_sync(
        self,
        connection_id: str,
        cursor: Optional[str] = None,
    ) -> SyncResult:
        sync_status = await self._create_sync_status(connection_id, "incremental")
        sync_status.cursor = cursor
        
        try:
            connection_query = select(FinancialConnection).where(
                FinancialConnection.id == connection_id
            )
            connection_result = await self.session.execute(connection_query)
            connection = connection_result.scalar_one_or_none()
            
            if not connection:
                raise NotFoundError(f"Financial connection {connection_id} not found")
            
            accounts = await self.account_service.get_accounts(connection_id, limit=100)
            
            total_synced = 0
            total_failed = 0
            
            for account in accounts:
                tx_data = await self._fetch_transactions_from_provider(
                    connection, account, cursor
                )
                synced, failed = await self.transaction_service.sync_transactions(
                    account.id, tx_data
                )
                total_synced += synced
                total_failed += failed
            
            sync_status.status = SyncStatusType.COMPLETED
            sync_status.items_synced = total_synced
            sync_status.items_failed = total_failed
            sync_status.completed_at = datetime.now(timezone.utc)
            
            connection.last_synced_at = datetime.now(timezone.utc)
            
        except Exception as e:
            sync_status.status = SyncStatusType.FAILED
            sync_status.error_code = "SYNC_FAILED"
            sync_status.error_message = str(e)
            sync_status.completed_at = datetime.now(timezone.utc)
        
        await self.session.flush()
        
        return SyncResult(
            sync_id=sync_status.id,
            status=sync_status.status.value,
            items_synced=sync_status.items_synced,
            items_failed=sync_status.items_failed,
            has_more=sync_status.has_more,
        )

    async def handle_webhook(
        self,
        webhook_data: Dict[str, Any],
        connection_type: str,
    ) -> Dict[str, Any]:
        webhook_type = webhook_data.get("webhook_type") or webhook_data.get("type")
        connection_id = webhook_data.get("connection_id") or webhook_data.get("item_id")
        
        if not connection_id:
            raise ValidationError("Missing connection_id in webhook")
        
        query = select(FinancialConnection).where(
            or_(
                FinancialConnection.id == connection_id,
                FinancialConnection.external_connection_id == connection_id,
            )
        )
        result = await self.session.execute(query)
        connection = result.scalar_one_or_none()
        
        if not connection:
            raise NotFoundError(f"Connection {connection_id} not found")
        
        result = {
            "connection_id": connection.id,
            "webhook_type": webhook_type,
            "processed": True,
        }
        
        if webhook_type in ["TRANSACTIONS_UPDATE", "transactions"]:
            await self.incremental_sync(connection.id)
            result["action"] = "sync_triggered"
        elif webhook_type in ["ITEM_STATUS_CHANGE", "connection_status"]:
            new_status = webhook_data.get("new_status", "active")
            if new_status == "disconnected":
                connection.status = ConnectionStatus.DISCONNECTED
            result["action"] = "status_updated"
        
        await self.session.flush()
        return result

    async def get_sync_status(self, connection_id: str) -> Optional[SyncStatus]:
        query = select(SyncStatus).where(
            SyncStatus.connection_id == connection_id
        ).order_by(SyncStatus.created_at.desc())
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _create_sync_status(
        self,
        connection_id: str,
        sync_type: str,
    ) -> SyncStatus:
        sync_status = SyncStatus(
            id=self._generate_id("sync"),
            connection_id=connection_id,
            status=SyncStatusType.SYNCING,
            sync_type=sync_type,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(sync_status)
        await self.session.flush()
        return sync_status

    async def _fetch_accounts_from_provider(
        self,
        connection: FinancialConnection,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "id": f"acc_{secrets.token_hex(8)}",
                "type": "checking",
                "name": "Primary Checking",
                "mask": "1234",
                "balances": {
                    "available": 500000,
                    "current": 525000,
                },
                "currency": "USD",
            },
            {
                "id": f"acc_{secrets.token_hex(8)}",
                "type": "savings",
                "name": "Savings Account",
                "mask": "5678",
                "balances": {
                    "available": 1000000,
                    "current": 1000000,
                },
                "currency": "USD",
            },
        ]

    async def _fetch_transactions_from_provider(
        self,
        connection: FinancialConnection,
        account: LinkedAccount,
        cursor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        transactions = []
        for i in range(10):
            tx_date = datetime.now(timezone.utc).date() - timedelta(days=i)
            transactions.append({
                "id": f"tx_{secrets.token_hex(8)}",
                "amount": secrets.randbelow(10000) - 5000,
                "description": f"Transaction {i + 1}",
                "date": tx_date,
                "pending": i == 0,
                "currency": "USD",
            })
        return transactions

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class SubscriptionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def subscribe(
        self,
        connection_id: str,
        account_id: str,
        webhook_url: str,
        event_types: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConnectionSubscription:
        secret = secrets.token_hex(32)
        
        subscription = ConnectionSubscription(
            id=self._generate_id("sub"),
            connection_id=connection_id,
            account_id=account_id,
            webhook_url=webhook_url,
            event_types=event_types,
            secret=secret,
            status="active",
            metadata_=metadata or {},
        )
        
        self.session.add(subscription)
        await self.session.flush()
        
        return subscription

    async def notify_update(
        self,
        connection_id: str,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        query = select(ConnectionSubscription).where(
            and_(
                ConnectionSubscription.connection_id == connection_id,
                ConnectionSubscription.status == "active",
                or_(
                    ConnectionSubscription.event_types.contains([event_type]),
                    ConnectionSubscription.event_types.contains(["*"]),
                ),
            )
        )
        
        result = await self.session.execute(query)
        subscriptions = list(result.scalars().all())
        
        notifications = []
        
        for sub in subscriptions:
            try:
                notification = {
                    "subscription_id": sub.id,
                    "event_type": event_type,
                    "webhook_url": sub.webhook_url,
                    "sent": True,
                }
                
                payload = {
                    "id": self._generate_id("evt"),
                    "type": event_type,
                    "data": event_data,
                    "connection_id": connection_id,
                    "timestamp": int(datetime.now(timezone.utc).timestamp()),
                }
                
                signature = self._generate_webhook_signature(payload, sub.secret)
                payload["signature"] = signature
                
                sub.last_triggered_at = datetime.now(timezone.utc)
                sub.failure_count = 0
                
                notifications.append(notification)
                
            except Exception as e:
                sub.failure_count += 1
                if sub.failure_count >= 5:
                    sub.status = "disabled"
                
                notifications.append({
                    "subscription_id": sub.id,
                    "event_type": event_type,
                    "sent": False,
                    "error": str(e),
                })
        
        await self.session.flush()
        return notifications

    async def unsubscribe(
        self,
        connection_id: str,
        account_id: Optional[str] = None,
    ) -> bool:
        stmt = delete(ConnectionSubscription).where(
            ConnectionSubscription.connection_id == connection_id
        )
        
        if account_id:
            stmt = stmt.where(ConnectionSubscription.account_id == account_id)
        
        result = await self.session.execute(stmt)
        await self.session.flush()
        
        return result.rowcount > 0

    async def list_subscriptions(
        self,
        connection_id: str,
    ) -> List[ConnectionSubscription]:
        query = select(ConnectionSubscription).where(
            ConnectionSubscription.connection_id == connection_id
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _generate_webhook_signature(
        self,
        payload: Dict[str, Any],
        secret: str,
    ) -> str:
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            secret.encode(),
            payload_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={signature}"

    def _generate_id(self, prefix: str) -> str:
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class TokenRefreshService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def refresh_oauth(
        self,
        connection_id: str,
    ) -> Dict[str, Any]:
        query = select(FinancialConnection).where(
            FinancialConnection.id == connection_id
        )
        result = await self.session.execute(query)
        connection = result.scalar_one_or_none()
        
        if not connection:
            raise NotFoundError(f"Financial connection {connection_id} not found")
        
        token_query = select(RefreshToken).where(
            and_(
                RefreshToken.connection_id == connection_id,
                RefreshToken.is_valid == True,
            )
        ).order_by(RefreshToken.created_at.desc())
        token_result = await self.session.execute(token_query)
        token_record = token_result.scalar_one_or_none()
        
        if not token_record:
            connection.status = ConnectionStatus.EXPIRED
            await self.session.flush()
            return {
                "success": False,
                "error": "No valid refresh token found",
            }
        
        access_token = self._decrypt_token(token_record.access_token_encrypted)
        refresh_token = None
        if token_record.refresh_token_encrypted:
            refresh_token = self._decrypt_token(token_record.refresh_token_encrypted)
        
        new_access_token = f"access_{secrets.token_hex(16)}"
        new_refresh_token = f"refresh_{secrets.token_hex(16)}"
        
        encrypted_new_access = self._encrypt_token(new_access_token)
        encrypted_new_refresh = self._encrypt_token(new_refresh_token)
        
        token_record.access_token_encrypted = encrypted_new_access
        token_record.refresh_token_encrypted = encrypted_new_refresh
        token_record.last_used_at = datetime.now(timezone.utc)
        
        connection.status = ConnectionStatus.ACTIVE
        connection.error_code = None
        connection.error_message = None
        
        await self.session.flush()
        
        return {
            "success": True,
            "connection_id": connection_id,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def validate_token(
        self,
        connection_id: str,
    ) -> Dict[str, Any]:
        query = select(FinancialConnection).where(
            FinancialConnection.id == connection_id
        )
        result = await self.session.execute(query)
        connection = result.scalar_one_or_none()
        
        if not connection:
            raise NotFoundError(f"Financial connection {connection_id} not found")
        
        token_query = select(RefreshToken).where(
            and_(
                RefreshToken.connection_id == connection_id,
                RefreshToken.is_valid == True,
            )
        ).order_by(RefreshToken.created_at.desc())
        token_result = await self.session.execute(token_query)
        token_record = token_result.scalar_one_or_none()
        
        if not token_record:
            return {
                "valid": False,
                "reason": "No valid token found",
            }
        
        is_expired = False
        if token_record.expires_at:
            if datetime.now(timezone.utc) > token_record.expires_at:
                is_expired = True
        
        return {
            "valid": not is_expired,
            "expires_at": token_record.expires_at.isoformat() if token_record.expires_at else None,
            "last_used_at": token_record.last_used_at.isoformat() if token_record.last_used_at else None,
        }

    async def revoke_token(
        self,
        connection_id: str,
    ) -> bool:
        stmt = update(RefreshToken).where(
            RefreshToken.connection_id == connection_id
        ).values(is_valid=False)
        
        result = await self.session.execute(stmt)
        await self.session.flush()
        
        return result.rowcount > 0

    def _encrypt_token(self, token: str) -> str:
        if not token:
            return ""
        return encrypt_data(token, ENCRYPTION_KEY)

    def _decrypt_token(self, encrypted: str) -> str:
        if not encrypted:
            return ""
        return decrypt_data(encrypted, ENCRYPTION_KEY)


class PlaidProvider:
    async def create_link_token(
        self,
        session_id: str,
        products: List[str],
        institution_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        link_token = f"link-sandbox-{session_id}"
        oauth_url = f"https://cdn.plaid.com/link/v2/stable/link.html?token={link_token}"
        return link_token, oauth_url

    async def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        return {
            "connection_id": f"item_{secrets.token_hex(16)}",
            "access_token": f"access-sandbox-{secrets.token_hex(16)}",
            "refresh_token": f"refresh-sandbox-{secrets.token_hex(16)}",
        }

    async def disconnect(self, connection_id: str) -> bool:
        return True

    async def refresh_access_token(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "access_token": f"access-sandbox-{secrets.token_hex(16)}",
            "refresh_token": f"refresh-sandbox-{secrets.token_hex(16)}",
        }


class MXProvider:
    async def create_link_token(
        self,
        session_id: str,
        products: List[str],
        institution_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        link_token = f"mx-link-{session_id}"
        oauth_url = f"https://int-widgets.moneydesktop.com/md/connect/{session_id}"
        return link_token, oauth_url

    async def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        return {
            "connection_id": f"member_{secrets.token_hex(16)}",
            "access_token": f"mx-access-{secrets.token_hex(16)}",
            "refresh_token": f"mx-refresh-{secrets.token_hex(16)}",
        }

    async def disconnect(self, connection_id: str) -> bool:
        return True

    async def refresh_access_token(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "access_token": f"mx-access-{secrets.token_hex(16)}",
            "refresh_token": f"mx-refresh-{secrets.token_hex(16)}",
        }


class YodleeProvider:
    async def create_link_token(
        self,
        session_id: str,
        products: List[str],
        institution_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        link_token = f"yodlee-token-{session_id}"
        oauth_url = f"https://yodlee.com/fastlink/{session_id}"
        return link_token, oauth_url

    async def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        return {
            "connection_id": f"provider_account_{secrets.token_hex(16)}",
            "access_token": f"yodlee-access-{secrets.token_hex(16)}",
            "refresh_token": f"yodlee-refresh-{secrets.token_hex(16)}",
        }

    async def disconnect(self, connection_id: str) -> bool:
        return True

    async def refresh_access_token(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "access_token": f"yodlee-access-{secrets.token_hex(16)}",
            "refresh_token": f"yodlee-refresh-{secrets.token_hex(16)}",
        }


class FinicityProvider:
    async def create_link_token(
        self,
        session_id: str,
        products: List[str],
        institution_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        link_token = f"finicity-link-{session_id}"
        oauth_url = f"https://connect.finicity.com/{session_id}"
        return link_token, oauth_url

    async def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        return {
            "connection_id": f"customer_{secrets.token_hex(16)}",
            "access_token": f"finicity-access-{secrets.token_hex(16)}",
            "refresh_token": f"finicity-refresh-{secrets.token_hex(16)}",
        }

    async def disconnect(self, connection_id: str) -> bool:
        return True

    async def refresh_access_token(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "access_token": f"finicity-access-{secrets.token_hex(16)}",
            "refresh_token": f"finicity-refresh-{secrets.token_hex(16)}",
        }


class TellerProvider:
    async def create_link_token(
        self,
        session_id: str,
        products: List[str],
        institution_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        link_token = f"teller-token-{session_id}"
        oauth_url = f"https://teller.io/connect/{session_id}"
        return link_token, oauth_url

    async def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        return {
            "connection_id": f"enrollment_{secrets.token_hex(16)}",
            "access_token": f"teller-access-{secrets.token_hex(16)}",
            "refresh_token": f"teller-refresh-{secrets.token_hex(16)}",
        }

    async def disconnect(self, connection_id: str) -> bool:
        return True

    async def refresh_access_token(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "access_token": f"teller-access-{secrets.token_hex(16)}",
            "refresh_token": f"teller-refresh-{secrets.token_hex(16)}",
        }
