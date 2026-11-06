"""Append-only Audit Logging Helpers.

Non-Negotiable Rule 9:
Audit log is append-only for:
- Login failures
- Role changes
- Consent changes
- Applications decisions
- Exports
- Admin actions
"""

import logging
from typing import Any, Dict, Optional

audit_logger = logging.getLogger("bykers.audit")


def record_audit_event(
    actor: str,
    action: str,
    resource: str,
    reason: str = "",
    request_id: str = "",
    outcome: str = "success",
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    """Record an audit trail event in structured logs."""
    audit_logger.info(
        "AUDIT: actor=%s action=%s resource=%s reason=%s outcome=%s request_id=%s metadata=%s",
        actor,
        action,
        resource,
        reason,
        outcome,
        request_id,
        metadata or {},
    )
