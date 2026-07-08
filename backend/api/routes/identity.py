from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
import base64

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, IdentityVerificationError

router = APIRouter()


class VerificationSessionCreateRequest(BaseModel):
    type: str = Field(..., description="Verification type: document, address, or identity")
    account_id: Optional[str] = Field(default=None, description="Account ID to verify")
    return_url: Optional[str] = Field(default=None, description="URL to redirect after verification")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class VerificationSessionResponse(BaseModel):
    id: str
    object: str = "identity.verification_session"
    account_id: Optional[str] = None
    type: str
    status: str
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    verified_at: Optional[int] = None
    expires_at: Optional[int] = None
    created: int
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None
    url: Optional[str] = None


class VerificationSessionCancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Cancellation reason")


class VerificationSessionRedactRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Redaction reason")


class DocumentVerificationUploadRequest(BaseModel):
    session_id: str = Field(..., description="Verification session ID")
    document_type: str = Field(..., description="Document type: passport, driver_license, id_card")
    country: str = Field(..., min_length=2, max_length=3, description="ISO country code")
    front_image: Optional[str] = Field(default=None, description="Base64 encoded front image")
    back_image: Optional[str] = Field(default=None, description="Base64 encoded back image")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class DocumentVerificationResponse(BaseModel):
    id: str
    object: str = "identity.document_verification"
    session_id: str
    document_type: str
    country: str
    status: str
    extracted_data: Optional[Dict[str, Any]] = None
    verification_result: Optional[Dict[str, Any]] = None
    ocr_confidence: Optional[float] = None
    document_number_masked: Optional[str] = None
    holder_name: Optional[str] = None
    expiry_date: Optional[str] = None
    created: int
    processed_at: Optional[int] = None
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class BiometricVerificationSubmitRequest(BaseModel):
    session_id: str = Field(..., description="Verification session ID")
    type: str = Field(..., description="Biometric type: face or selfie")
    image: str = Field(..., description="Base64 encoded image")
    challenge_data: Optional[Dict[str, Any]] = Field(default=None, description="Liveness challenge data")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class BiometricVerificationResponse(BaseModel):
    id: str
    object: str = "identity.biometric_verification"
    session_id: str
    type: str
    status: str
    confidence_score: Optional[float] = None
    liveness_result: Optional[Dict[str, Any]] = None
    face_match_result: Optional[Dict[str, Any]] = None
    verification_result: Optional[Dict[str, Any]] = None
    created: int
    processed_at: Optional[int] = None
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class AddressVerificationSubmitRequest(BaseModel):
    session_id: str = Field(..., description="Verification session ID")
    verification_method: str = Field(..., description="Method: document, utility_bill, bank_statement, geolocation")
    address: Dict[str, Any] = Field(..., description="Address data")
    evidence_document: Optional[str] = Field(default=None, description="Base64 encoded evidence document")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class AddressVerificationResponse(BaseModel):
    id: str
    object: str = "identity.address_verification"
    session_id: str
    address_data: Optional[Dict[str, Any]] = None
    verification_method: str
    status: str
    formatted_address: Optional[str] = None
    country_code: Optional[str] = None
    postal_code: Optional[str] = None
    geocode_result: Optional[Dict[str, Any]] = None
    verification_result: Optional[Dict[str, Any]] = None
    created: int
    processed_at: Optional[int] = None
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class VerificationReportResponse(BaseModel):
    id: str
    object: str = "identity.verification_report"
    session_id: str
    overall_status: str
    checks_passed: int
    checks_failed: int
    checks_pending: int
    risk_score: Optional[float] = None
    risk_factors: Optional[List[str]] = None
    failure_reasons: Optional[List[str]] = None
    document_check: Optional[Dict[str, Any]] = None
    biometric_check: Optional[Dict[str, Any]] = None
    address_check: Optional[Dict[str, Any]] = None
    sanctions_check: Optional[Dict[str, Any]] = None
    pep_check: Optional[Dict[str, Any]] = None
    aml_check: Optional[Dict[str, Any]] = None
    identity_document: Optional[Dict[str, Any]] = None
    created: int
    updated: Optional[int] = None
    livemode: bool = False


def _get_account_id(request: Request) -> Optional[str]:
    return getattr(request.state, "account_id", None)


