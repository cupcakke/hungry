from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, validator

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.models.address import Address
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.backend.domain.issuing import (
    CardholderStatus, CardholderType, CardType, IssuingCardStatus,
    AuthorizationStatus, SpendingLimitInterval, IssuingDisputeStatus,
    IssuingDisputeReason, AuthorizationMethod,
)

router = APIRouter()


class AddressRequest(BaseModel):
    line1: str = Field(..., max_length=100, description="Address line 1")
    line2: Optional[str] = Field(default=None, max_length=100, description="Address line 2")
    city: str = Field(..., max_length=50, description="City")
    state: Optional[str] = Field(default=None, max_length=50, description="State/Province")
    postal_code: str = Field(..., max_length=20, description="Postal/ZIP code")
    country: str = Field(..., min_length=2, max_length=2, description="Two-letter country code")


class IndividualRequest(BaseModel):
    first_name: str = Field(..., max_length=50)
    last_name: str = Field(..., max_length=50)
    dob: Optional[Dict[str, Any]] = Field(default=None)
    card_issuing: Optional[Dict[str, Any]] = Field(default=None)


class CompanyRequest(BaseModel):
    name: str = Field(..., max_length=100)
    tax_id: Optional[str] = Field(default=None, max_length=50)


class SpendingLimitRequest(BaseModel):
    amount: int = Field(..., ge=0, description="Amount in minor units")
    interval: SpendingLimitInterval = Field(..., description="Spending interval")
    categories: Optional[List[str]] = Field(default=None, description="Merchant categories")


class CardholderCreateRequest(BaseModel):
    type: CardholderType = Field(..., description="Cardholder type")
    name: str = Field(..., max_length=100, description="Cardholder name")
    email: Optional[EmailStr] = Field(default=None, description="Email address")
    phone_number: Optional[str] = Field(default=None, max_length=20, description="Phone number")
    billing: AddressRequest = Field(..., description="Billing address")
    individual: Optional[IndividualRequest] = Field(default=None, description="Individual details")
    company: Optional[CompanyRequest] = Field(default=None, description="Company details")
    spending_controls: Optional[Dict[str, Any]] = Field(default=None, description="Spending controls")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")

    @validator("individual", "company", pre=True, always=True)
    def validate_type_details(cls, v, values):
        if "type" not in values:
            return v
        cardholder_type = values["type"]
        if cardholder_type == CardholderType.INDIVIDUAL and not v.get("individual"):
            if "individual" in values:
                pass
        return v


class CardholderVerificationRequest(BaseModel):
    verification_type: str = Field(..., description="Type of verification")
    document_type: Optional[str] = Field(default=None, description="Document type")
    document_front: Optional[str] = Field(default=None, description="Document front file ID")
    document_back: Optional[str] = Field(default=None, description="Document back file ID")


class CardCreateRequest(BaseModel):
    cardholder: str = Field(..., description="Cardholder ID")
    type: CardType = Field(..., description="Card type (virtual/physical)")
    currency: str = Field(..., min_length=3, max_length=3, description="Currency code")
    status: Optional[str] = Field(default="inactive", description="Initial status")
    spending_controls: Optional[Dict[str, Any]] = Field(default=None, description="Spending controls")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")


class AuthorizationCreateRequest(BaseModel):
    card: str = Field(..., description="Card ID")
    amount: int = Field(..., ge=1, description="Amount in minor units")
    currency: str = Field(..., min_length=3, max_length=3, description="Currency code")
    merchant_data: Dict[str, Any] = Field(..., description="Merchant information")
    authorization_method: AuthorizationMethod = Field(..., description="Authorization method")
    verification_data: Optional[Dict[str, Any]] = Field(default=None, description="Verification data")


class AuthorizationApproveRequest(BaseModel):
    amount: Optional[int] = Field(default=None, ge=0, description="Approved amount")


class AuthorizationDeclineRequest(BaseModel):
    reason: str = Field(..., max_length=100, description="Decline reason")


class DisputeCreateRequest(BaseModel):
    transaction: str = Field(..., description="Transaction ID")
    amount: int = Field(..., ge=1, description="Dispute amount in minor units")
    reason: IssuingDisputeReason = Field(..., description="Dispute reason")
    evidence: Optional[Dict[str, Any]] = Field(default=None, description="Evidence")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")


class CardholderResponse(BaseModel):
    id: str
    object: str = "issuing.cardholder"
    type: str
    status: str
    name: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    billing: Optional[Dict[str, Any]] = None
    company: Optional[Dict[str, Any]] = None
    individual: Optional[Dict[str, Any]] = None
    requirements: Optional[Dict[str, Any]] = None
    spending_controls: Optional[Dict[str, Any]] = None
    metadata: Dict[str, str] = {}
    created: int
    livemode: bool = False

    class Config:
        from_attributes = True


