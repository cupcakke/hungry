import base64
import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional, Tuple

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from payment_platform.shared.config import settings


def get_encryption_key() -> bytes:
    key = settings.security.encryption_key
    if key is None:
        key = settings.security.secret_key
    return hashlib.sha256(key.encode()).digest()


def hash_password(password: str, rounds: int = 12) -> str:
    import bcrypt
    salt = bcrypt.gensalt(rounds=rounds)
    hashed = bcrypt.hashpw(password.encode(), salt)
    return hashed.decode()


def verify_password(password: str, hashed_password: str) -> bool:
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode(), hashed_password.encode())
    except Exception:
        return False


def encrypt_data(
    plaintext: str,
    key: Optional[bytes] = None,
    associated_data: Optional[bytes] = None,
) -> str:
    if key is None:
        key = get_encryption_key()
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    if associated_data:
        encryptor.authenticate_additional_data(associated_data)
    ciphertext = encryptor.update(plaintext.encode()) + encryptor.finalize()
    tag = encryptor.tag
    result = nonce + tag + ciphertext
    return base64.b64encode(result).decode()


def decrypt_data(
    ciphertext: str,
    key: Optional[bytes] = None,
    associated_data: Optional[bytes] = None,
) -> str:
    if key is None:
        key = get_encryption_key()
    data = base64.b64decode(ciphertext.encode())
    nonce = data[:12]
    tag = data[12:28]
    actual_ciphertext = data[28:]
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
    decryptor = cipher.decryptor()
    if associated_data:
        decryptor.authenticate_additional_data(associated_data)
    plaintext = decryptor.update(actual_ciphertext) + decryptor.finalize()
    return plaintext.decode()


def sign_webhook_payload(
    payload: str,
    secret: str,
    timestamp: Optional[int] = None,
    version: str = "v1",
) -> str:
    if timestamp is None:
        timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},{version}={signature}"


def verify_webhook_signature(
    payload: str,
    signature_header: str,
    secret: str,
    tolerance: int = 300,
) -> Tuple[bool, Optional[int]]:
    parts = {}
    for part in signature_header.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            parts[key] = value
    if "t" not in parts:
        return False, None
    timestamp = int(parts["t"])
    current_time = int(time.time())
    if abs(current_time - timestamp) > tolerance:
        return False, timestamp
    signed_payload = f"{timestamp}.{payload}"
    for key, value in parts.items():
        if key != "t":
            expected_signature = hmac.new(
                secret.encode(),
                signed_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(value, expected_signature):
                return True, timestamp
    return False, timestamp


def generate_signature(data: str, secret: str, algorithm: str = "sha256") -> str:
    if algorithm == "sha256":
        return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    elif algorithm == "sha512":
        return hmac.new(secret.encode(), data.encode(), hashlib.sha512).hexdigest()
    elif algorithm == "md5":
        return hmac.new(secret.encode(), data.encode(), hashlib.md5).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def hash_sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def hash_sha512(data: str) -> str:
    return hashlib.sha512(data.encode()).hexdigest()


def encrypt_card_number(card_number: str, key: Optional[bytes] = None) -> str:
    return encrypt_data(card_number, key)


def decrypt_card_number(encrypted: str, key: Optional[bytes] = None) -> str:
    return decrypt_data(encrypted, key)


def generate_card_fingerprint(card_number: str) -> str:
    normalized = card_number.replace(" ", "").replace("-", "")
    return hash_sha256(normalized)


def mask_card_number(card_number: str) -> str:
    cleaned = card_number.replace(" ", "").replace("-", "")
    if len(cleaned) < 8:
        return "*" * len(cleaned)
    return cleaned[:4] + "*" * (len(cleaned) - 8) + cleaned[-4:]
