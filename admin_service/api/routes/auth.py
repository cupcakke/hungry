import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.admin_service.domain.models import (
    AdminUser,
    AdminSession,
    AdminAuditLog,
    AdminRole,
    AdminUserStatus,
    SessionStatus,
)
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, UnauthorizedError
from payment_platform.shared.utils.identifiers import generate_id

router = APIRouter()

ACCESS_TOKEN_EXPIRY_MINUTES = 60
REFRESH_TOKEN_EXPIRY_DAYS = 7
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Admin email address")
    password: str = Field(..., min_length=8, description="Password")
    mfa_code: Optional[str] = Field(default=None, description="MFA TOTP code")
    remember_me: bool = Field(default=False, description="Extend session duration")


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: Dict[str, Any]
    mfa_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh token")


class MFASetupResponse(BaseModel):
    secret: str
    qr_code_url: str
    backup_codes: List[str]


class MFAVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, description="TOTP code")


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=8, description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")
    confirm_password: str = Field(..., min_length=8, description="Confirm new password")


class AdminUserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    permissions: Optional[List[str]] = None
    mfa_enabled: bool
    status: str
    last_login_at: Optional[datetime] = None
    created_at: datetime


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, salt: Optional[str] = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, stored_hash = password_hash.split("$")
        computed_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
        return hmac.compare_digest(stored_hash, computed_hash)
    except (ValueError, TypeError):
        return False


def generate_totp_secret() -> str:
    return secrets.token_hex(20)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    try:
        current_time = int(time.time()) // 30
        for offset in range(-window, window + 1):
            time_counter = current_time + offset
            expected = _generate_totp_code(secret, time_counter)
            if hmac.compare_digest(code, expected):
                return True
        return False
    except (ValueError, TypeError):
        return False


def _generate_totp_code(secret: str, time_counter: int) -> str:
    import struct
    key = bytes.fromhex(secret)
    msg = struct.pack(">Q", time_counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1000000:06d}"


def user_to_response(user: AdminUser) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value if isinstance(user.role, AdminRole) else user.role,
        permissions=user.permissions,
        mfa_enabled=user.mfa_enabled,
        status=user.status.value if hasattr(user.status, 'value') else user.status,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


async def get_current_admin(
    authorization: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
) -> AdminUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or invalid authorization header")

    token = authorization[7:]
    token_hash = hash_token(token)

    result = await session.execute(
        select(AdminSession).where(
            and_(
                AdminSession.token_hash == token_hash,
                AdminSession.status == SessionStatus.ACTIVE,
                AdminSession.expires_at > datetime.now(timezone.utc),
            )
        )
    )
    admin_session = result.scalar_one_or_none()

    if not admin_session:
        raise UnauthorizedError("Invalid or expired token")

    result = await session.execute(
        select(AdminUser).where(AdminUser.id == admin_session.admin_user_id)
    )
    user = result.scalar_one_or_none()

    if not user or user.is_deleted:
        raise UnauthorizedError("User not found")

    if user.status != AdminUserStatus.ACTIVE:
        raise UnauthorizedError("User account is not active")

    admin_session.last_activity_at = datetime.now(timezone.utc)
    await session.commit()

    return user


