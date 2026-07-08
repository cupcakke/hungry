from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.admin_service.domain.models import (
    AdminUser,
    AdminSession,
    ApiKey,
    Permission,
    RolePermission,
    AdminRole,
    AdminUserStatus,
    SessionStatus,
)
from payment_platform.admin_service.api.routes.auth import (
    get_current_admin,
    log_audit,
    hash_password,
)
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError
from payment_platform.shared.utils.identifiers import generate_id

router = APIRouter()


class AdminUserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    permissions: Optional[List[str]] = None
    mfa_enabled: bool
    status: str
    last_login_at: Optional[datetime] = None
    last_login_ip: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AdminUserDetailResponse(AdminUserResponse):
    failed_login_attempts: int
    locked_until: Optional[datetime] = None
    session_count: int = 0


class AdminUserCreateRequest(BaseModel):
    email: EmailStr = Field(..., description="Admin email address")
    name: str = Field(..., min_length=2, max_length=100, description="Full name")
    password: str = Field(..., min_length=8, description="Initial password")
    role: str = Field(default="admin", description="Role: super_admin, admin, analyst, support")
    permissions: Optional[List[str]] = None
    send_invite: bool = Field(default=True, description="Send invitation email")


class AdminUserUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    status: Optional[str] = None


class PermissionsUpdateRequest(BaseModel):
    permissions: List[str] = Field(..., description="List of permission names")
    action: str = Field(default="replace", description="Action: replace, add, remove")


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    permissions: Optional[List[str]] = None
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="API key name")
    permissions: Optional[List[str]] = None
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365, description="Days until expiration")


class PermissionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    resource: str
    action: str
    is_active: bool


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
        last_login_ip=user.last_login_ip,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def user_to_detail_response(user: AdminUser, session_count: int = 0) -> AdminUserDetailResponse:
    return AdminUserDetailResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value if isinstance(user.role, AdminRole) else user.role,
        permissions=user.permissions,
        mfa_enabled=user.mfa_enabled,
        status=user.status.value if hasattr(user.status, 'value') else user.status,
        last_login_at=user.last_login_at,
        last_login_ip=user.last_login_ip,
        created_at=user.created_at,
        updated_at=user.updated_at,
        failed_login_attempts=user.failed_login_attempts,
        locked_until=user.locked_until,
        session_count=session_count,
    )


def api_key_to_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        permissions=api_key.permissions,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
    )


def permission_to_response(permission: Permission) -> PermissionResponse:
    return PermissionResponse(
        id=permission.id,
        name=permission.name,
        description=permission.description,
        resource=permission.resource,
        action=permission.action,
        is_active=permission.is_active,
    )


async def require_super_admin(current_user: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if current_user.role != AdminRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="This action requires super admin privileges"
        )
    return current_user


