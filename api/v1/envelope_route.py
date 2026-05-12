# -*- coding: utf-8 -*-
"""Custom ``APIRoute`` that wraps handler return values into ``APIResponse``.

Endpoints declare ``response_model=APIResponse[X]`` and keep the ergonomic
``return X`` style. This route subclass intercepts the endpoint call and
wraps its result into a success envelope before FastAPI runs response_model
validation, so the wire format always matches the contract in
``code-quality.mdc`` §3.

Pass-through cases:
- ``Response`` instances (e.g. ``JSONResponse`` / ``StreamingResponse`` /
  ``EventSourceResponse``) — already finalised, leave alone.
- ``APIResponse`` instances — the endpoint opted into manual wrapping
  (e.g. to override ``code`` / ``message``).
- Dicts that already look like an envelope (``code`` + ``message`` +
  ``timestamp`` keys).
"""
from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable

from fastapi.routing import APIRoute
from starlette.responses import Response

from api.v1.schemas.envelope import APIResponse, success_response


def _is_envelope_dict(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "code" in value
        and "message" in value
        and "timestamp" in value
    )


def _wrap_value(value: Any) -> Any:
    """Wrap *value* into an APIResponse envelope unless it already is one."""
    if isinstance(value, Response):
        return value
    if isinstance(value, APIResponse):
        return value
    if _is_envelope_dict(value):
        return value
    return success_response(value)


def _wrap_endpoint(endpoint: Callable) -> Callable:
    """Return a callable with the same signature that envelopes its result."""
    if asyncio.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await endpoint(*args, **kwargs)
            return _wrap_value(result)

        return async_wrapper

    @functools.wraps(endpoint)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        result = endpoint(*args, **kwargs)
        return _wrap_value(result)

    return sync_wrapper


class EnvelopeRoute(APIRoute):
    """APIRoute that auto-wraps handler return values into APIResponse."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        endpoint = kwargs.get("endpoint")
        if endpoint is None and args:
            # APIRoute(path, endpoint, ...) positional form.
            endpoint = args[1] if len(args) > 1 else None
        if endpoint is not None:
            wrapped = _wrap_endpoint(endpoint)
            if "endpoint" in kwargs:
                kwargs["endpoint"] = wrapped
            else:
                args = (args[0], wrapped, *args[2:])
        super().__init__(*args, **kwargs)
