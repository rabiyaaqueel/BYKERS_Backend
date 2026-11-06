"""Idempotency Layer Helpers.

Non-Negotiable Rule 7:
Mutating operations (attendance, RSVP, location batches, payments) accept an Idempotency-Key header.
Reusing the same key with a different body returns 409 Conflict.
"""

import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from app.core.errors import ConflictError

# In-memory storage fallback for dev/testing: key -> (body_hash, response_data)
_IDEMPOTENCY_STORE: Dict[str, Tuple[str, Any]] = {}


def check_and_get_idempotent_response(
    key: Optional[str],
    body_data: Any,
) -> Optional[Any]:
    """Checks if an idempotency key was previously processed.

    If key exists with the exact same payload hash, returns the cached response.
    If key exists with a different payload hash, raises ConflictError (409).
    If key does not exist or key is None, returns None.
    """
    if not key:
        return None

    body_repr = (
        json.dumps(body_data, sort_keys=True, default=str)
        if not isinstance(body_data, (str, bytes))
        else str(body_data)
    )
    body_hash = hashlib.sha256(body_repr.encode("utf-8")).hexdigest()

    entry = _IDEMPOTENCY_STORE.get(key)
    if entry:
        stored_hash, stored_response = entry
        if stored_hash != body_hash:
            raise ConflictError(
                "Idempotency key was already used with a different request payload.",
                code="IDEMPOTENCY_CONFLICT",
                details={"key": key},
            )
        return stored_response
    return None


def store_idempotent_response(
    key: Optional[str],
    body_data: Any,
    response_data: Any,
) -> None:
    """Stores response associated with an idempotency key and body hash."""
    if not key:
        return
    body_repr = (
        json.dumps(body_data, sort_keys=True, default=str)
        if not isinstance(body_data, (str, bytes))
        else str(body_data)
    )
    body_hash = hashlib.sha256(body_repr.encode("utf-8")).hexdigest()
    _IDEMPOTENCY_STORE[key] = (body_hash, response_data)


def get_stored_idempotency_response(key: str) -> Any:
    """Retrieve previously recorded response for an idempotency key (legacy helper)."""
    entry = _IDEMPOTENCY_STORE.get(key)
    return entry[1] if entry else None


def store_idempotency_response(key: str, response_data: Any) -> None:
    """Store the response for an idempotency key (legacy helper)."""
    _IDEMPOTENCY_STORE[key] = ("", response_data)
