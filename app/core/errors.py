"""Standard Error Handling Module.

This file defines the standard error format for the BYKERS Backend according to Rule 4:
All error responses MUST return:
{
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "details": {},
    "request_id": "uuid-or-empty"
}
Errors never leak private data, stack traces, or internal server secrets to the client.
"""

from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Base exception class for application-specific errors."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class UnauthorizedError(AppError):
    """401 Not Signed In / Invalid Token."""

    def __init__(
        self,
        message: str = "Authentication required",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code="UNAUTHORIZED",
            message=message,
            status_code=401,
            details=details,
        )


class ForbiddenError(AppError):
    """403 Denied / Lack of Permission."""

    def __init__(
        self,
        message: str = "Access denied",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code="FORBIDDEN",
            message=message,
            status_code=403,
            details=details,
        )


class NotFoundError(AppError):
    """404 Not Found (or privacy-preserving denied)."""

    def __init__(
        self,
        message: str = "Resource not found",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code="NOT_FOUND",
            message=message,
            status_code=404,
            details=details,
        )


class ConflictError(AppError):
    """409 Version/State/Idempotency conflict."""

    def __init__(
        self,
        message: str = "Conflict with current state",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code="CONFLICT",
            message=message,
            status_code=409,
            details=details,
        )


class ValidationError(AppError):
    """422 Request or business validation error."""

    def __init__(
        self,
        message: str = "Validation failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=422,
            details=details,
        )


class RateLimitError(AppError):
    """429 Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Too many requests",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code="RATE_LIMITED",
            message=message,
            status_code=429,
            details=details,
        )


def get_request_id(request: Request) -> str:
    """Retrieve the correlation request_id attached by RequestIdMiddleware."""
    return getattr(request.state, "request_id", "")


def format_error_response(
    code: str,
    message: str,
    details: Dict[str, Any],
    request_id: str,
    status_code: int,
) -> JSONResponse:
    """Construct a standard JSON error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        },
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handles all custom AppError exceptions."""
    return format_error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
        request_id=get_request_id(request),
        status_code=exc.status_code,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handles standard Starlette / FastAPI HTTPExceptions (including 404 for unknown routes)."""
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_SERVER_ERROR",
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    message = str(exc.detail) if exc.detail else "An error occurred"
    return format_error_response(
        code=code,
        message=message,
        details={},
        request_id=get_request_id(request),
        status_code=exc.status_code,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handles Pydantic validation errors on query, path, and body fields."""
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(item) for item in err.get("loc", []))
        errors.append({
            "field": loc,
            "message": err.get("msg", "Invalid input"),
            "type": err.get("type", "value_error"),
        })

    return format_error_response(
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details={"errors": errors},
        request_id=get_request_id(request),
        status_code=422,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled internal exceptions to avoid leaking trace details."""
    import logging
    logger = logging.getLogger("bykers.server")
    req_id = get_request_id(request)
    logger.error("Unhandled server exception [request_id=%s]: %s", req_id, str(exc), exc_info=True)

    return format_error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred. Please try again later.",
        details={},
        request_id=req_id,
        status_code=500,
    )
