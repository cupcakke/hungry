from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class PaymentRequestStatus(Enum):
    NOT_SUPPORTED = "not_supported"
    READY = "ready"
    SHIPPING_ADDRESS_CHANGE = "shipping_address_change"
    SHIPPING_OPTION_CHANGE = "shipping_option_change"
    PAYMENT_METHOD_CHANGE = "payment_method_change"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class SupportedPaymentMethod(Enum):
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"
    BASIC_CARD = "basic-card"
    SECURE_PAYMENT_CONFIRMATION = "secure_payment_confirmation"


@dataclass
class PaymentRequestOptions:
    country: str = "US"
    currency: str = "USD"
    total_label: str = "Total"
    request_payer_name: bool = False
    request_payer_email: bool = False
    request_payer_phone: bool = False
    request_shipping: bool = False
    shipping_type: str = "shipping"


@dataclass
class PaymentAmount:
    currency: str
    value: str
    label: str = "Total"


@dataclass
class DisplayItem:
    label: str
    amount: PaymentAmount
    pending: bool = False


@dataclass
class ShippingOption:
    id: str
    label: str
    amount: PaymentAmount
    selected: bool = False


@dataclass
class ShippingAddress:
    country: Optional[str] = None
    address_line: List[str] = field(default_factory=list)
    region: Optional[str] = None
    city: Optional[str] = None
    dependent_locality: Optional[str] = None
    postal_code: Optional[str] = None
    sorting_code: Optional[str] = None
    organization: Optional[str] = None
    recipient: Optional[str] = None
    phone: Optional[str] = None


@dataclass
class PaymentMethodData:
    supported_methods: str
    data: Optional[Dict[str, Any]] = None


@dataclass
class PaymentResponse:
    request_id: str
    method_name: str
    payer_name: Optional[str] = None
    payer_email: Optional[str] = None
    payer_phone: Optional[str] = None
    shipping_address: Optional[ShippingAddress] = None
    shipping_option: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class ApplePayConfig:
    def __init__(
        self,
        merchant_identifier: str,
        supported_networks: Optional[List[str]] = None,
        supported_capabilities: Optional[List[str]] = None,
        merchant_capabilities: Optional[List[str]] = None,
        required_billing_contact_fields: Optional[List[str]] = None,
        required_shipping_contact_fields: Optional[List[str]] = None,
    ):
        self.merchant_identifier = merchant_identifier
        self.supported_networks = supported_networks or ["visa", "masterCard", "amex", "discover"]
        self.supported_capabilities = supported_capabilities or ["credit", "debit"]
        self.merchant_capabilities = merchant_capabilities or ["supports3DS"]
        self.required_billing_contact_fields = required_billing_contact_fields or []
        self.required_shipping_contact_fields = required_shipping_contact_fields or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "merchantIdentifier": self.merchant_identifier,
            "supportedNetworks": self.supported_networks,
            "supportedCapabilities": self.supported_capabilities,
            "merchantCapabilities": self.merchant_capabilities,
            "requiredBillingContactFields": self.required_billing_contact_fields,
            "requiredShippingContactFields": self.required_shipping_contact_fields,
        }


class GooglePayConfig:
    def __init__(
        self,
        merchant_id: str,
        merchant_name: str,
        allowed_card_networks: Optional[List[str]] = None,
        allowed_auth_methods: Optional[List[str]] = None,
        billing_address_required: bool = False,
        shipping_address_required: bool = False,
    ):
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.allowed_card_networks = allowed_card_networks or ["VISA", "MASTERCARD", "AMEX", "DISCOVER"]
        self.allowed_auth_methods = allowed_auth_methods or ["PAN_ONLY", "CRYPTOGRAM_3DS"]
        self.billing_address_required = billing_address_required
        self.shipping_address_required = shipping_address_required

    def to_dict(self) -> Dict[str, Any]:
        return {
            "merchantInfo": {
                "merchantId": self.merchant_id,
                "merchantName": self.merchant_name,
            },
            "allowedPaymentMethods": [
                {
                    "type": "CARD",
                    "parameters": {
                        "allowedAuthMethods": self.allowed_auth_methods,
                        "allowedCardNetworks": self.allowed_card_networks,
                        "billingAddressRequired": self.billing_address_required,
                    },
                    "tokenizationSpecification": {
                        "type": "PAYMENT_GATEWAY",
                        "parameters": {
                            "gateway": "example",
                            "gatewayMerchantId": self.merchant_id,
                        },
                    },
                }
            ],
        }


