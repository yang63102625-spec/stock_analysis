# -*- coding: utf-8 -*-
"""Global exception handlers — emit unified :class:`APIResponse` envelope.

Every uncaught exception is converted to an envelope of the form::

    {"code": <ApiErrorCode>, "message": <str>, "data": null|<obj>,
     "timestamp": "..."}

The HTTP status code is preserved (e.g. 422 for validation, 5xx for
server errors) so existing client retry/back-off logic still works, but
the body is uniform across success and failure.

Project-defined exceptions from :mod:`src.exceptions` are mapped to a
fixed taxonomy in :class:`api.v1.schemas.envelope.ApiErrorCode` so
callers can branch on ``code`` without parsing ``message`` strings.
"""
from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.v1.schemas.envelope import ApiErrorCode, error_response
from src.exceptions import (
    DataFetchError,
    DataSourceUnavailableError,
    NetworkError,
    RateLimitError,
    ValidationError as ProjectValidationError,
)

logger = logging.getLogger(__name__)


def _http_status_for(code: ApiErrorCode) -> int:
    """Map an ``ApiErrorCode`` to the HTTP status code clients should see."""
    return {
        ApiErrorCode.VALIDATION_ERROR: status.HTTP_422_UNPROCESSABLE_ENTITY,
        ApiErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
        ApiErrorCode.UNAUTHORIZED: status.HTTP_401_UNAUTHORIZED,
        ApiErrorCode.FORBIDDEN: status.HTTP_403_FORBIDDEN,
        ApiErrorCode.HTTP_ERROR: status.HTTP_400_BAD_REQUEST,
        ApiErrorCode.RATE_LIMIT: status.HTTP_429_TOO_MANY_REQUESTS,
        ApiErrorCode.NETWORK_ERROR: status.HTTP_502_BAD_GATEWAY,
        ApiErrorCode.DATA_SOURCE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
        ApiErrorCode.INTERNAL_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
        ApiErrorCode.UNKNOWN_ERROR: status.HTTP_500_INTERNAL_SERVER_ERROR,
    }.get(code, status.HTTP_500_INTERNAL_SERVER_ERROR)


def _envelope(
    code: ApiErrorCode,
    message: str,
    data=None,
    http_status: int | None = None,
) -> JSONResponse:
    """Build a ``JSONResponse`` whose body is an :class:`APIResponse` envelope."""
    return JSONResponse(
        status_code=http_status or _http_status_for(code),
        content=error_response(code, message, data),
    )


def add_error_handlers(app: FastAPI) -> None:
    """Register all unified exception handlers on the FastAPI app."""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Map common HTTP statuses to their dedicated ``ApiErrorCode``.
        code_map = {
            status.HTTP_400_BAD_REQUEST: ApiErrorCode.HTTP_ERROR,
            status.HTTP_401_UNAUTHORIZED: ApiErrorCode.UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN: ApiErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ApiErrorCode.NOT_FOUND,
            status.HTTP_422_UNPROCESSABLE_ENTITY: ApiErrorCode.VALIDATION_ERROR,
            status.HTTP_429_TOO_MANY_REQUESTS: ApiErrorCode.RATE_LIMIT,
        }
        api_code = code_map.get(exc.status_code, ApiErrorCode.HTTP_ERROR)

        detail = exc.detail
        # If a route already produced a fully-formed envelope (rare;
        # auth.py uses ``error_response`` directly via ``JSONResponse``),
        # passthrough verbatim. Endpoints SHOULD pass plain strings to
        # ``HTTPException(detail=...)`` and let this handler envelope them.
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)

        message = str(detail) if detail else "HTTP Error"
        return _envelope(api_code, message, http_status=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return _envelope(
            ApiErrorCode.VALIDATION_ERROR,
            "请求参数验证失败",
            data=exc.errors(),
        )

    @app.exception_handler(RateLimitError)
    async def rate_limit_handler(request: Request, exc: RateLimitError):
        logger.warning("[%s %s] RateLimit: %s", request.method, request.url.path, exc)
        return _envelope(ApiErrorCode.RATE_LIMIT, str(exc) or "API rate limit exceeded")

    @app.exception_handler(NetworkError)
    async def network_error_handler(request: Request, exc: NetworkError):
        logger.warning("[%s %s] Network: %s", request.method, request.url.path, exc)
        return _envelope(ApiErrorCode.NETWORK_ERROR, str(exc) or "Network error")

    @app.exception_handler(DataSourceUnavailableError)
    async def data_source_handler(request: Request, exc: DataSourceUnavailableError):
        logger.warning("[%s %s] DataSourceUnavailable: %s", request.method, request.url.path, exc)
        return _envelope(
            ApiErrorCode.DATA_SOURCE_UNAVAILABLE,
            str(exc) or "Data source unavailable",
        )

    @app.exception_handler(ProjectValidationError)
    async def project_validation_handler(request: Request, exc: ProjectValidationError):
        return _envelope(ApiErrorCode.VALIDATION_ERROR, str(exc) or "Validation error")

    @app.exception_handler(DataFetchError)
    async def data_fetch_handler(request: Request, exc: DataFetchError):
        # Generic data-layer failure that did not match a more specific
        # subclass above — surface as a 500-level internal error.
        logger.error(
            "[%s %s] DataFetchError: %s", request.method, request.url.path, exc,
            exc_info=True,
        )
        return _envelope(ApiErrorCode.INTERNAL_ERROR, str(exc) or "Data fetch failed")

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception on %s %s: %s\n%s",
            request.method, request.url.path, exc, traceback.format_exc(),
        )
        return _envelope(ApiErrorCode.UNKNOWN_ERROR, "服务器内部错误")