async def log_audit(
    session: AsyncSession,
    admin_user_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    changes: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    status: str = "success",
    error_message: Optional[str] = None,
) -> AdminAuditLog:
    log = AdminAuditLog(
        id=generate_id("audit"),
        admin_user_id=admin_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
        status=status,
        error_message=error_message,
    )
    session.add(log)
    return log


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    data: LoginRequest,
    session: AsyncSession = Depends(get_session),
):
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    result = await session.execute(
        select(AdminUser).where(AdminUser.email == data.email.lower())
    )
    user = result.scalar_one_or_none()

    if not user or user.is_deleted:
        await log_audit(
            session, "system", "login_failed", "admin_user",
            changes={"email": data.email, "reason": "user_not_found"},
            ip_address=ip_address, user_agent=user_agent, status="failed"
        )
        raise UnauthorizedError("Invalid credentials")

    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        await log_audit(
            session, user.id, "login_failed", "admin_user",
            resource_id=user.id,
            changes={"reason": "account_locked"},
            ip_address=ip_address, user_agent=user_agent, status="failed"
        )
        raise UnauthorizedError("Account is temporarily locked")

    if not verify_password(data.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            user.failed_login_attempts = 0

        await log_audit(
            session, user.id, "login_failed", "admin_user",
            resource_id=user.id,
            changes={"reason": "invalid_password", "attempts": user.failed_login_attempts},
            ip_address=ip_address, user_agent=user_agent, status="failed"
        )
        await session.commit()
        raise UnauthorizedError("Invalid credentials")

    if user.status != AdminUserStatus.ACTIVE:
        raise UnauthorizedError("Account is not active")

    if user.mfa_enabled:
        if not data.mfa_code:
            return LoginResponse(
                access_token="",
                refresh_token="",
                expires_in=0,
                user=user_to_response(user).model_dump(),
                mfa_required=True,
            )

        if not user.mfa_secret or not verify_totp(user.mfa_secret, data.mfa_code):
            await log_audit(
                session, user.id, "mfa_failed", "admin_user",
                resource_id=user.id,
                ip_address=ip_address, user_agent=user_agent, status="failed"
            )
            raise UnauthorizedError("Invalid MFA code")

    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)

    expiry_minutes = REFRESH_TOKEN_EXPIRY_DAYS * 24 * 60 if data.remember_me else ACCESS_TOKEN_EXPIRY_MINUTES

    admin_session = AdminSession(
        id=generate_id("sess"),
        admin_user_id=user.id,
        token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        ip_address=ip_address,
        user_agent=user_agent,
        status=SessionStatus.ACTIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
        refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS),
    )
    session.add(admin_session)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip_address

    await log_audit(
        session, user.id, "login", "admin_user",
        resource_id=user.id,
        ip_address=ip_address, user_agent=user_agent
    )

    await session.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=expiry_minutes * 60,
        user=user_to_response(user).model_dump(),
        mfa_required=False,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        token_hash = hash_token(token)

        result = await session.execute(
            select(AdminSession).where(AdminSession.token_hash == token_hash)
        )
        admin_session = result.scalar_one_or_none()

        if admin_session:
            admin_session.status = SessionStatus.REVOKED

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "logout", "admin_user",
        resource_id=current_user.id,
        ip_address=ip_address
    )

    await session.commit()


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: Request,
    data: RefreshRequest,
    session: AsyncSession = Depends(get_session),
):
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    refresh_hash = hash_token(data.refresh_token)

    result = await session.execute(
        select(AdminSession).where(
            and_(
                AdminSession.refresh_token_hash == refresh_hash,
                AdminSession.status == SessionStatus.ACTIVE,
                AdminSession.refresh_expires_at > datetime.now(timezone.utc),
            )
        )
    )
    admin_session = result.scalar_one_or_none()

    if not admin_session:
        raise UnauthorizedError("Invalid or expired refresh token")

    result = await session.execute(
        select(AdminUser).where(AdminUser.id == admin_session.admin_user_id)
    )
    user = result.scalar_one_or_none()

    if not user or user.is_deleted or user.status != AdminUserStatus.ACTIVE:
        raise UnauthorizedError("User not found or inactive")

    access_token = secrets.token_urlsafe(32)
    new_refresh_token = secrets.token_urlsafe(32)

    admin_session.token_hash = hash_token(access_token)
    admin_session.refresh_token_hash = hash_token(new_refresh_token)
    admin_session.expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRY_MINUTES)
    admin_session.refresh_expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)
    admin_session.ip_address = ip_address
    admin_session.user_agent = user_agent
    admin_session.last_activity_at = datetime.now(timezone.utc)

    await log_audit(
        session, user.id, "token_refresh", "admin_user",
        resource_id=user.id,
        ip_address=ip_address, user_agent=user_agent
    )

    await session.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="Bearer",
        expires_in=ACCESS_TOKEN_EXPIRY_MINUTES * 60,
        user=user_to_response(user).model_dump(),
        mfa_required=False,
    )


