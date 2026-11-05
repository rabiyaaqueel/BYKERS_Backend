"""Main FastAPI Application Entry Point for BYKERS Backend.

This file creates and configures the FastAPI application instance:
- Request ID middleware (attaches unique correlation ID to every request)
- Ngrok bypass compatibility
- CORS middleware (permits mobile and partner clients in dev)
- Standardized error handlers (Rule 4: code, message, details, request_id)
- Structured privacy-preserving logging
- Root and API v1 health endpoints
"""

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.errors import (
    AppError,
    app_error_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.logging import setup_logging
from app.modules.auth.router import auth_router, me_router
from app.modules.health.router import router as health_router


class RequestIdMiddleware:
    """Pure ASGI middleware that assigns a unique correlation request_id to each HTTP request.

    Stores the ID in scope['state']['request_id'] and appends X-Request-ID to the response headers.
    Avoids Starlette BaseHTTPMiddleware streaming and taskgroup deadlocks.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                request_id = value.decode("latin1")
                break
        if not request_id:
            request_id = str(uuid.uuid4())

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle management."""
    # Initialize structured logging with secret redaction
    setup_logging(env=settings.ENV)
    yield


def create_app() -> FastAPI:
    """FastAPI Application Factory."""
    app = FastAPI(
        title="BYKERS Backend API",
        description="Motorcycle community platform backend for riders in India.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Add Request ID and Ngrok Compatibility Middleware
    app.add_middleware(RequestIdMiddleware)

    # 2. Add CORS Middleware
    if settings.ENV == "dev":
        # Allow all origins for dev development (including Flutter app and ngrok tunnel)
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=".*",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*", "ngrok-skip-browser-warning", "X-Request-ID", "Idempotency-Key"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*", "ngrok-skip-browser-warning", "X-Request-ID", "Idempotency-Key"],
        )

    # 3. Register Standard Error Handlers (Rule 4)
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)

    # 4. Register Routers
    app.include_router(health_router)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(me_router, prefix="/api/v1")

    return app


# Module-level instance for uvicorn
app = create_app()
