"""Health Endpoint Schemas.

Defines the response contract for GET /health and GET /api/v1/health.
"""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response payload."""

    status: str = Field(default="ok", description="Overall service status")
    env: str = Field(description="Environment (e.g., dev, test, staging, prod)")
    database: str = Field(description="Database connectivity status: 'up' or 'down'")
    postgis: str = Field(description="PostGIS extension version string or 'missing'")
