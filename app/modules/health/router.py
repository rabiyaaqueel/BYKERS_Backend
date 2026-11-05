"""Health Check Router.

Provides unauthenticated health check endpoints:
- GET /health (standard load balancer / monitor health check)
- GET /api/v1/health (versioned API health check)

Both report the service environment, database connectivity, and PostGIS status.
"""

from fastapi import APIRouter

import app.core.db as db_core
from app.core.config import settings
from app.modules.health.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Root Service Health",
    description="Public endpoint to check overall backend and database health.",
)
async def get_root_health() -> HealthResponse:
    """Return health status at the root /health path."""
    db_info = await db_core.check_database_connection()
    return HealthResponse(
        status="ok",
        env=settings.ENV,
        database=db_info["database"],
        postgis=db_info["postgis"],
    )


@router.get(
    "/api/v1/health",
    response_model=HealthResponse,
    summary="API v1 Service Health",
    description="Public endpoint to check overall backend and database health under /api/v1.",
)
async def get_v1_health() -> HealthResponse:
    """Return health status at the versioned /api/v1/health path."""
    db_info = await db_core.check_database_connection()
    return HealthResponse(
        status="ok",
        env=settings.ENV,
        database=db_info["database"],
        postgis=db_info["postgis"],
    )