class CardResponse(BaseModel):
    id: str
    object: str = "issuing.card"
    cardholder: str
    type: str
    status: str
    brand: str
    funding: str
    last4: str
    exp_month: int
    exp_year: int
    currency: str
    spending_controls: Optional[Dict[str, Any]] = None
    metadata: Dict[str, str] = {}
    created: int
    livemode: bool = False

    class Config:
        from_attributes = True


class CardDetailsResponse(BaseModel):
    id: str
    object: str = "issuing.card"
    cardholder: str
    type: str
    status: str
    brand: str
    number: str
    cvc: str
    exp_month: int
    exp_year: int
    currency: str
    last4: str
    metadata: Dict[str, str] = {}
    created: int

    class Config:
        from_attributes = True


class AuthorizationResponse(BaseModel):
    id: str
    object: str = "issuing.authorization"
    card: str
    cardholder: str
    amount: int
    currency: str
    merchant_data: Optional[Dict[str, Any]] = None
    status: str
    approved: bool
    approved_amount: Optional[int] = None
    decline_reason: Optional[str] = None
    authorization_method: str
    created: int
    livemode: bool = False

    class Config:
        from_attributes = True


class TransactionResponse(BaseModel):
    id: str
    object: str = "issuing.transaction"
    card: str
    cardholder: str
    authorization: str
    amount: int
    currency: str
    merchant_data: Optional[Dict[str, Any]] = None
    merchant_amount: int
    merchant_currency: str
    type: str
    created: int
    livemode: bool = False

    class Config:
        from_attributes = True


class DisputeResponse(BaseModel):
    id: str
    object: str = "issuing.dispute"
    transaction: str
    amount: int
    currency: str
    reason: str
    status: str
    evidence: Optional[Dict[str, Any]] = None
    outcome: Optional[Dict[str, Any]] = None
    metadata: Dict[str, str] = {}
    created: int
    livemode: bool = False

    class Config:
        from_attributes = True


def cardholder_to_response(cardholder: Any) -> CardholderResponse:
    return CardholderResponse(
        id=cardholder.id,
        type=cardholder.type,
        status=cardholder.status,
        name=cardholder.name,
        email=cardholder.email,
        phone_number=cardholder.phone_number,
        billing={
            "address": {
                "line1": cardholder.billing_address_line1,
                "line2": cardholder.billing_address_line2,
                "city": cardholder.billing_address_city,
                "state": cardholder.billing_address_state,
                "postal_code": cardholder.billing_address_postal_code,
                "country": cardholder.billing_address_country,
            }
        },
        company=cardholder.company,
        individual=cardholder.individual,
        requirements=cardholder.requirements,
        spending_controls=cardholder.spending_controls,
        metadata=cardholder.metadata_ or {},
        created=cardholder.created,
        livemode=cardholder.livemode,
    )


def card_to_response(card: Any) -> CardResponse:
    return CardResponse(
        id=card.id,
        cardholder=card.cardholder_id,
        type=card.type,
        status=card.status,
        brand=card.brand,
        funding="credit" if card.type == "virtual" else "debit",
        last4=card.last4,
        exp_month=card.exp_month,
        exp_year=card.exp_year,
        currency=card.currency,
        spending_controls=card.spending_controls,
        metadata=card.metadata_ or {},
        created=card.created,
        livemode=card.livemode,
    )


def authorization_to_response(auth: Any) -> AuthorizationResponse:
    return AuthorizationResponse(
        id=auth.id,
        card=auth.card_id,
        cardholder=auth.cardholder_id,
        amount=auth.amount,
        currency=auth.currency,
        merchant_data=auth.merchant_data,
        status=auth.status,
        approved=auth.approved,
        approved_amount=auth.amount if auth.approved else None,
        decline_reason=None if auth.approved else "declined",
        authorization_method=auth.authorization_method,
        created=auth.created,
        livemode=auth.livemode,
    )


def transaction_to_response(txn: Any) -> TransactionResponse:
    return TransactionResponse(
        id=txn.id,
        card=txn.card_id,
        cardholder=txn.cardholder_id,
        authorization=txn.authorization_id,
        amount=txn.amount,
        currency=txn.currency,
        merchant_data=txn.merchant_data,
        merchant_amount=txn.merchant_amount,
        merchant_currency=txn.merchant_currency,
        type=txn.type,
        created=txn.created,
        livemode=txn.livemode,
    )


