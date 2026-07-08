from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


class PaymentMethodType(Enum):
    CARD = "card"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"
    BANK_TRANSFER = "bank_transfer"
    KLARNA = "klarna"
    AFTERPAY = "afterpay"
    PAYPAL = "paypal"


class CheckoutStatus(Enum):
    INITIALIZED = "initialized"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REQUIRES_ACTION = "requires_action"


@dataclass
class LineItem:
    id: str
    name: str
    description: Optional[str] = None
    quantity: int = 1
    unit_amount: int = 0
    currency: str = "usd"
    image_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_amount(self) -> int:
        return self.unit_amount * self.quantity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "quantity": self.quantity,
            "unit_amount": self.unit_amount,
            "currency": self.currency,
            "total_amount": self.total_amount,
            "image_url": self.image_url,
        }


@dataclass
class CustomerInfo:
    email: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "name": self.name,
            "phone": self.phone,
            "address": {
                "line1": self.address_line1,
                "line2": self.address_line2,
                "city": self.city,
                "state": self.state,
                "postal_code": self.postal_code,
                "country": self.country,
            },
        }


@dataclass
class ShippingOption:
    id: str
    name: str
    amount: int
    currency: str = "usd"
    estimated_days: Optional[int] = None
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "amount": self.amount,
            "currency": self.currency,
            "estimated_days": self.estimated_days,
            "description": self.description,
        }


@dataclass
class CheckoutSession:
    id: str
    amount_total: int
    currency: str
    line_items: List[LineItem] = field(default_factory=list)
    customer_info: Optional[CustomerInfo] = None
    payment_method_types: List[PaymentMethodType] = field(default_factory=lambda: [PaymentMethodType.CARD])
    shipping_options: List[ShippingOption] = field(default_factory=list)
    selected_shipping: Optional[str] = None
    status: CheckoutStatus = CheckoutStatus.INITIALIZED
    client_secret: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def amount_subtotal(self) -> int:
        return sum(item.total_amount for item in self.line_items)

    @property
    def shipping_amount(self) -> int:
        if not self.selected_shipping:
            return 0
        for option in self.shipping_options:
            if option.id == self.selected_shipping:
                return option.amount
        return 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "amount_total": self.amount_total,
            "amount_subtotal": self.amount_subtotal,
            "shipping_amount": self.shipping_amount,
            "currency": self.currency,
            "line_items": [item.to_dict() for item in self.line_items],
            "customer_info": self.customer_info.to_dict() if self.customer_info else None,
            "payment_method_types": [p.value for p in self.payment_method_types],
            "shipping_options": [opt.to_dict() for opt in self.shipping_options],
            "selected_shipping": self.selected_shipping,
            "status": self.status.value,
        }


@dataclass
class CheckoutOptions:
    brand_color: str = "#635BFF"
    brand_name: str = "Checkout"
    logo_url: Optional[str] = None
    submit_button_text: str = "Pay"
    show_line_items: bool = True
    show_shipping_options: bool = True
    show_customer_form: bool = True
    require_shipping_address: bool = False
    require_billing_address: bool = False
    success_message: str = "Payment successful!"
    custom_css: Optional[str] = None
    locale: str = "en"


