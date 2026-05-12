# -*- coding: utf-8 -*-
"""Backward-compatibility shim.

The AkshareFetcher implementation now lives in the ``data_provider.akshare``
sub-package, split into ``base`` / ``historical`` / ``realtime`` / ``market``
mixins. Existing imports keep working through this shim, including direct
access to module-level helpers such as ``SINA_REALTIME_ENDPOINT`` and
``_to_sina_tx_symbol`` used by tests / test.sh.
"""
from data_provider.akshare import AkshareFetcher, is_hk_stock_code  # noqa: F401
from data_provider.akshare.utils import (  # noqa: F401
    SINA_REALTIME_ENDPOINT,
    TENCENT_REALTIME_ENDPOINT,
    _AFTERHOURS_TTL,
    _INTRADAY_TTL,
    _build_realtime_failure_message,
    _classify_realtime_http_error,
    _etf_realtime_cache,
    _get_realtime_ttl,
    _is_etf_code,
    _is_hk_code,
    _is_us_code,
    _realtime_cache,
    _to_sina_tx_symbol,
)

__all__ = [
    "AkshareFetcher",
    "is_hk_stock_code",
    "SINA_REALTIME_ENDPOINT",
    "TENCENT_REALTIME_ENDPOINT",
]
