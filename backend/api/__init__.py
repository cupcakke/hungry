from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from payment_platform.backend.api.routes import (
    customers,
    payment_intents,
    charges,
    refunds,
    subscriptions,
    invoices,
    checkout_sessions,
    payment_methods,
    webhook_endpoints,
    events,
    accounts,
    products,
    prices,
    payouts,
    transfers,
    setup_intents,
    balance,
    tax_rates,
    disputes,
    coupons,
    promotion_codes,
    ledger,
    issuing,
    treasury,
    capital,
    crypto,
    climate,
    identity,
    revenue_recognition,
    terminal,
    payment_links,
    radar,
    financial_connections,
    confirmation_tokens,
    usage,
    reporting,
)

router = APIRouter()
security = HTTPBearer(auto_error=False)

router.include_router(customers.router, prefix="/v1/customers", tags=["Customers"])
router.include_router(payment_intents.router, prefix="/v1/payment_intents", tags=["Payment Intents"])
router.include_router(charges.router, prefix="/v1/charges", tags=["Charges"])
router.include_router(refunds.router, prefix="/v1/refunds", tags=["Refunds"])
router.include_router(subscriptions.router, prefix="/v1/subscriptions", tags=["Subscriptions"])
router.include_router(invoices.router, prefix="/v1/invoices", tags=["Invoices"])
router.include_router(checkout_sessions.router, prefix="/v1/checkout/sessions", tags=["Checkout Sessions"])
router.include_router(payment_methods.router, prefix="/v1/payment_methods", tags=["Payment Methods"])
router.include_router(webhook_endpoints.router, prefix="/v1/webhook_endpoints", tags=["Webhook Endpoints"])
router.include_router(events.router, prefix="/v1/events", tags=["Events"])
router.include_router(accounts.router, prefix="/v1/accounts", tags=["Accounts"])
router.include_router(products.router, prefix="/v1/products", tags=["Products"])
router.include_router(prices.router, prefix="/v1/prices", tags=["Prices"])
router.include_router(payouts.router, prefix="/v1/payouts", tags=["Payouts"])
router.include_router(transfers.router, prefix="/v1/transfers", tags=["Transfers"])
router.include_router(setup_intents.router, prefix="/v1/setup_intents", tags=["Setup Intents"])
router.include_router(balance.router, prefix="/v1/balance", tags=["Balance"])
router.include_router(tax_rates.router, prefix="/v1/tax_rates", tags=["Tax Rates"])
router.include_router(disputes.router, prefix="/v1/disputes", tags=["Disputes"])
router.include_router(coupons.router, prefix="/v1/coupons", tags=["Coupons"])
router.include_router(promotion_codes.router, prefix="/v1/promotion_codes", tags=["Promotion Codes"])
router.include_router(ledger.router, prefix="/v1/ledger", tags=["Ledger"])
router.include_router(issuing.router, prefix="/v1/issuing", tags=["Issuing"])
router.include_router(treasury.router, prefix="/v1/treasury", tags=["Treasury"])
router.include_router(capital.router, prefix="/v1/capital", tags=["Capital"])
router.include_router(crypto.router, prefix="/v1/crypto", tags=["Crypto"])
router.include_router(climate.router, prefix="/v1/climate", tags=["Climate"])
router.include_router(identity.router, prefix="/v1/identity", tags=["Identity"])
router.include_router(revenue_recognition.router, prefix="/v1/revenue_recognition", tags=["Revenue Recognition"])
router.include_router(terminal.router, prefix="/v1/terminal", tags=["Terminal"])
router.include_router(payment_links.router, prefix="/v1/payment_links", tags=["Payment Links"])
router.include_router(radar.router, prefix="/v1/radar", tags=["Radar"])
router.include_router(financial_connections.router, prefix="/v1/financial_connections", tags=["Financial Connections"])
router.include_router(confirmation_tokens.router, prefix="/v1/confirmation_tokens", tags=["Confirmation Tokens"])
router.include_router(usage.router, prefix="/v1/usage", tags=["Usage"])
router.include_router(reporting.router, prefix="/v1/reporting", tags=["Reporting"])
