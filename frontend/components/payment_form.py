from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class CardBrand(str, Enum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"
    JCB = "jcb"
    DINERS = "diners"
    UNIONPAY = "unionpay"
    UNKNOWN = "unknown"


class PaymentStatus(str, Enum):
    REQUIRES_PAYMENT_METHOD = "requires_payment_method"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class CardValidationResult:
    is_valid: bool
    error_message: Optional[str] = None
    error_field: Optional[str] = None


@dataclass
class CardDetails:
    number: str
    exp_month: int
    exp_year: int
    cvc: str
    brand: CardBrand = CardBrand.UNKNOWN
    last4: str = ""
    
    def __post_init__(self):
        self.brand = self._detect_brand()
        self.last4 = self.number[-4:] if len(self.number) >= 4 else ""
    
    def _detect_brand(self) -> CardBrand:
        number = self.number.replace(" ", "")
        if number.startswith("4"):
            return CardBrand.VISA
        elif number.startswith(("51", "52", "53", "54", "55")) or (
            len(number) >= 4 and 2221 <= int(number[:4]) <= 2720
        ):
            return CardBrand.MASTERCARD
        elif number.startswith(("34", "37")):
            return CardBrand.AMEX
        elif number.startswith("6011") or number.startswith("65"):
            return CardBrand.DISCOVER
        elif number.startswith("35"):
            return CardBrand.JCB
        elif number.startswith(("30", "36", "38", "39")):
            return CardBrand.DINERS
        elif number.startswith(("62", "81")):
            return CardBrand.UNIONPAY
        return CardBrand.UNKNOWN


@dataclass
class PaymentFormConfig:
    client_secret: str
    publishable_key: str
    amount: int
    currency: str
    appearance: Dict[str, Any] = field(default_factory=dict)
    layout: str = "tabs"
    payment_method_types: List[str] = field(default_factory=lambda: ["card"])
    default_values: Dict[str, Any] = field(default_factory=dict)
    return_url: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class PaymentFormAppearance:
    theme: str = "stripe"
    variables: Dict[str, str] = field(default_factory=lambda: {
        "fontFamily": "system-ui, sans-serif",
        "borderRadius": "4px",
        "colorPrimary": "#635bff",
    })
    rules: Dict[str, Dict[str, str]] = field(default_factory=dict)


class PaymentForm:
    def __init__(self, config: PaymentFormConfig):
        self.config = config
        self._card_element = None
        self._payment_request_button = None
        self._is_mounted = False
    
    def mount(self, element_id: str) -> bool:
        self._is_mounted = True
        return True
    
    def unmount(self) -> None:
        self._is_mounted = False
        self._card_element = None
    
    async def create_payment_method(self, card_details: CardDetails) -> Dict[str, Any]:
        validation = self._validate_card(card_details)
        if not validation.is_valid:
            return {
                "error": {
                    "message": validation.error_message,
                    "field": validation.error_field,
                }
            }
        return {
            "payment_method": {
                "id": "pm_generated_123",
                "type": "card",
                "card": {
                    "brand": card_details.brand.value,
                    "last4": card_details.last4,
                    "exp_month": card_details.exp_month,
                    "exp_year": card_details.exp_year,
                }
            }
        }
    
    async def confirm_payment(self, payment_method_id: str) -> Dict[str, Any]:
        return {
            "payment_intent": {
                "id": "pi_test",
                "status": PaymentStatus.SUCCEEDED.value,
                "amount": self.config.amount,
                "currency": self.config.currency,
            }
        }
    
    def _validate_card(self, card: CardDetails) -> CardValidationResult:
        number = card.number.replace(" ", "").replace("-", "")
        if not self._luhn_check(number):
            return CardValidationResult(
                is_valid=False,
                error_message="Your card number is invalid.",
                error_field="number"
            )
        
        import datetime
        now = datetime.datetime.now()
        if card.exp_year < now.year or (
            card.exp_year == now.year and card.exp_month < now.month
        ):
            return CardValidationResult(
                is_valid=False,
                error_message="Your card has expired.",
                error_field="expiry"
            )
        
        cvc_length = 4 if card.brand == CardBrand.AMEX else 3
        if len(card.cvc) != cvc_length:
            return CardValidationResult(
                is_valid=False,
                error_message="Your card's security code is invalid.",
                error_field="cvc"
            )
        
        return CardValidationResult(is_valid=True)
    
    def _luhn_check(self, number: str) -> bool:
        if not number.isdigit():
            return False
        digits = [int(d) for d in number]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        total = sum(odd_digits)
        for d in even_digits:
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        return total % 10 == 0


class CardElement:
    def __init__(self, options: Dict[str, Any] = None):
        self.options = options or {}
        self._value = ""
        self._is_focused = False
        self._is_complete = False
        self._brand = CardBrand.UNKNOWN
    
    def on(self, event: str, handler: callable) -> None:
        pass
    
    def mount(self, element_id: str) -> None:
        pass
    
    def unmount(self) -> None:
        pass
    
    def update(self, options: Dict[str, Any]) -> None:
        self.options.update(options)
    
    def clear(self) -> None:
        self._value = ""
        self._is_complete = False


class PaymentRequestButton:
    def __init__(self, payment_request: "PaymentRequest"):
        self.payment_request = payment_request
    
    def on(self, event: str, handler: callable) -> None:
        pass
    
    def mount(self, element_id: str) -> None:
        pass
    
    def unmount(self) -> None:
        pass


class PaymentRequest:
    def __init__(
        self,
        country: str,
        currency: str,
        total: Dict[str, Any],
        request_payer_name: bool = True,
        request_payer_email: bool = True,
        request_payer_phone: bool = False,
        request_shipping: bool = False,
        shipping_options: List[Dict[str, Any]] = None,
    ):
        self.country = country
        self.currency = currency
        self.total = total
        self.request_payer_name = request_payer_name
        self.request_payer_email = request_payer_email
        self.request_payer_phone = request_payer_phone
        self.request_shipping = request_shipping
        self.shipping_options = shipping_options or []
    
    def can_make_payment(self) -> Dict[str, bool]:
        return {
            "applePay": True,
            "googlePay": True,
        }
    
    def on(self, event: str, handler: callable) -> None:
        pass
    
    def update(self, total: Dict[str, Any]) -> None:
        self.total = total
    
    def show(self) -> None:
        pass
    
    def abort(self) -> None:
        pass


def create_payment_form(config: PaymentFormConfig) -> PaymentForm:
    return PaymentForm(config)


def create_card_element(options: Dict[str, Any] = None) -> CardElement:
    return CardElement(options)


def create_payment_request(
    country: str,
    currency: str,
    total: Dict[str, Any],
    **kwargs
) -> PaymentRequest:
    return PaymentRequest(country, currency, total, **kwargs)


def create_payment_request_button(payment_request: PaymentRequest) -> PaymentRequestButton:
    return PaymentRequestButton(payment_request)
