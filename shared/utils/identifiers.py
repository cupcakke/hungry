import hashlib
import secrets
import string
import time
import uuid
from typing import Optional, Tuple


ID_PREFIXES = {
    "customer": "cus",
    "payment_intent": "pi",
    "charge": "ch",
    "refund": "re",
    "subscription": "sub",
    "invoice": "in",
    "invoice_item": "ii",
    "checkout_session": "cs",
    "setup_intent": "seti",
    "payout": "po",
    "transfer": "tr",
    "event": "evt",
    "file": "file",
    "webhook_endpoint": "we",
    "api_key": "sk",
    "account": "acct",
    "product": "prod",
    "price": "price",
    "coupon": "coupon",
    "promotion_code": "promo",
    "tax_rate": "txr",
    "credit_note": "cn",
    "dispute": "dp",
    "payment_method": "pm",
    "source": "src",
    "token": "tok",
    "card": "card",
    "bank_account": "ba",
    "mandate": "mandate",
    "order": "or",
    "order_item": "oi",
    "report": "rpt",
    "report_run": "rr",
    "review": "rv",
    "terminal_reader": "tmr",
    "location": "tml",
    "cardholder": "ich",
    "issuing_card": "ic",
    "issuing_authorization": "iauth",
    "issuing_transaction": "ipi",
    "financial_account": "fa",
    "treasury_transaction": "trxn",
    "capital_financing": "financing",
    "verification_session": "vs",
    "connected_account": "ca",
    "application_fee": "fee",
    "balance_transaction": "txn",
    "climate_order": "climorder",
    "credit_balance": "cb",
    "ledger_account": "lda",
    "ledger_entry": "le",
    "journal_entry": "je",
}


def generate_id(prefix: Optional[str] = None, length: int = 24) -> str:
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(length))
    if prefix:
        return f"{prefix}_{random_part}"
    return random_part


def generate_prefixed_id(prefix: str) -> str:
    if prefix not in ID_PREFIXES:
        raise ValueError(f"Unknown ID prefix: {prefix}")
    actual_prefix = ID_PREFIXES[prefix]
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{actual_prefix}_{random_part}"


def generate_customer_id() -> str:
    return generate_prefixed_id("customer")


def generate_payment_intent_id() -> str:
    return generate_prefixed_id("payment_intent")


def generate_charge_id() -> str:
    return generate_prefixed_id("charge")


def generate_refund_id() -> str:
    return generate_prefixed_id("refund")


def generate_subscription_id() -> str:
    return generate_prefixed_id("subscription")


def generate_invoice_id() -> str:
    return generate_prefixed_id("invoice")


def generate_invoice_item_id() -> str:
    return generate_prefixed_id("invoice_item")


def generate_checkout_session_id() -> str:
    return generate_prefixed_id("checkout_session")


def generate_setup_intent_id() -> str:
    return generate_prefixed_id("setup_intent")


def generate_payout_id() -> str:
    return generate_prefixed_id("payout")


def generate_transfer_id() -> str:
    return generate_prefixed_id("transfer")


def generate_event_id() -> str:
    return generate_prefixed_id("event")


def generate_file_id() -> str:
    return generate_prefixed_id("file")


def generate_webhook_endpoint_id() -> str:
    return generate_prefixed_id("webhook_endpoint")


def generate_api_key_id(test: bool = False) -> str:
    prefix = "sk_test" if test else "sk_live"
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(48))
    return f"{prefix}_{random_part}"


def generate_publishable_key(test: bool = False) -> str:
    prefix = "pk_test" if test else "pk_live"
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(48))
    return f"{prefix}_{random_part}"


def generate_restricted_key(test: bool = False) -> str:
    prefix = "rk_test" if test else "rk_live"
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(48))
    return f"{prefix}_{random_part}"


def generate_account_id() -> str:
    return generate_prefixed_id("account")


def generate_product_id() -> str:
    return generate_prefixed_id("product")


def generate_price_id() -> str:
    return generate_prefixed_id("price")


