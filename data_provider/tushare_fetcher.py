# -*- coding: utf-8 -*-
"""Backward-compatibility shim.

The TushareFetcher implementation now lives in the ``data_provider.tushare``
sub-package, split into ``base`` / ``historical`` / ``realtime`` / ``market``
mixins. Legacy callers keep working through this shim, including direct
access to module-level realtime caches such as ``_realtime_list_cache`` and
``_rt_k_cache_time`` (used by :mod:`src.services.picker.quantitative_filter`
to force cache expiry).
"""
# Re-export the public class.
from data_provider.tushare import TushareFetcher  # noqa: F401

# Re-export module-level caches/locks/circuit-breaker counters and helpers
# so legacy callers that mutate them keep working.
from data_provider.tushare.realtime import (  # noqa: F401
    _SHARED_EXECUTOR,
    _daily_basic_cache,
    _daily_basic_cache_date,
    _daily_basic_lock,
    _daily_vol_avg_cache,
    _daily_vol_avg_cache_date,
    _daily_vol_avg_lock,
    _REALTIME_LIST_COOLDOWN,
    _REALTIME_LIST_MAX_FAILURES,
    _RT_K_COOLDOWN,
    _RT_K_MAX_FAILURES,
    _realtime_list_cache,
    _realtime_list_disabled_until,
    _realtime_list_fail_count,
    _realtime_list_lock,
    _rt_k_cache,
    _rt_k_cache_time,
    _rt_k_disabled_until,
    _rt_k_fail_count,
    _rt_k_lock,
)
from data_provider.tushare.utils import (  # noqa: F401
    _ETF_ALL_PREFIXES,
    _ETF_SH_PREFIXES,
    _ETF_SZ_PREFIXES,
    _get_dynamic_cache_ttl,
    _is_etf_code,
    _is_us_code,
)

__all__ = ["TushareFetcher"]
