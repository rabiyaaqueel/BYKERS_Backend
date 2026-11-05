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

audit_logger = logging.getLogger("bykers.audit")


def record_audit_event(
    actor: str,
    action: str,
    resource: str,
    reason: str = "",
    request_id: str = "",
) -> None:
    """Record an audit trail event."""
    audit_logger.info(
        "AUDIT: actor=%s action=%s resource=%s reason=%s request_id=%s",
        actor, action, resource, reason, request_id
    )
