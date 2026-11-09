"""Security and Cryptography Helpers.

This file handles cryptographic operations:
- Hashing OTPs and refresh tokens (never stored as plain text)
- Verification of hashes
- JWT creation and validation
- Secure random token generation
- Phone number privacy masking
"""

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt
from cryptography.fernet import Fernet

from app.core.config import settings
from app.core.errors import ValidationError


def hash_token(token: str) -> str:
    """Computes a SHA-256 hash of a string (such as an OTP or refresh token).

    We store hashes in the database, never the raw readable token.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_hash(plain_value: str, hashed_value: str) -> bool:
    """Verifies a plain value against a stored SHA-256 hash using constant-time comparison."""
    calculated = hash_token(plain_value)
    return hmac.compare_digest(calculated, hashed_value)


def generate_secure_token(nbytes: int = 32) -> str:
    """Generates a cryptographically strong, URL-safe random string."""
    return secrets.token_urlsafe(nbytes)


def create_access_token(
    user_id: str,
    session_id: str,
    permission_version: int = 1,
    interface: str = "rider_app",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Creates a signed JWT access token.

    Note (Rule 2): Access tokens carry user identity, session id, permission version,
    and interface. They DO NOT carry role names as authority.
    """
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)

    payload: Dict[str, Any] = {
        "sub": user_id,
        "session_id": session_id,
        "pv": permission_version,
        "interface": interface,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decodes and validates a JWT access token.

    Raises jwt.PyJWTError if expired, malformed, or signature invalid.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


def mask_phone(phone: str) -> str:
    """Masks a phone number for logging and privacy display (e.g. +91******3210)."""
    clean = phone.strip()
    if len(clean) <= 6:
        return "***"
    prefix = clean[:3]
    suffix = clean[-4:]
    return f"{prefix}******{suffix}"


def _get_fernet() -> Fernet:
    """Derive deterministic 32-byte urlsafe Fernet key from application SECRET_KEY."""
    raw_key = getattr(settings, "REGISTRATION_ENCRYPTION_KEY", None)
    if raw_key:
        return Fernet(raw_key.encode("utf-8") if isinstance(raw_key, str) else raw_key)
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_registration(registration: str) -> str:
    """Encrypts a bike registration number at rest using AES-Fernet."""
    f = _get_fernet()
    return f.encrypt(registration.encode("utf-8")).decode("utf-8")


def decrypt_registration(encrypted_token: str) -> str:
    """Decrypts a stored bike registration number."""
    f = _get_fernet()
    return f.decrypt(encrypted_token.encode("utf-8")).decode("utf-8")


def mask_registration(last4: Optional[str]) -> Optional[str]:
    """Masks bike registration number showing only the last 4 characters (e.g. ******1234)."""
    if not last4:
        return None
    clean = last4.strip().upper()
    return f"******{clean}"


def clean_and_validate_registration(registration: str) -> Tuple[str, str]:
    """Cleans, normalizes, and validates motorcycle registration number.

    Rule: uppercase, remove spaces and hyphens, accept letters and digits only, 6 to 12 chars.
    Returns (cleaned_registration, last4).
    Raises ValidationError with field-level details on failure.
    """
    clean = re.sub(r"[\s\-]", "", registration.strip()).upper()
    if not re.fullmatch(r"^[A-Z0-9]{6,12}$", clean):
        raise ValidationError(
            "Registration number must be 6 to 12 alphanumeric characters without symbols.",
            details={"field": "registration", "rejected_value": registration},
        )
    return clean, clean[-4:]
