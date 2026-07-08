import re
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Union

from payment_platform.shared.models.money import CURRENCY_DECIMAL_PLACES, CURRENCY_SYMBOLS


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_phone(phone: str, country_code: Optional[str] = None) -> str:
    cleaned = re.sub(r"[^\d+]", "", phone)
    if not cleaned.startswith("+"):
        if country_code:
            if country_code == "US" or country_code == "CA":
                if len(cleaned) == 10:
                    cleaned = "+1" + cleaned
                elif len(cleaned) == 11 and cleaned.startswith("1"):
                    cleaned = "+" + cleaned
            else:
                cleaned = "+" + cleaned
        else:
            if len(cleaned) == 10:
                cleaned = "+1" + cleaned
            elif len(cleaned) == 11 and cleaned.startswith("1"):
                cleaned = "+" + cleaned
    return cleaned


def format_money(amount: int, currency: str, include_symbol: bool = True) -> str:
    decimal_places = CURRENCY_DECIMAL_PLACES.get(currency, 2)
    divisor = 10 ** decimal_places
    decimal_amount = Decimal(amount) / Decimal(divisor)
    formatted = f"{decimal_amount:,.{decimal_places}f}"
    if include_symbol:
        symbol = CURRENCY_SYMBOLS.get(currency, currency)
        return f"{symbol}{formatted}"
    return formatted


def parse_money(formatted: str, currency: str) -> int:
    cleaned = re.sub(r"[^\d.\-]", "", formatted)
    decimal_amount = Decimal(cleaned)
    decimal_places = CURRENCY_DECIMAL_PLACES.get(currency, 2)
    multiplier = 10 ** decimal_places
    return int(decimal_amount * multiplier)


def format_card_number(card_number: str) -> str:
    cleaned = re.sub(r"\D", "", card_number)
    if len(cleaned) == 16:
        return f"{cleaned[:4]} {cleaned[4:8]} {cleaned[8:12]} {cleaned[12:16]}"
    elif len(cleaned) == 15:
        return f"{cleaned[:4]} {cleaned[4:10]} {cleaned[10:15]}"
    elif len(cleaned) == 14:
        return f"{cleaned[:4]} {cleaned[4:10]} {cleaned[10:14]}"
    else:
        chunks = [cleaned[i:i+4] for i in range(0, len(cleaned), 4)]
        return " ".join(chunks)


def format_expiry_date(month: int, year: int) -> str:
    return f"{month:02d}/{year % 100:02d}"


def mask_card_number(card_number: str, show_first: int = 4, show_last: int = 4) -> str:
    cleaned = re.sub(r"\D", "", card_number)
    if len(cleaned) < show_first + show_last:
        return "*" * len(cleaned)
    masked_length = len(cleaned) - show_first - show_last
    return cleaned[:show_first] + "*" * masked_length + cleaned[-show_last:]


def format_percentage(value: Union[Decimal, float, int], decimal_places: int = 2) -> str:
    if isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        decimal_value = Decimal(str(value))
    else:
        decimal_value = value
    formatted = f"{decimal_value:.{decimal_places}f}"
    return f"{formatted}%"


def format_timestamp(timestamp: Union[int, float, datetime], format_str: Optional[str] = None) -> str:
    if isinstance(timestamp, (int, float)):
        dt = datetime.utcfromtimestamp(timestamp)
    else:
        dt = timestamp
    if format_str:
        return dt.strftime(format_str)
    return dt.isoformat()


def format_date(date_value: Union[str, date, datetime], format_str: str = "%Y-%m-%d") -> str:
    if isinstance(date_value, str):
        dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        return dt.strftime(format_str)
    elif isinstance(date_value, datetime):
        return date_value.strftime(format_str)
    else:
        return date_value.strftime(format_str)