class CheckoutPage:
    def __init__(self, session: CheckoutSession, options: Optional[CheckoutOptions] = None):
        self.session = session
        self.options = options or CheckoutOptions()
        self._validation_errors: Dict[str, str] = {}
        self._payment_error: Optional[str] = None

    def set_customer_info(self, info: CustomerInfo) -> None:
        self.session.customer_info = info

    def set_shipping(self, shipping_id: str) -> bool:
        for option in self.session.shipping_options:
            if option.id == shipping_id:
                self.session.selected_shipping = shipping_id
                return True
        return False

    def validate_customer_info(self) -> Dict[str, str]:
        errors = {}
        info = self.session.customer_info
        
        if not info or not info.email:
            errors["email"] = "Email is required"
        elif "@" not in info.email:
            errors["email"] = "Please enter a valid email"
        
        if self.options.require_billing_address:
            if not info or not info.address_line1:
                errors["address_line1"] = "Address is required"
            if not info or not info.city:
                errors["city"] = "City is required"
            if not info or not info.postal_code:
                errors["postal_code"] = "Postal code is required"
            if not info or not info.country:
                errors["country"] = "Country is required"
        
        self._validation_errors = errors
        return errors

    def render(self) -> str:
        return self._render_checkout_html()

    def render_success(self) -> str:
        return self._render_success_html()

    def render_error(self, message: str) -> str:
        self._payment_error = message
        return self._render_checkout_html()

    def _render_checkout_html(self) -> str:
        opts = self.options
        brand_color = opts.brand_color
        
        return f'''
<!DOCTYPE html>
<html lang="{opts.locale}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Checkout - {opts.brand_name}</title>
    {self._get_base_styles()}
    {f'<style>{opts.custom_css}</style>' if opts.custom_css else ''}
</head>
<body>
    <div class="checkout-container" data-checkout-id="{self.session.id}">
        <div class="checkout-header">
            {f'<img src="{opts.logo_url}" alt="{opts.brand_name}" class="checkout-logo">' if opts.logo_url else f'<div class="checkout-brand">{opts.brand_name}</div>'}
        </div>
        
        <div class="checkout-main">
            <div class="checkout-left">
                {self._render_line_items_section() if opts.show_line_items else ''}
                {self._render_customer_form() if opts.show_customer_form else ''}
                {self._render_shipping_section() if opts.show_shipping_options and self.session.shipping_options else ''}
            </div>
            
            <div class="checkout-right">
                <div class="checkout-summary">
                    <h3 class="checkout-summary-title">Order Summary</h3>
                    {self._render_summary_items()}
                    {self._render_summary_shipping()}
                    <div class="checkout-summary-total">
                        <span>Total</span>
                        <span class="checkout-amount">{self._format_amount(self.session.amount_total, self.session.currency)}</span>
                    </div>
                </div>
                
                {self._render_payment_section()}
                
                {self._render_payment_error() if self._payment_error else ''}
                
                <button type="button" class="checkout-submit" data-checkout-submit>
                    <span class="checkout-submit-text">{opts.submit_button_text}</span>
                    <span class="checkout-submit-amount">{self._format_amount(self.session.amount_total, self.session.currency)}</span>
                </button>
                
                <div class="checkout-secure">
                    <svg class="checkout-secure-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M12 1C8.676 1 6 3.676 6 7v2H4v14h16V9h-2V7c0-3.324-2.676-6-6-6zm0 2c2.276 0 4 1.724 4 4v2H8V7c0-2.276 1.724-4 4-4zm0 10c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2z"/></svg>
                    <span>Secure payment powered by {opts.brand_name}</span>
                </div>
            </div>
        </div>
    </div>
    {self._get_checkout_script()}
</body>
</html>
'''

    def _render_line_items_section(self) -> str:
        items_html = ""
        for item in self.session.line_items:
            items_html += f'''
            <div class="checkout-item">
                {f'<img src="{item.image_url}" alt="{item.name}" class="checkout-item-image">' if item.image_url else '<div class="checkout-item-placeholder"></div>'}
                <div class="checkout-item-details">
                    <div class="checkout-item-name">{item.name}</div>
                    {f'<div class="checkout-item-desc">{item.description}</div>' if item.description else ''}
                    <div class="checkout-item-qty">Qty: {item.quantity}</div>
                </div>
                <div class="checkout-item-price">{self._format_amount(item.total_amount, item.currency)}</div>
            </div>
            '''
        
        return f'''
        <div class="checkout-section">
            <h2 class="checkout-section-title">Your Items</h2>
            <div class="checkout-items">
                {items_html}
            </div>
        </div>
        '''

    def _render_customer_form(self) -> str:
        info = self.session.customer_info or CustomerInfo()
        errors = self._validation_errors
        
        return f'''
        <div class="checkout-section">
            <h2 class="checkout-section-title">Contact Information</h2>
            <div class="checkout-form">
                <div class="checkout-field">
                    <label for="customer_email">Email</label>
                    <input type="email" id="customer_email" name="customer_email" value="{info.email or ''}" placeholder="you@example.com" required>
                    {f'<span class="checkout-error">{errors.get("email", "")}</span>' if "email" in errors else ''}
                </div>
                <div class="checkout-row">
                    <div class="checkout-field">
                        <label for="customer_name">Name</label>
                        <input type="text" id="customer_name" name="customer_name" value="{info.name or ''}" placeholder="Full name">
                    </div>
                    <div class="checkout-field">
                        <label for="customer_phone">Phone</label>
                        <input type="tel" id="customer_phone" name="customer_phone" value="{info.phone or ''}" placeholder="+1 (555) 000-0000">
                    </div>
                </div>
                {self._render_address_fields(info, errors) if self.options.require_billing_address else ''}
            </div>
        </div>
        '''

    def _render_address_fields(self, info: CustomerInfo, errors: Dict[str, str]) -> str:
        return f'''
        <div class="checkout-address">
            <div class="checkout-field">
                <label for="address_line1">Address</label>
                <input type="text" id="address_line1" name="address_line1" value="{info.address_line1 or ''}" placeholder="Street address">
                {f'<span class="checkout-error">{errors.get("address_line1", "")}</span>' if "address_line1" in errors else ''}
            </div>
            <div class="checkout-field">
                <label for="address_line2">Apt, suite, etc. (optional)</label>
                <input type="text" id="address_line2" name="address_line2" value="{info.address_line2 or ''}" placeholder="Apartment, suite, etc.">
            </div>
            <div class="checkout-row checkout-row--3">
                <div class="checkout-field">
                    <label for="city">City</label>
                    <input type="text" id="city" name="city" value="{info.city or ''}" placeholder="City">
                    {f'<span class="checkout-error">{errors.get("city", "")}</span>' if "city" in errors else ''}
                </div>
                <div class="checkout-field">
                    <label for="state">State</label>
                    <input type="text" id="state" name="state" value="{info.state or ''}" placeholder="State">
                </div>
                <div class="checkout-field">
                    <label for="postal_code">ZIP</label>
                    <input type="text" id="postal_code" name="postal_code" value="{info.postal_code or ''}" placeholder="ZIP code">
                    {f'<span class="checkout-error">{errors.get("postal_code", "")}</span>' if "postal_code" in errors else ''}
                </div>
            </div>
            <div class="checkout-field">
                <label for="country">Country</label>
                <select id="country" name="country">
                    <option value="">Select country</option>
                    <option value="US" {'selected' if info.country == 'US' else ''}>United States</option>
                    <option value="CA" {'selected' if info.country == 'CA' else ''}>Canada</option>
                    <option value="GB" {'selected' if info.country == 'GB' else ''}>United Kingdom</option>
                    <option value="AU" {'selected' if info.country == 'AU' else ''}>Australia</option>
                    <option value="DE" {'selected' if info.country == 'DE' else ''}>Germany</option>
                    <option value="FR" {'selected' if info.country == 'FR' else ''}>France</option>
                </select>
                {f'<span class="checkout-error">{errors.get("country", "")}</span>' if "country" in errors else ''}
            </div>
        </div>
        '''

    def _render_shipping_section(self) -> str:
        options_html = ""
        for option in self.session.shipping_options:
            is_selected = option.id == self.session.selected_shipping
            options_html += f'''
            <label class="checkout-shipping-option{' checkout-shipping-option--selected' if is_selected else ''}" data-shipping-id="{option.id}">
                <input type="radio" name="shipping_option" value="{option.id}" {'checked' if is_selected else ''}>
                <div class="checkout-shipping-content">
                    <div class="checkout-shipping-name">{option.name}</div>
                    {f'<div class="checkout-shipping-desc">{option.description}</div>' if option.description else ''}
                    {f'<div class="checkout-shipping-days">{option.estimated_days} business days</div>' if option.estimated_days else ''}
                </div>
                <div class="checkout-shipping-price">{self._format_amount(option.amount, option.currency)}</div>
            </label>
            '''
        
        return f'''
        <div class="checkout-section">
            <h2 class="checkout-section-title">Shipping Method</h2>
            <div class="checkout-shipping">
                {options_html}
            </div>
        </div>
        '''

    def _render_payment_section(self) -> str:
        payment_methods = self.session.payment_method_types
        available_methods = []
        
        if PaymentMethodType.CARD in payment_methods:
            available_methods.append(self._render_card_payment())
        if PaymentMethodType.APPLE_PAY in payment_methods:
            available_methods.append(self._render_apple_pay())
        if PaymentMethodType.GOOGLE_PAY in payment_methods:
            available_methods.append(self._render_google_pay())
        if PaymentMethodType.PAYPAL in payment_methods:
            available_methods.append(self._render_paypal())
        
        return f'''
        <div class="checkout-payment">
            <h3 class="checkout-payment-title">Payment Method</h3>
            <div class="checkout-payment-methods">
                {''.join(available_methods)}
            </div>
            <div class="checkout-payment-form" data-payment-form>
                {self._render_card_form()}
            </div>
        </div>
        '''

    def _render_card_payment(self) -> str:
        return f'''
        <label class="checkout-payment-method checkout-payment-method--selected" data-payment-type="card">
            <input type="radio" name="payment_method_type" value="card" checked>
            <div class="checkout-payment-icon">
                <svg viewBox="0 0 24 24"><path fill="currentColor" d="M20 4H4c-1.11 0-1.99.89-1.99 2L2 18c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V6c0-1.11-.89-2-2-2zm0 14H4v-6h16v6zm0-10H4V6h16v2z"/></svg>
            </div>
            <span>Card</span>
        </label>
        '''

    def _render_apple_pay(self) -> str:
        return '''
        <label class="checkout-payment-method" data-payment-type="apple_pay">
            <input type="radio" name="payment_method_type" value="apple_pay">
            <div class="checkout-payment-icon checkout-payment-icon--apple">
                <svg viewBox="0 0 24 24"><path fill="currentColor" d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/></svg>
            </div>
            <span>Apple Pay</span>
        </label>
        '''

    def _render_google_pay(self) -> str:
        return '''
        <label class="checkout-payment-method" data-payment-type="google_pay">
            <input type="radio" name="payment_method_type" value="google_pay">
            <div class="checkout-payment-icon checkout-payment-icon--google">
                <svg viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            </div>
            <span>Google Pay</span>
        </label>
        '''

    def _render_paypal(self) -> str:
        return '''
        <label class="checkout-payment-method" data-payment-type="paypal">
            <input type="radio" name="payment_method_type" value="paypal">
            <div class="checkout-payment-icon checkout-payment-icon--paypal">
                <svg viewBox="0 0 24 24"><path fill="#003087" d="M7.076 21.337H2.47a.641.641 0 0 1-.633-.74L4.944 3.72a.77.77 0 0 1 .757-.64h6.68c2.21 0 3.94.48 5.14 1.43 1.21.95 1.63 2.36 1.27 4.18-.28 1.4-.86 2.55-1.73 3.42-.87.87-1.9 1.48-3.06 1.81-1.12.32-2.47.48-4.01.48H7.71a.77.77 0 0 0-.76.64l-.87 5.29z"/><path fill="#0070E0" d="M21.81 8.34c-.07.46-.16.93-.27 1.42-1.18 5.44-5.21 7.33-10.35 7.33H8.49a1.27 1.27 0 0 0-1.26 1.07l-1.34 8.5a.67.67 0 0 0 .66.77h4.63c.38 0 .7-.27.76-.64l.03-.17.58-3.68.04-.2a.77.77 0 0 1 .76-.64h.48c3.1 0 5.53-1.26 6.24-4.91.3-1.52.14-2.78-.63-3.67a3.02 3.02 0 0 0-1.63-1.18z"/></svg>
            </div>
            <span>PayPal</span>
        </label>
        '''

    def _render_card_form(self) -> str:
        return f'''
        <div class="checkout-card-form">
            <div class="checkout-field">
                <label for="card_number">Card number</label>
                <div class="checkout-card-input">
                    <input type="text" id="card_number" name="card_number" placeholder="1234 5678 9012 3456" autocomplete="cc-number" maxlength="19" data-card-number>
                    <div class="checkout-card-brand" data-card-brand></div>
                </div>
            </div>
            <div class="checkout-row">
                <div class="checkout-field">
                    <label for="card_expiry">Expiry</label>
                    <input type="text" id="card_expiry" name="card_expiry" placeholder="MM/YY" autocomplete="cc-exp" maxlength="5" data-card-expiry>
                </div>
                <div class="checkout-field">
                    <label for="card_cvc">CVC</label>
                    <input type="text" id="card_cvc" name="card_cvc" placeholder="123" autocomplete="cc-csc" maxlength="4" data-card-cvc>
                </div>
            </div>
        </div>
        '''

    def _render_summary_items(self) -> str:
        items_html = ""
        for item in self.session.line_items:
            items_html += f'''
            <div class="checkout-summary-item">
                <span>{item.name} x{item.quantity}</span>
                <span>{self._format_amount(item.total_amount, item.currency)}</span>
            </div>
            '''
        return items_html

    def _render_summary_shipping(self) -> str:
        if not self.session.selected_shipping:
            return ""
        shipping_amount = self.shipping_amount
        return f'''
        <div class="checkout-summary-shipping">
            <span>Shipping</span>
            <span>{self._format_amount(shipping_amount, self.session.currency) if shipping_amount > 0 else 'Free'}</span>
        </div>
        '''

    def _render_payment_error(self) -> str:
        if not self._payment_error:
            return ""
        return f'''
        <div class="checkout-payment-error">
            <svg class="checkout-payment-error-icon" viewBox="0 0 24 24"><path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>
            <span>{self._payment_error}</span>
        </div>
        '''

    def _render_success_html(self) -> str:
        opts = self.options
        return f'''
<!DOCTYPE html>
<html lang="{opts.locale}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Successful - {opts.brand_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #f6f9fc 0%, #eef2f7 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .success-container {{
            max-width: 420px;
            width: 100%;
            background: white;
            border-radius: 16px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.1);
            text-align: center;
            padding: 48px 32px;
        }}
        .success-icon {{
            width: 80px;
            height: 80px;
            margin: 0 auto 24px;
            background: #10b981;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .success-icon svg {{
            width: 40px;
            height: 40px;
            fill: white;
        }}
        .success-title {{
            font-size: 24px;
            font-weight: 600;
            color: #111827;
            margin-bottom: 12px;
        }}
        .success-message {{
            font-size: 16px;
            color: #6b7280;
            margin-bottom: 24px;
        }}
        .success-details {{
            background: #f9fafb;
            border-radius: 12px;
            padding: 16px;
            text-align: left;
        }}
        .success-detail-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #e5e7eb;
        }}
        .success-detail-row:last-child {{ border-bottom: none; }}
        .success-detail-label {{ color: #6b7280; font-size: 14px; }}
        .success-detail-value {{ color: #111827; font-weight: 500; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="success-container">
        <div class="success-icon">
            <svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>
        </div>
        <h1 class="success-title">Payment Successful!</h1>
        <p class="success-message">{opts.success_message}</p>
        <div class="success-details">
            <div class="success-detail-row">
                <span class="success-detail-label">Amount</span>
                <span class="success-detail-value">{self._format_amount(self.session.amount_total, self.session.currency)}</span>
            </div>
            <div class="success-detail-row">
                <span class="success-detail-label">Reference</span>
                <span class="success-detail-value">{self.session.id}</span>
            </div>
        </div>
    </div>
</body>
</html>
'''

    def _get_base_styles(self) -> str:
        brand_color = self.options.brand_color
        return f'''
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #f6f9fc;
        min-height: 100vh;
    }}
    .checkout-container {{
        max-width: 1000px;
        margin: 0 auto;
        padding: 24px;
    }}
    .checkout-header {{
        padding: 16px 0;
        border-bottom: 1px solid #e5e7eb;
        margin-bottom: 24px;
    }}
    .checkout-logo {{ height: 40px; }}
    .checkout-brand {{
        font-size: 24px;
        font-weight: 700;
        color: {brand_color};
    }}
    .checkout-main {{
        display: grid;
        grid-template-columns: 1fr 400px;
        gap: 32px;
    }}
    .checkout-left {{ }}
    .checkout-right {{
        position: sticky;
        top: 24px;
        height: fit-content;
    }}
    .checkout-section {{
        background: white;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    .checkout-section-title {{
        font-size: 18px;
        font-weight: 600;
        color: #111827;
        margin-bottom: 16px;
    }}
    .checkout-items {{ }}
    .checkout-item {{
        display: flex;
        align-items: center;
        padding: 12px 0;
        border-bottom: 1px solid #f3f4f6;
    }}
    .checkout-item:last-child {{ border-bottom: none; }}
    .checkout-item-image {{
        width: 64px;
        height: 64px;
        border-radius: 8px;
        object-fit: cover;
        margin-right: 16px;
    }}
    .checkout-item-placeholder {{
        width: 64px;
        height: 64px;
        border-radius: 8px;
        background: #e5e7eb;
        margin-right: 16px;
    }}
    .checkout-item-details {{ flex: 1; }}
    .checkout-item-name {{
        font-size: 14px;
        font-weight: 500;
        color: #111827;
    }}
    .checkout-item-desc {{
        font-size: 12px;
        color: #6b7280;
        margin-top: 2px;
    }}
    .checkout-item-qty {{
        font-size: 12px;
        color: #9ca3af;
        margin-top: 4px;
    }}
    .checkout-item-price {{
        font-size: 14px;
        font-weight: 500;
        color: #111827;
    }}
    .checkout-form {{ }}
    .checkout-field {{ margin-bottom: 16px; }}
    .checkout-field:last-child {{ margin-bottom: 0; }}
    .checkout-field label {{
        display: block;
        font-size: 14px;
        font-weight: 500;
        color: #374151;
        margin-bottom: 6px;
    }}
    .checkout-field input,
    .checkout-field select {{
        width: 100%;
        padding: 12px 14px;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        font-size: 16px;
        transition: border-color 0.2s, box-shadow 0.2s;
    }}
    .checkout-field input:focus,
    .checkout-field select:focus {{
        outline: none;
        border-color: {brand_color};
        box-shadow: 0 0 0 3px {brand_color}33;
    }}
    .checkout-error {{
        font-size: 13px;
        color: #ef4444;
        margin-top: 4px;
        display: block;
    }}
    .checkout-row {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
    }}
    .checkout-row--3 {{
        grid-template-columns: 2fr 1fr 1fr;
    }}
    .checkout-shipping {{ }}
    .checkout-shipping-option {{
        display: flex;
        align-items: center;
        padding: 16px;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        margin-bottom: 8px;
        cursor: pointer;
        transition: all 0.2s;
    }}
    .checkout-shipping-option:hover {{ border-color: {brand_color}; }}
    .checkout-shipping-option--selected {{
        border-color: {brand_color};
        background: {brand_color}0d;
    }}
    .checkout-shipping-option input {{ margin-right: 12px; }}
    .checkout-shipping-content {{ flex: 1; }}
    .checkout-shipping-name {{
        font-size: 14px;
        font-weight: 500;
        color: #111827;
    }}
    .checkout-shipping-desc {{
        font-size: 12px;
        color: #6b7280;
        margin-top: 2px;
    }}
    .checkout-shipping-days {{
        font-size: 12px;
        color: #9ca3af;
        margin-top: 4px;
    }}
    .checkout-shipping-price {{
        font-size: 14px;
        font-weight: 500;
        color: #111827;
    }}
    .checkout-summary {{
        background: white;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    .checkout-summary-title {{
        font-size: 18px;
        font-weight: 600;
        color: #111827;
        margin-bottom: 16px;
    }}
    .checkout-summary-item {{
        display: flex;
        justify-content: space-between;
        padding: 8px 0;
        font-size: 14px;
        color: #6b7280;
    }}
    .checkout-summary-shipping {{
        display: flex;
        justify-content: space-between;
        padding: 8px 0;
        border-top: 1px solid #f3f4f6;
        font-size: 14px;
        color: #6b7280;
    }}
    .checkout-summary-total {{
        display: flex;
        justify-content: space-between;
        padding: 16px 0;
        border-top: 1px solid #e5e7eb;
        margin-top: 8px;
        font-size: 18px;
        font-weight: 600;
        color: #111827;
    }}
    .checkout-amount {{ color: {brand_color}; }}
    .checkout-payment {{
        background: white;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    .checkout-payment-title {{
        font-size: 18px;
        font-weight: 600;
        color: #111827;
        margin-bottom: 16px;
    }}
    .checkout-payment-methods {{
        display: flex;
        gap: 8px;
        margin-bottom: 16px;
    }}
    .checkout-payment-method {{
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 12px;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s;
    }}
    .checkout-payment-method:hover {{ border-color: {brand_color}; }}
    .checkout-payment-method--selected {{
        border-color: {brand_color};
        background: {brand_color}0d;
    }}
    .checkout-payment-method input {{ display: none; }}
    .checkout-payment-icon {{
        width: 24px;
        height: 24px;
        margin-right: 8px;
    }}
    .checkout-payment-icon svg {{ width: 100%; height: 100%; }}
    .checkout-card-form {{ }}
    .checkout-card-input {{
        position: relative;
    }}
    .checkout-card-input input {{
        padding-right: 50px;
    }}
    .checkout-card-brand {{
        position: absolute;
        right: 12px;
        top: 50%;
        transform: translateY(-50%);
        width: 32px;
        height: 20px;
    }}
    .checkout-payment-error {{
        display: flex;
        align-items: center;
        padding: 12px;
        background: #fef2f2;
        border: 1px solid #fecaca;
        border-radius: 8px;
        margin-bottom: 16px;
    }}
    .checkout-payment-error-icon {{
        width: 20px;
        height: 20px;
        margin-right: 8px;
        fill: #ef4444;
    }}
    .checkout-payment-error span {{
        font-size: 14px;
        color: #991b1b;
    }}
    .checkout-submit {{
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 16px;
        background: {brand_color};
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
    }}
    .checkout-submit:hover {{ filter: brightness(1.1); }}
    .checkout-submit:active {{ transform: scale(0.98); }}
    .checkout-submit-text {{ }}
    .checkout-submit-amount {{
        background: rgba(255,255,255,0.2);
        padding: 4px 12px;
        border-radius: 4px;
    }}
    .checkout-secure {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        margin-top: 16px;
        font-size: 12px;
        color: #6b7280;
    }}
    .checkout-secure-icon {{
        width: 16px;
        height: 16px;
        fill: #6b7280;
    }}
    @media (max-width: 768px) {{
        .checkout-main {{
            grid-template-columns: 1fr;
        }}
        .checkout-right {{
            position: static;
            order: -1;
        }}
        .checkout-row {{
            grid-template-columns: 1fr;
        }}
        .checkout-row--3 {{
            grid-template-columns: 1fr;
        }}
    }}
</style>
'''

    def _get_checkout_script(self) -> str:
        return '''
<script>
(function() {
    const container = document.querySelector('[data-checkout-id]');
    if (!container) return;
    
    const cardInput = container.querySelector('[data-card-number]');
    const expiryInput = container.querySelector('[data-card-expiry]');
    const submitBtn = container.querySelector('[data-checkout-submit]');
    
    function formatCardNumber(value) {
        const sanitized = value.replace(/\\s/g, '').replace(/-/g, '');
        if (/^3[47]/.test(sanitized)) {
            return [sanitized.slice(0,4), sanitized.slice(4,10), sanitized.slice(10,15)].filter(Boolean).join(' ');
        }
        return sanitized.match(/.{1,4}/g)?.join(' ') || sanitized;
    }
    
    function formatExpiry(value) {
        const sanitized = value.replace(/\\//g, '').replace(/\\s/g, '');
        if (sanitized.length >= 2) {
            return sanitized.slice(0, 2) + '/' + sanitized.slice(2, 4);
        }
        return sanitized;
    }
    
    cardInput?.addEventListener('input', function(e) {
        e.target.value = formatCardNumber(e.target.value);
    });
    
    expiryInput?.addEventListener('input', function(e) {
        e.target.value = formatExpiry(e.target.value);
    });
    
    container.querySelectorAll('.checkout-shipping-option').forEach(option => {
        option.addEventListener('click', function() {
            container.querySelectorAll('.checkout-shipping-option').forEach(o => {
                o.classList.remove('checkout-shipping-option--selected');
            });
            this.classList.add('checkout-shipping-option--selected');
            this.querySelector('input').checked = true;
        });
    });
    
    container.querySelectorAll('.checkout-payment-method').forEach(method => {
        method.addEventListener('click', function() {
            container.querySelectorAll('.checkout-payment-method').forEach(m => {
                m.classList.remove('checkout-payment-method--selected');
            });
            this.classList.add('checkout-payment-method--selected');
            this.querySelector('input').checked = true;
            
            const type = this.dataset.paymentType;
            const cardForm = container.querySelector('.checkout-card-form');
            if (cardForm) {
                cardForm.style.display = type === 'card' ? 'block' : 'none';
            }
        });
    });
    
    submitBtn?.addEventListener('click', function() {
        this.disabled = true;
        this.innerHTML = '<span class="checkout-submit-text">Processing...</span>';
    });
})();
</script>
'''

    def _format_amount(self, amount: int, currency: str) -> str:
        decimal_amount = Decimal(amount) / Decimal(100)
        currency_symbols = {
            "usd": "$", "eur": "€", "gbp": "£", "jpy": "¥",
            "cad": "C$", "aud": "A$", "chf": "CHF", "cny": "¥"
        }
        symbol = currency_symbols.get(currency.lower(), currency.upper())
        return f"{symbol}{decimal_amount:,.2f}"


class CheckoutPageRenderer:
    @staticmethod
    def render(
        session_id: str,
        amount: int,
        currency: str,
        line_items: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        items = [
            LineItem(
                id=item.get("id", ""),
                name=item.get("name", ""),
                description=item.get("description"),
                quantity=item.get("quantity", 1),
                unit_amount=item.get("unit_amount", 0),
                currency=item.get("currency", currency),
                image_url=item.get("image_url"),
            )
            for item in line_items
        ]
        
        opts = CheckoutOptions(**options) if options else CheckoutOptions()
        
        session = CheckoutSession(
            id=session_id,
            amount_total=amount,
            currency=currency,
            line_items=items,
        )
        
        page = CheckoutPage(session, opts)
        return page.render()
