# -*- coding: utf-8 -*-
"""Public surface of the ``data_provider.base`` package.

Every existing ``from data_provider.base import …`` call site keeps
working unchanged because this module re-exports the canonical names.
"""

from src.exceptions import (
    DataFetchError,
    DataSourceUnavailableError,
    RateLimitError,
)

from .codes import (
    STANDARD_COLUMNS,
    canonical_stock_code,
    is_bse_code,
    is_kc_cy_stock,
    is_st_stock,
    normalize_stock_code,
    summarize_exception,
    unwrap_exception,
)
from .fetcher import BaseFetcher
from .manager import DataFetcherManager

__all__ = [
    # Helpers
    "STANDARD_COLUMNS",
    "canonical_stock_code",
    "is_bse_code",
    "is_kc_cy_stock",
    "is_st_stock",
    "normalize_stock_code",
    "summarize_exception",
    "unwrap_exception",
    # Classes
    "BaseFetcher",
    "DataFetcherManager",
    # Exceptions (re-exported for backward import compatibility)
    "DataFetchError",
    "DataSourceUnavailableError",
    "RateLimitError",
]