def dispute_to_response(dispute: Any) -> DisputeResponse:
    return DisputeResponse(
        id=dispute.id,
        transaction=dispute.transaction_id,
        amount=dispute.amount,
        currency=dispute.currency,
        reason=dispute.reason,
        status=dispute.status,
        evidence=dispute.evidence,
        outcome=dispute.outcome,
        metadata=dispute.metadata_ or {},
        created=dispute.created,
        livemode=dispute.livemode,
    )


@router.post("/cardholders", response_model=CardholderResponse, status_code=status.HTTP_201_CREATED)
async def create_cardholder(
    request: Request,
    data: CardholderCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import CardholderService
    account_id = getattr(request.state, "account_id", None)
    service = CardholderService(session)
    cardholder = await service.create_cardholder(
        account_id=account_id,
        cardholder_type=data.type.value,
        name=data.name,
        email=data.email.lower() if data.email else None,
        phone_number=data.phone_number,
        billing_address={
            "line1": data.billing.line1,
            "line2": data.billing.line2,
            "city": data.billing.city,
            "state": data.billing.state,
            "postal_code": data.billing.postal_code,
            "country": data.billing.country,
        },
        individual=data.individual.dict() if data.individual else None,
        company=data.company.dict() if data.company else None,
        spending_controls=data.spending_controls,
        metadata=data.metadata,
    )
    await session.commit()
    return cardholder_to_response(cardholder)


@router.get("/cardholders", response_model=PaginatedResponse[CardholderResponse])
async def list_cardholders(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import BaseRepository
    from payment_platform.backend.domain.models import Cardholder
    account_id = getattr(request.state, "account_id", None)
    repo = BaseRepository(session, Cardholder)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if status:
        filters["status"] = status
    if type:
        filters["type"] = type
    if email:
        filters["email"] = email.lower()
    cardholders = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(cardholders) > limit
    if has_more:
        cardholders = cardholders[:limit]
    return PaginatedResponse(
        data=[cardholder_to_response(c) for c in cardholders],
        has_more=has_more,
    )


@router.get("/cardholders/{cardholder_id}", response_model=CardholderResponse)
async def get_cardholder(
    cardholder_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import BaseRepository
    from payment_platform.backend.domain.models import Cardholder
    repo = BaseRepository(session, Cardholder)
    cardholder = await repo.get_by_id(cardholder_id)
    if not cardholder:
        raise NotFoundError(f"Cardholder {cardholder_id} not found")
    return cardholder_to_response(cardholder)


@router.post("/cardholders/{cardholder_id}/verify", response_model=Dict[str, Any])
async def verify_cardholder(
    cardholder_id: str,
    request: Request,
    data: CardholderVerificationRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import CardholderService
    account_id = getattr(request.state, "account_id", None)
    service = CardholderService(session)
    verification = await service.verify_cardholder(
        cardholder_id=cardholder_id,
        account_id=account_id,
        verification_type=data.verification_type,
        document_type=data.document_type,
        document_front_id=data.document_front,
        document_back_id=data.document_back,
    )
    await session.commit()
    return {
        "id": verification.id,
        "object": "issuing.verification",
        "cardholder": cardholder_id,
        "status": verification.status,
        "verification_type": verification.verification_type,
        "created": verification.created,
    }


@router.post("/cards", response_model=CardResponse, status_code=status.HTTP_201_CREATED)
async def create_card(
    request: Request,
    data: CardCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import CardService
    account_id = getattr(request.state, "account_id", None)
    service = CardService(session)
    card = await service.create_card(
        account_id=account_id,
        cardholder_id=data.cardholder,
        card_type=data.type.value,
        currency=data.currency,
        initial_status=data.status,
        spending_controls=data.spending_controls,
        metadata=data.metadata,
    )
    await session.commit()
    return card_to_response(card)


@router.get("/cards", response_model=PaginatedResponse[CardResponse])
async def list_cards(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    cardholder: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import BaseRepository
    from payment_platform.backend.domain.models import IssuingCard
    account_id = getattr(request.state, "account_id", None)
    repo = BaseRepository(session, IssuingCard)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if cardholder:
        filters["cardholder_id"] = cardholder
    if status:
        filters["status"] = status
    if type:
        filters["type"] = type
    cards = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(cards) > limit
    if has_more:
        cards = cards[:limit]
    return PaginatedResponse(
        data=[card_to_response(c) for c in cards],
        has_more=has_more,
    )


@router.get("/cards/{card_id}", response_model=CardResponse)
async def get_card(
    card_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import BaseRepository
    from payment_platform.backend.domain.models import IssuingCard
    repo = BaseRepository(session, IssuingCard)
    card = await repo.get_by_id(card_id)
    if not card:
        raise NotFoundError(f"Card {card_id} not found")
    return card_to_response(card)


@router.post("/cards/{card_id}/activate", response_model=CardResponse)
async def activate_card(
    card_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import CardService
    service = CardService(session)
    card = await service.activate_card(card_id)
    await session.commit()
    return card_to_response(card)


@router.post("/cards/{card_id}/deactivate", response_model=CardResponse)
async def deactivate_card(
    card_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import CardService
    service = CardService(session)
    card = await service.deactivate_card(card_id)
    await session.commit()
    return card_to_response(card)


@router.get("/cards/{card_id}/details", response_model=CardDetailsResponse)
async def get_card_details(
    card_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import CardService
    service = CardService(session)
    card, pan, cvc = await service.get_card_details(card_id)
    return CardDetailsResponse(
        id=card.id,
        cardholder=card.cardholder_id,
        type=card.type,
        status=card.status,
        brand=card.brand,
        number=pan,
        cvc=cvc,
        exp_month=card.exp_month,
        exp_year=card.exp_year,
        currency=card.currency,
        last4=card.last4,
        metadata=card.metadata_ or {},
        created=card.created,
    )


@router.post("/authorizations", response_model=AuthorizationResponse, status_code=status.HTTP_201_CREATED)
async def create_authorization(
    request: Request,
    data: AuthorizationCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import AuthorizationService
    account_id = getattr(request.state, "account_id", None)
    service = AuthorizationService(session)
    authorization = await service.create_authorization(
        account_id=account_id,
        card_id=data.card,
        amount=data.amount,
        currency=data.currency,
        merchant_data=data.merchant_data,
        authorization_method=data.authorization_method.value,
        verification_data=data.verification_data,
    )
    await session.commit()
    return authorization_to_response(authorization)


@router.post("/authorizations/{authorization_id}/approve", response_model=AuthorizationResponse)
async def approve_authorization(
    authorization_id: str,
    request: Request,
    data: AuthorizationApproveRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import AuthorizationService
    service = AuthorizationService(session)
    authorization = await service.approve_authorization(
        authorization_id=authorization_id,
        approved_amount=data.amount,
    )
    await session.commit()
    return authorization_to_response(authorization)


@router.post("/authorizations/{authorization_id}/decline", response_model=AuthorizationResponse)
async def decline_authorization(
    authorization_id: str,
    request: Request,
    data: AuthorizationDeclineRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import AuthorizationService
    service = AuthorizationService(session)
    authorization = await service.decline_authorization(
        authorization_id=authorization_id,
        decline_reason=data.reason,
    )
    await session.commit()
    return authorization_to_response(authorization)


@router.get("/transactions", response_model=PaginatedResponse[TransactionResponse])
async def list_transactions(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    card: Optional[str] = Query(default=None),
    cardholder: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import BaseRepository
    from payment_platform.backend.domain.models import IssuingTransaction
    account_id = getattr(request.state, "account_id", None)
    repo = BaseRepository(session, IssuingTransaction)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if card:
        filters["card_id"] = card
    if cardholder:
        filters["cardholder_id"] = cardholder
    transactions = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(transactions) > limit
    if has_more:
        transactions = transactions[:limit]
    return PaginatedResponse(
        data=[transaction_to_response(t) for t in transactions],
        has_more=has_more,
    )


@router.get("/disputes", response_model=PaginatedResponse[DisputeResponse])
async def list_disputes(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    transaction: Optional[str] = Query(default=None),
    session = Depends(get_session),
):
    from payment_platform.backend.infrastructure.persistence import BaseRepository
    from payment_platform.backend.domain.issuing import IssuingDispute
    account_id = getattr(request.state, "account_id", None)
    repo = BaseRepository(session, IssuingDispute)
    filters = {}
    if account_id:
        filters["account_id"] = account_id
    if status:
        filters["status"] = status
    if transaction:
        filters["transaction_id"] = transaction
    disputes = await repo.list(
        filters=filters,
        limit=limit + 1,
        order_by="created_at",
        order_desc=True,
    )
    has_more = len(disputes) > limit
    if has_more:
        disputes = disputes[:limit]
    return PaginatedResponse(
        data=[dispute_to_response(d) for d in disputes],
        has_more=has_more,
    )


@router.post("/disputes", response_model=DisputeResponse, status_code=status.HTTP_201_CREATED)
async def create_dispute(
    request: Request,
    data: DisputeCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.issuing_service import DisputeService
    account_id = getattr(request.state, "account_id", None)
    service = DisputeService(session)
    dispute = await service.create_dispute(
        account_id=account_id,
        transaction_id=data.transaction,
        amount=data.amount,
        reason=data.reason.value,
        evidence=data.evidence,
        metadata=data.metadata,
    )
    await session.commit()
    return dispute_to_response(dispute)
