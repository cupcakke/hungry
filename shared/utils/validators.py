import re
from datetime import datetime
from typing import Optional, Tuple
import phonenumbers


CARD_BIN_RANGES = {
    "visa": [(4000000000000, 4999999999999), (4000000000000000, 4999999999999999)],
    "mastercard": [
        (2221000000000000, 2720999999999999),
        (5100000000000000, 5599999999999999),
        (2221000000000, 2720999999999),
        (5100000000000, 5599999999999),
    ],
    "amex": [(340000000000000, 349999999999999), (370000000000000, 379999999999999)],
    "discover": [
        (6011000000000000, 6011999999999999),
        (6221260000000000, 6229259999999999),
        (6440000000000000, 6599999999999999),
    ],
    "diners": [(30000000000000, 30599999999999), (36000000000000, 36999999999999)],
    "jcb": [(3528000000000000, 3589999999999999)],
    "unionpay": [
        (6200000000000000, 6299999999999999),
        (6220000000000000, 6221259999999999),
        (6229260000000000, 6239999999999999),
    ],
}


def validate_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_phone(phone: str, country_code: Optional[str] = None) -> bool:
    try:
        parsed = phonenumbers.parse(phone, country_code)
        return phonenumbers.is_valid_number(parsed)
    except Exception:
        return False


def validate_card_number(card_number: str) -> Tuple[bool, Optional[str]]:
    cleaned = re.sub(r"\D", "", card_number)
    if not cleaned:
        return False, None
    if len(cleaned) < 13 or len(cleaned) > 19:
        return False, None
    card_type = identify_card_type(cleaned)
    if not card_type:
        return False, None
    if not luhn_check(cleaned):
        return False, card_type
    return True, card_type


def identify_card_type(card_number: str) -> Optional[str]:
    cleaned = re.sub(r"\D", "", card_number)
    num = int(cleaned)
    for card_type, ranges in CARD_BIN_RANGES.items():
        for start, end in ranges:
            if start <= num <= end:
                return card_type
    if cleaned.startswith("4"):
        return "visa"
    if cleaned.startswith(("51", "52", "53", "54", "55")):
        return "mastercard"
    if cleaned.startswith(("34", "37")):
        return "amex"
    if cleaned.startswith("6011") or cleaned.startswith("65"):
        return "discover"
    return None


def luhn_check(card_number: str) -> bool:
    cleaned = re.sub(r"\D", "", card_number)
    if not cleaned.isdigit():
        return False
    digits = [int(d) for d in cleaned]
    checksum = 0
    is_even = len(digits) % 2 == 0
    for i, digit in enumerate(digits):
        if is_even:
            if i % 2 == 0:
                doubled = digit * 2
                checksum += doubled if doubled < 10 else doubled - 9
            else:
                checksum += digit
        else:
            if i % 2 == 1:
                doubled = digit * 2
                checksum += doubled if doubled < 10 else doubled - 9
            else:
                checksum += digit
    return checksum % 10 == 0


def validate_expiry_date(month: int, year: int) -> bool:
    if month < 1 or month > 12:
        return False
    current_year = datetime.utcnow().year
    current_month = datetime.utcnow().month
    if year < 100:
        year += 2000
    if year < current_year:
        return False
    if year == current_year and month < current_month:
        return False
    return True


def validate_cvv(cvv: str, card_type: Optional[str] = None) -> bool:
    cleaned = re.sub(r"\D", "", cvv)
    if not cleaned:
        return False
    if card_type == "amex":
        return len(cleaned) == 4
    return len(cleaned) == 3


def validate_iban(iban: str) -> Tuple[bool, Optional[str]]:
    cleaned = iban.replace(" ", "").upper()
    if len(cleaned) < 15 or len(cleaned) > 34:
        return False, None
    if not cleaned[:2].isalpha():
        return False, None
    country_code = cleaned[:2]
    if not cleaned[2:4].isdigit():
        return False, None
    rearranged = cleaned[4:] + cleaned[:4]
    numeric = ""
    for char in rearranged:
        if char.isalpha():
            numeric += str(ord(char) - 55)
        else:
            numeric += char
    checksum = int(numeric) % 97
    is_valid = checksum == 1
    return is_valid, country_code


def validate_routing_number(routing_number: str) -> bool:
    cleaned = re.sub(r"\D", "", routing_number)
    if len(cleaned) != 9:
        return False
    weights = [3, 7, 1, 3, 7, 1, 3, 7, 1]
    total = sum(int(digit) * weight for digit, weight in zip(cleaned, weights))
    return total % 10 == 0


def validate_account_number(account_number: str, min_length: int = 4, max_length: int = 17) -> bool:
    cleaned = re.sub(r"\D", "", account_number)
    return min_length <= len(cleaned) <= max_length


