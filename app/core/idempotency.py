"""Idempotency Layer Helpers.

Non-Negotiable Rule 7:
Mutating operations (attendance, RSVP, location batches, payments) accept an Idempotency-Key header.
Reusing the same key with a different body returns 409 Conflict.
"""

from typing import Any, Dict

# In-memory storage fallback for dev/testing
_IDEMPOTENCY_STORE: Dict[str, Any] = {}


def get_stored_idempotency_response(key: str) -> Any:
    """Retrieve previously recorded response for an idempotency key."""
    return _IDEMPOTENCY_STORE.get(key)


def store_idempotency_response(key: str, response_data: Any) -> None:
    """Store the response for an idempotency key."""
    _IDEMPOTENCY_STORE[key] = response_data
