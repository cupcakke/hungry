import base64
import hashlib
import hmac
import os
import secrets
import string
from typing import Optional, Tuple

from payment_platform.shared.config import settings


def generate_secret_key(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def generate_api_key(prefix: str = "sk", test: bool = False) -> str:
    environment = "test" if test else "live"
    key_prefix = f"{prefix}_{environment}"
    random_part = secrets.token_urlsafe(36)
    return f"{key_prefix}_{random_part}"


def generate_webhook_secret() -> str:
    random_part = secrets.token_urlsafe(32)
    return f"whsec_{random_part}"


def generate_mfa_secret() -> str:
    return secrets.token_urlsafe(20).upper()


def generate_jwt_secret() -> str:
    return secrets.token_urlsafe(64)


def generate_signing_key() -> Tuple[str, str]:
    private_key = secrets.token_urlsafe(64)
    public_key = hashlib.sha256(private_key.encode()).hexdigest()
    return private_key, public_key


def generate_encryption_key() -> bytes:
    return secrets.token_bytes(32)


def generate_salt(length: int = 16) -> bytes:
    return secrets.token_bytes(length)


def generate_nonce(length: int = 12) -> bytes:
    return secrets.token_bytes(length)


def generate_otp(length: int = 6) -> str:
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length))


def generate_password(length: int = 16) -> str:
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%^&*()-_=+[]{}|;:,.<>?"
    all_chars = lowercase + uppercase + digits + special
    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    for _ in range(length - 4):
        password.append(secrets.choice(all_chars))
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def generate_reset_token() -> str:
    return secrets.token_urlsafe(48)


def generate_verification_code(length: int = 6) -> str:
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length))


def generate_api_key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def api_key_prefix_from_key(api_key: str) -> str:
    return api_key[:13]


def is_test_api_key(api_key: str) -> bool:
    return api_key.startswith(("sk_test_", "pk_test_", "rk_test_"))