def format_datetime(
    datetime_value: Union[str, datetime],
    format_str: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    if isinstance(datetime_value, str):
        dt = datetime.fromisoformat(datetime_value.replace("Z", "+00:00"))
        return dt.strftime(format_str)
    else:
        return datetime_value.strftime(format_str)


def format_phone(phone: str, country_code: Optional[str] = None) -> str:
    cleaned = normalize_phone(phone, country_code)
    if cleaned.startswith("+1") and len(cleaned) == 12:
        number = cleaned[2:]
        return f"+1 ({number[:3]}) {number[3:6]}-{number[6:]}"
    elif cleaned.startswith("+44") and len(cleaned) >= 12:
        number = cleaned[3:]
        return f"+44 {number[:4]} {number[4:]}"
    elif cleaned.startswith("+"):
        return f"{cleaned[:3]} {cleaned[3:6]} {cleaned[6:]}"
    return cleaned


def format_iban(iban: str) -> str:
    cleaned = iban.replace(" ", "").upper()
    chunks = [cleaned[i:i+4] for i in range(0, len(cleaned), 4)]
    return " ".join(chunks)


def format_routing_number(routing_number: str) -> str:
    cleaned = re.sub(r"\D", "", routing_number)
    if len(cleaned) == 9:
        return f"{cleaned[:2]}-{cleaned[2:5]}-{cleaned[5:]}"
    return cleaned


def format_account_number(account_number: str, show_last: int = 4) -> str:
    cleaned = re.sub(r"\D", "", account_number)
    if len(cleaned) <= show_last:
        return "*" * len(cleaned)
    return "*" * (len(cleaned) - show_last) + cleaned[-show_last:]


def format_tax_id(tax_id: str, country: str = "US") -> str:
    cleaned = re.sub(r"[^\dA-Za-z]", "", tax_id).upper()
    if country == "US":
        if len(cleaned) == 9:
            return f"{cleaned[:2]}-{cleaned[2:]}"
    elif country == "GB":
        if len(cleaned) in [9, 10, 11]:
            return f"{cleaned[:3]} {cleaned[3:6]} {cleaned[6:]}"
    elif country == "CA":
        if len(cleaned) == 9:
            return f"{cleaned[:5]} {cleaned[5:8]} {cleaned[8]}"
    return cleaned


def format_order_number(sequence: int, prefix: str = "ORD") -> str:
    return f"{prefix}-{sequence:08d}"


def format_invoice_number(sequence: int, prefix: str = "INV") -> str:
    return f"{prefix}-{sequence:06d}"


def format_receipt_number(charge_id: str) -> str:
    return f"{charge_id}-receipt"


def format_reference_id(prefix: str = "REF", length: int = 8) -> str:
    import secrets
    import string
    chars = string.ascii_uppercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(length))
    return f"{prefix}-{random_part}"


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        if remaining_seconds == 0:
            return f"{minutes}m"
        return f"{minutes}m {remaining_seconds}s"
    elif seconds < 86400:
        hours = seconds // 3600
        remaining_minutes = (seconds % 3600) // 60
        if remaining_minutes == 0:
            return f"{hours}h"
        return f"{hours}h {remaining_minutes}m"
    else:
        days = seconds // 86400
        remaining_hours = (seconds % 86400) // 3600
        if remaining_hours == 0:
            return f"{days}d"
        return f"{days}d {remaining_hours}h"


def format_file_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} PB"


def format_currency_code(currency: str) -> str:
    return currency.upper()


def format_country_code(country: str) -> str:
    return country.upper()


def format_language_code(language: str) -> str:
    return language.lower()


def format_locale(language: str, country: Optional[str] = None) -> str:
    if country:
        return f"{language.lower()}-{country.upper()}"
    return language.lower()


def format_amount_for_display(amount: int, currency: str) -> str:
    decimal_places = CURRENCY_DECIMAL_PLACES.get(currency, 2)
    divisor = 10 ** decimal_places
    decimal_amount = amount / divisor
    if decimal_amount == int(decimal_amount):
        return f"{int(decimal_amount)}"
    return f"{decimal_amount:.{decimal_places}f}".rstrip("0").rstrip(".")
