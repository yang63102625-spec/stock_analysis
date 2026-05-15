# -*- coding: utf-8 -*-
"""
Caching utilities for the data provider layer.

This module exposes two complementary primitives:

1. :class:`CachingDataFetcherManager` — a backtest-time wrapper around
   :class:`DataFetcherManager` that memoises ``get_daily_data`` results within
   a single run. Already used in production.

2. :class:`TTLCache` — a generic thread-safe cache with per-entry TTL and
   hit/miss observability. Used by fetchers that previously kept their own
   module-level dicts (e.g. :mod:`data_provider.fundamentals_fetcher`).

Trading-session aware TTL helpers
---------------------------------
:func:`trading_session_ttl` returns a short TTL during the A-share trading
window (09:30-11:30 / 13:00-15:00 CST, with a small pre-open buffer) and a
longer TTL outside it. Callers can pass it to ``TTLCache.get_or_set``::

    from data_provider.caching_manager import TTLCache, trading_session_ttl

    cache = TTLCache()
    df = cache.get_or_set(
        key=("realtime", code),
        ttl=trading_session_ttl(short=30.0, long_=600.0),
        loader=lambda: fetch_realtime(code),
    )
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import pandas as pd

from .base import DataFetcherManager

logger = logging.getLogger(__name__)

_DISK_CACHE_ROOT = Path(
    os.environ.get("STOCK_DAILY_CACHE_DIR", "data/cache/daily")
)


# ---------------------------------------------------------------------------
# Generic TTL cache
# ---------------------------------------------------------------------------


class TTLCache:
    """Thread-safe in-memory cache with per-entry TTL and hit/miss stats.

    The cache is intentionally minimal — no LRU eviction, no async loaders —
    because most fetcher caches in this project are bounded by the size of
    the A-share universe (~5000 entries).
    """

    def __init__(self, name: str = "ttl_cache") -> None:
        self.name = name
        self._lock = threading.RLock()
        # key -> (value, expires_at_epoch)
        self._store: Dict[Any, Tuple[Any, float]] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: Any) -> Optional[Any]:
        """Return cached value or ``None`` if missing/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if time.time() >= expires_at:
                # Expired — drop and report miss.
                self._store.pop(key, None)
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: Any, value: Any, ttl: float) -> None:
        """Store ``value`` under ``key`` with ``ttl`` seconds lifetime."""
        if ttl <= 0:
            return
        with self._lock:
            self._store[key] = (value, time.time() + ttl)

    def get_or_set(self, key: Any, ttl: float, loader: Callable[[], Any]) -> Any:
        """Return cached value or compute via ``loader`` and cache the result.

        ``loader`` is invoked **outside** the lock so a slow load does not
        block other readers; a stampede on the same key is acceptable for
        this use case (the second caller simply replaces the entry).
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        value = loader()
        # Allow loaders to return ``None`` without polluting the cache
        # (callers that need to cache None should pass a sentinel).
        if value is not None:
            self.set(key, value, ttl)
        return value

    def invalidate(self, key: Any) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, int]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate_pct = int(self._hits * 100 / total) if total else 0
            return {
                "name": self.name,
                "size": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_pct": hit_rate_pct,
            }


def trading_session_ttl(short: float = 30.0, long_: float = 600.0) -> float:
    """Return ``short`` during A-share trading hours, ``long_`` otherwise.

    Trading window (Asia/Shanghai):
        - 09:15 - 11:30 (call auction + morning session)
        - 13:00 - 15:00 (afternoon session)
    """
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
    except ImportError:  # pragma: no cover - zoneinfo is stdlib in 3.9+
        import pytz

        now = datetime.now(pytz.timezone("Asia/Shanghai"))

    t = now.hour * 100 + now.minute
    if (915 <= t <= 1130) or (1300 <= t <= 1500):
        return short
    return long_


# ---------------------------------------------------------------------------
# Daily-data cache wrapper (existing API, unchanged)
# ---------------------------------------------------------------------------


class CachingDataFetcherManager:
    """Wraps :class:`DataFetcherManager` with an in-memory cache for
    ``get_daily_data``. Exposes ``_fetchers`` for ``get_tushare_api``
    compatibility.
    """

    def __init__(self, underlying: DataFetcherManager):
        self._underlying = underlying
        self._cache: dict = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def _fetchers(self):
        return self._underlying._fetchers

    def _disk_path(self, key: Tuple) -> Path:
        h = hashlib.md5(repr(key).encode()).hexdigest()[:16]
        stock_code = str(key[0])
        return _DISK_CACHE_ROOT / stock_code / f"{h}.parquet"

    def _load_disk(self, key: Tuple) -> Optional[Tuple[pd.DataFrame, str]]:
        p = self._disk_path(key)
        if not p.exists():
            return None
        try:
            df = pd.read_parquet(p)
            meta_p = p.with_suffix(".src")
            src = meta_p.read_text().strip() if meta_p.exists() else "disk_cache"
            return df, src
        except Exception as e:
            logger.debug(f"[DailyCache] load failed {p}: {e}")
            return None

    def _save_disk(self, key: Tuple, value: Tuple[pd.DataFrame, str]) -> None:
        df, src = value
        if df is None or df.empty:
            return
        p = self._disk_path(key)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
            p.with_suffix(".src").write_text(src or "")
        except Exception as e:
            logger.debug(f"[DailyCache] save failed {p}: {e}")

    def get_daily_data(
        self,
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
    ) -> Tuple[pd.DataFrame, str]:
        """Fetch daily data with two-tier cache (memory + parquet disk).

        Same (code, start, end, days) returns cached result. Disk cache
        survives across processes — critical for backtests that hit Tushare
        repeatedly for the same historical windows.
        """
        key = (stock_code, start_date or "", end_date or "", days)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                return self._cache[key]

        disk = self._load_disk(key)
        if disk is not None:
            with self._lock:
                self._cache[key] = disk
                self._hits += 1
            return disk

        with self._lock:
            self._misses += 1
        result = self._underlying.get_daily_data(
            stock_code, start_date=start_date, end_date=end_date, days=days
        )
        with self._lock:
            self._cache[key] = result
        self._save_disk(key, result)
        return result

    def get_index_daily_data(
        self,
        index_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 30,
    ):
        """Cache index daily data (CSI300 etc) with same two-tier strategy.

        Index data is heavily reused by MarketGuard across all backtest
        days — caching gives a ~100x speedup on repeated runs.
        """
        key = ("__index__", index_code, start_date or "", end_date or "", days)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                return self._cache[key]

        disk = self._load_disk(key)
        if disk is not None:
            with self._lock:
                self._cache[key] = disk
                self._hits += 1
            return disk

        with self._lock:
            self._misses += 1
        result = self._underlying.get_index_daily_data(
            index_code, start_date=start_date, end_date=end_date, days=days
        )
        with self._lock:
            self._cache[key] = result
        self._save_disk(key, result)
        return result

    def __getattr__(self, name: str):
        """Delegate any non-overridden attribute (methods like
        get_index_daily_data, get_stock_basic, etc.) to the underlying
        manager. Avoids having to mirror every method here.
        """
        return getattr(self._underlying, name)

    def clear_cache(self) -> None:
        """Clear cache (e.g. before a new backtest run)."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def cache_stats(self) -> Tuple[int, int]:
        """Return (hits, misses) for debugging."""
        with self._lock:
            return self._hits, self._misses


__all__ = [
    "TTLCache",
    "trading_session_ttl",
    "CachingDataFetcherManager",
]