@router.get("", response_model=PaginatedResponse[AdminUserResponse])
async def list_admin_users(
    request: Request,
    role: Optional[str] = Query(default=None, description="Filter by role"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status"),
    search: Optional[str] = Query(default=None, description="Search by name or email"),
    limit: int = Query(default=20, ge=1, le=100),
    starting_after: Optional[str] = Query(default=None),
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(AdminUser).where(AdminUser.is_deleted == False)

    if role:
        try:
            role_enum = AdminRole(role)
            query = query.where(AdminUser.role == role_enum)
        except ValueError:
            pass

    if status_filter:
        try:
            status_enum = AdminUserStatus(status_filter)
            query = query.where(AdminUser.status == status_enum)
        except ValueError:
            pass

    if search:
        query = query.where(
            or_(
                AdminUser.name.ilike(f"%{search}%"),
                AdminUser.email.ilike(f"%{search}%"),
            )
        )

    if starting_after:
        result = await session.execute(
            select(AdminUser).where(AdminUser.id == starting_after)
        )
        cursor_user = result.scalar_one_or_none()
        if cursor_user:
            query = query.where(AdminUser.created_at < cursor_user.created_at)

    query = query.order_by(AdminUser.created_at.desc()).limit(limit + 1)

    result = await session.execute(query)
    users = result.scalars().all()

    has_more = len(users) > limit
    if has_more:
        users = users[:limit]

    return PaginatedResponse(
        data=[user_to_response(u) for u in users],
        has_more=has_more,
    )


@router.get("/{user_id}", response_model=AdminUserDetailResponse)
async def get_admin_user(
    user_id: str,
    request: Request,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(
            and_(
                AdminUser.id == user_id,
                AdminUser.is_deleted == False,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError(f"Admin user {user_id} not found")

    result = await session.execute(
        select(func.count()).select_from(AdminSession).where(
            and_(
                AdminSession.admin_user_id == user_id,
                AdminSession.status == SessionStatus.ACTIVE,
            )
        )
    )
    session_count = result.scalar() or 0

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "view_admin_user", "admin_user",
        resource_id=user_id,
        ip_address=ip_address
    )
    await session.commit()

    return user_to_detail_response(user, session_count)


@router.post("", response_model=AdminUserDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    request: Request,
    data: AdminUserCreateRequest,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(AdminUser.email == data.email.lower())
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise ValidationError("An admin user with this email already exists")

    try:
        role_enum = AdminRole(data.role.lower())
    except ValueError:
        role_enum = AdminRole.ADMIN

    user = AdminUser(
        id=generate_id("admin"),
        email=data.email.lower(),
        name=data.name,
        password_hash=hash_password(data.password),
        role=role_enum,
        permissions=data.permissions,
        mfa_enabled=False,
        status=AdminUserStatus.PENDING,
    )
    session.add(user)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "create_admin_user", "admin_user",
        resource_id=user.id,
        new_values={"email": data.email, "name": data.name, "role": data.role},
        ip_address=ip_address
    )

    await session.commit()

    return user_to_detail_response(user, 0)


@router.put("/{user_id}", response_model=AdminUserDetailResponse)
async def update_admin_user(
    user_id: str,
    request: Request,
    data: AdminUserUpdateRequest,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(
            and_(
                AdminUser.id == user_id,
                AdminUser.is_deleted == False,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError(f"Admin user {user_id} not found")

    if user.id == current_user.id:
        raise ValidationError("Cannot modify your own account through this endpoint")

    old_values = {}
    new_values = {}

    if data.name:
        old_values["name"] = user.name
        user.name = data.name
        new_values["name"] = data.name

    if data.email:
        result = await session.execute(
            select(AdminUser).where(
                and_(
                    AdminUser.email == data.email.lower(),
                    AdminUser.id != user_id,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise ValidationError("Email is already in use")

        old_values["email"] = user.email
        user.email = data.email.lower()
        new_values["email"] = data.email

    if data.role:
        try:
            role_enum = AdminRole(data.role.lower())
            old_values["role"] = user.role.value if isinstance(user.role, AdminRole) else user.role
            user.role = role_enum
            new_values["role"] = data.role
        except ValueError:
            pass

    if data.status:
        try:
            status_enum = AdminUserStatus(data.status.lower())
            old_values["status"] = user.status.value if hasattr(user.status, 'value') else user.status
            user.status = status_enum
            new_values["status"] = data.status
        except ValueError:
            pass

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "update_admin_user", "admin_user",
        resource_id=user_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address
    )

    await session.commit()

    result = await session.execute(
        select(func.count()).select_from(AdminSession).where(
            and_(
                AdminSession.admin_user_id == user_id,
                AdminSession.status == SessionStatus.ACTIVE,
            )
        )
    )
    session_count = result.scalar() or 0

    return user_to_detail_response(user, session_count)


@router.delete("/{user_id}")
async def delete_admin_user(
    user_id: str,
    request: Request,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(
            and_(
                AdminUser.id == user_id,
                AdminUser.is_deleted == False,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError(f"Admin user {user_id} not found")

    if user.id == current_user.id:
        raise ValidationError("Cannot delete your own account")

    if user.role == AdminRole.SUPER_ADMIN:
        result = await session.execute(
            select(func.count()).select_from(AdminUser).where(
                and_(
                    AdminUser.role == AdminRole.SUPER_ADMIN,
                    AdminUser.is_deleted == False,
                    AdminUser.id != user_id,
                )
            )
        )
        remaining_super_admins = result.scalar() or 0

        if remaining_super_admins == 0:
            raise ValidationError("Cannot delete the last super admin")

    user.deleted_at = datetime.now(timezone.utc)
    user.status = AdminUserStatus.INACTIVE

    result = await session.execute(
        select(AdminSession).where(
            and_(
                AdminSession.admin_user_id == user_id,
                AdminSession.status == SessionStatus.ACTIVE,
            )
        )
    )
    active_sessions = result.scalars().all()
    for admin_session in active_sessions:
        admin_session.status = SessionStatus.REVOKED

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "delete_admin_user", "admin_user",
        resource_id=user_id,
        ip_address=ip_address
    )

    await session.commit()

    return {"message": "Admin user deleted successfully", "id": user_id}


@router.put("/{user_id}/permissions", response_model=AdminUserDetailResponse)
async def update_permissions(
    user_id: str,
    request: Request,
    data: PermissionsUpdateRequest,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(
            and_(
                AdminUser.id == user_id,
                AdminUser.is_deleted == False,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError(f"Admin user {user_id} not found")

    if user.id == current_user.id:
        raise ValidationError("Cannot modify your own permissions")

    old_permissions = user.permissions or []

    if data.action == "replace":
        user.permissions = data.permissions
    elif data.action == "add":
        current_perms = set(user.permissions or [])
        current_perms.update(data.permissions)
        user.permissions = list(current_perms)
    elif data.action == "remove":
        current_perms = set(user.permissions or [])
        current_perms.difference_update(data.permissions)
        user.permissions = list(current_perms)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "update_permissions", "admin_user",
        resource_id=user_id,
        old_values={"permissions": old_permissions},
        new_values={"permissions": user.permissions},
        ip_address=ip_address
    )

    await session.commit()

    result = await session.execute(
        select(func.count()).select_from(AdminSession).where(
            and_(
                AdminSession.admin_user_id == user_id,
                AdminSession.status == SessionStatus.ACTIVE,
            )
        )
    )
    session_count = result.scalar() or 0

    return user_to_detail_response(user, session_count)


@router.post("/{user_id}/unlock")
async def unlock_admin_user(
    user_id: str,
    request: Request,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(
            and_(
                AdminUser.id == user_id,
                AdminUser.is_deleted == False,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError(f"Admin user {user_id} not found")

    user.locked_until = None
    user.failed_login_attempts = 0

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "unlock_admin_user", "admin_user",
        resource_id=user_id,
        ip_address=ip_address
    )

    await session.commit()

    return {"message": "Admin user unlocked successfully", "id": user_id}


@router.post("/{user_id}/reset-password")
async def reset_admin_password(
    user_id: str,
    request: Request,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(
            and_(
                AdminUser.id == user_id,
                AdminUser.is_deleted == False,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError(f"Admin user {user_id} not found")

    import secrets
    temp_password = secrets.token_urlsafe(12)

    user.password_hash = hash_password(temp_password)
    user.locked_until = None
    user.failed_login_attempts = 0
    user.status = AdminUserStatus.PENDING

    result = await session.execute(
        select(AdminSession).where(AdminSession.admin_user_id == user_id)
    )
    sessions = result.scalars().all()
    for admin_session in sessions:
        admin_session.status = SessionStatus.REVOKED

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "reset_admin_password", "admin_user",
        resource_id=user_id,
        ip_address=ip_address
    )

    await session.commit()

    return {
        "message": "Password reset successfully",
        "temp_password": temp_password,
    }


@router.get("/{user_id}/api-keys", response_model=PaginatedResponse[ApiKeyResponse])
async def list_user_api_keys(
    user_id: str,
    request: Request,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(ApiKey).where(
            and_(
                ApiKey.admin_user_id == user_id,
                ApiKey.is_deleted == False,
            )
        ).order_by(ApiKey.created_at.desc())
    )
    api_keys = result.scalars().all()

    return PaginatedResponse(
        data=[api_key_to_response(k) for k in api_keys],
        has_more=False,
    )


@router.post("/{user_id}/api-keys", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_api_key(
    user_id: str,
    request: Request,
    data: ApiKeyCreateRequest,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(AdminUser).where(
            and_(
                AdminUser.id == user_id,
                AdminUser.is_deleted == False,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError(f"Admin user {user_id} not found")

    import secrets
    import hashlib

    raw_key = f"pk_admin_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    api_key = ApiKey(
        id=generate_id("key"),
        admin_user_id=user_id,
        name=data.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        permissions=data.permissions,
        expires_at=datetime.now(timezone.utc) + timedelta(days=data.expires_in_days) if data.expires_in_days else None,
    )
    session.add(api_key)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "create_api_key", "api_key",
        resource_id=api_key.id,
        new_values={"name": data.name, "user_id": user_id},
        ip_address=ip_address
    )

    await session.commit()

    return {
        "id": api_key.id,
        "name": api_key.name,
        "key": raw_key,
        "key_prefix": key_prefix,
        "message": "Store this key securely. It will not be shown again.",
    }


@router.delete("/{user_id}/api-keys/{key_id}")
async def revoke_api_key(
    user_id: str,
    key_id: str,
    request: Request,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(ApiKey).where(
            and_(
                ApiKey.id == key_id,
                ApiKey.admin_user_id == user_id,
            )
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise NotFoundError(f"API key {key_id} not found")

    api_key.is_active = False
    api_key.deleted_at = datetime.now(timezone.utc)

    ip_address = request.client.host if request.client else None
    await log_audit(
        session, current_user.id, "revoke_api_key", "api_key",
        resource_id=key_id,
        ip_address=ip_address
    )

    await session.commit()

    return {"message": "API key revoked successfully", "id": key_id}


@router.get("/permissions/list", response_model=List[PermissionResponse])
async def list_permissions(
    request: Request,
    resource: Optional[str] = Query(default=None, description="Filter by resource"),
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    query = select(Permission).where(Permission.is_active == True)

    if resource:
        query = query.where(Permission.resource == resource)

    result = await session.execute(query.order_by(Permission.resource, Permission.action))
    permissions = result.scalars().all()

    return [permission_to_response(p) for p in permissions]


@router.get("/roles/permissions", response_model=Dict[str, List[str]])
async def get_role_permissions(
    request: Request,
    current_user: AdminUser = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(RolePermission).order_by(RolePermission.role)
    )
    role_perms = result.scalars().all()

    roles_map: Dict[str, List[str]] = {}
    for rp in role_perms:
        role_name = rp.role.value if hasattr(rp.role, 'value') else rp.role
        if role_name not in roles_map:
            roles_map[role_name] = []
        roles_map[role_name].append(rp.permission_id)

    return roles_map
