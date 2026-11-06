"""Security and Cryptography Helpers.

This file handles cryptographic operations:
- Hashing OTPs and refresh tokens (never stored as plain text)
- Verification of hashes
- JWT creation and validation
- Secure random token generation
- Phone number privacy masking
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from app.core.config import settings


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
