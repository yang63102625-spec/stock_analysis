# -*- coding: utf-8 -*-
"""Unified API response envelope.

Every endpoint in this codebase MUST return a payload that conforms to
:class:`APIResponse`, regardless of whether the call succeeded or failed.
This is enforced by the global exception handlers in
``api.middlewares.error_handler`` and by routing every endpoint
through ``response_model=APIResponse[...]``.

The envelope mirrors the contract specified in
``.cursor/rules/code-quality.mdc`` §3:

.. code-block:: json

    {
      "code": 0,
      "message": "success",
      "data": { ... },
      "timestamp": "2026-05-12T19:00:00+08:00"
    }

``code == 0`` denotes success. Non-zero values map to a fixed taxonomy
(``ApiErrorCode``) so clients can branch on category without parsing
``message`` strings.
"""
from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Any, Generic, Optional, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiErrorCode(IntEnum):
    """Stable numeric codes used in :class:`APIResponse.code`.

    The numeric values are part of the wire contract — never renumber or
    re-purpose an existing entry. New codes must be appended.
    """

    SUCCESS = 0
    # 1xxx — client-side input issues
    VALIDATION_ERROR = 1001
    NOT_FOUND = 1002
    UNAUTHORIZED = 1003
    FORBIDDEN = 1004
    HTTP_ERROR = 1099
    # 2xxx — upstream / external dependency issues
    RATE_LIMIT = 2001
    NETWORK_ERROR = 2002
    DATA_SOURCE_UNAVAILABLE = 2003
    # 9xxx — server-side / unknown
    INTERNAL_ERROR = 9000
    UNKNOWN_ERROR = 9999


_BEIJING = ZoneInfo("Asia/Shanghai")


def _now_iso() -> str:
    """Return current Beijing time as an ISO-8601 string with offset."""
    return datetime.now(_BEIJING).isoformat(timespec="seconds")


class APIResponse(BaseModel, Generic[T]):
    """Unified envelope for every API response.

    Type parameter ``T`` is the inner payload type. Use ``APIResponse[None]``
    for endpoints that have no body (e.g. delete operations) and
    ``APIResponse[Any]`` only when the payload is genuinely heterogeneous.
    """

    code: int = Field(
        default=ApiErrorCode.SUCCESS.value,
        description="0 == success; non-zero values follow the ApiErrorCode taxonomy.",
        examples=[0],
    )
    message: str = Field(
        default="success",
        description="Human-readable status message.",
        examples=["success"],
    )
    data: Optional[T] = Field(
        default=None,
        description="Endpoint-specific payload. Null on errors.",
    )
    timestamp: str = Field(
        default_factory=_now_iso,
        description="ISO-8601 timestamp of when the response was built (Beijing time).",
        examples=["2026-05-12T19:00:00+08:00"],
    )


def success_response(data: Any = None, message: str = "success") -> dict:
    """Build a JSON-serialisable success envelope.

    Returned as a plain ``dict`` so callers can stuff it into a
    :class:`fastapi.responses.JSONResponse` or hand it to
    ``response_model=APIResponse[...]`` validation transparently.
    """
    return {
        "code": ApiErrorCode.SUCCESS.value,
        "message": message,
        "data": data,
        "timestamp": _now_iso(),
    }


def error_response(
    code: ApiErrorCode | int,
    message: str,
    data: Any = None,
) -> dict:
    """Build a JSON-serialisable error envelope.

    ``code`` MUST be an :class:`ApiErrorCode` member or its integer value.
    ``data`` is reserved for structured error context (e.g. validation
    errors include the failing fields here); ``None`` for simple cases.
    """
    code_value = int(code)
    return {
        "code": code_value,
        "message": message,
        "data": data,
        "timestamp": _now_iso(),
    }


__all__ = [
    "APIResponse",
    "ApiErrorCode",
    "error_response",
    "success_response",
]
