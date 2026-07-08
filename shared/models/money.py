from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, getcontext
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

getcontext().prec = 28


class Currency(str, Enum):
    AED = "AED"
    AFN = "AFN"
    ALL = "ALL"
    AMD = "AMD"
    ANG = "ANG"
    AOA = "AOA"
    ARS = "ARS"
    AUD = "AUD"
    AWG = "AWG"
    AZN = "AZN"
    BAM = "BAM"
    BBD = "BBD"
    BDT = "BDT"
    BGN = "BGN"
    BHD = "BHD"
    BIF = "BIF"
    BMD = "BMD"
    BND = "BND"
    BOB = "BOB"
    BRL = "BRL"
    BSD = "BSD"
    BTN = "BTN"
    BWP = "BWP"
    BYN = "BYN"
    BZD = "BZD"
    CAD = "CAD"
    CDF = "CDF"
    CHF = "CHF"
    CLP = "CLP"
    CNY = "CNY"
    COP = "COP"
    CRC = "CRC"
    CUP = "CUP"
    CVE = "CVE"
    CZK = "CZK"
    DJF = "DJF"
    DKK = "DKK"
    DOP = "DOP"
    DZD = "DZD"
    EGP = "EGP"
    ERN = "ERN"
    ETB = "ETB"
    EUR = "EUR"
    FJD = "FJD"
    FKP = "FKP"
    GBP = "GBP"
    GEL = "GEL"
    GGP = "GGP"
    GHS = "GHS"
    GIP = "GIP"
    GMD = "GMD"
    GNF = "GNF"
    GTQ = "GTQ"
    GYD = "GYD"
    HKD = "HKD"
    HNL = "HNL"
    HRK = "HRK"
    HTG = "HTG"
    HUF = "HUF"
    IDR = "IDR"
    ILS = "ILS"
    IMP = "IMP"
    INR = "INR"
    IQD = "IQD"
    IRR = "IRR"
    ISK = "ISK"
    JEP = "JEP"
    JMD = "JMD"
    JOD = "JOD"
    JPY = "JPY"
    KES = "KES"
    KGS = "KGS"
    KHR = "KHR"
    KMF = "KMF"
    KPW = "KPW"
    KRW = "KRW"
    KWD = "KWD"
    KYD = "KYD"
    KZT = "KZT"
    LAK = "LAK"
    LBP = "LBP"
    LKR = "LKR"
    LRD = "LRD"
    LSL = "LSL"
    LYD = "LYD"
    MAD = "MAD"
    MDL = "MDL"
    MGA = "MGA"
    MKD = "MKD"
    MMK = "MMK"
    MNT = "MNT"
    MOP = "MOP"
    MRU = "MRU"
    MUR = "MUR"
    MVR = "MVR"
    MWK = "MWK"
    MXN = "MXN"
    MYR = "MYR"
    MZN = "MZN"
    NAD = "NAD"
    NGN = "NGN"
    NIO = "NIO"
    NOK = "NOK"
    NPR = "NPR"
    NZD = "NZD"
    OMR = "OMR"
    PAB = "PAB"
    PEN = "PEN"
    PGK = "PGK"
    PHP = "PHP"
    PKR = "PKR"
    PLN = "PLN"
    PYG = "PYG"
    QAR = "QAR"
    RON = "RON"
    RSD = "RSD"
    RUB = "RUB"
    RWF = "RWF"
    SAR = "SAR"
    SBD = "SBD"
    SCR = "SCR"
    SDG = "SDG"
    SEK = "SEK"
    SGD = "SGD"
    SHP = "SHP"
    SLE = "SLE"
    SLL = "SLL"
    SOS = "SOS"
    SRD = "SRD"
    SSP = "SSP"
    STN = "STN"
    SYP = "SYP"
    SZL = "SZL"
    THB = "THB"
    TJS = "TJS"
    TMT = "TMT"
    TND = "TND"
    TOP = "TOP"
    TRY = "TRY"
    TTD = "TTD"
    TVD = "TVD"
    TWD = "TWD"
    TZS = "TZS"
    UAH = "UAH"
    UGX = "UGX"
    USD = "USD"
    UYU = "UYU"
    UZS = "UZS"
    VED = "VED"
    VES = "VES"
    VND = "VND"
    VUV = "VUV"
    WST = "WST"
    XAF = "XAF"
    XCD = "XCD"
    XOF = "XOF"
    XPF = "XPF"
    YER = "YER"
    ZAR = "ZAR"
    ZMW = "ZMW"
    ZWL = "ZWL"


