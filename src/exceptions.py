# -*- coding: utf-8 -*-
"""Unified exception taxonomy for the stock_analysis project.

Categories
----------
- ``RateLimitError``: API rate / quota limit exceeded.
- ``NetworkError``: Connection timeout, DNS failure, refused/reset.
- ``DataSourceUnavailableError``: Data source is down or returns 404 / not found.
- ``ValidationError``: Input or data validation failure (bad columns, types, ...).
- ``UnknownError``: Last-resort bucket for unexpected exceptions.

Backward compatibility
----------------------
``data_provider.base`` historically defined ``DataFetchError`` /
``RateLimitError`` / ``DataSourceUnavailableError``. To avoid breaking the 50+
existing call sites, those classes remain the canonical ones and this module
re-exports them. New code should import from here.
"""

from __future__ import annotations

# Re-export the established base classes so old call sites keep working.
from data_provider.base import (  # noqa: F401
    DataFetchError,
    DataSourceUnavailableError,
    RateLimitError,
)


class NetworkError(DataFetchError):
    """Network-layer failure: connection refused, reset, DNS, timeout."""


class ValidationError(DataFetchError):
    """Input or data validation failure (bad columns, types, ranges, ...)."""


class UnknownError(DataFetchError):
    """Last-resort bucket for unexpected exceptions."""


__all__ = [
    "DataFetchError",
    "RateLimitError",
    "NetworkError",
    "DataSourceUnavailableError",
    "ValidationError",
    "UnknownError",
]
