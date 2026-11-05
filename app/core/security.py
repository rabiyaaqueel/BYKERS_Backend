"""Security and Cryptography Helpers.

This file handles cryptographic operations:
- Hashing OTPs and refresh tokens (never stored as plain text)
- Verification of hashes
- Encryption/decryption placeholders for sensitive fields (e.g. trusted contacts, bike registration)
"""

import hashlib
import hmac


def hash_token(token: str) -> str:
    """Computes a SHA-256 hash of a string (such as an OTP or refresh token).

    We store hashes in the database, never the raw readable token.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_hash(plain_value: str, hashed_value: str) -> bool:
    """Verifies a plain value against a stored SHA-256 hash using constant-time comparison."""
    calculated = hash_token(plain_value)
    return hmac.compare_digest(calculated, hashed_value)
