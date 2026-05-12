# -*- coding: utf-8 -*-
"""Unified exception taxonomy for the stock_analysis project.

This module is the single source of truth for every project-defined
exception class. Other modules (including ``data_provider.base``) MUST
import from here rather than redefining their own copy.

Categories
----------
- ``DataFetchError``: Base class for every data-layer failure.
- ``RateLimitError``: API rate / quota limit exceeded.
- ``NetworkError``: Connection timeout, DNS failure, refused/reset.
- ``DataSourceUnavailableError``: Data source is down or returns 404.
- ``ValidationError``: Input or data validation failure (bad columns,
  types, ranges, ...).
- ``UnknownError``: Last-resort bucket for unexpected exceptions.
"""

from __future__ import annotations


class DataFetchError(Exception):
    """Base class for every data-layer failure raised inside this project."""


class RateLimitError(DataFetchError):
    """API rate / quota limit exceeded."""


class NetworkError(DataFetchError):
    """Network-layer failure: connection refused, reset, DNS, timeout."""


class DataSourceUnavailableError(DataFetchError):
    """Data source is down or returns a not-found / unauthorised response."""


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