def validate_tax_id(tax_id: str, country: str = "US") -> Tuple[bool, Optional[str]]:
    cleaned = re.sub(r"[^\dA-Za-z]", "", tax_id).upper()
    if country == "US":
        if len(cleaned) == 9 and cleaned.isdigit():
            return True, "us_ein"
        if len(cleaned) == 11 and cleaned.isdigit():
            return True, "us_ssn"
    elif country == "GB":
        pattern = r"^[A-Z]{2}\d{6}[A-D]?$"
        if re.match(pattern, cleaned):
            return True, "gb_vat"
        pattern = r"^\d{9}$"
        if re.match(pattern, cleaned):
            return True, "gb_company_number"
    elif country == "DE":
        pattern = r"^\d{11}$"
        if re.match(pattern, cleaned):
            return True, "de_vat"
    elif country == "FR":
        pattern = r"^[A-Z]{2}\d{9}$"
        if re.match(pattern, cleaned):
            return True, "fr_vat"
    elif country == "CA":
        pattern = r"^\d{9}$"
        if re.match(pattern, cleaned):
            return True, "ca_bn"
    elif country == "AU":
        pattern = r"^\d{11}$"
        if re.match(pattern, cleaned):
            return True, "au_abn"
    elif country == "EU":
        pattern = r"^[A-Z]{2}[A-Z0-9]{2,12}$"
        if re.match(pattern, cleaned):
            return True, "eu_vat"
    return False, None


def validate_url(url: str) -> bool:
    pattern = r"^https?://[^\s/$.?#].[^\s]*$"
    return bool(re.match(pattern, url, re.IGNORECASE))


def validate_ip_address(ip: str) -> Tuple[bool, Optional[str]]:
    ipv4_pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
    ipv6_pattern = r"^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$"
    if re.match(ipv4_pattern, ip):
        parts = ip.split(".")
        if all(0 <= int(part) <= 255 for part in parts):
            return True, "ipv4"
    if re.match(ipv6_pattern, ip):
        return True, "ipv6"
    return False, None


def validate_postal_code(postal_code: str, country: str) -> bool:
    patterns = {
        "US": r"^\d{5}(-\d{4})?$",
        "CA": r"^[A-Z]\d[A-Z] \d[A-Z]\d$",
        "GB": r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$",
        "DE": r"^\d{5}$",
        "FR": r"^\d{5}$",
        "AU": r"^\d{4}$",
        "JP": r"^\d{3}-\d{4}$",
    }
    pattern = patterns.get(country)
    if pattern:
        return bool(re.match(pattern, postal_code.upper()))
    return True


def validate_credit_card_cvv(cvv: str) -> bool:
    cleaned = re.sub(r"\D", "", cvv)
    return 3 <= len(cleaned) <= 4


def validate_currency(currency: str) -> bool:
    from payment_platform.shared.models.money import Currency
    return currency.upper() in [c.value for c in Currency]


def validate_country_code(country: str) -> bool:
    from payment_platform.shared.models.enums import CountryCode
    return country.upper() in [c.value for c in CountryCode]


def validate_language_code(language: str) -> bool:
    from payment_platform.shared.models.enums import LanguageCode
    return language.lower() in [c.value for c in LanguageCode]


def validate_amount(amount: int, currency: str) -> Tuple[bool, Optional[str]]:
    from payment_platform.shared.config import settings
    if amount < 0:
        return False, "Amount cannot be negative"
    min_amount = settings.payment.min_payment_amount.get(currency, 50)
    max_amount = settings.payment.max_payment_amount.get(currency, 9999999999)
    if amount < min_amount:
        return False, f"Amount must be at least {min_amount} in minor units"
    if amount > max_amount:
        return False, f"Amount exceeds maximum of {max_amount} in minor units"
    return True, None


def validate_metadata(metadata: dict, max_keys: int = 50, max_key_length: int = 40, max_value_length: int = 500) -> Tuple[bool, Optional[str]]:
    if not metadata:
        return True, None
    if len(metadata) > max_keys:
        return False, f"Metadata cannot have more than {max_keys} keys"
    for key, value in metadata.items():
        if not isinstance(key, str):
            return False, "Metadata key must be a string"
        if len(key) > max_key_length:
            return False, f"Metadata key '{key}' exceeds maximum length of {max_key_length}"
        if not key.replace("_", "").replace("-", "").isalnum():
            return False, f"Metadata key '{key}' contains invalid characters"
        if value is not None:
            if not isinstance(value, str):
                value = str(value)
            if len(value) > max_value_length:
                return False, f"Metadata value for key '{key}' exceeds maximum length of {max_value_length}"
    return True, None


def validate_id(id_string: str, expected_prefix: Optional[str] = None) -> bool:
    from payment_platform.shared.utils.identifiers import is_valid_id
    return is_valid_id(id_string, expected_prefix)


def validate_timestamp(timestamp: int) -> bool:
    min_timestamp = 946684800
    max_timestamp = 4102444800
    return min_timestamp <= timestamp <= max_timestamp


def validate_future_timestamp(timestamp: int) -> bool:
    import time
    return timestamp > int(time.time())


def validate_past_timestamp(timestamp: int) -> bool:
    import time
    return timestamp < int(time.time())


def validate_webhook_url(url: str) -> Tuple[bool, Optional[str]]:
    if not validate_url(url):
        return False, "Invalid URL format"
    if not url.startswith("https://"):
        return False, "Webhook URL must use HTTPS"
    blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
    for host in blocked_hosts:
        if host in url:
            return False, f"Webhook URL cannot use blocked host: {host}"
    return True, None


def validate_subscription_interval(interval: str, interval_count: int) -> Tuple[bool, Optional[str]]:
    valid_intervals = ["day", "week", "month", "year"]
    if interval not in valid_intervals:
        return False, f"Invalid interval: {interval}"
    max_counts = {"day": 365, "week": 52, "month": 12, "year": 1}
    if interval_count < 1 or interval_count > max_counts.get(interval, 1):
        return False, f"Invalid interval_count for {interval}: must be 1-{max_counts.get(interval, 1)}"
    return True, None
