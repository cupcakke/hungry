class PaymentProcessor {
    constructor(options) {
        this.publishableKey = options.publishableKey;
        this.clientSecret = options.clientSecret;
        this.amount = options.amount;
        this.currency = options.currency;
        this.returnUrl = options.returnUrl || window.location.href;
        this.onSuccess = options.onSuccess || (() => {});
        this.onError = options.onError || (() => {});
        this.onProcessing = options.onProcessing || (() => {});
        this.container = document.getElementById(options.containerId || 'payment-form');
    }

    async init() {
        this.setupEventListeners();
        this.setupCardElement();
        await this.loadPaymentRequest();
    }

    setupEventListeners() {
        const form = this.container.querySelector('form');
        if (form) {
            form.addEventListener('submit', (e) => this.handleSubmit(e));
        }

        const cardNumber = this.container.querySelector('[data-card-number]');
        if (cardNumber) {
            cardNumber.addEventListener('input', (e) => this.formatCardNumber(e));
            cardNumber.addEventListener('input', (e) => this.detectCardBrand(e));
        }

        const expiry = this.container.querySelector('[data-expiry]');
        if (expiry) {
            expiry.addEventListener('input', (e) => this.formatExpiry(e));
        }

        const cvc = this.container.querySelector('[data-cvc]');
        if (cvc) {
            cvc.addEventListener('input', (e) => this.formatCvc(e));
        }
    }

    setupCardElement() {
        const cardElement = this.container.querySelector('.card-element');
        if (cardElement) {
            cardElement.innerHTML = this.getCardElementHTML();
        }
    }

    getCardElementHTML() {
        return `
            <div class="card-element-wrapper">
                <div class="card-number-wrapper">
                    <input type="text" 
                           data-card-number 
                           placeholder="Card number" 
                           maxlength="19"
                           autocomplete="cc-number"
                           class="form-input card-number-input">
                    <div class="card-brand-icon"></div>
                </div>
                <div class="card-details-row">
                    <input type="text" 
                           data-expiry 
                           placeholder="MM / YY" 
                           maxlength="7"
                           autocomplete="cc-exp"
                           class="form-input">
                    <input type="text" 
                           data-cvc 
                           placeholder="CVC" 
                           maxlength="4"
                           autocomplete="cc-csc"
                           class="form-input">
                </div>
            </div>
        `;
    }

    async loadPaymentRequest() {
        if (!window.PaymentRequest) {
            return;
        }

        const paymentRequest = new PaymentRequest(
            [{
                supportedMethods: 'basic-card',
                data: {
                    supportedNetworks: ['visa', 'mastercard', 'amex'],
                    supportedTypes: ['credit', 'debit']
                }
            }],
            {
                total: {
                    label: 'Total',
                    amount: {
                        currency: this.currency.toUpperCase(),
                        value: (this.amount / 100).toFixed(2)
                    }
                }
            },
            {
                requestPayerName: true,
                requestPayerEmail: true
            }
        );

        this.paymentRequest = paymentRequest;
    }

    formatCardNumber(e) {
        let value = e.target.value.replace(/\s/g, '').replace(/\D/g, '');
        let formatted = '';
        for (let i = 0; i < value.length && i < 16; i++) {
            if (i > 0 && i % 4 === 0) {
                formatted += ' ';
            }
            formatted += value[i];
        }
        e.target.value = formatted;
    }

    formatExpiry(e) {
        let value = e.target.value.replace(/\D/g, '');
        if (value.length >= 2) {
            value = value.substring(0, 2) + ' / ' + value.substring(2, 4);
        }
        e.target.value = value;
    }

    formatCvc(e) {
        e.target.value = e.target.value.replace(/\D/g, '').substring(0, 4);
    }

    detectCardBrand(e) {
        const number = e.target.value.replace(/\s/g, '');
        const brandIcon = this.container.querySelector('.card-brand-icon');
        
        let brand = '';
        if (number.startsWith('4')) {
            brand = 'visa';
        } else if (number.startsWith(('51', '52', '53', '54', '55')) || 
                   (number.length >= 4 && parseInt(number.substring(0, 4)) >= 2221 && parseInt(number.substring(0, 4)) <= 2720)) {
            brand = 'mastercard';
        } else if (number.startsWith(('34', '37'))) {
            brand = 'amex';
        }

        if (brandIcon) {
            brandIcon.className = `card-brand-icon card-brand-${brand}`;
        }
    }

    async handleSubmit(e) {
        e.preventDefault();
        
        const cardNumber = this.container.querySelector('[data-card-number]').value.replace(/\s/g, '');
        const expiry = this.container.querySelector('[data-expiry]').value;
        const cvc = this.container.querySelector('[data-cvc]').value;

        const validation = this.validateCard(cardNumber, expiry, cvc);
        if (!validation.valid) {
            this.showError(validation.error);
            return;
        }

        this.setProcessing(true);

        try {
            const paymentMethod = await this.createPaymentMethod(cardNumber, expiry, cvc);
            const result = await this.confirmPayment(paymentMethod.id);
            
            if (result.error) {
                this.showError(result.error.message);
            } else if (result.paymentIntent.status === 'succeeded') {
                this.showSuccess(result.paymentIntent);
            } else if (result.paymentIntent.status === 'requires_action') {
                await this.handleAction(result.paymentIntent);
            }
        } catch (error) {
            this.showError(error.message || 'An unexpected error occurred.');
        } finally {
            this.setProcessing(false);
        }
    }

    validateCard(number, expiry, cvc) {
        if (!number || number.length < 13 || number.length > 19) {
            return { valid: false, error: 'Please enter a valid card number.' };
        }

        if (!this.luhnCheck(number)) {
            return { valid: false, error: 'Your card number is invalid.' };
        }

        const expiryParts = expiry.split('/').map(p => p.trim());
        if (expiryParts.length !== 2) {
            return { valid: false, error: 'Please enter a valid expiry date.' };
        }

        const month = parseInt(expiryParts[0], 10);
        const year = parseInt('20' + expiryParts[1], 10);
        const now = new Date();
        
        if (month < 1 || month > 12 || year < now.getFullYear() || 
            (year === now.getFullYear() && month < now.getMonth() + 1)) {
            return { valid: false, error: 'Your card has expired.' };
        }

        if (!cvc || cvc.length < 3) {
            return { valid: false, error: 'Please enter a valid security code.' };
        }

        return { valid: true };
    }

    luhnCheck(number) {
        let sum = 0;
        let isEven = false;
        
        for (let i = number.length - 1; i >= 0; i--) {
            let digit = parseInt(number[i], 10);
            
            if (isEven) {
                digit *= 2;
                if (digit > 9) {
                    digit -= 9;
                }
            }
            
            sum += digit;
            isEven = !isEven;
        }
        
        return sum % 10 === 0;
    }

    async createPaymentMethod(number, expiry, cvc) {
        const expiryParts = expiry.split('/').map(p => p.trim());
        
        const response = await fetch('/v1/payment_methods', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.publishableKey}`
            },
            body: JSON.stringify({
                type: 'card',
                card: {
                    number: number,
                    exp_month: parseInt(expiryParts[0], 10),
                    exp_year: parseInt('20' + expiryParts[1], 10),
                    cvc: cvc
                }
            })
        });

        return response.json();
    }

    async confirmPayment(paymentMethodId) {
        const response = await fetch(`/v1/payment_intents/${this.extractPaymentIntentId()}/confirm`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.publishableKey}`
            },
            body: JSON.stringify({
                payment_method: paymentMethodId,
                return_url: this.returnUrl
            })
        });

        return response.json();
    }

    extractPaymentIntentId() {
        const match = this.clientSecret.match(/pi_[a-zA-Z0-9]+/);
        return match ? match[0] : null;
    }

    async handleAction(paymentIntent) {
        if (paymentIntent.next_action && paymentIntent.next_action.type === 'redirect_to_url') {
            window.location.href = paymentIntent.next_action.redirect_to_url.url;
        }
    }

    setProcessing(processing) {
        const submitButton = this.container.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.disabled = processing;
            submitButton.classList.toggle('loading', processing);
        }
        this.onProcessing(processing);
    }

    showError(message) {
        const errorContainer = this.container.querySelector('.error-message');
        if (errorContainer) {
            errorContainer.textContent = message;
            errorContainer.style.display = 'flex';
        } else {
            const newError = document.createElement('div');
            newError.className = 'error-message';
            newError.innerHTML = `
                <svg class="error-icon" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
                </svg>
                <span>${message}</span>
            `;
            this.container.insertBefore(newError, this.container.firstChild);
        }
        this.onError(message);
    }

    showSuccess(paymentIntent) {
        this.container.innerHTML = `
            <div class="success-container">
                <svg class="success-icon" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
                </svg>
                <h2 class="success-title">Payment Successful</h2>
                <p class="success-message">Thank you for your payment of ${(paymentIntent.amount / 100).toFixed(2)} ${paymentIntent.currency.toUpperCase()}</p>
            </div>
        `;
        this.onSuccess(paymentIntent);
    }
}

window.PaymentProcessor = PaymentProcessor;
