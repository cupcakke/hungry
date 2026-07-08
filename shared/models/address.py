from typing import Any, Dict, Optional
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator
from payment_platform.shared.models.enums import CountryCode


class Address(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    line1: Optional[str] = Field(default=None, max_length=100, description="Address line 1")
    line2: Optional[str] = Field(default=None, max_length=100, description="Address line 2")
    city: Optional[str] = Field(default=None, max_length=50, description="City")
    state: Optional[str] = Field(default=None, max_length=50, description="State/Province")
    postal_code: Optional[str] = Field(default=None, max_length=20, description="Postal/ZIP code")
    country: Optional[str] = Field(default=None, max_length=2, description="Two-letter country code")

    @field_validator("country")
    @classmethod
    def validate_country(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.upper()
        valid_countries = [c.value for c in CountryCode]
        if v not in valid_countries:
            raise ValueError(f"Invalid country code: {v}")
        return v

    @field_validator("line1", "line2", "city", "state", "postal_code")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None

    @property
    def is_empty(self) -> bool:
        return not any([self.line1, self.line2, self.city, self.state, self.postal_code, self.country])

    @property
    def is_complete(self) -> bool:
        return all([self.line1, self.city, self.country])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line1": self.line1,
            "line2": self.line2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
        }

    def format_single_line(self) -> str:
        parts = []
        if self.line1:
            parts.append(self.line1)
        if self.line2:
            parts.append(self.line2)
        city_state_postal = []
        if self.city:
            city_state_postal.append(self.city)
        if self.state:
            city_state_postal.append(self.state)
        if self.postal_code:
            city_state_postal.append(self.postal_code)
        if city_state_postal:
            parts.append(", ".join(city_state_postal))
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


class BillingDetails(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: Optional[str] = Field(default=None, max_length=100, description="Billing name")
    email: Optional[str] = Field(default=None, max_length=254, description="Billing email")
    phone: Optional[str] = Field(default=None, max_length=20, description="Billing phone")
    address: Optional[Address] = Field(default=None, description="Billing address")
    tax_id: Optional[str] = Field(default=None, max_length=50, description="Tax ID")
    tax_id_type: Optional[str] = Field(default=None, max_length=20, description="Tax ID type")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError(f"Invalid email format: {v}")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        import re
        cleaned = re.sub(r"[^\d+]", "", v)
        if not cleaned:
            raise ValueError(f"Invalid phone format: {v}")
        return cleaned

    @property
    def is_empty(self) -> bool:
        return not any([self.name, self.email, self.phone, self.address, self.tax_id])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address.to_dict() if self.address else None,
            "tax_id": self.tax_id,
            "tax_id_type": self.tax_id_type,
        }


class ShippingDetails(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: Optional[str] = Field(default=None, max_length=100, description="Shipping recipient name")
    phone: Optional[str] = Field(default=None, max_length=20, description="Shipping phone")
    address: Optional[Address] = Field(default=None, description="Shipping address")
    carrier: Optional[str] = Field(default=None, max_length=50, description="Shipping carrier")
    tracking_number: Optional[str] = Field(default=None, max_length=100, description="Tracking number")
    tracking_url: Optional[str] = Field(default=None, max_length=500, description="Tracking URL")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        import re
        cleaned = re.sub(r"[^\d+]", "", v)
        if not cleaned:
            raise ValueError(f"Invalid phone format: {v}")
        return cleaned

    @property
    def is_empty(self) -> bool:
        return not any([self.name, self.phone, self.address, self.carrier, self.tracking_number])

    @property
    def is_trackable(self) -> bool:
        return bool(self.tracking_number)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "phone": self.phone,
            "address": self.address.to_dict() if self.address else None,
            "carrier": self.carrier,
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url,
        }


class TaxAddress(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    city: Optional[str] = Field(default=None, description="City")
    country: Optional[str] = Field(default=None, description="Country code")
    line1: Optional[str] = Field(default=None, description="Address line 1")
    line2: Optional[str] = Field(default=None, description="Address line 2")
    postal_code: Optional[str] = Field(default=None, description="Postal code")
    state: Optional[str] = Field(default=None, description="State")

    @classmethod
    def from_address(cls, address: Address) -> "TaxAddress":
        return cls(
            city=address.city,
            country=address.country,
            line1=address.line1,
            line2=address.line2,
            postal_code=address.postal_code,
            state=address.state,
        )


class ShippingRate(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(default=None, description="Shipping rate ID")
    display_name: str = Field(..., description="Display name")
    amount: int = Field(..., ge=0, description="Amount in minor units")
    currency: str = Field(..., description="Currency code")
    delivery_estimate: Optional[Dict[str, Any]] = Field(default=None, description="Delivery estimate")
    tax_code: Optional[str] = Field(default=None, description="Tax code")
    tax_behavior: str = Field(default="exclusive", description="Tax behavior")
    fixed_amount: Optional[Dict[str, int]] = Field(default=None, description="Fixed amount by currency")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata")

    @property
    def is_free(self) -> bool:
        return self.amount == 0


class ShippingOption(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    shipping_rate: str = Field(..., description="Shipping rate ID")
    shipping_rate_data: Optional[ShippingRate] = Field(default=None, description="Shipping rate data")


class CustomerAddress(PydanticBaseModel):
    model_config = ConfigDict(populate_by_name=True)

    billing: Optional[Address] = Field(default=None, description="Billing address")
    shipping: Optional[Address] = Field(default=None, description="Shipping address")

    @property
    def has_billing(self) -> bool:
        return self.billing is not None and not self.billing.is_empty

    @property
    def has_shipping(self) -> bool:
        return self.shipping is not None and not self.shipping.is_empty