class PaymentRequestButton:
    def __init__(
        self,
        amount: int,
        currency: str,
        label: str = "Pay",
        options: Optional[PaymentRequestOptions] = None,
        apple_pay_config: Optional[ApplePayConfig] = None,
        google_pay_config: Optional[GooglePayConfig] = None,
        display_items: Optional[List[DisplayItem]] = None,
        shipping_options: Optional[List[ShippingOption]] = None,
    ):
        self.amount = amount
        self.currency = currency
        self.label = label
        self.options = options or PaymentRequestOptions()
        self.apple_pay_config = apple_pay_config
        self.google_pay_config = google_pay_config
        self.display_items = display_items or []
        self.shipping_options = shipping_options or []
        self._status = PaymentRequestStatus.READY
        self._on_shipping_address_change: Optional[Callable] = None
        self._on_shipping_option_change: Optional[Callable] = None
        self._on_payment_method_change: Optional[Callable] = None
        self._on_success: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_cancel: Optional[Callable] = None

    @property
    def status(self) -> PaymentRequestStatus:
        return self._status

    def on_shipping_address_change(self, callback: Callable) -> None:
        self._on_shipping_address_change = callback

    def on_shipping_option_change(self, callback: Callable) -> None:
        self._on_shipping_option_change = callback

    def on_payment_method_change(self, callback: Callable) -> None:
        self._on_payment_method_change = callback

    def on_success(self, callback: Callable) -> None:
        self._on_success = callback

    def on_error(self, callback: Callable) -> None:
        self._on_error = callback

    def on_cancel(self, callback: Callable) -> None:
        self._on_cancel = callback

    def can_make_payment(self) -> Dict[str, bool]:
        return {
            "apple_pay": self._check_apple_pay_availability(),
            "google_pay": self._check_google_pay_availability(),
            "basic_card": self._check_basic_card_availability(),
        }

    def _check_apple_pay_availability(self) -> bool:
        if not self.apple_pay_config:
            return False
        return True

    def _check_google_pay_availability(self) -> bool:
        if not self.google_pay_config:
            return False
        return True

    def _check_basic_card_availability(self) -> bool:
        return True

    def show(self) -> None:
        self._status = PaymentRequestStatus.PROCESSING

    def abort(self) -> None:
        self._status = PaymentRequestStatus.CANCELED

    def complete(self, success: bool = True) -> None:
        self._status = PaymentRequestStatus.SUCCEEDED if success else PaymentRequestStatus.FAILED

    def update(self, details: Dict[str, Any]) -> None:
        if "displayItems" in details:
            self.display_items = [
                DisplayItem(
                    label=item.get("label", ""),
                    amount=PaymentAmount(
                        currency=item.get("amount", {}).get("currency", self.currency),
                        value=item.get("amount", {}).get("value", "0"),
                    ),
                )
                for item in details["displayItems"]
            ]
        if "shippingOptions" in details:
            self.shipping_options = [
                ShippingOption(
                    id=opt.get("id", ""),
                    label=opt.get("label", ""),
                    amount=PaymentAmount(
                        currency=opt.get("amount", {}).get("currency", self.currency),
                        value=opt.get("amount", {}).get("value", "0"),
                    ),
                    selected=opt.get("selected", False),
                )
                for opt in details["shippingOptions"]
            ]

    def render(self, button_style: str = "default") -> str:
        return self._render_payment_request_html(button_style)

    def _render_payment_request_html(self, button_style: str) -> str:
        decimal_amount = Decimal(self.amount) / Decimal(100)
        
        apple_pay_button = self._render_apple_pay_button(button_style) if self.apple_pay_config else ""
        google_pay_button = self._render_google_pay_button(button_style) if self.google_pay_config else ""
        payment_request_button = self._render_browser_payment_button(button_style)
        
        return f'''
<div class="payment-request-container" data-payment-request>
    <div class="payment-request-buttons">
        {apple_pay_button}
        {google_pay_button}
    </div>
    
    <div class="payment-request-divider">
        <span>Or pay with card</span>
    </div>
    
    {payment_request_button}
    
    <noscript>
        <p class="payment-request-noscript">JavaScript is required for express checkout.</p>
    </noscript>
</div>
{self._get_payment_request_styles(button_style)}
{self._get_payment_request_script()}
'''

    def _render_apple_pay_button(self, style: str) -> str:
        button_type = "pay"
        button_style = "black"
        if style == "white":
            button_style = "white"
        elif style == "white-outline":
            button_style = "white-outline"
        
        return f'''
<button 
    class="apple-pay-button apple-pay-button-{button_style}" 
    data-apple-pay
    aria-label="Pay with Apple Pay"
>
    <span class="apple-pay-button-text">Pay with Apple Pay</span>
</button>
'''

    def _render_google_pay_button(self, style: str) -> str:
        button_color = "black"
        if style == "white":
            button_color = "white"
        
        return f'''
<button 
    class="google-pay-button google-pay-button-{button_color}" 
    data-google-pay
    aria-label="Pay with Google Pay"
>
    <svg class="google-pay-logo" viewBox="0 0 324 64">
        <path fill="#4285F4" d="M204.5 32.5c0-5.25-4.27-9.5-9.5-9.5s-9.5 4.25-9.5 9.5c0 5.24 4.27 9.5 9.5 9.5s9.5-4.26 9.5-9.5zm-4.15 0c0 3.28-2.4 5.56-5.35 5.56s-5.35-2.28-5.35-5.56c0-3.3 2.4-5.56 5.35-5.56s5.35 2.26 5.35 5.56z"/>
        <path fill="#EA4335" d="M224.5 32.5c0-5.25-4.27-9.5-9.5-9.5s-9.5 4.25-9.5 9.5c0 5.24 4.27 9.5 9.5 9.5s9.5-4.26 9.5-9.5zm-4.15 0c0 3.28-2.4 5.56-5.35 5.56s-5.35-2.28-5.35-5.56c0-3.3 2.4-5.56 5.35-5.56s5.35 2.26 5.35 5.56z"/>
        <path fill="#FBBC05" d="M243.5 23.5v17.6h-4.05v-2.12h-.11c-1.04 1.53-2.79 2.52-5.05 2.52-4.2 0-7.29-3.5-7.29-8.5s3.09-8.5 7.29-8.5c2.26 0 4.01.99 5.05 2.52h.11V23.5h4.05zm-4.05 9.5c0-3.28-2.17-5.56-5.02-5.56-2.9 0-5.02 2.28-5.02 5.56 0 3.27 2.12 5.56 5.02 5.56 2.85 0 5.02-2.29 5.02-5.56z"/>
        <path fill="#4285F4" d="M249.5 14.5v26h-4v-26h4z"/>
        <path fill="#34A853" d="M269.5 35.22c-.72 2.42-2.85 4.28-5.9 4.28-3.9 0-6.37-2.85-6.37-6.5 0-3.88 2.54-6.5 6.37-6.5 3.05 0 5.18 1.86 5.9 4.28l-3.77 1.57c-.34-1.23-1.04-2.12-2.13-2.12-1.47 0-2.32 1.28-2.32 2.77 0 1.66.85 2.77 2.32 2.77 1.09 0 1.79-.89 2.13-2.12l3.77 1.57z"/>
        <path fill="#EA4335" d="M289.5 23v17.6h-4v-2.12h-.11c-1.04 1.53-2.79 2.52-5.05 2.52-4.2 0-7.29-3.5-7.29-8.5s3.09-8.5 7.29-8.5c2.26 0 4.01.99 5.05 2.52h.11V23h4zm-4 9.5c0-3.28-2.17-5.56-5.02-5.56-2.9 0-5.02 2.28-5.02 5.56 0 3.27 2.12 5.56 5.02 5.56 2.85 0 5.02-2.29 5.02-5.56z"/>
        <path fill="#5F6368" d="M78 33.28v-11h3.45c2.13 0 3.54 1.35 3.54 3.44 0 2.11-1.42 3.46-3.54 3.46h-2.03v4.1H78zm3.18-6.75h-1.77v3.06h1.77c1.06 0 1.66-.64 1.66-1.53 0-.89-.6-1.53-1.66-1.53zm10.08 6.75l-.87-2.32h-3.74l-.87 2.32h-1.62l3.55-8.73h1.62l3.55 8.73h-1.62zm-2.75-7.21l-1.49 3.95h2.98l-1.49-3.95zm7.24 7.21v-7.25h-2.52v-1.48h6.58v1.48h-2.52v7.25h-1.54zm8.42 0v-8.73h5.17v1.48h-3.62v2.09h3.45v1.48h-3.45v2.21h3.62v1.48h-5.17zm9.21 0v-8.73h3.45c2.13 0 3.54 1.35 3.54 3.44 0 2.11-1.42 3.46-3.54 3.46h-1.9v4.1h-1.55zm3.18-6.75h-1.63v3.06h1.63c1.06 0 1.66-.64 1.66-1.53 0-.89-.6-1.53-1.66-1.53z"/>
    </svg>
</button>
'''

    def _render_browser_payment_button(self, style: str) -> str:
        decimal_amount = Decimal(self.amount) / Decimal(100)
        currency_symbols = {"usd": "$", "eur": "€", "gbp": "£", "jpy": "¥"}
        symbol = currency_symbols.get(self.currency.lower(), "")
        
        return f'''
<button 
    class="payment-request-fallback-button" 
    data-payment-request-button
    aria-label="Pay with browser"
>
    <span class="payment-request-fallback-text">Pay {symbol}{decimal_amount:,.2f}</span>
</button>
'''

    def _get_payment_request_styles(self, button_style: str) -> str:
        return '''
<style>
.payment-request-container {
    width: 100%;
}
.payment-request-buttons {
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.apple-pay-button {
    -webkit-appearance: -apple-pay-button;
    -apple-pay-button-type: pay;
    width: 100%;
    min-height: 44px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
}
.apple-pay-button-black {
    -apple-pay-button-style: black;
}
.apple-pay-button-white {
    -apple-pay-button-style: white;
}
.apple-pay-button-white-outline {
    -apple-pay-button-style: white-outline;
}
.apple-pay-button-text {
    display: none;
}
.google-pay-button {
    width: 100%;
    min-height: 44px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 12px 24px;
}
.google-pay-button-black {
    background: #000;
}
.google-pay-button-white {
    background: #fff;
    border: 1px solid #ddd;
}
.google-pay-logo {
    height: 24px;
    width: auto;
}
.payment-request-divider {
    display: flex;
    align-items: center;
    margin: 20px 0;
}
.payment-request-divider::before,
.payment-request-divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: #e5e7eb;
}
.payment-request-divider span {
    padding: 0 16px;
    font-size: 14px;
    color: #6b7280;
}
.payment-request-fallback-button {
    width: 100%;
    padding: 14px;
    background: #635BFF;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    transition: background-color 0.2s;
}
.payment-request-fallback-button:hover {
    background: #4F46E5;
}
.payment-request-fallback-text {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
}
.payment-request-noscript {
    color: #ef4444;
    font-size: 14px;
    text-align: center;
    padding: 20px;
}
</style>
'''

    def _get_payment_request_script(self) -> str:
        amount_str = str(Decimal(self.amount) / Decimal(100))
        
        return f'''
<script>
(function() {{
    const container = document.querySelector('[data-payment-request]');
    if (!container) return;
    
    const amount = {amount_str};
    const currency = '{self.currency.upper()}';
    const label = '{self.label}';
    const country = '{self.options.country}';
    
    const paymentDetails = {{
        total: {{
            label: label,
            amount: {{ currency: currency, value: amount }}
        }},
        displayItems: [
            {self._get_display_items_json()}
        ]
    }};
    
    const paymentOptions = {{
        requestPayerName: {str(self.options.request_payer_name).lower()},
        requestPayerEmail: {str(self.options.request_payer_email).lower()},
        requestPayerPhone: {str(self.options.request_payer_phone).lower()},
        requestShipping: {str(self.options.request_shipping).lower()},
        shippingType: '{self.options.shipping_type}'
    }};
    
    const supportedMethods = [
        {{
            supportedMethods: 'https://apple.com/apple-pay',
            data: {{
                version: 3,
                merchantIdentifier: '{self.apple_pay_config.merchant_identifier if self.apple_pay_config else ""}',
                supportedNetworks: {self._get_apple_networks_json()},
                merchantCapabilities: ['supports3DS']
            }}
        }},
        {{
            supportedMethods: 'https://google.com/pay',
            data: {{
                environment: 'PRODUCTION',
                apiVersion: 2,
                apiVersionMinor: 0,
                merchantInfo: {{
                    merchantId: '{self.google_pay_config.merchant_id if self.google_pay_config else ""}',
                    merchantName: '{self.google_pay_config.merchant_name if self.google_pay_config else ""}'
                }},
                allowedPaymentMethods: [{{
                    type: 'CARD',
                    parameters: {{
                        allowedAuthMethods: ['PAN_ONLY', 'CRYPTOGRAM_3DS'],
                        allowedCardNetworks: {self._get_google_networks_json()}
                    }}
                }}]
            }}
        }},
        {{
            supportedMethods: 'basic-card',
            data: {{
                supportedNetworks: ['visa', 'mastercard', 'amex', 'discover']
            }}
        }}
    ];
    
    let paymentRequest = null;
    
    async function initPaymentRequest() {{
        if (!window.PaymentRequest) {{
            console.log('Payment Request API not supported');
            hideExpressButtons();
            return;
        }}
        
        try {{
            paymentRequest = new PaymentRequest(supportedMethods, paymentDetails, paymentOptions);
            
            paymentRequest.onshippingaddresschange = function(e) {{
                e.updateWith(new Promise(function(resolve) {{
                    resolve({{
                        total: paymentDetails.total,
                        shippingOptions: []
                    }});
                }}));
            }};
            
            paymentRequest.onshippingoptionchange = function(e) {{
                e.updateWith(new Promise(function(resolve) {{
                    resolve({{ total: paymentDetails.total }});
                }}));
            }};
            
            paymentRequest.onpaymentmethodchange = function(e) {{
                e.updateWith(new Promise(function(resolve) {{
                    resolve({{ total: paymentDetails.total }});
                }}));
            }};
            
            const canMakePayment = await paymentRequest.canMakePayment();
            if (!canMakePayment) {{
                console.log('Cannot make payment');
                hideExpressButtons();
            }}
        }} catch (err) {{
            console.error('Payment Request init error:', err);
            hideExpressButtons();
        }}
    }}
    
    function hideExpressButtons() {{
        const appleBtn = container.querySelector('[data-apple-pay]');
        const googleBtn = container.querySelector('[data-google-pay]');
        const divider = container.querySelector('.payment-request-divider');
        
        if (appleBtn) appleBtn.style.display = 'none';
        if (googleBtn) googleBtn.style.display = 'none';
        if (divider) divider.style.display = 'none';
    }}
    
    async function handlePayment() {{
        if (!paymentRequest) {{
            console.log('Payment request not initialized');
            return;
        }}
        
        try {{
            const response = await paymentRequest.show();
            
            await response.complete('success');
            
            console.log('Payment successful:', response);
            
        }} catch (err) {{
            if (err.name === 'AbortError') {{
                console.log('Payment aborted');
            }} else {{
                console.error('Payment error:', err);
            }}
        }}
    }}
    
    const appleBtn = container.querySelector('[data-apple-pay]');
    const googleBtn = container.querySelector('[data-google-pay]');
    const fallbackBtn = container.querySelector('[data-payment-request-button]');
    
    if (appleBtn) {{
        appleBtn.addEventListener('click', handlePayment);
    }}
    if (googleBtn) {{
        googleBtn.addEventListener('click', handlePayment);
    }}
    if (fallbackBtn) {{
        fallbackBtn.addEventListener('click', handlePayment);
    }}
    
    initPaymentRequest();
}})();
</script>
'''

    def _get_display_items_json(self) -> str:
        items = []
        for item in self.display_items:
            items.append(f'''{{
                label: '{item.label}',
                amount: {{ currency: '{item.amount.currency}', value: '{item.amount.value}' }}
            }}''')
        return ', '.join(items)

    def _get_apple_networks_json(self) -> str:
        if self.apple_pay_config:
            networks = [f"'{n}'" for n in self.apple_pay_config.supported_networks]
            return '[' + ', '.join(networks) + ']'
        return "['visa', 'masterCard', 'amex', 'discover']"

    def _get_google_networks_json(self) -> str:
        if self.google_pay_config:
            networks = [f"'{n}'" for n in self.google_pay_config.allowed_card_networks]
            return '[' + ', '.join(networks) + ']'
        return "['VISA', 'MASTERCARD', 'AMEX', 'DISCOVER']"


class PaymentRequestButtonRenderer:
    @staticmethod
    def render(
        amount: int,
        currency: str,
        label: str = "Pay",
        options: Optional[Dict[str, Any]] = None,
        apple_pay_config: Optional[Dict[str, Any]] = None,
        google_pay_config: Optional[Dict[str, Any]] = None,
        button_style: str = "default",
    ) -> str:
        opts = PaymentRequestOptions(**options) if options else PaymentRequestOptions()
        
        apple_config = None
        if apple_pay_config:
            apple_config = ApplePayConfig(**apple_pay_config)
        
        google_config = None
        if google_pay_config:
            google_config = GooglePayConfig(**google_pay_config)
        
        button = PaymentRequestButton(
            amount=amount,
            currency=currency,
            label=label,
            options=opts,
            apple_pay_config=apple_config,
            google_pay_config=google_config,
        )
        
        return button.render(button_style)
