import logging

from app.core.audit import record_audit_event
from app.core.idempotency import get_stored_idempotency_response, store_idempotency_response
from app.core.permissions import RoleCode
from app.core.security import hash_token, verify_hash


def test_token_hashing_and_verification():
    token = "test-secret-otp-123456"
    hashed = hash_token(token)
    assert hashed != token
    assert len(hashed) == 64
    assert verify_hash(token, hashed) is True
    assert verify_hash("wrong-otp", hashed) is False


def test_permissions_and_roles():
    assert RoleCode.RL01_RIDER.value == "RL01"
    assert RoleCode.RL14_SUPER_ADMIN.value == "RL14"
    assert len(RoleCode) == 14


def test_audit_log_execution(caplog):
    with caplog.at_level(logging.INFO):
        record_audit_event(
            actor="user_123",
            action="login",
            resource="auth",
            reason="OTP verified",
            request_id="req_test_001",
        )
    assert "user_123" in caplog.text
    assert "OTP verified" in caplog.text


def test_idempotency_storage():
    key = "idem-test-key-999"
    assert get_stored_idempotency_response(key) is None
    data = {"status": "success", "id": 42}
    store_idempotency_response(key, data)
    assert get_stored_idempotency_response(key) == data
