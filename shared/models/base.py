from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=False,
        json_encoders={
            datetime: lambda v: v.isoformat() if v else None,
            UUID: lambda v: str(v) if v else None,
        },
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique identifier")


class TimestampMixin(PydanticBaseModel):
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()


class SoftDeleteMixin(PydanticBaseModel):
    deleted_at: Optional[datetime] = Field(default=None, description="Deletion timestamp")
    deleted_by: Optional[str] = Field(default=None, description="ID of user who deleted")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, deleted_by: Optional[str] = None) -> None:
        self.deleted_at = datetime.utcnow()
        self.deleted_by = deleted_by

    def restore(self) -> None:
        self.deleted_at = None
        self.deleted_by = None


class AuditMixin(PydanticBaseModel):
    created_by: Optional[str] = Field(default=None, description="ID of user who created")
    updated_by: Optional[str] = Field(default=None, description="ID of user who last updated")
    version: int = Field(default=1, ge=1, description="Version number for optimistic locking")

    def increment_version(self, updated_by: Optional[str] = None) -> None:
        self.version += 1
        self.updated_by = updated_by


class Entity(BaseModel, TimestampMixin, AuditMixin):
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom metadata")


class FinancialEntity(Entity):
    def validate_amounts(self) -> bool:
        return True


class DeletableEntity(Entity, SoftDeleteMixin):
    pass
