from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class CardElementType(Enum):
    CARD_NUMBER = "cardNumber"
    CARD_EXPIRY = "cardExpiry"
    CARD_CVC = "cardCvc"
    CARD_POSTAL_CODE = "postalCode"


class CardBrand(Enum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"
    JCB = "jcb"
    DINERS = "diners"
    UNIONPAY = "unionpay"
    UNKNOWN = "unknown"


class ValidationState(Enum):
    VALID = "valid"
    INVALID = "invalid"
    INCOMPLETE = "incomplete"
    POTENTIALLY_VALID = "potentially_valid"


class FocusState(Enum):
    FOCUSED = "focused"
    BLURRED = "blurred"


@dataclass
class CardElementState:
    value: str = ""
    brand: CardBrand = CardBrand.UNKNOWN
    empty: bool = True
    complete: bool = False
    error: Optional[str] = None
    valid: bool = False
    potentially_valid: bool = False
    focused: bool = False


@dataclass
class CardElementOptions:
    placeholder: str = ""
    icon_style: str = "default"
    hide_icon: bool = False
    hide_postal_code: bool = True
    disabled: bool = False
    value: str = ""
    style: Optional[Dict[str, Any]] = None
    classes: Optional[Dict[str, str]] = None


@dataclass
class CardElementStyle:
    base: Dict[str, Any] = field(default_factory=lambda: {
        "color": "#32325d",
        "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        "fontSize": "16px",
        "fontSmoothing": "antialiased",
        "::placeholder": {"color": "#a0aec0"},
        ":focus": {"color": "#32325d"},
    })
    invalid: Dict[str, Any] = field(default_factory=lambda: {
        "color": "#fa755a",
        ":focus": {"color": "#fa755a"},
    })
    complete: Dict[str, Any] = field(default_factory=lambda: {
        "color": "#32325d",
    })


@dataclass
class CardTokenizationResult:
    token: Optional[str] = None
    error: Optional[str] = None
    card: Optional[Dict[str, Any]] = None


class SecureCardInput:
    def __init__(self, element_type: CardElementType, options: Optional[CardElementOptions] = None):
        self.element_type = element_type
        self.options = options or CardElementOptions()
        self._value = ""
        self._display_value = ""
        self._state = CardElementState()
        self._validators: List[Callable[[str], Tuple[bool, Optional[str]]]] = []
        self._formatters: List[Callable[[str], str]] = []
        self._on_change_callbacks: List[Callable[[CardElementState], None]] = []
        self._on_focus_callbacks: List[Callable[[], None]] = []
        self._on_blur_callbacks: List[Callable[[], None]] = []
        self._on_ready_callbacks: List[Callable[[], None]] = []
        self._setup_element()

    def _setup_element(self) -> None:
        if self.element_type == CardElementType.CARD_NUMBER:
            self._formatters = [self._format_card_number]
            self._validators = [self._validate_card_number]
            self.options.placeholder = self.options.placeholder or "1234 5678 9012 3456"
        elif self.element_type == CardElementType.CARD_EXPIRY:
            self._formatters = [self._format_expiry]
            self._validators = [self._validate_expiry]
            self.options.placeholder = self.options.placeholder or "MM/YY"
        elif self.element_type == CardElementType.CARD_CVC:
            self._formatters = [self._format_cvc]
            self._validators = [self._validate_cvc]
            self.options.placeholder = self.options.placeholder or "CVC"
        elif self.element_type == CardElementType.CARD_POSTAL_CODE:
            self._formatters = []
            self._validators = [self._validate_postal_code]
            self.options.placeholder = self.options.placeholder or "ZIP"

    def _format_card_number(self, value: str) -> str:
        sanitized = value.replace(" ", "").replace("-", "")
        brand = self._detect_brand(sanitized)
        
        if brand == CardBrand.AMEX:
            parts = [sanitized[:4], sanitized[4:10], sanitized[10:15]]
            return " ".join(p for p in parts if p)
        
        parts = [sanitized[i:i+4] for i in range(0, len(sanitized), 4)]
        return " ".join(parts)

    def _format_expiry(self, value: str) -> str:
        sanitized = value.replace("/", "").replace(" ", "")
        
        if len(sanitized) == 0:
            return ""
        if len(sanitized) == 1:
            if sanitized in "123456789":
                return sanitized
            if sanitized == "0":
                return "0"
            if sanitized == "1":
                return "1"
            return ""
        if len(sanitized) == 2:
            month = int(sanitized)
            if month > 12:
                return "1" + sanitized[1] + "/"
            if month == 0:
                return "0" + sanitized[1] + "/"
            return sanitized + "/"
        if len(sanitized) >= 3:
            month = sanitized[:2]
            year = sanitized[2:4]
            try:
                month_int = int(month)
                if month_int > 12:
                    month = "12"
                elif month_int == 0:
                    month = "01"
            except ValueError:
                pass
            return month + "/" + year
        return sanitized

    def _format_cvc(self, value: str) -> str:
        return value[:4] if value.isdigit() else "".join(c for c in value if c.isdigit())[:4]

    def _detect_brand(self, card_number: str) -> CardBrand:
        if card_number.startswith("4"):
            return CardBrand.VISA
        if len(card_number) >= 2:
            prefix2 = card_number[:2]
            if prefix2 in ("51", "52", "53", "54", "55"):
                return CardBrand.MASTERCARD
            if prefix2 in ("22", "23", "24", "25", "26", "27"):
                return CardBrand.MASTERCARD
        if card_number.startswith("34") or card_number.startswith("37"):
            return CardBrand.AMEX
        if card_number.startswith("6011") or card_number.startswith("65"):
            return CardBrand.DISCOVER
        if card_number.startswith("35"):
            return CardBrand.JCB
        if card_number.startswith("30") or card_number.startswith("36") or card_number.startswith("38"):
            return CardBrand.DINERS
        if card_number.startswith("62") or card_number.startswith("81"):
            return CardBrand.UNIONPAY
        return CardBrand.UNKNOWN

    def _validate_card_number(self, value: str) -> Tuple[bool, Optional[str]]:
        sanitized = value.replace(" ", "").replace("-", "")
        
        if not sanitized:
            return (False, "Your card number is incomplete.")
        
        if not sanitized.isdigit():
            return (False, "Your card number is invalid.")
        
        brand = self._detect_brand(sanitized)
        expected_lengths = {CardBrand.VISA: [16, 18, 19], CardBrand.MASTERCARD: [16], CardBrand.AMEX: [15], CardBrand.DISCOVER: [16, 19], CardBrand.JCB: [16], CardBrand.DINERS: [14], CardBrand.UNIONPAY: [16, 17, 18, 19]}
        
        if brand != CardBrand.UNKNOWN and len(sanitized) not in expected_lengths.get(brand, [16]):
            return (False, "Your card number is invalid.")
        
        if not self._luhn_check(sanitized):
            return (False, "Your card number is invalid.")
        
        return (True, None)

    def _validate_expiry(self, value: str) -> Tuple[bool, Optional[str]]:
        import datetime
        
        if not value:
            return (False, "Your card's expiration date is incomplete.")
        
        parts = value.split("/")
        if len(parts) != 2:
            return (False, "Your card's expiration date is invalid.")
        
        month_str, year_str = parts
        
        try:
            month = int(month_str)
            year = int(year_str)
            
            if month < 1 or month > 12:
                return (False, "Your card's expiration month is invalid.")
            
            if year < 100:
                year += 2000
            
            now = datetime.datetime.now()
            expiry_date = datetime.datetime(year, month, 1)
            current_date = datetime.datetime(now.year, now.month, 1)
            
            if expiry_date < current_date:
                return (False, "Your card has expired.")
            
            return (True, None)
        except ValueError:
            return (False, "Your card's expiration date is invalid.")

    def _validate_cvc(self, value: str) -> Tuple[bool, Optional[str]]:
        if not value:
            return (False, "Your card's security code is incomplete.")
        
        if not value.isdigit():
            return (False, "Your card's security code is invalid.")
        
        if len(value) < 3:
            return (False, "Your card's security code is incomplete.")
        
        return (True, None)

    def _validate_postal_code(self, value: str) -> Tuple[bool, Optional[str]]:
        if not value:
            return (False, "Your postal code is incomplete.")
        
        if len(value) < 3:
            return (False, "Your postal code is incomplete.")
        
        return (True, None)

    def _luhn_check(self, card_number: str) -> bool:
        digits = [int(d) for d in card_number]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        checksum = sum(odd_digits)
        
        for d in even_digits:
            d *= 2
            if d > 9:
                d -= 9
            checksum += d
        
        return checksum % 10 == 0

    def set_value(self, value: str) -> CardElementState:
        formatted_value = value
        for formatter in self._formatters:
            formatted_value = formatter(formatted_value)
        
        self._value = value
        self._display_value = formatted_value
        
        is_valid = True
        error = None
        for validator in self._validators:
            valid, err = validator(formatted_value)
            if not valid:
                is_valid = False
                error = err
                break
        
        brand = CardBrand.UNKNOWN
        if self.element_type == CardElementType.CARD_NUMBER:
            brand = self._detect_brand(value.replace(" ", "").replace("-", ""))
        
        self._state = CardElementState(
            value=formatted_value,
            brand=brand,
            empty=len(formatted_value) == 0,
            complete=is_valid,
            error=error,
            valid=is_valid,
            potentially_valid=len(formatted_value) > 0 and not is_valid,
            focused=self._state.focused,
        )
        
        self._notify_change()
        return self._state

    def focus(self) -> None:
        self._state.focused = True
        for callback in self._on_focus_callbacks:
            callback()

    def blur(self) -> None:
        self._state.focused = False
        for callback in self._on_blur_callbacks:
            callback()

    def clear(self) -> None:
        self._value = ""
        self._display_value = ""
        self._state = CardElementState()

    def on_change(self, callback: Callable[[CardElementState], None]) -> None:
        self._on_change_callbacks.append(callback)

    def on_focus(self, callback: Callable[[], None]) -> None:
        self._on_focus_callbacks.append(callback)

    def on_blur(self, callback: Callable[[], None]) -> None:
        self._on_blur_callbacks.append(callback)

    def on_ready(self, callback: Callable[[], None]) -> None:
        self._on_ready_callbacks.append(callback)

    def _notify_change(self) -> None:
        for callback in self._on_change_callbacks:
            callback(self._state)

    @property
    def state(self) -> CardElementState:
        return self._state

    def render(self) -> str:
        return self._render_element()

    def _render_element(self) -> str:
        element_id = f"card-element-{self.element_type.value}"
        brand_icon = self._get_brand_icon() if self.element_type == CardElementType.CARD_NUMBER else ""
        
        return f'''
<div class="card-element card-element--{self.element_type.value}" data-card-element data-element-type="{self.element_type.value}">
    <div class="card-element__wrapper">
        <input
            type="text"
            id="{element_id}"
            name="{self.element_type.value}"
            class="card-element__input"
            placeholder="{self.options.placeholder}"
            autocomplete="{self._get_autocomplete()}"
            maxlength="{self._get_maxlength()}"
            {self._get_input_mode()}
            data-card-input
            {'' if not self.options.disabled else 'disabled'}
        >
        {f'<div class="card-element__brand" data-card-brand>{brand_icon}</div>' if self.element_type == CardElementType.CARD_NUMBER and not self.options.hide_icon else ''}
    </div>
    <div class="card-element__error" data-card-error></div>
</div>
{self._get_element_styles()}
{self._get_element_script()}
'''

    def _get_autocomplete(self) -> str:
        autocomplete_map = {
            CardElementType.CARD_NUMBER: "cc-number",
            CardElementType.CARD_EXPIRY: "cc-exp",
            CardElementType.CARD_CVC: "cc-csc",
            CardElementType.CARD_POSTAL_CODE: "postal-code",
        }
        return autocomplete_map.get(self.element_type, "off")

    def _get_maxlength(self) -> str:
        maxlength_map = {
            CardElementType.CARD_NUMBER: "19",
            CardElementType.CARD_EXPIRY: "5",
            CardElementType.CARD_CVC: "4",
            CardElementType.CARD_POSTAL_CODE: "10",
        }
        return maxlength_map.get(self.element_type, "50")

    def _get_input_mode(self) -> str:
        if self.element_type in [CardElementType.CARD_NUMBER, CardElementType.CARD_CVC]:
            return 'inputmode="numeric" pattern="[0-9]*"'
        return ''

    def _get_brand_icon(self) -> str:
        return '''
<svg class="card-brand-icon card-brand-icon--default" viewBox="0 0 24 24">
    <path fill="currentColor" d="M20 4H4c-1.11 0-1.99.89-1.99 2L2 18c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V6c0-1.11-.89-2-2-2zm0 14H4v-6h16v6zm0-10H4V6h16v2z"/>
</svg>
'''

    def _get_element_styles(self) -> str:
        return '''
<style>
.card-element {
    width: 100%;
}
.card-element__wrapper {
    position: relative;
    display: flex;
    align-items: center;
}
.card-element__input {
    width: 100%;
    padding: 12px 14px;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    font-size: 16px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #32325d;
    transition: border-color 0.2s, box-shadow 0.2s;
    background: white;
}
.card-element__input::placeholder {
    color: #a0aec0;
}
.card-element__input:focus {
    outline: none;
    border-color: #635BFF;
    box-shadow: 0 0 0 3px rgba(99, 91, 255, 0.2);
}
.card-element--invalid .card-element__input {
    border-color: #fa755a;
}
.card-element--invalid .card-element__input:focus {
    box-shadow: 0 0 0 3px rgba(250, 117, 90, 0.2);
}
.card-element--complete .card-element__input {
    border-color: #32325d;
}
.card-element--cardNumber .card-element__input {
    padding-right: 50px;
}
.card-element__brand {
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    width: 32px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
}
.card-brand-icon {
    width: 100%;
    height: 100%;
}
.card-brand-icon--visa {
    fill: #1A1F71;
}
.card-brand-icon--mastercard {
    fill: #EB001B;
}
.card-brand-icon--amex {
    fill: #006FCF;
}
.card-element__error {
    font-size: 13px;
    color: #fa755a;
    margin-top: 4px;
    min-height: 18px;
    display: none;
}
.card-element--invalid .card-element__error {
    display: block;
}
.card-element--focused {
}
</style>
'''

    def _get_element_script(self) -> str:
        return f'''
<script>
(function() {{
    const element = document.querySelector('[data-element-type="{self.element_type.value}"]');
    if (!element) return;
    
    const input = element.querySelector('[data-card-input]');
    const errorEl = element.querySelector('[data-card-error]');
    const brandEl = element.querySelector('[data-card-brand]');
    
    function formatValue(value) {{
        {self._get_format_script()}
    }}
    
    function validateValue(value) {{
        {self._get_validation_script()}
        return {{ valid: true, error: null }};
    }}
    
    function updateState(value) {{
        const formatted = formatValue(value);
        const validation = validateValue(formatted);
        
        input.value = formatted;
        
        element.classList.remove('card-element--valid', 'card-element--invalid', 'card-element--complete');
        
        if (validation.valid) {{
            element.classList.add('card-element--complete');
        }} else if (formatted.length > 0) {{
            element.classList.add('card-element--invalid');
            errorEl.textContent = validation.error;
        }}
        
        if (brandEl) {{
            updateBrand(formatted);
        }}
    }}
    
    function updateBrand(value) {{
        const sanitized = value.replace(/\\s/g, '').replace(/-/g, '');
        let brand = 'default';
        
        if (sanitized.startsWith('4')) brand = 'visa';
        else if (/^5[1-5]/.test(sanitized) || /^2[2-7]/.test(sanitized)) brand = 'mastercard';
        else if (sanitized.startsWith('34') || sanitized.startsWith('37')) brand = 'amex';
        else if (sanitized.startsWith('6011') || sanitized.startsWith('65')) brand = 'discover';
        
        brandEl.dataset.brand = brand;
    }}
    
    input.addEventListener('input', function(e) {{
        updateState(e.target.value);
    }});
    
    input.addEventListener('focus', function() {{
        element.classList.add('card-element--focused');
    }});
    
    input.addEventListener('blur', function() {{
        element.classList.remove('card-element--focused');
    }});
}})();
</script>
'''

    def _get_format_script(self) -> str:
        if self.element_type == CardElementType.CARD_NUMBER:
            return '''
        const sanitized = value.replace(/\\s/g, '').replace(/-/g, '');
        const isAmex = sanitized.startsWith('34') || sanitized.startsWith('37');
        if (isAmex) {
            const parts = [sanitized.slice(0,4), sanitized.slice(4,10), sanitized.slice(10,15)];
            return parts.filter(p => p).join(' ');
        }
        return sanitized.match(/.{1,4}/g)?.join(' ') || sanitized;
'''
        elif self.element_type == CardElementType.CARD_EXPIRY:
            return '''
        const sanitized = value.replace(/\\//g, '').replace(/\\s/g, '');
        if (sanitized.length >= 2) {
            return sanitized.slice(0, 2) + '/' + sanitized.slice(2, 4);
        }
        return sanitized;
'''
        elif self.element_type == CardElementType.CARD_CVC:
            return 'return value.slice(0, 4);'
        return 'return value;'

    def _get_validation_script(self) -> str:
        if self.element_type == CardElementType.CARD_NUMBER:
            return '''
        const sanitized = formatted.replace(/\\s/g, '');
        if (!sanitized) return { valid: false, error: 'Your card number is incomplete.' };
        if (!/^\\d+$/.test(sanitized)) return { valid: false, error: 'Your card number is invalid.' };
        if (sanitized.length < 13 || sanitized.length > 19) return { valid: false, error: 'Your card number is invalid.' };
        return { valid: true, error: null };
'''
        elif self.element_type == CardElementType.CARD_EXPIRY:
            return '''
        if (!formatted || formatted.length < 5) return { valid: false, error: 'Your card expiration is incomplete.' };
        const parts = formatted.split('/');
        if (parts.length !== 2) return { valid: false, error: 'Your card expiration is invalid.' };
        const month = parseInt(parts[0], 10);
        if (month < 1 || month > 12) return { valid: false, error: 'Your card expiration month is invalid.' };
        return { valid: true, error: null };
'''
        elif self.element_type == CardElementType.CARD_CVC:
            return '''
        if (!formatted) return { valid: false, error: 'Your card security code is incomplete.' };
        if (!/^\\d{3,4}$/.test(formatted)) return { valid: false, error: 'Your card security code is invalid.' };
        return { valid: true, error: null };
'''
        return 'return { valid: true, error: null };'


class CardElement:
    def __init__(self, options: Optional[Dict[str, Any]] = None):
        self.options = options or {}
        self._card_number = SecureCardInput(CardElementType.CARD_NUMBER)
        self._card_expiry = SecureCardInput(CardElementType.CARD_EXPIRY)
        self._card_cvc = SecureCardInput(CardElementType.CARD_CVC)
        self._postal_code: Optional[SecureCardInput] = None
        
        if not self.options.get("hidePostalCode", True):
            self._postal_code = SecureCardInput(CardElementType.CARD_POSTAL_CODE)
        
        self._on_change_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self._on_ready_callbacks: List[Callable[[], None]] = []
        self._on_focus_callbacks: List[Callable[[], None]] = []
        self._on_blur_callbacks: List[Callable[[], None]] = []

    def mount(self, selector: str) -> None:
        pass

    def on(self, event: str, callback: Callable) -> None:
        if event == "change":
            self._on_change_callbacks.append(callback)
        elif event == "ready":
            self._on_ready_callbacks.append(callback)
        elif event == "focus":
            self._on_focus_callbacks.append(callback)
        elif event == "blur":
            self._on_blur_callbacks.append(callback)

    def add_listener(self, event: str, callback: Callable) -> None:
        self.on(event, callback)

    def update(self, options: Dict[str, Any]) -> None:
        self.options.update(options)

    def get_value(self) -> Dict[str, str]:
        return {
            "card_number": self._card_number.state.value,
            "expiry": self._card_expiry.state.value,
            "cvc": self._card_cvc.state.value,
            "postal_code": self._postal_code.state.value if self._postal_code else "",
        }

    def validate(self) -> Dict[str, Any]:
        card_valid = self._card_number.state.valid
        expiry_valid = self._card_expiry.state.valid
        cvc_valid = self._card_cvc.state.valid
        
        postal_valid = True
        if self._postal_code:
            postal_valid = self._postal_code.state.valid
        
        all_valid = card_valid and expiry_valid and cvc_valid and postal_valid
        
        return {
            "valid": all_valid,
            "card_number": {
                "valid": card_valid,
                "error": self._card_number.state.error,
            },
            "expiry": {
                "valid": expiry_valid,
                "error": self._card_expiry.state.error,
            },
            "cvc": {
                "valid": cvc_valid,
                "error": self._card_cvc.state.error,
            },
            "postal_code": {
                "valid": postal_valid,
                "error": self._postal_code.state.error if self._postal_code else None,
            },
        }

    def clear(self) -> None:
        self._card_number.clear()
        self._card_expiry.clear()
        self._card_cvc.clear()
        if self._postal_code:
            self._postal_code.clear()

    def focus(self) -> None:
        self._card_number.focus()

    def blur(self) -> None:
        self._card_number.blur()

    @property
    def brand(self) -> CardBrand:
        return self._card_number.state.brand

    @property
    def complete(self) -> bool:
        return (
            self._card_number.state.complete
            and self._card_expiry.state.complete
            and self._card_cvc.state.complete
            and (self._postal_code.state.complete if self._postal_code else True)
        )

    def render(self) -> str:
        return self._render_card_element()

    def _render_card_element(self) -> str:
        card_number = self._card_number.render()
        card_expiry = self._card_expiry.render()
        card_cvc = self._card_cvc.render()
        postal_code = self._postal_code.render() if self._postal_code else ""
        
        return f'''
<div class="card-element-container" data-card-element-container>
    <div class="card-element-row card-element-row--card-number">
        {card_number}
    </div>
    <div class="card-element-row card-element-row--expiry-cvc">
        <div class="card-element-col">
            {card_expiry}
        </div>
        <div class="card-element-col">
            {card_cvc}
        </div>
    </div>
    {f'<div class="card-element-row card-element-row--postal">{postal_code}</div>' if self._postal_code else ''}
</div>
<style>
.card-element-container {
    width: 100%;
}
.card-element-row {
    margin-bottom: 16px;
}
.card-element-row:last-child {
    margin-bottom: 0;
}
.card-element-row--expiry-cvc {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}
.card-element-col {
}
@media (max-width: 480px) {
    .card-element-row--expiry-cvc {
        grid-template-columns: 1fr;
    }
}
</style>
'''


class CardElementRenderer:
    @staticmethod
    def render(options: Optional[Dict[str, Any]] = None) -> str:
        element = CardElement(options)
        return element.render()

    @staticmethod
    def render_standalone(
        element_type: str,
        placeholder: Optional[str] = None,
        disabled: bool = False,
    ) -> str:
        type_map = {
            "cardNumber": CardElementType.CARD_NUMBER,
            "cardExpiry": CardElementType.CARD_EXPIRY,
            "cardCvc": CardElementType.CARD_CVC,
            "postalCode": CardElementType.CARD_POSTAL_CODE,
        }
        
        et = type_map.get(element_type, CardElementType.CARD_NUMBER)
        opts = CardElementOptions(
            placeholder=placeholder or "",
            disabled=disabled,
        )
        
        secure_input = SecureCardInput(et, opts)
        return secure_input.render()
