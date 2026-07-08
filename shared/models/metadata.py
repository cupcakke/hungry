from typing import Any, Dict, Iterator, List, Optional, Tuple, Union
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator


class Metadata(PydanticBaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
        max_length=500,
    )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        for key, value in data.items():
            if value is not None:
                object.__setattr__(self, key, value)

    @field_validator("*")
    @classmethod
    def validate_value(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            if len(v) > 500:
                raise ValueError(f"Metadata value exceeds maximum length of 500 characters")
            return v
        if isinstance(v, (int, float, bool)):
            return str(v)
        raise ValueError(f"Metadata value must be a string, got {type(v).__name__}")

    def __getitem__(self, key: str) -> Optional[str]:
        return getattr(self, key, None)

    def __setitem__(self, key: str, value: Optional[str]) -> None:
        if value is not None:
            object.__setattr__(self, key, value)

    def __delitem__(self, key: str) -> None:
        if hasattr(self, key):
            object.__setattr__(self, key, None)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and getattr(self, key) is not None

    def __iter__(self) -> Iterator[Tuple[str, str]]:
        for key, value in self.model_dump().items():
            if value is not None:
                yield key, value

    def __len__(self) -> int:
        return len([k for k, v in self if v is not None])

    def __bool__(self) -> bool:
        return len(self) > 0

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return getattr(self, key, default)

    def keys(self) -> List[str]:
        return [k for k, v in self]

    def values(self) -> List[str]:
        return [v for k, v in self]

    def items(self) -> List[Tuple[str, str]]:
        return list(self)

    def update(self, other: Union[Dict[str, Any], "Metadata"]) -> None:
        if isinstance(other, Metadata):
            for key, value in other:
                self[key] = value
        elif isinstance(other, dict):
            for key, value in other.items():
                self[key] = str(value) if value is not None else None

    def to_dict(self) -> Dict[str, str]:
        return {k: v for k, v in self}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Metadata":
        if data is None:
            return cls()
        return cls(**data)

    def copy(self) -> "Metadata":
        return Metadata.from_dict(self.to_dict())


class MetadataMixin(PydanticBaseModel):
    metadata: Optional[Dict[str, str]] = Field(default_factory=dict, description="Custom metadata")

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, v: Optional[Dict[str, Any]]) -> Dict[str, str]:
        if v is None:
            return {}
        validated = {}
        for key, value in v.items():
            if not isinstance(key, str):
                raise ValueError(f"Metadata key must be a string, got {type(key).__name__}")
            if len(key) > 40:
                raise ValueError(f"Metadata key '{key}' exceeds maximum length of 40 characters")
            if not key.replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"Metadata key '{key}' contains invalid characters")
            if value is not None:
                if isinstance(value, str):
                    if len(value) > 500:
                        raise ValueError(f"Metadata value for key '{key}' exceeds maximum length of 500 characters")
                    validated[key] = value
                else:
                    validated[key] = str(value)
        if len(validated) > 50:
            raise ValueError("Metadata cannot have more than 50 keys")
        return validated

    def get_metadata(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.metadata.get(key, default) if self.metadata else default

    def set_metadata(self, key: str, value: str) -> None:
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value

    def delete_metadata(self, key: str) -> None:
        if self.metadata and key in self.metadata:
            del self.metadata[key]


class ExpandableMetadata(MetadataMixin):
    pass


class RequestMetadata(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ip_address: Optional[str] = Field(default=None, description="Client IP address")
    user_agent: Optional[str] = Field(default=None, description="User agent")
    referer: Optional[str] = Field(default=None, description="Referer URL")
    origin: Optional[str] = Field(default=None, description="Origin URL")
    request_id: Optional[str] = Field(default=None, description="Request ID")
    session_id: Optional[str] = Field(default=None, description="Session ID")
    device_id: Optional[str] = Field(default=None, description="Device fingerprint")
    custom: Optional[Dict[str, str]] = Field(default=None, description="Custom metadata")


class EventMetadata(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: Optional[str] = Field(default=None, description="Event ID")
    event_type: Optional[str] = Field(default=None, description="Event type")
    timestamp: Optional[str] = Field(default=None, description="Event timestamp")
    source: Optional[str] = Field(default=None, description="Event source")
    version: Optional[str] = Field(default=None, description="Event version")


def merge_metadata(base: Optional[Dict[str, str]], update: Optional[Dict[str, str]]) -> Dict[str, str]:
    result = dict(base) if base else {}
    if update:
        result.update(update)
    return result


def validate_metadata_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    if len(key) > 40:
        return False
    if not key.replace("_", "").replace("-", "").isalnum():
        return False
    return True


def validate_metadata_value(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) > 500:
        return False
    return True
