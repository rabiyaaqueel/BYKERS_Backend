"""Pytest Fixtures and Test Configuration.

Sets up an asynchronous HTTP client using httpx to test the FastAPI app endpoints.
"""

from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provides an async HTTP client connected directly to the FastAPI ASGI app."""
    settings.ENV = "test"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
