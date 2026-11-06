"""Pytest Fixtures and Test Configuration.

Sets up an asynchronous HTTP client using httpx to test the FastAPI app endpoints.
"""

import os

# Ensure ENV=test is active for all test modules
os.environ["ENV"] = "test"

from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings

# Test database safety verification
if "test" not in settings.TEST_DATABASE_URL.lower():
    raise RuntimeError(
        f"TEST SAFETY REFUSAL: URL '{settings.TEST_DATABASE_URL}' does not contain 'test'."
    )

from app.core.db import engine
from app.main import app

settings.ENV = "test"


@pytest.fixture(autouse=True)
async def cleanup_database_pool():
    """Ensure database connection pool is cleanly disposed at the end of each async test."""
    yield
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provides an async HTTP client connected directly to the FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