def generate_coupon_id() -> str:
    return generate_prefixed_id("coupon")


def generate_promotion_code_id() -> str:
    return generate_prefixed_id("promotion_code")


def generate_tax_rate_id() -> str:
    return generate_prefixed_id("tax_rate")


def generate_dispute_id() -> str:
    return generate_prefixed_id("dispute")


def generate_payment_method_id() -> str:
    return generate_prefixed_id("payment_method")


def generate_mandate_id() -> str:
    return generate_prefixed_id("mandate")


def generate_credit_note_id() -> str:
    return generate_prefixed_id("credit_note")


def generate_balance_transaction_id() -> str:
    return generate_prefixed_id("balance_transaction")


def generate_application_fee_id() -> str:
    return generate_prefixed_id("application_fee")


def generate_terminal_reader_id() -> str:
    return generate_prefixed_id("terminal_reader")


def generate_location_id() -> str:
    return generate_prefixed_id("location")


def generate_cardholder_id() -> str:
    return generate_prefixed_id("cardholder")


def generate_issuing_card_id() -> str:
    return generate_prefixed_id("issuing_card")


def generate_issuing_authorization_id() -> str:
    return generate_prefixed_id("issuing_authorization")


def generate_issuing_transaction_id() -> str:
    return generate_prefixed_id("issuing_transaction")


def generate_financial_account_id() -> str:
    return generate_prefixed_id("financial_account")


def generate_treasury_transaction_id() -> str:
    return generate_prefixed_id("treasury_transaction")


def generate_capital_financing_id() -> str:
    return generate_prefixed_id("capital_financing")


def generate_verification_session_id() -> str:
    return generate_prefixed_id("verification_session")


def generate_connected_account_id() -> str:
    return generate_prefixed_id("connected_account")


def generate_order_id() -> str:
    return generate_prefixed_id("order")


def generate_review_id() -> str:
    return generate_prefixed_id("review")


def generate_report_id() -> str:
    return generate_prefixed_id("report")


def generate_report_run_id() -> str:
    return generate_prefixed_id("report_run")


def generate_climate_order_id() -> str:
    return generate_prefixed_id("climate_order")


def generate_idempotency_key() -> str:
    return str(uuid.uuid4())


def parse_id_prefix(id_string: str) -> Tuple[Optional[str], str]:
    if "_" not in id_string:
        return None, id_string
    parts = id_string.split("_", 1)
    if len(parts) != 2:
        return None, id_string
    prefix = parts[0]
    suffix = parts[1]
    reverse_prefixes = {v: k for k, v in ID_PREFIXES.items()}
    resource_type = reverse_prefixes.get(prefix)
    return resource_type, suffix


def is_valid_id(id_string: str, expected_prefix: Optional[str] = None) -> bool:
    if not id_string:
        return False
    if "_" not in id_string:
        return expected_prefix is None
    resource_type, suffix = parse_id_prefix(id_string)
    if resource_type is None:
        return False
    if expected_prefix:
        expected_actual = ID_PREFIXES.get(expected_prefix)
        actual_prefix = id_string.split("_")[0]
        return actual_prefix == expected_actual
    return True


def generate_short_id(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def generate_invoice_number(prefix: str = "", sequence: int = 1) -> str:
    formatted_sequence = str(sequence).zfill(6)
    if prefix:
        return f"{prefix}-{formatted_sequence}"
    return formatted_sequence


def generate_order_number(sequence: int = 1) -> str:
    formatted_sequence = str(sequence).zfill(8)
    return f"ORD-{formatted_sequence}"


def generate_reference_id(prefix: str = "REF") -> str:
    timestamp = int(time.time())
    random_part = secrets.token_hex(4).upper()
    return f"{prefix}-{timestamp}-{random_part}"


def generate_ledger_account_id() -> str:
    return generate_prefixed_id("ledger_account")


def generate_ledger_entry_id() -> str:
    return generate_prefixed_id("ledger_entry")


def generate_journal_entry_id() -> str:
    return generate_prefixed_id("journal_entry")