CURRENCY_DECIMAL_PLACES: Dict[str, int] = {
    "AED": 2, "AFN": 2, "ALL": 2, "AMD": 2, "ANG": 2, "AOA": 2, "ARS": 2, "AUD": 2,
    "AWG": 2, "AZN": 2, "BAM": 2, "BBD": 2, "BDT": 2, "BGN": 2, "BHD": 3, "BIF": 0,
    "BMD": 2, "BND": 2, "BOB": 2, "BRL": 2, "BSD": 2, "BTN": 2, "BWP": 2, "BYN": 2,
    "BZD": 2, "CAD": 2, "CDF": 2, "CHF": 2, "CLP": 0, "CNY": 2, "COP": 2, "CRC": 2,
    "CUP": 2, "CVE": 2, "CZK": 2, "DJF": 0, "DKK": 2, "DOP": 2, "DZD": 2, "EGP": 2,
    "ERN": 2, "ETB": 2, "EUR": 2, "FJD": 2, "FKP": 2, "GBP": 2, "GEL": 2, "GGP": 2,
    "GHS": 2, "GIP": 2, "GMD": 2, "GNF": 0, "GTQ": 2, "GYD": 2, "HKD": 2, "HNL": 2,
    "HRK": 2, "HTG": 2, "HUF": 2, "IDR": 2, "ILS": 2, "IMP": 2, "INR": 2, "IQD": 3,
    "IRR": 2, "ISK": 0, "JEP": 2, "JMD": 2, "JOD": 3, "JPY": 0, "KES": 2, "KGS": 2,
    "KHR": 2, "KMF": 0, "KPW": 2, "KRW": 0, "KWD": 3, "KYD": 2, "KZT": 2, "LAK": 2,
    "LBP": 2, "LKR": 2, "LRD": 2, "LSL": 2, "LYD": 3, "MAD": 2, "MDL": 2, "MGA": 2,
    "MKD": 2, "MMK": 2, "MNT": 2, "MOP": 2, "MRU": 2, "MUR": 2, "MVR": 2, "MWK": 2,
    "MXN": 2, "MYR": 2, "MZN": 2, "NAD": 2, "NGN": 2, "NIO": 2, "NOK": 2, "NPR": 2,
    "NZD": 2, "OMR": 3, "PAB": 2, "PEN": 2, "PGK": 2, "PHP": 2, "PKR": 2, "PLN": 2,
    "PYG": 0, "QAR": 2, "RON": 2, "RSD": 2, "RUB": 2, "RWF": 0, "SAR": 2, "SBD": 2,
    "SCR": 2, "SDG": 2, "SEK": 2, "SGD": 2, "SHP": 2, "SLE": 2, "SLL": 2, "SOS": 2,
    "SRD": 2, "SSP": 2, "STN": 2, "SYP": 2, "SZL": 2, "THB": 2, "TJS": 2, "TMT": 2,
    "TND": 3, "TOP": 2, "TRY": 2, "TTD": 2, "TVD": 2, "TWD": 2, "TZS": 2, "UAH": 2,
    "UGX": 0, "USD": 2, "UYU": 2, "UZS": 2, "VED": 2, "VES": 2, "VND": 0, "VUV": 0,
    "WST": 2, "XAF": 0, "XCD": 2, "XOF": 0, "XPF": 0, "YER": 2, "ZAR": 2, "ZMW": 2,
    "ZWL": 2,
}

CURRENCY_SYMBOLS: Dict[str, str] = {
    "AED": "د.إ", "AUD": "A$", "CAD": "C$", "CHF": "CHF", "CNY": "¥", "EUR": "€",
    "GBP": "£", "HKD": "HK$", "INR": "₹", "JPY": "¥", "KRW": "₩", "MXN": "Mex$",
    "NOK": "kr", "NZD": "NZ$", "RUB": "₽", "SEK": "kr", "SGD": "S$", "TRY": "₺",
    "USD": "$", "ZAR": "R",
}

