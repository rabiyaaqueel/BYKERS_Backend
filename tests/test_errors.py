"""Tests for standard error format, unknown routes, and request_id middleware."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_id_generated_and_returned(client: AsyncClient):
    """Every response must return an X-Request-ID header."""
    response = await client.get("/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


@pytest.mark.asyncio
async def test_client_request_id_preserved(client: AsyncClient):
    """If client sends X-Request-ID, the server preserves and echoes it back."""
    custom_id = "req-custom-bykers-test-1234"
    response = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.headers.get("X-Request-ID") == custom_id


@pytest.mark.asyncio
async def test_unknown_route_returns_standard_404_format(client: AsyncClient):
    """Unknown routes must return 404 with {"code", "message", "details", "request_id"}."""
    response = await client.get("/api/v1/non-existent-endpoint-test")
    assert response.status_code == 404
    data = response.json()
    assert "code" in data
    assert "message" in data
    assert "details" in data
    assert "request_id" in data
    assert data["code"] == "NOT_FOUND"
    assert len(data["request_id"]) > 0


@pytest.mark.asyncio
async def test_ngrok_skip_browser_warning_header_handled(client: AsyncClient):
    """Requests passing ngrok-skip-browser-warning must succeed smoothly."""
    headers = {"ngrok-skip-browser-warning": "true"}
    response = await client.get("/health", headers=headers)
    assert response.status_code == 200