def _generate_id(prefix: str) -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{prefix}_{random_part}"


def _get_timestamp() -> int:
    import time
    return int(time.time())


@router.post("/verification_sessions", response_model=VerificationSessionResponse, status_code=201)
async def create_verification_session(
    request: Request,
    data: VerificationSessionCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.identity import (
        VerificationSession, VerificationSessionType, VerificationSessionStatus
    )
    
    session_type = VerificationSessionType.DOCUMENT
    if data.type == "address":
        session_type = VerificationSessionType.ADDRESS
    elif data.type == "identity":
        session_type = VerificationSessionType.IDENTITY
    
    vs_id = _generate_id("vs")
    timestamp = _get_timestamp()
    expires_at = timestamp + 86400 * 7
    
    verification_session = VerificationSession(
        id=vs_id,
        account_id=data.account_id,
        type=session_type,
        status=VerificationSessionStatus.PENDING,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500] if request.headers.get("user-agent") else None,
        expires_at=expires_at,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(verification_session)
    await session.flush()
    
    return VerificationSessionResponse(
        id=verification_session.id,
        account_id=verification_session.account_id,
        type=verification_session.type.value,
        status=verification_session.status.value,
        client_ip=verification_session.client_ip,
        user_agent=verification_session.user_agent,
        verified_at=verification_session.verified_at,
        expires_at=verification_session.expires_at,
        created=verification_session.created,
        url=f"https://verify.payment-platform.com/vs/{verification_session.id}",
        metadata=verification_session.metadata_,
    )


@router.get("/verification_sessions", response_model=PaginatedResponse[VerificationSessionResponse])
async def list_verification_sessions(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
    account_id: Optional[str] = None,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.identity import VerificationSession
    
    query = select(VerificationSession)
    
    if account_id:
        query = query.where(VerificationSession.account_id == account_id)
    if status:
        query = query.where(VerificationSession.status == status)
    if type:
        query = query.where(VerificationSession.type == type)
    if starting_after:
        query = query.where(VerificationSession.id > starting_after)
    
    query = query.order_by(VerificationSession.created_at.desc()).limit(limit + 1)
    
    result = await session.execute(query)
    sessions = list(result.scalars().all())
    
    has_more = len(sessions) > limit
    if has_more:
        sessions = sessions[:limit]
    
    data = [
        VerificationSessionResponse(
            id=vs.id,
            account_id=vs.account_id,
            type=vs.type.value,
            status=vs.status.value,
            client_ip=vs.client_ip,
            user_agent=vs.user_agent,
            verified_at=vs.verified_at,
            expires_at=vs.expires_at,
            created=vs.created,
            metadata=vs.metadata_,
        )
        for vs in sessions
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/verification_sessions/{session_id}", response_model=VerificationSessionResponse)
async def get_verification_session(
    session_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.identity import VerificationSession
    
    query = select(VerificationSession).where(VerificationSession.id == session_id)
    result = await session.execute(query)
    vs = result.scalar_one_or_none()
    
    if not vs:
        raise NotFoundError(f"Verification session {session_id} not found")
    
    return VerificationSessionResponse(
        id=vs.id,
        account_id=vs.account_id,
        type=vs.type.value,
        status=vs.status.value,
        client_ip=vs.client_ip,
        user_agent=vs.user_agent,
        verified_at=vs.verified_at,
        expires_at=vs.expires_at,
        created=vs.created,
        metadata=vs.metadata_,
    )


@router.post("/verification_sessions/{session_id}/cancel", response_model=VerificationSessionResponse)
async def cancel_verification_session(
    session_id: str,
    request: Request,
    data: VerificationSessionCancelRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.identity import VerificationSession, VerificationSessionStatus
    
    query = select(VerificationSession).where(VerificationSession.id == session_id)
    result = await session.execute(query)
    vs = result.scalar_one_or_none()
    
    if not vs:
        raise NotFoundError(f"Verification session {session_id} not found")
    
    if vs.status not in [VerificationSessionStatus.PENDING, VerificationSessionStatus.REQUIRES_INPUT]:
        raise IdentityVerificationError(
            f"Cannot cancel session in {vs.status.value} status",
            verification_id=session_id,
        )
    
    vs.status = VerificationSessionStatus.CANCELED
    await session.flush()
    
    return VerificationSessionResponse(
        id=vs.id,
        account_id=vs.account_id,
        type=vs.type.value,
        status=vs.status.value,
        client_ip=vs.client_ip,
        user_agent=vs.user_agent,
        verified_at=vs.verified_at,
        expires_at=vs.expires_at,
        created=vs.created,
        metadata=vs.metadata_,
    )


@router.post("/verification_sessions/{session_id}/redact", response_model=VerificationSessionResponse)
async def redact_verification_session(
    session_id: str,
    request: Request,
    data: VerificationSessionRedactRequest,
    session = Depends(get_session),
):
    from sqlalchemy import select, update
    from payment_platform.backend.domain.identity import (
        VerificationSession, VerificationSessionStatus,
        DocumentVerification, BiometricVerification, AddressVerification,
        IdentityDocument,
    )
    
    query = select(VerificationSession).where(VerificationSession.id == session_id)
    result = await session.execute(query)
    vs = result.scalar_one_or_none()
    
    if not vs:
        raise NotFoundError(f"Verification session {session_id} not found")
    
    timestamp = _get_timestamp()
    vs.redacted_at = timestamp
    vs.client_ip = None
    vs.user_agent = None
    
    await session.execute(
        update(DocumentVerification)
        .where(DocumentVerification.session_id == session_id)
        .values(images=None, extracted_data=None, images_encrypted=False)
    )
    
    await session.execute(
        update(BiometricVerification)
        .where(BiometricVerification.session_id == session_id)
        .values(images=None, images_encrypted=False)
    )
    
    await session.execute(
        update(AddressVerification)
        .where(AddressVerification.session_id == session_id)
        .values(evidence_documents=None)
    )
    
    await session.execute(
        update(IdentityDocument)
        .where(IdentityDocument.verification_session_id == session_id)
        .values(document_number_masked=None, holder_name=None)
    )
    
    await session.flush()
    
    return VerificationSessionResponse(
        id=vs.id,
        account_id=vs.account_id,
        type=vs.type.value,
        status=vs.status.value,
        client_ip=vs.client_ip,
        user_agent=vs.user_agent,
        verified_at=vs.verified_at,
        expires_at=vs.expires_at,
        created=vs.created,
        metadata=vs.metadata_,
    )


@router.post("/document_verifications", response_model=DocumentVerificationResponse, status_code=201)
async def upload_document_verification(
    request: Request,
    data: DocumentVerificationUploadRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.identity import (
        VerificationSession, DocumentVerification, DocumentType,
        DocumentVerificationStatus, VerificationSessionStatus
    )
    from sqlalchemy import select
    
    vs_query = select(VerificationSession).where(VerificationSession.id == data.session_id)
    vs_result = await session.execute(vs_query)
    vs = vs_result.scalar_one_or_none()
    
    if not vs:
        raise NotFoundError(f"Verification session {data.session_id} not found")
    
    if vs.status == VerificationSessionStatus.EXPIRED:
        raise IdentityVerificationError(
            "Verification session has expired",
            verification_id=data.session_id,
        )
    
    document_type = DocumentType.PASSPORT
    if data.document_type == "driver_license":
        document_type = DocumentType.DRIVER_LICENSE
    elif data.document_type == "id_card":
        document_type = DocumentType.ID_CARD
    
    images = []
    if data.front_image:
        images.append(data.front_image[:100])
    if data.back_image:
        images.append(data.back_image[:100])
    
    dv_id = _generate_id("dv")
    timestamp = _get_timestamp()
    
    doc_verification = DocumentVerification(
        id=dv_id,
        session_id=data.session_id,
        document_type=document_type,
        country=data.country.upper(),
        images=images if images else None,
        images_encrypted=True,
        status=DocumentVerificationStatus.PENDING,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    vs.status = VerificationSessionStatus.PROCESSING
    session.add(doc_verification)
    await session.flush()
    
    return DocumentVerificationResponse(
        id=doc_verification.id,
        session_id=doc_verification.session_id,
        document_type=doc_verification.document_type.value,
        country=doc_verification.country,
        status=doc_verification.status.value,
        created=doc_verification.created,
        metadata=doc_verification.metadata_,
    )


@router.get("/document_verifications/{document_id}", response_model=DocumentVerificationResponse)
async def get_document_verification(
    document_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.identity import DocumentVerification
    
    query = select(DocumentVerification).where(DocumentVerification.id == document_id)
    result = await session.execute(query)
    dv = result.scalar_one_or_none()
    
    if not dv:
        raise NotFoundError(f"Document verification {document_id} not found")
    
    return DocumentVerificationResponse(
        id=dv.id,
        session_id=dv.session_id,
        document_type=dv.document_type.value,
        country=dv.country,
        status=dv.status.value,
        extracted_data=dv.extracted_data,
        verification_result=dv.verification_result,
        ocr_confidence=dv.ocr_confidence,
        document_number_masked=dv.document_number_masked,
        holder_name=dv.holder_name,
        expiry_date=dv.expiry_date,
        created=dv.created,
        processed_at=dv.processed_at,
        metadata=dv.metadata_,
    )


@router.post("/biometric_verifications", response_model=BiometricVerificationResponse, status_code=201)
async def submit_biometric_verification(
    request: Request,
    data: BiometricVerificationSubmitRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.identity import (
        VerificationSession, BiometricVerification, BiometricType,
        BiometricStatus, VerificationSessionStatus
    )
    from sqlalchemy import select
    
    vs_query = select(VerificationSession).where(VerificationSession.id == data.session_id)
    vs_result = await session.execute(vs_query)
    vs = vs_result.scalar_one_or_none()
    
    if not vs:
        raise NotFoundError(f"Verification session {data.session_id} not found")
    
    if vs.status == VerificationSessionStatus.EXPIRED:
        raise IdentityVerificationError(
            "Verification session has expired",
            verification_id=data.session_id,
        )
    
    biometric_type = BiometricType.FACE
    if data.type == "selfie":
        biometric_type = BiometricType.SELFIE
    
    bv_id = _generate_id("bv")
    timestamp = _get_timestamp()
    
    images = [data.image[:100]] if data.image else None
    
    biometric_verification = BiometricVerification(
        id=bv_id,
        session_id=data.session_id,
        type=biometric_type,
        images=images,
        images_encrypted=True,
        status=BiometricStatus.PENDING,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(biometric_verification)
    await session.flush()
    
    return BiometricVerificationResponse(
        id=biometric_verification.id,
        session_id=biometric_verification.session_id,
        type=biometric_verification.type.value,
        status=biometric_verification.status.value,
        created=biometric_verification.created,
        metadata=biometric_verification.metadata_,
    )


@router.get("/biometric_verifications/{biometric_id}", response_model=BiometricVerificationResponse)
async def get_biometric_verification(
    biometric_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.identity import BiometricVerification
    
    query = select(BiometricVerification).where(BiometricVerification.id == biometric_id)
    result = await session.execute(query)
    bv = result.scalar_one_or_none()
    
    if not bv:
        raise NotFoundError(f"Biometric verification {biometric_id} not found")
    
    return BiometricVerificationResponse(
        id=bv.id,
        session_id=bv.session_id,
        type=bv.type.value,
        status=bv.status.value,
        confidence_score=bv.confidence_score,
        liveness_result=bv.liveness_result,
        face_match_result=bv.face_match_result,
        verification_result=bv.verification_result,
        created=bv.created,
        processed_at=bv.processed_at,
        metadata=bv.metadata_,
    )


@router.post("/address_verifications", response_model=AddressVerificationResponse, status_code=201)
async def submit_address_verification(
    request: Request,
    data: AddressVerificationSubmitRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.domain.identity import (
        VerificationSession, AddressVerification, AddressVerificationMethod,
        AddressVerificationStatus, VerificationSessionStatus
    )
    from sqlalchemy import select
    
    vs_query = select(VerificationSession).where(VerificationSession.id == data.session_id)
    vs_result = await session.execute(vs_query)
    vs = vs_result.scalar_one_or_none()
    
    if not vs:
        raise NotFoundError(f"Verification session {data.session_id} not found")
    
    if vs.status == VerificationSessionStatus.EXPIRED:
        raise IdentityVerificationError(
            "Verification session has expired",
            verification_id=data.session_id,
        )
    
    verification_method = AddressVerificationMethod.DOCUMENT
    if data.verification_method == "utility_bill":
        verification_method = AddressVerificationMethod.UTILITY_BILL
    elif data.verification_method == "bank_statement":
        verification_method = AddressVerificationMethod.BANK_STATEMENT
    elif data.verification_method == "geolocation":
        verification_method = AddressVerificationMethod.GEOLOCATION
    
    av_id = _generate_id("av")
    timestamp = _get_timestamp()
    
    evidence_docs = [data.evidence_document[:100]] if data.evidence_document else None
    
    address_verification = AddressVerification(
        id=av_id,
        session_id=data.session_id,
        address_data=data.address,
        verification_method=verification_method,
        evidence_documents=evidence_docs,
        status=AddressVerificationStatus.PENDING,
        country_code=data.address.get("country", "").upper() if data.address else None,
        postal_code=data.address.get("postal_code") if data.address else None,
        created=timestamp,
        metadata_=data.metadata,
    )
    
    session.add(address_verification)
    await session.flush()
    
    return AddressVerificationResponse(
        id=address_verification.id,
        session_id=address_verification.session_id,
        address_data=address_verification.address_data,
        verification_method=address_verification.verification_method.value,
        status=address_verification.status.value,
        country_code=address_verification.country_code,
        postal_code=address_verification.postal_code,
        created=address_verification.created,
        metadata=address_verification.metadata_,
    )


@router.get("/address_verifications/{address_id}", response_model=AddressVerificationResponse)
async def get_address_verification(
    address_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.identity import AddressVerification
    
    query = select(AddressVerification).where(AddressVerification.id == address_id)
    result = await session.execute(query)
    av = result.scalar_one_or_none()
    
    if not av:
        raise NotFoundError(f"Address verification {address_id} not found")
    
    return AddressVerificationResponse(
        id=av.id,
        session_id=av.session_id,
        address_data=av.address_data,
        verification_method=av.verification_method.value,
        status=av.status.value,
        formatted_address=av.formatted_address,
        country_code=av.country_code,
        postal_code=av.postal_code,
        geocode_result=av.geocode_result,
        verification_result=av.verification_result,
        created=av.created,
        processed_at=av.processed_at,
        metadata=av.metadata_,
    )


@router.get("/verification_reports/{session_id}", response_model=VerificationReportResponse)
async def get_verification_report(
    session_id: str,
    request: Request,
    session = Depends(get_session),
):
    from sqlalchemy import select
    from payment_platform.backend.domain.identity import (
        VerificationSession, VerificationResult, IdentityDocument
    )
    
    vs_query = select(VerificationSession).where(VerificationSession.id == session_id)
    vs_result = await session.execute(vs_query)
    vs = vs_result.scalar_one_or_none()
    
    if not vs:
        raise NotFoundError(f"Verification session {session_id} not found")
    
    vr_query = select(VerificationResult).where(VerificationResult.session_id == session_id)
    vr_result = await session.execute(vr_query)
    vr = vr_result.scalar_one_or_none()
    
    id_query = select(IdentityDocument).where(IdentityDocument.verification_session_id == session_id)
    id_result = await session.execute(id_query)
    identity_doc = id_result.scalar_one_or_none()
    
    if not vr:
        timestamp = _get_timestamp()
        vr = VerificationResult(
            id=_generate_id("vr"),
            session_id=session_id,
            created=timestamp,
        )
        session.add(vr)
        await session.flush()
    
    identity_doc_data = None
    if identity_doc:
        identity_doc_data = {
            "id": identity_doc.id,
            "document_type": identity_doc.document_type.value,
            "document_number_masked": identity_doc.document_number_masked,
            "issuing_country": identity_doc.issuing_country,
            "expiry_date": identity_doc.expiry_date,
            "holder_name": identity_doc.holder_name,
        }
    
    return VerificationReportResponse(
        id=vr.id,
        session_id=vr.session_id,
        overall_status=vr.overall_status.value,
        checks_passed=vr.checks_passed,
        checks_failed=vr.checks_failed,
        checks_pending=vr.checks_pending,
        risk_score=vr.risk_score,
        risk_factors=vr.risk_factors,
        failure_reasons=vr.failure_reasons,
        document_check=vr.document_check,
        biometric_check=vr.biometric_check,
        address_check=vr.address_check,
        sanctions_check=vr.sanctions_check,
        pep_check=vr.pep_check,
        aml_check=vr.aml_check,
        identity_document=identity_doc_data,
        created=vr.created,
        updated=vr.updated,
    )
