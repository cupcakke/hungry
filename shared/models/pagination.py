from typing import Any, Dict, Generic, List, Optional, TypeVar, Union
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator

T = TypeVar("T")


class PaginationParams(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    limit: int = Field(default=10, ge=1, le=100, description="Number of items to return")
    starting_after: Optional[str] = Field(default=None, description="Cursor for forward pagination")
    ending_before: Optional[str] = Field(default=None, description="Cursor for backward pagination")

    @field_validator("ending_before")
    @classmethod
    def validate_cursors(cls, v: Optional[str], info) -> Optional[str]:
        if v and info.data.get("starting_after"):
            raise ValueError("Cannot use both starting_after and ending_before")
        return v

    @property
    def has_cursor(self) -> bool:
        return bool(self.starting_after or self.ending_before)

    @property
    def direction(self) -> str:
        if self.ending_before:
            return "backward"
        return "forward"


class PaginatedResponse(PydanticBaseModel, Generic[T]):
    model_config = ConfigDict(populate_by_name=True)

    object: str = Field(default="list", description="Object type")
    data: List[T] = Field(default_factory=list, description="List of items")
    has_more: bool = Field(default=False, description="Whether there are more items")
    total_count: Optional[int] = Field(default=None, description="Total count of items")
    url: Optional[str] = Field(default=None, description="URL of the endpoint")

    @property
    def is_empty(self) -> bool:
        return len(self.data) == 0

    @property
    def count(self) -> int:
        return len(self.data)


class PaginatedMeta(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: Optional[str] = Field(default=None, description="Request ID")
    api_version: Optional[str] = Field(default=None, description="API version")


class PaginatedLinks(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    self: Optional[str] = Field(default=None, description="Current page URL")
    next: Optional[str] = Field(default=None, description="Next page URL")
    previous: Optional[str] = Field(default=None, description="Previous page URL")
    first: Optional[str] = Field(default=None, description="First page URL")
    last: Optional[str] = Field(default=None, description="Last page URL")


class CursorPagination(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    before: Optional[str] = Field(default=None, description="Cursor before current page")
    after: Optional[str] = Field(default=None, description="Cursor after current page")


class OffsetPagination(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    limit: int = Field(default=10, ge=1, le=100, description="Number of items per page")
    total: Optional[int] = Field(default=None, description="Total number of items")

    @property
    def page(self) -> int:
        return (self.offset // self.limit) + 1 if self.limit > 0 else 1

    @property
    def total_pages(self) -> Optional[int]:
        if self.total is None or self.limit == 0:
            return None
        return (self.total + self.limit - 1) // self.limit

    @property
    def has_next(self) -> bool:
        if self.total is None:
            return True
        return self.offset + self.limit < self.total

    @property
    def has_previous(self) -> bool:
        return self.offset > 0


class SortingParams(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sort_by: Optional[str] = Field(default=None, description="Field to sort by")
    sort_order: str = Field(default="desc", description="Sort order: asc or desc")

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: str) -> str:
        if v.lower() not in ("asc", "desc"):
            raise ValueError("sort_order must be 'asc' or 'desc'")
        return v.lower()


class FilterParams(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    created_gte: Optional[str] = Field(default=None, description="Filter by creation date greater than or equal")
    created_lte: Optional[str] = Field(default=None, description="Filter by creation date less than or equal")
    updated_gte: Optional[str] = Field(default=None, description="Filter by update date greater than or equal")
    updated_lte: Optional[str] = Field(default=None, description="Filter by update date less than or equal")


class SearchParams(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: Optional[str] = Field(default=None, description="Search query")
    fields: Optional[List[str]] = Field(default=None, description="Fields to search in")
    fuzzy: bool = Field(default=True, description="Enable fuzzy matching")


class ListQueryParams(PaginationParams, SortingParams, FilterParams, SearchParams):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    expand: Optional[List[str]] = Field(default=None, description="Fields to expand")

    @field_validator("expand", mode="before")
    @classmethod
    def parse_expand(cls, v: Optional[Union[str, List[str]]]) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            return [item.strip() for item in v.split(",")]
        return v


class DateRangeParams(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_date: Optional[str] = Field(default=None, description="Start date")
    end_date: Optional[str] = Field(default=None, description="End date")

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, v: Optional[str], info) -> Optional[str]:
        if v and info.data.get("start_date"):
            from datetime import datetime
            try:
                start = datetime.fromisoformat(info.data["start_date"])
                end = datetime.fromisoformat(v)
                if end < start:
                    raise ValueError("end_date must be after start_date")
            except ValueError as e:
                raise ValueError(f"Invalid date format: {e}")
        return v


class TimeWindowParams(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    window: str = Field(default="24h", description="Time window (e.g., 1h, 24h, 7d, 30d)")
    granularity: Optional[str] = Field(default=None, description="Data granularity")

    @field_validator("window")
    @classmethod
    def validate_window(cls, v: str) -> str:
        import re
        if not re.match(r"^\d+[hdmwy]$", v):
            raise ValueError("Window must be in format like 1h, 24h, 7d, 30d")
        return v


def create_paginated_response(
    data: List[T],
    has_more: bool = False,
    total_count: Optional[int] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "object": "list",
        "data": data,
        "has_more": has_more,
        "total_count": total_count,
        "url": url,
    }


def get_pagination_offset(page: int, limit: int) -> int:
    return max(0, (page - 1) * limit)


def get_pagination_page(offset: int, limit: int) -> int:
    return (offset // limit) + 1 if limit > 0 else 1


def calculate_total_pages(total: int, limit: int) -> int:
    return (total + limit - 1) // limit if limit > 0 else 0