ZERO_DECIMAL_CURRENCIES: set = {
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "MGA", "PYG",
    "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}

THREE_DECIMAL_CURRENCIES: set = {
    "BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND",
}


@dataclass(frozen=True)
class Money:
    amount: int
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("Amount cannot be negative")
        if not self.currency:
            raise ValueError("Currency is required")
        self._validate_currency(self.currency)

    @staticmethod
    def _validate_currency(currency: str) -> None:
        if currency not in [c.value for c in Currency]:
            raise ValueError(f"Invalid currency: {currency}")

    @property
    def decimal_places(self) -> int:
        return CURRENCY_DECIMAL_PLACES.get(self.currency, 2)

    @property
    def is_zero_decimal(self) -> bool:
        return self.currency in ZERO_DECIMAL_CURRENCIES

    @property
    def is_three_decimal(self) -> bool:
        return self.currency in THREE_DECIMAL_CURRENCIES

    @property
    def symbol(self) -> str:
        return CURRENCY_SYMBOLS.get(self.currency, self.currency)

    @property
    def decimal_amount(self) -> Decimal:
        divisor = 10 ** self.decimal_places
        return Decimal(self.amount) / Decimal(divisor)

    @property
    def formatted(self) -> str:
        decimal_amount = self.decimal_amount
        formatted = f"{decimal_amount:,.{self.decimal_places}f}"
        return f"{self.symbol}{formatted}"

    @classmethod
    def from_decimal(cls, amount: Union[Decimal, float, str], currency: str) -> "Money":
        decimal_places = CURRENCY_DECIMAL_PLACES.get(currency, 2)
        decimal_amount = Decimal(str(amount))
        minor_units = int(decimal_amount * (10 ** decimal_places))
        return cls(amount=minor_units, currency=currency)

    @classmethod
    def from_major_units(cls, amount: Union[Decimal, float, str], currency: str) -> "Money":
        return cls.from_decimal(amount, currency)

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(amount=0, currency=currency)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot add different currencies: {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract different currencies: {self.currency} and {other.currency}")
        result = self.amount - other.amount
        if result < 0:
            raise ValueError("Result would be negative")
        return Money(amount=result, currency=self.currency)

    def multiply(self, multiplier: Union[Decimal, float, int]) -> "Money":
        decimal_multiplier = Decimal(str(multiplier))
        result = Decimal(self.amount) * decimal_multiplier
        return Money(amount=int(result.quantize(Decimal("1"))), currency=self.currency)

    def divide(self, divisor: Union[Decimal, float, int]) -> "Money":
        if divisor == 0:
            raise ValueError("Cannot divide by zero")
        decimal_divisor = Decimal(str(divisor))
        result = Decimal(self.amount) / decimal_divisor
        return Money(amount=int(result.quantize(Decimal("1"))), currency=self.currency)

    def percentage(self, percent: Union[Decimal, float]) -> "Money":
        return self.multiply(Decimal(str(percent)) / Decimal("100"))

    def is_zero(self) -> bool:
        return self.amount == 0

    def is_positive(self) -> bool:
        return self.amount > 0

    def is_greater_than(self, other: "Money") -> bool:
        if self.currency != other.currency:
            raise ValueError(f"Cannot compare different currencies: {self.currency} and {other.currency}")
        return self.amount > other.amount

    def is_less_than(self, other: "Money") -> bool:
        if self.currency != other.currency:
            raise ValueError(f"Cannot compare different currencies: {self.currency} and {other.currency}")
        return self.amount < other.amount

    def is_equal_to(self, other: "Money") -> bool:
        return self.amount == other.amount and self.currency == other.currency

    def is_greater_or_equal(self, other: "Money") -> bool:
        return self.is_equal_to(other) or self.is_greater_than(other)

    def is_less_or_equal(self, other: "Money") -> bool:
        return self.is_equal_to(other) or self.is_less_than(other)

    def allocate(self, ratios: List[int]) -> List["Money"]:
        if not ratios:
            return []
        total_ratio = sum(ratios)
        if total_ratio == 0:
            raise ValueError("Total ratio cannot be zero")
        results = []
        remaining = self.amount
        for i, ratio in enumerate(ratios):
            if i == len(ratios) - 1:
                amount = remaining
            else:
                amount = int(Decimal(self.amount * ratio) / Decimal(total_ratio))
                remaining -= amount
            results.append(Money(amount=amount, currency=self.currency))
        return results

    def split(self, n: int) -> List["Money"]:
        if n <= 0:
            raise ValueError("Number of splits must be positive")
        base_amount = self.amount // n
        remainder = self.amount % n
        results = []
        for i in range(n):
            amount = base_amount + (1 if i < remainder else 0)
            results.append(Money(amount=amount, currency=self.currency))
        return results

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Money":
        return cls(amount=data["amount"], currency=data["currency"])

    def __add__(self, other: "Money") -> "Money":
        return self.add(other)

    def __sub__(self, other: "Money") -> "Money":
        return self.subtract(other)

    def __mul__(self, multiplier: Union[Decimal, float, int]) -> "Money":
        return self.multiply(multiplier)

    def __truediv__(self, divisor: Union[Decimal, float, int]) -> "Money":
        return self.divide(divisor)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        return self.is_equal_to(other)

    def __lt__(self, other: "Money") -> bool:
        return self.is_less_than(other)

    def __le__(self, other: "Money") -> bool:
        return self.is_less_or_equal(other)

    def __gt__(self, other: "Money") -> bool:
        return self.is_greater_than(other)

    def __ge__(self, other: "Money") -> bool:
        return self.is_greater_or_equal(other)

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    def __repr__(self) -> str:
        return f"Money(amount={self.amount}, currency='{self.currency}')"

    def __str__(self) -> str:
        return self.formatted
