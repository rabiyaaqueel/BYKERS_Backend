"""Tests for /health and /api/v1/health endpoints."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.db import check_database_connection


@pytest.mark.asyncio
async def test_root_health_returns_200(client: AsyncClient):
    """GET /health should return 200 and standard health payload."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["env"] == settings.ENV
    assert data["database"] in ["up", "down"]
    assert isinstance(data["postgis"], str)
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_v1_health_returns_200(client: AsyncClient):
    """GET /api/v1/health should return 200 and standard health payload."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["env"] == settings.ENV
    assert data["database"] in ["up", "down"]
    assert isinstance(data["postgis"], str)
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_health_with_database_up(client: AsyncClient):
    """When database is healthy with PostGIS 3.4.0, verify exact response shape."""
    check_database_connection.mock_result = {"database": "up", "postgis": "3.4.0"}
    try:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "status": "ok",
            "env": settings.ENV,
            "database": "up",
            "postgis": "3.4.0",
        }
    finally:
        del check_database_connection.mock_result


@pytest.mark.asyncio
async def test_health_with_database_down_resilient(client: AsyncClient):
    """When database is unreachable, health endpoint stays resilient and reports down."""
    check_database_connection.mock_result = {"database": "down", "postgis": "missing"}
    try:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "status": "ok",
            "env": settings.ENV,
            "database": "down",
            "postgis": "missing",
        }
    finally:
        del check_database_connection.mock_result


@pytest.mark.asyncio
async def test_live_probe_logic_when_database_fails():
    """Verify check_database_connection catches exceptions and reports down when probe fails."""
    orig_env = settings.ENV
    settings.ENV = "dev"
    try:
        with patch(
            "sqlalchemy.ext.asyncio.AsyncEngine.connect",
            side_effect=Exception("Connection refused"),
        ):
            result = await check_database_connection()
            assert result == {"database": "down", "postgis": "missing"}
    finally:
        settings.ENV = orig_env
