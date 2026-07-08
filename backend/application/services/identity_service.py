from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import hashlib
import secrets
import string
import re
import json

from sqlalchemy import select, update, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.domain.identity import (
    VerificationSession,
    DocumentVerification,
    BiometricVerification,
    AddressVerification,
    VerificationResult,
    IdentityDocument,
    VerificationAttempt,
    SanctionsScreeningResult,
    DataRetentionRecord,
    VerificationSessionType,
    VerificationSessionStatus,
    DocumentType,
    DocumentVerificationStatus,
    BiometricType,
    BiometricStatus,
    AddressVerificationMethod,
    AddressVerificationStatus,
    VerificationAttemptStatus,
    OverallVerificationStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    IdentityVerificationError,
)


@dataclass
class OCRResult:
    document_number: Optional[str] = None
    holder_name: Optional[str] = None
    holder_dob: Optional[str] = None
    expiry_date: Optional[str] = None
    issue_date: Optional[str] = None
    issuing_country: Optional[str] = None
    nationality: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    raw_text: Optional[str] = None


@dataclass
class LivenessCheckResult:
    is_live: bool
    confidence: float
    check_type: str
    challenge_passed: bool
    blink_detected: Optional[bool] = None
    motion_detected: Optional[bool] = None
    texture_score: Optional[float] = None


@dataclass
class FaceMatchResult:
    is_match: bool
    confidence: float
    similarity_score: float
    quality_score: float


@dataclass
class GeocodeResult:
    formatted_address: str
    latitude: float
    longitude: float
    country_code: str
    postal_code: str
    accuracy: str
    partial_match: bool


@dataclass
class RiskAssessment:
    risk_score: float
    risk_level: str
    risk_factors: List[str]
    recommendation: str


@dataclass
class ComplianceCheckResult:
    passed: bool
    match_count: int
    potential_match_count: int
    matches: List[Dict[str, Any]]
    screened_at: int


class VerificationSessionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(
        self,
        account_id: str,
        verification_type: str,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VerificationSession:
        session_type = VerificationSessionType.DOCUMENT
        if verification_type == "address":
            session_type = VerificationSessionType.ADDRESS
        elif verification_type == "identity":
            session_type = VerificationSessionType.IDENTITY

        timestamp = int(datetime.now(timezone.utc).timestamp())
        expires_at = timestamp + 86400 * 7

        verification_session = VerificationSession(
            id=self._generate_id("vs"),
            account_id=account_id,
            type=session_type,
            status=VerificationSessionStatus.PENDING,
            client_ip=client_ip,
            user_agent=user_agent,
            expires_at=expires_at,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(verification_session)
        await self._create_verification_attempt(verification_session.id, client_ip, user_agent)
        await self._create_data_retention_records(verification_session.id)
        await self.session.flush()

        return verification_session

    async def get_session(self, session_id: str) -> Optional[VerificationSession]:
        query = select(VerificationSession).where(VerificationSession.id == session_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        verification_type: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[VerificationSession]:
        query = select(VerificationSession)

        if account_id:
            query = query.where(VerificationSession.account_id == account_id)
        if status:
            query = query.where(VerificationSession.status == status)
        if verification_type:
            query = query.where(VerificationSession.type == verification_type)

        query = query.order_by(VerificationSession.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def process_session(self, session_id: str) -> VerificationSession:
        verification_session = await self.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        if verification_session.status not in [VerificationSessionStatus.PENDING]:
            raise IdentityVerificationError(
                f"Session {session_id} is not in pending status",
                verification_id=session_id,
            )

        verification_session.status = VerificationSessionStatus.PROCESSING
        await self.session.flush()
        return verification_session

    async def complete_session(
        self,
        session_id: str,
        success: bool = True,
        failure_reasons: Optional[List[str]] = None,
    ) -> VerificationSession:
        verification_session = await self.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        if success:
            verification_session.status = VerificationSessionStatus.VERIFIED
            verification_session.verified_at = timestamp
        else:
            verification_session.status = VerificationSessionStatus.FAILED

        await self.session.flush()
        return verification_session

    async def cancel_session(
        self,
        session_id: str,
        reason: Optional[str] = None,
    ) -> VerificationSession:
        verification_session = await self.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        if verification_session.status not in [
            VerificationSessionStatus.PENDING,
            VerificationSessionStatus.REQUIRES_INPUT,
        ]:
            raise IdentityVerificationError(
                f"Cannot cancel session in {verification_session.status.value} status",
                verification_id=session_id,
            )

        verification_session.status = VerificationSessionStatus.CANCELED
        await self.session.flush()
        return verification_session

    async def redact_session(self, session_id: str) -> VerificationSession:
        verification_session = await self.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        verification_session.redacted_at = timestamp
        verification_session.client_ip = None
        verification_session.user_agent = None

        await self.session.execute(
            update(DocumentVerification)
            .where(DocumentVerification.session_id == session_id)
            .values(images=None, extracted_data=None, images_encrypted=False)
        )

        await self.session.execute(
            update(BiometricVerification)
            .where(BiometricVerification.session_id == session_id)
            .values(images=None, images_encrypted=False)
        )

        await self.session.execute(
            update(AddressVerification)
            .where(AddressVerification.session_id == session_id)
            .values(evidence_documents=None)
        )

        await self.session.execute(
            update(IdentityDocument)
            .where(IdentityDocument.verification_session_id == session_id)
            .values(document_number_masked=None, holder_name=None)
        )

        await self.session.flush()
        return verification_session

    async def _create_verification_attempt(
        self,
        session_id: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
    ) -> VerificationAttempt:
        timestamp = int(datetime.now(timezone.utc).timestamp())

        attempt = VerificationAttempt(
            id=self._generate_id("va"),
            session_id=session_id,
            attempt_number=1,
            status=VerificationAttemptStatus.PENDING,
            ip_address=client_ip,
            user_agent=user_agent,
            created=timestamp,
        )

        self.session.add(attempt)
        return attempt

    async def _create_data_retention_records(self, session_id: str) -> None:
        timestamp = int(datetime.now(timezone.utc).timestamp())
        retention_periods = {
            "document_images": 2555,
            "biometric_data": 2555,
            "address_data": 2555,
            "extracted_data": 2555,
            "session_data": 3650,
        }

        for data_type, retention_days in retention_periods.items():
            record = DataRetentionRecord(
                id=self._generate_id("drr"),
                session_id=session_id,
                data_type=data_type,
                retention_period_days=retention_days,
                scheduled_deletion_at=timestamp + (retention_days * 86400),
                created=timestamp,
            )
            self.session.add(record)

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class DocumentVerificationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.session_service = VerificationSessionService(session)

    async def upload_document(
        self,
        session_id: str,
        document_type: str,
        country: str,
        front_image: Optional[bytes] = None,
        back_image: Optional[bytes] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentVerification:
        verification_session = await self.session_service.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        if verification_session.status == VerificationSessionStatus.EXPIRED:
            raise IdentityVerificationError(
                "Verification session has expired",
                verification_id=session_id,
            )

        doc_type = self._parse_document_type(document_type)
        timestamp = int(datetime.now(timezone.utc).timestamp())

        images = []
        if front_image:
            images.append(self._hash_image(front_image))
        if back_image:
            images.append(self._hash_image(back_image))

        doc_verification = DocumentVerification(
            id=self._generate_id("dv"),
            session_id=session_id,
            document_type=doc_type,
            country=country.upper(),
            images=images if images else None,
            images_encrypted=True,
            status=DocumentVerificationStatus.PENDING,
            created=timestamp,
            metadata_=metadata or {},
        )

        verification_session.status = VerificationSessionStatus.PROCESSING
        self.session.add(doc_verification)
        await self.session.flush()

        return doc_verification

    async def get_document(self, document_id: str) -> Optional[DocumentVerification]:
        query = select(DocumentVerification).where(DocumentVerification.id == document_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[DocumentVerification]:
        query = select(DocumentVerification)

        if session_id:
            query = query.where(DocumentVerification.session_id == session_id)
        if status:
            query = query.where(DocumentVerification.status == status)

        query = query.order_by(DocumentVerification.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def extract_data(self, document_id: str) -> OCRResult:
        document = await self.get_document(document_id)
        if not document:
            raise NotFoundError(f"Document {document_id} not found")

        document.status = DocumentVerificationStatus.PROCESSING
        await self.session.flush()

        ocr_result = await self._perform_ocr(document)

        document.extracted_data = {
            "document_number": self._mask_document_number(ocr_result.document_number),
            "holder_name": ocr_result.holder_name,
            "holder_dob": ocr_result.holder_dob,
            "expiry_date": ocr_result.expiry_date,
            "issue_date": ocr_result.issue_date,
            "issuing_country": ocr_result.issuing_country,
            "nationality": ocr_result.nationality,
            "gender": ocr_result.gender,
            "address": ocr_result.address,
        }
        document.ocr_confidence = ocr_result.confidence
        document.document_number_masked = self._mask_document_number(ocr_result.document_number)
        document.holder_name = ocr_result.holder_name
        document.expiry_date = ocr_result.expiry_date
        document.issue_date = ocr_result.issue_date
        document.issuing_authority = ocr_result.issuing_country

        await self._create_identity_document(document, ocr_result)

        await self.session.flush()
        return ocr_result

    async def validate_document(self, document_id: str) -> Dict[str, Any]:
        document = await self.get_document(document_id)
        if not document:
            raise NotFoundError(f"Document {document_id} not found")

        validation_result = {
            "is_valid": True,
            "checks": [],
            "warnings": [],
            "errors": [],
        }

        if document.extracted_data:
            expiry_date = document.extracted_data.get("expiry_date")
            if expiry_date:
                is_expired = self._check_document_expiry(expiry_date)
                if is_expired:
                    validation_result["is_valid"] = False
                    validation_result["errors"].append("Document has expired")

            if document.ocr_confidence and document.ocr_confidence < 0.7:
                validation_result["warnings"].append("Low OCR confidence score")

        validation_result["checks"] = [
            {"name": "document_format", "passed": True},
            {"name": "text_extraction", "passed": document.ocr_confidence is not None and document.ocr_confidence > 0.5},
            {"name": "expiry_check", "passed": True},
        ]

        timestamp = int(datetime.now(timezone.utc).timestamp())
        document.verification_result = validation_result

        if validation_result["is_valid"]:
            document.status = DocumentVerificationStatus.VERIFIED
        else:
            document.status = DocumentVerificationStatus.FAILED

        document.processed_at = timestamp
        await self.session.flush()

        return validation_result

    async def _perform_ocr(self, document: DocumentVerification) -> OCRResult:
        return OCRResult(
            document_number=self._generate_mock_document_number(document.document_type),
            holder_name="JOHN DOE",
            holder_dob="1990-01-15",
            expiry_date="2030-01-15",
            issue_date="2020-01-15",
            issuing_country=document.country,
            nationality=document.country,
            gender="M",
            address={"street": "123 Main St", "city": "New York", "country": "US"},
            confidence=0.95,
            raw_text="Sample OCR extracted text",
        )

    async def _create_identity_document(
        self,
        document: DocumentVerification,
        ocr_result: OCRResult,
    ) -> IdentityDocument:
        timestamp = int(datetime.now(timezone.utc).timestamp())

        identity_doc = IdentityDocument(
            id=self._generate_id("id"),
            verification_session_id=document.session_id,
            document_type=document.document_type,
            document_number_masked=self._mask_document_number(ocr_result.document_number),
            issuing_country=ocr_result.issuing_country,
            expiry_date=ocr_result.expiry_date,
            issue_date=ocr_result.issue_date,
            holder_name=ocr_result.holder_name,
            holder_dob=ocr_result.holder_dob,
            holder_nationality=ocr_result.nationality,
            holder_gender=ocr_result.gender,
            holder_address=ocr_result.address,
            created=timestamp,
        )

        self.session.add(identity_doc)
        return identity_doc

    def _parse_document_type(self, document_type: str) -> DocumentType:
        type_map = {
            "passport": DocumentType.PASSPORT,
            "driver_license": DocumentType.DRIVER_LICENSE,
            "id_card": DocumentType.ID_CARD,
            "residence_permit": DocumentType.RESIDENCE_PERMIT,
        }
        if document_type.lower() not in type_map:
            raise ValidationError(f"Invalid document type: {document_type}", param="document_type")
        return type_map[document_type.lower()]

    def _hash_image(self, image_data: bytes) -> str:
        return hashlib.sha256(image_data).hexdigest()[:64]

    def _mask_document_number(self, document_number: Optional[str]) -> Optional[str]:
        if not document_number or len(document_number) < 4:
            return document_number
        return "*" * (len(document_number) - 4) + document_number[-4:]

    def _generate_mock_document_number(self, doc_type: DocumentType) -> str:
        if doc_type == DocumentType.PASSPORT:
            return f"P{secrets.token_hex(4).upper()}{secrets.randbelow(90000000) + 10000000}"
        elif doc_type == DocumentType.DRIVER_LICENSE:
            return f"DL{secrets.token_hex(3).upper()}{secrets.randbelow(900000) + 100000}"
        else:
            return f"ID{secrets.token_hex(4).upper()}{secrets.randbelow(90000) + 10000}"

    def _check_document_expiry(self, expiry_date: str) -> bool:
        try:
            from datetime import datetime
            exp = datetime.strptime(expiry_date, "%Y-%m-%d")
            return exp < datetime.now()
        except ValueError:
            return False

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class BiometricService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.session_service = VerificationSessionService(session)

    async def process_biometric(
        self,
        session_id: str,
        biometric_type: str,
        image_data: bytes,
        challenge_data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BiometricVerification:
        verification_session = await self.session_service.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        bio_type = BiometricType.FACE
        if biometric_type.lower() == "selfie":
            bio_type = BiometricType.SELFIE

        timestamp = int(datetime.now(timezone.utc).timestamp())

        biometric = BiometricVerification(
            id=self._generate_id("bv"),
            session_id=session_id,
            type=bio_type,
            images=[self._hash_image(image_data)],
            images_encrypted=True,
            status=BiometricStatus.PENDING,
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(biometric)
        await self.session.flush()

        return biometric

    async def get_biometric(self, biometric_id: str) -> Optional[BiometricVerification]:
        query = select(BiometricVerification).where(BiometricVerification.id == biometric_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def check_liveness(
        self,
        biometric_id: str,
        challenge_data: Optional[Dict[str, Any]] = None,
    ) -> LivenessCheckResult:
        biometric = await self.get_biometric(biometric_id)
        if not biometric:
            raise NotFoundError(f"Biometric verification {biometric_id} not found")

        biometric.status = BiometricStatus.PROCESSING
        await self.session.flush()

        liveness_result = await self._perform_liveness_check(biometric, challenge_data)

        biometric.liveness_result = {
            "is_live": liveness_result.is_live,
            "confidence": liveness_result.confidence,
            "check_type": liveness_result.check_type,
            "challenge_passed": liveness_result.challenge_passed,
            "blink_detected": liveness_result.blink_detected,
            "motion_detected": liveness_result.motion_detected,
            "texture_score": liveness_result.texture_score,
        }

        await self.session.flush()
        return liveness_result

    async def compare_faces(
        self,
        biometric_id: str,
        document_image_reference: str,
    ) -> FaceMatchResult:
        biometric = await self.get_biometric(biometric_id)
        if not biometric:
            raise NotFoundError(f"Biometric verification {biometric_id} not found")

        face_match_result = await self._perform_face_match(biometric, document_image_reference)

        biometric.face_match_result = {
            "is_match": face_match_result.is_match,
            "confidence": face_match_result.confidence,
            "similarity_score": face_match_result.similarity_score,
            "quality_score": face_match_result.quality_score,
            "document_reference": document_image_reference,
        }

        timestamp = int(datetime.now(timezone.utc).timestamp())
        biometric.confidence_score = face_match_result.confidence
        biometric.verification_result = {
            "liveness_passed": biometric.liveness_result.get("is_live", False) if biometric.liveness_result else False,
            "face_match_passed": face_match_result.is_match,
            "overall_confidence": (biometric.liveness_result.get("confidence", 0) + face_match_result.confidence) / 2 if biometric.liveness_result else face_match_result.confidence,
        }

        if biometric.verification_result.get("liveness_passed") and face_match_result.is_match:
            biometric.status = BiometricStatus.VERIFIED
        else:
            biometric.status = BiometricStatus.FAILED

        biometric.processed_at = timestamp
        await self.session.flush()

        return face_match_result

    async def _perform_liveness_check(
        self,
        biometric: BiometricVerification,
        challenge_data: Optional[Dict[str, Any]] = None,
    ) -> LivenessCheckResult:
        return LivenessCheckResult(
            is_live=True,
            confidence=0.95,
            check_type="active" if challenge_data else "passive",
            challenge_passed=True if challenge_data else True,
            blink_detected=True,
            motion_detected=True,
            texture_score=0.92,
        )

    async def _perform_face_match(
        self,
        biometric: BiometricVerification,
        document_image_reference: str,
    ) -> FaceMatchResult:
        similarity = 0.85 + (secrets.randbelow(10) / 100)
        return FaceMatchResult(
            is_match=similarity > 0.8,
            confidence=similarity,
            similarity_score=similarity,
            quality_score=0.9,
        )

    def _hash_image(self, image_data: bytes) -> str:
        return hashlib.sha256(image_data).hexdigest()[:64]

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class AddressVerificationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.session_service = VerificationSessionService(session)

    async def verify_address(
        self,
        session_id: str,
        address: Dict[str, Any],
        verification_method: str,
        evidence_document: Optional[bytes] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AddressVerification:
        verification_session = await self.session_service.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        method = self._parse_verification_method(verification_method)
        timestamp = int(datetime.now(timezone.utc).timestamp())

        evidence_refs = None
        if evidence_document:
            evidence_refs = [self._hash_document(evidence_document)]

        address_verification = AddressVerification(
            id=self._generate_id("av"),
            session_id=session_id,
            address_data=address,
            verification_method=method,
            evidence_documents=evidence_refs,
            status=AddressVerificationStatus.PENDING,
            country_code=address.get("country", "").upper(),
            postal_code=address.get("postal_code"),
            created=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(address_verification)
        await self.session.flush()

        return address_verification

    async def get_address_verification(self, address_id: str) -> Optional[AddressVerification]:
        query = select(AddressVerification).where(AddressVerification.id == address_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def geocode(self, address_id: str) -> GeocodeResult:
        address_verification = await self.get_address_verification(address_id)
        if not address_verification:
            raise NotFoundError(f"Address verification {address_id} not found")

        address_verification.status = AddressVerificationStatus.PROCESSING
        await self.session.flush()

        geocode_result = await self._perform_geocoding(address_verification.address_data)

        address_verification.geocode_result = {
            "formatted_address": geocode_result.formatted_address,
            "latitude": geocode_result.latitude,
            "longitude": geocode_result.longitude,
            "country_code": geocode_result.country_code,
            "postal_code": geocode_result.postal_code,
            "accuracy": geocode_result.accuracy,
            "partial_match": geocode_result.partial_match,
        }
        address_verification.formatted_address = geocode_result.formatted_address
        address_verification.country_code = geocode_result.country_code
        address_verification.postal_code = geocode_result.postal_code

        await self.session.flush()
        return geocode_result

    async def validate_address(self, address_id: str) -> Dict[str, Any]:
        address_verification = await self.get_address_verification(address_id)
        if not address_verification:
            raise NotFoundError(f"Address verification {address_id} not found")

        validation_result = {
            "is_valid": True,
            "checks": [],
            "warnings": [],
            "errors": [],
        }

        if address_verification.geocode_result:
            if address_verification.geocode_result.get("partial_match"):
                validation_result["warnings"].append("Address was partially matched")

            if address_verification.geocode_result.get("accuracy") not in ["ROOFTOP", "RANGE_INTERPOLATED"]:
                validation_result["warnings"].append("Address accuracy is not precise")

        validation_result["checks"] = [
            {"name": "format_validation", "passed": self._validate_address_format(address_verification.address_data)},
            {"name": "geocoding", "passed": address_verification.geocode_result is not None},
            {"name": "country_validation", "passed": address_verification.country_code is not None},
        ]

        if not all(c["passed"] for c in validation_result["checks"]):
            validation_result["is_valid"] = False

        timestamp = int(datetime.now(timezone.utc).timestamp())
        address_verification.verification_result = validation_result

        if validation_result["is_valid"]:
            address_verification.status = AddressVerificationStatus.VERIFIED
        else:
            address_verification.status = AddressVerificationStatus.FAILED

        address_verification.processed_at = timestamp
        await self.session.flush()

        return validation_result

    async def _perform_geocoding(self, address_data: Dict[str, Any]) -> GeocodeResult:
        street = address_data.get("street", "")
        city = address_data.get("city", "")
        country = address_data.get("country", "US")
        postal_code = address_data.get("postal_code", "10001")

        formatted = f"{street}, {city}, {country} {postal_code}".strip(", ")

        return GeocodeResult(
            formatted_address=formatted,
            latitude=40.7128 + (secrets.randbelow(100) / 1000),
            longitude=-74.0060 + (secrets.randbelow(100) / 1000),
            country_code=country.upper(),
            postal_code=postal_code,
            accuracy="ROOFTOP",
            partial_match=False,
        )

    def _validate_address_format(self, address_data: Optional[Dict[str, Any]]) -> bool:
        if not address_data:
            return False

        required_fields = ["street", "city", "country"]
        return all(field in address_data for field in required_fields)

    def _parse_verification_method(self, method: str) -> AddressVerificationMethod:
        method_map = {
            "document": AddressVerificationMethod.DOCUMENT,
            "utility_bill": AddressVerificationMethod.UTILITY_BILL,
            "bank_statement": AddressVerificationMethod.BANK_STATEMENT,
            "geolocation": AddressVerificationMethod.GEOLOCATION,
        }
        if method.lower() not in method_map:
            raise ValidationError(f"Invalid verification method: {method}", param="verification_method")
        return method_map[method.lower()]

    def _hash_document(self, document_data: bytes) -> str:
        return hashlib.sha256(document_data).hexdigest()[:64]

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class RiskAssessmentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.session_service = VerificationSessionService(session)

    async def calculate_risk_score(self, session_id: str) -> RiskAssessment:
        verification_session = await self.session_service.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        risk_factors = []
        base_score = 0.0

        doc_query = select(DocumentVerification).where(DocumentVerification.session_id == session_id)
        doc_result = await self.session.execute(doc_query)
        documents = list(doc_result.scalars().all())

        for doc in documents:
            if doc.ocr_confidence and doc.ocr_confidence < 0.7:
                risk_factors.append("low_ocr_confidence")
                base_score += 15
            if doc.status == DocumentVerificationStatus.FAILED:
                risk_factors.append("document_verification_failed")
                base_score += 30

        bio_query = select(BiometricVerification).where(BiometricVerification.session_id == session_id)
        bio_result = await self.session.execute(bio_query)
        biometrics = list(bio_result.scalars().all())

        for bio in biometrics:
            if bio.confidence_score and bio.confidence_score < 0.8:
                risk_factors.append("low_biometric_confidence")
                base_score += 20
            if bio.status == BiometricStatus.FAILED:
                risk_factors.append("biometric_verification_failed")
                base_score += 35

        addr_query = select(AddressVerification).where(AddressVerification.session_id == session_id)
        addr_result = await self.session.execute(addr_query)
        addresses = list(addr_result.scalars().all())

        for addr in addresses:
            if addr.geocode_result and addr.geocode_result.get("partial_match"):
                risk_factors.append("partial_address_match")
                base_score += 10
            if addr.status == AddressVerificationStatus.FAILED:
                risk_factors.append("address_verification_failed")
                base_score += 25

        attempts_query = select(VerificationAttempt).where(
            and_(
                VerificationAttempt.session_id == session_id,
                VerificationAttempt.status == VerificationAttemptStatus.FAILED,
            )
        )
        attempts_result = await self.session.execute(attempts_query)
        failed_attempts = list(attempts_result.scalars().all())

        if len(failed_attempts) > 2:
            risk_factors.append("multiple_failed_attempts")
            base_score += 20

        final_score = min(base_score, 100)
        risk_level = self._get_risk_level(final_score)
        recommendation = self._get_recommendation(final_score, risk_factors)

        return RiskAssessment(
            risk_score=final_score,
            risk_level=risk_level,
            risk_factors=risk_factors,
            recommendation=recommendation,
        )

    async def flag_suspicious(
        self,
        session_id: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        verification_result = await self._get_or_create_verification_result(session_id)

        if verification_result.risk_factors is None:
            verification_result.risk_factors = []
        verification_result.risk_factors.append(f"suspicious:{reason}")

        verification_result.risk_score = min((verification_result.risk_score or 0) + 50, 100)

        if verification_result.failure_reasons is None:
            verification_result.failure_reasons = []
        verification_result.failure_reasons.append(reason)

        await self.session.flush()
        return verification_result

    async def update_verification_result(
        self,
        session_id: str,
        check_type: str,
        check_result: Dict[str, Any],
    ) -> VerificationResult:
        verification_result = await self._get_or_create_verification_result(session_id)

        if check_type == "document":
            verification_result.document_check = check_result
            if check_result.get("passed"):
                verification_result.checks_passed += 1
            else:
                verification_result.checks_failed += 1
        elif check_type == "biometric":
            verification_result.biometric_check = check_result
            if check_result.get("passed"):
                verification_result.checks_passed += 1
            else:
                verification_result.checks_failed += 1
        elif check_type == "address":
            verification_result.address_check = check_result
            if check_result.get("passed"):
                verification_result.checks_passed += 1
            else:
                verification_result.checks_failed += 1
        elif check_type == "sanctions":
            verification_result.sanctions_check = check_result
            if check_result.get("passed"):
                verification_result.checks_passed += 1
            else:
                verification_result.checks_failed += 1
        elif check_type == "pep":
            verification_result.pep_check = check_result
            if check_result.get("passed"):
                verification_result.checks_passed += 1
            else:
                verification_result.checks_failed += 1
        elif check_type == "aml":
            verification_result.aml_check = check_result
            if check_result.get("passed"):
                verification_result.checks_passed += 1
            else:
                verification_result.checks_failed += 1

        verification_result.updated = int(datetime.now(timezone.utc).timestamp())
        await self.session.flush()
        return verification_result

    async def _get_or_create_verification_result(self, session_id: str) -> VerificationResult:
        query = select(VerificationResult).where(VerificationResult.session_id == session_id)
        result = await self.session.execute(query)
        verification_result = result.scalar_one_or_none()

        if not verification_result:
            timestamp = int(datetime.now(timezone.utc).timestamp())
            verification_result = VerificationResult(
                id=self._generate_id("vr"),
                session_id=session_id,
                created=timestamp,
            )
            self.session.add(verification_result)
            await self.session.flush()

        return verification_result

    def _get_risk_level(self, score: float) -> str:
        if score < 20:
            return "low"
        elif score < 50:
            return "medium"
        elif score < 75:
            return "high"
        else:
            return "critical"

    def _get_recommendation(self, score: float, risk_factors: List[str]) -> str:
        if score < 20:
            return "approve"
        elif score < 50:
            return "review"
        elif score < 75:
            return "manual_review"
        else:
            return "reject"

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ComplianceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.session_service = VerificationSessionService(session)

    async def check_sanctions(
        self,
        session_id: str,
        name: str,
        date_of_birth: Optional[str] = None,
        nationality: Optional[str] = None,
    ) -> ComplianceCheckResult:
        verification_session = await self.session_service.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        matches = await self._screen_against_sanctions_lists(name, date_of_birth, nationality)

        screening_result = SanctionsScreeningResult(
            id=self._generate_id("ss"),
            session_id=session_id,
            screening_type="sanctions",
            name_screened=name,
            matches=matches,
            match_count=len([m for m in matches if m.get("match_type") == "exact"]),
            potential_match_count=len([m for m in matches if m.get("match_type") == "potential"]),
            status="completed",
            screened_at=timestamp,
            created=timestamp,
        )

        self.session.add(screening_result)

        passed = len(matches) == 0 or all(m.get("match_type") == "potential" for m in matches)

        result = ComplianceCheckResult(
            passed=passed,
            match_count=screening_result.match_count,
            potential_match_count=screening_result.potential_match_count,
            matches=matches,
            screened_at=timestamp,
        )

        return result

    async def check_pep(
        self,
        session_id: str,
        name: str,
        date_of_birth: Optional[str] = None,
        nationality: Optional[str] = None,
    ) -> ComplianceCheckResult:
        verification_session = await self.session_service.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        matches = await self._screen_against_pep_lists(name, date_of_birth, nationality)

        screening_result = SanctionsScreeningResult(
            id=self._generate_id("ss"),
            session_id=session_id,
            screening_type="pep",
            name_screened=name,
            matches=matches,
            match_count=len([m for m in matches if m.get("match_type") == "exact"]),
            potential_match_count=len([m for m in matches if m.get("match_type") == "potential"]),
            status="completed",
            screened_at=timestamp,
            created=timestamp,
        )

        self.session.add(screening_result)

        passed = len(matches) == 0 or all(m.get("match_type") == "potential" for m in matches)

        result = ComplianceCheckResult(
            passed=passed,
            match_count=screening_result.match_count,
            potential_match_count=screening_result.potential_match_count,
            matches=matches,
            screened_at=timestamp,
        )

        return result

    async def aml_screening(
        self,
        session_id: str,
        name: str,
        date_of_birth: Optional[str] = None,
        nationality: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None,
    ) -> ComplianceCheckResult:
        verification_session = await self.session_service.get_session(session_id)
        if not verification_session:
            raise NotFoundError(f"Verification session {session_id} not found")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        sanctions_result = await self.check_sanctions(session_id, name, date_of_birth, nationality)
        pep_result = await self.check_pep(session_id, name, date_of_birth, nationality)

        all_matches = (sanctions_result.matches or []) + (pep_result.matches or [])

        passed = sanctions_result.passed and pep_result.passed

        screening_result = SanctionsScreeningResult(
            id=self._generate_id("ss"),
            session_id=session_id,
            screening_type="aml",
            name_screened=name,
            matches=all_matches,
            match_count=len([m for m in all_matches if m.get("match_type") == "exact"]),
            potential_match_count=len([m for m in all_matches if m.get("match_type") == "potential"]),
            status="completed",
            screened_at=timestamp,
            created=timestamp,
        )

        self.session.add(screening_result)

        return ComplianceCheckResult(
            passed=passed,
            match_count=screening_result.match_count,
            potential_match_count=screening_result.potential_match_count,
            matches=all_matches,
            screened_at=timestamp,
        )

    async def _screen_against_sanctions_lists(
        self,
        name: str,
        date_of_birth: Optional[str] = None,
        nationality: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return []

    async def _screen_against_pep_lists(
        self,
        name: str,
        date_of_birth: Optional[str] = None,
        nationality: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return []

    def _generate_id(self, prefix: str) -> str:
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"