@router.post("/mfa/enable", response_model=MFASetupResponse)
async def enable_mfa(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    if current_user.mfa_enabled:
        raise ValidationError("MFA is already enabled")

    secret = generate_totp_secret()
    backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]

    current_user.mfa_secret = secret
    current_user.mfa_enabled = True

    qr_url = f"otpauth://totp/PaymentPlatform:{current_user.email}?secret={secret}&issuer=PaymentPlatform"

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "mfa_enabled", "admin_user",
        resource_id=current_user.id,
        ip_address=ip_address
    )

    await session.commit()

    return MFASetupResponse(
        secret=secret,
        qr_code_url=qr_url,
        backup_codes=backup_codes,
    )


@router.post("/mfa/verify")
async def verify_mfa(
    request: Request,
    data: MFAVerifyRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    if not current_user.mfa_enabled or not current_user.mfa_secret:
        raise ValidationError("MFA is not enabled for this account")

    if not verify_totp(current_user.mfa_secret, data.code):
        ip_address = request.client.host if request.client else None
        await log_audit(
            session, current_user.id, "mfa_verify_failed", "admin_user",
            resource_id=current_user.id,
            ip_address=ip_address, status="failed"
        )
        raise UnauthorizedError("Invalid MFA code")

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "mfa_verified", "admin_user",
        resource_id=current_user.id,
        ip_address=ip_address
    )

    await session.commit()

    return {"verified": True}


@router.get("/me", response_model=AdminUserResponse)
async def get_current_user(
    current_user: AdminUser = Depends(get_current_admin),
):
    return user_to_response(current_user)


@router.put("/password")
async def change_password(
    request: Request,
    data: PasswordChangeRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    if data.new_password != data.confirm_password:
        raise ValidationError("Passwords do not match")

    if len(data.new_password) < 8:
        raise ValidationError("Password must be at least 8 characters")

    if not verify_password(data.current_password, current_user.password_hash):
        raise UnauthorizedError("Current password is incorrect")

    current_user.password_hash = hash_password(data.new_password)

    result = await session.execute(
        select(AdminSession).where(
            and_(
                AdminSession.admin_user_id == current_user.id,
                AdminSession.status == SessionStatus.ACTIVE,
            )
        )
    )
    active_sessions = result.scalars().all()

    for admin_session in active_sessions:
        admin_session.status = SessionStatus.REVOKED

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "password_changed", "admin_user",
        resource_id=current_user.id,
        ip_address=ip_address
    )

    await session.commit()

    return {"message": "Password changed successfully"}


@router.delete("/mfa")
async def disable_mfa(
    request: Request,
    data: MFAVerifyRequest,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    if not current_user.mfa_enabled:
        raise ValidationError("MFA is not enabled")

    if not verify_totp(current_user.mfa_secret, data.code):
        raise UnauthorizedError("Invalid MFA code")

    current_user.mfa_enabled = False
    current_user.mfa_secret = None

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "mfa_disabled", "admin_user",
        resource_id=current_user.id,
        ip_address=ip_address
    )

    await session.commit()

    return {"message": "MFA disabled successfully"}


@router.get("/sessions")
async def list_sessions(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminSession).where(
            and_(
                AdminSession.admin_user_id == current_user.id,
                AdminSession.status == SessionStatus.ACTIVE,
            )
        ).order_by(AdminSession.last_activity_at.desc())
    )
    sessions = result.scalars().all()

    return {
        "sessions": [
            {
                "id": s.id,
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "created_at": s.created_at.isoformat(),
                "last_activity_at": s.last_activity_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
            }
            for s in sessions
        ]
    }


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminSession).where(
            and_(
                AdminSession.id == session_id,
                AdminSession.admin_user_id == current_user.id,
            )
        )
    )
    admin_session = result.scalar_one_or_none()

    if not admin_session:
        raise NotFoundError("Session not found")

    admin_session.status = SessionStatus.REVOKED

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "session_revoked", "admin_session",
        resource_id=session_id,
        ip_address=ip_address
    )

    await session.commit()

    return {"message": "Session revoked successfully"}
