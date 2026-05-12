# -*- coding: utf-8 -*-
"""
Realtime quote helpers: full-market snapshots (``realtime_list`` / ``rt_k``),
daily_basic and 5-day volume caches, and the per-stock ``get_realtime_quote``.

Module-level caches and locks live here because they are shared across
threads of a single process and are only consumed by this mixin.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from ..base import is_bse_code
from ..caching_manager import TTLCache
from ..realtime_types import ChipDistribution  # noqa: F401  (re-export expected by callers)
from ..realtime_types import UnifiedRealtimeQuote, safe_float, safe_int
from .utils import _get_dynamic_cache_ttl

logger = logging.getLogger(__name__)

# Shared executor for Tushare network calls. Reusing a single pool avoids the
# cost of creating and tearing down threads on every request.
_SHARED_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tushare_fetch")

# ---------------------------------------------------------------------------
# Module-level caches use the unified ``TTLCache`` (per-entry TTL, thread-safe,
# hit/miss stats). Each cache has a single key that holds the most recent
# snapshot. Locks are still kept around the *fetcher* so only one thread
# refreshes a stale entry — TTLCache itself does not deduplicate stampedes.
# ---------------------------------------------------------------------------
_REALTIME_LIST_KEY = "snapshot"
_RT_K_KEY = "snapshot"
_DAILY_BASIC_KEY = "snapshot"
_DAILY_VOL_AVG_KEY = "snapshot"
# 24h: any same-day repeat call will hit; the next trading day's first call
# misses naturally because daily_basic / daily_vol_avg are keyed by today_str
# inside the loader, but here a single key + 24h TTL is cheaper and avoids
# unbounded growth.
_DAILY_TTL_SECONDS = 24 * 60 * 60

_realtime_list_cache = TTLCache(name="tushare_realtime_list")
_realtime_list_lock = threading.Lock()
_realtime_list_fail_count = 0
_realtime_list_disabled_until = 0.0
_REALTIME_LIST_MAX_FAILURES = 3
_REALTIME_LIST_COOLDOWN = 60.0  # seconds

_rt_k_cache = TTLCache(name="tushare_rt_k")
_rt_k_lock = threading.Lock()
_rt_k_fail_count = 0
_rt_k_disabled_until = 0.0
_RT_K_MAX_FAILURES = 3
_RT_K_COOLDOWN = 60.0  # seconds

_daily_basic_cache = TTLCache(name="tushare_daily_basic")
_daily_basic_lock = threading.Lock()

_daily_vol_avg_cache = TTLCache(name="tushare_daily_vol_avg")
_daily_vol_avg_lock = threading.Lock()


class _RealtimeMixin:
    """Mixin: full-market snapshots, per-stock realtime, enrichment helpers."""

    # ------------------------------------------------------------------
    # realtime_list full-market snapshot (cached, with wall-clock timeout)
    # ------------------------------------------------------------------
    def _fetch_realtime_list(self, timeout: float = 10.0) -> Optional[pd.DataFrame]:
        """
        Fetch full-market realtime snapshot via ts.realtime_list(src='dc').

        Features:
        - Module-level cache (TTL 30s) to avoid hammering the crawler endpoint.
        - Double-check locking: only ONE thread fetches when cache expires;
          other concurrent threads wait and reuse the refreshed cache.
        - Circuit breaker: after 3 consecutive failures, skip for 60s.
        - Wall-clock timeout (default 10s) via ThreadPoolExecutor.
        - Rate-limit safe: realtime_list is a 0-credit crawler API.

        Returns:
            DataFrame with ~5000 rows, or None on failure / timeout.
        """
        global _realtime_list_fail_count, _realtime_list_disabled_until

        current_time = time.time()

        # --- circuit breaker: skip if recently failed multiple times ---
        if current_time < _realtime_list_disabled_until:
            logger.debug(
                "[realtime_list] circuit breaker active, %.0fs remaining",
                _realtime_list_disabled_until - current_time,
            )
            return None

        # --- fast path: cache hit (no lock needed) ---
        cached_df = _realtime_list_cache.get(_REALTIME_LIST_KEY)
        if cached_df is not None:
            logger.debug("[realtime_list] cache hit (TTL %ds)", _get_dynamic_cache_ttl())
            return cached_df

        # --- slow path: acquire lock, double-check, then fetch ---
        with _realtime_list_lock:
            # Double-check after acquiring lock (another thread may have refreshed)
            cached_df = _realtime_list_cache.get(_REALTIME_LIST_KEY)
            if cached_df is not None:
                logger.debug("[realtime_list] cache hit after lock (another thread refreshed)")
                return cached_df

            # Also re-check circuit breaker inside lock
            current_time = time.time()
            if current_time < _realtime_list_disabled_until:
                return None

            # --- fetch with timeout (shared executor to avoid thread leak) ---
            import tushare as ts

            def _call():
                return ts.realtime_list(src='dc')

            future = _SHARED_EXECUTOR.submit(_call)
            try:
                df = future.result(timeout=timeout)

                if df is not None and not df.empty:
                    dyn_ttl = _get_dynamic_cache_ttl()
                    _realtime_list_cache.set(_REALTIME_LIST_KEY, df, dyn_ttl)
                    _realtime_list_fail_count = 0  # reset on success
                    logger.info(
                        f"[realtime_list] fetched {len(df)} rows, cache refreshed "
                        f"(TTL={dyn_ttl}s)"
                    )
                    return df
                else:
                    logger.warning("[realtime_list] returned empty DataFrame")
                    self._record_realtime_list_failure()
                    return None

            except FuturesTimeoutError:
                logger.warning(f"[realtime_list] wall-clock timeout ({timeout}s)")
                self._record_realtime_list_failure()
                return None
            except Exception as e:
                logger.warning(f"[realtime_list] failed: {e}")
                self._record_realtime_list_failure()
                return None

    @staticmethod
    def _record_realtime_list_failure():
        """Increment failure counter and activate circuit breaker if threshold reached."""
        global _realtime_list_fail_count, _realtime_list_disabled_until
        _realtime_list_fail_count += 1
        if _realtime_list_fail_count >= _REALTIME_LIST_MAX_FAILURES:
            _realtime_list_disabled_until = time.time() + _REALTIME_LIST_COOLDOWN
            logger.warning(
                "[realtime_list] circuit breaker activated: disabled for %.0fs "
                "after %d consecutive failures",
                _REALTIME_LIST_COOLDOWN,
                _realtime_list_fail_count,
            )

    # ------------------------------------------------------------------
    # rt_k full-market snapshot (cached, with wall-clock timeout)
    # ------------------------------------------------------------------
    def _fetch_realtime_rt_k(self, timeout: float = 8.0) -> Dict[str, UnifiedRealtimeQuote]:
        """Fetch full-market realtime snapshot via pro_api.rt_k().

        Features:
        - Module-level cache (TTL 30s) to avoid hammering the endpoint.
        - Double-check locking: only ONE thread fetches when cache expires.
        - Circuit breaker: after 3 consecutive failures, skip for 60s.
        - Wall-clock timeout (default 8s) via ThreadPoolExecutor.
        - Returns dict keyed by ts_code (e.g. '600000.SH').

        rt_k fields: ts_code, name, open, close, high, low, pre_close, vol, amount, ...
        Note: rt_k vol is in shares (股), converted to lots (手) by /100.
        """
        global _rt_k_fail_count, _rt_k_disabled_until

        if self._api is None:
            return {}

        current_time = time.time()

        # --- circuit breaker ---
        if current_time < _rt_k_disabled_until:
            logger.debug(
                "[rt_k] circuit breaker active, %.0fs remaining",
                _rt_k_disabled_until - current_time,
            )
            return {}

        # --- fast path: cache hit ---
        cached = _rt_k_cache.get(_RT_K_KEY)
        if cached:
            logger.debug("[rt_k] cache hit (TTL %ds)", _get_dynamic_cache_ttl())
            return cached

        # --- slow path: lock, double-check, fetch ---
        with _rt_k_lock:
            cached = _rt_k_cache.get(_RT_K_KEY)
            if cached:
                logger.debug("[rt_k] cache hit after lock")
                return cached

            current_time = time.time()
            if current_time < _rt_k_disabled_until:
                return {}

            from ..realtime_types import RealtimeSource

            # Batch requests: SH + SZ (covers main boards + ChiNext + STAR)
            batch_patterns = [
                '6*.SH',              # Shanghai main board + STAR (688xxx)
                '0*.SZ,3*.SZ',        # Shenzhen main board + ChiNext
            ]

            all_quotes: Dict[str, UnifiedRealtimeQuote] = {}

            for pattern in batch_patterns:
                def _call(p=pattern):
                    return self._api.rt_k(ts_code=p)

                future = _SHARED_EXECUTOR.submit(_call)
                try:
                    df = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    logger.warning("[rt_k] wall-clock timeout (%.0fs) for pattern %s", timeout, pattern)
                    self._record_rt_k_failure()
                    continue
                except Exception as e:
                    logger.warning("[rt_k] fetch failed for pattern %s: %s", pattern, e)
                    self._record_rt_k_failure()
                    continue

                if df is None or df.empty:
                    logger.debug("[rt_k] empty response for pattern %s", pattern)
                    continue

                # Normalize column names
                df.columns = [c.lower() for c in df.columns]

                for _, row in df.iterrows():
                    ts_code = str(row.get('ts_code', ''))
                    if not ts_code:
                        continue

                    close = safe_float(row.get('close'))
                    pre_close = safe_float(row.get('pre_close'))
                    if close is None or close <= 0:
                        continue

                    # Compute change_pct from close / pre_close
                    change_pct = None
                    change_amount = None
                    if pre_close and pre_close > 0:
                        change_amount = round(close - pre_close, 4)
                        change_pct = round((close - pre_close) / pre_close * 100, 2)

                    # vol is in shares (股), convert to lots (手) by /100
                    raw_vol = safe_float(row.get('vol'))
                    volume_lots = int(raw_vol / 100) if raw_vol and raw_vol > 0 else None

                    all_quotes[ts_code] = UnifiedRealtimeQuote(
                        code=ts_code,
                        name=str(row.get('name', '')),
                        source=RealtimeSource.TUSHARE,
                        price=close,
                        change_pct=change_pct,
                        change_amount=change_amount,
                        volume=volume_lots,
                        amount=safe_float(row.get('amount')),  # yuan
                        open_price=safe_float(row.get('open')),
                        high=safe_float(row.get('high')),
                        low=safe_float(row.get('low')),
                        pre_close=pre_close,
                    )

            if all_quotes:
                # Enrich with daily_basic (PE/PB/MV/turnover)
                self._enrich_rt_k_quotes(all_quotes)

                dyn_ttl = _get_dynamic_cache_ttl()
                _rt_k_cache.set(_RT_K_KEY, all_quotes, dyn_ttl)
                _rt_k_fail_count = 0
                logger.info("[rt_k] fetched %d quotes, cache refreshed (TTL=%.0fs)", len(all_quotes), dyn_ttl)
            else:
                self._record_rt_k_failure()
                logger.warning("[rt_k] all batches returned empty")

            return all_quotes

    @staticmethod
    def _record_rt_k_failure():
        """Increment rt_k failure counter and activate circuit breaker if threshold reached."""
        global _rt_k_fail_count, _rt_k_disabled_until
        _rt_k_fail_count += 1
        if _rt_k_fail_count >= _RT_K_MAX_FAILURES:
            _rt_k_disabled_until = time.time() + _RT_K_COOLDOWN
            logger.warning(
                "[rt_k] circuit breaker activated: disabled for %.0fs after %d consecutive failures",
                _RT_K_COOLDOWN, _rt_k_fail_count,
            )

    # ------------------------------------------------------------------
    # daily_basic cache (PE/PB/MV/turnover, refreshed once per trade date)
    # ------------------------------------------------------------------
    def _get_cached_daily_basic(self) -> Optional[pd.DataFrame]:
        """Get daily_basic data for the latest trade date, cached for the entire day.

        Returns DataFrame with columns: ts_code, turnover_rate, pe_ttm, pb,
        total_share, float_share, total_mv, circ_mv.
        """
        if self._api is None:
            return None

        china_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        today_str = china_now.strftime("%Y%m%d")
        cache_key = (_DAILY_BASIC_KEY, today_str)

        # Fast path: cache still valid for today
        cached = _daily_basic_cache.get(cache_key)
        if cached is not None:
            return cached

        with _daily_basic_lock:
            # Double-check
            cached = _daily_basic_cache.get(cache_key)
            if cached is not None:
                return cached

            try:
                # Determine latest trade date
                start_date = (china_now - pd.Timedelta(days=10)).strftime("%Y%m%d")
                self._check_rate_limit()
                df_cal = self._api.trade_cal(exchange="SSE", start_date=start_date, end_date=today_str)
                if df_cal is None or df_cal.empty:
                    return None
                df_cal.columns = [c.lower() for c in df_cal.columns]
                open_dates = sorted(df_cal[df_cal["is_open"] == 1]["cal_date"].tolist(), reverse=True)
                if not open_dates:
                    return None

                # Try latest trade dates (data may not be ready yet for today)
                for try_date in open_dates[:3]:
                    self._check_rate_limit()
                    df = self._api.daily_basic(
                        trade_date=try_date,
                        fields='ts_code,turnover_rate,pe_ttm,pb,total_share,float_share,total_mv,circ_mv',
                    )
                    if df is not None and not df.empty:
                        df.columns = [c.lower() for c in df.columns]
                        _daily_basic_cache.set(cache_key, df, _DAILY_TTL_SECONDS)
                        logger.info("[daily_basic] cached %d rows for trade_date=%s", len(df), try_date)
                        return df

                logger.warning("[daily_basic] no data for recent trade dates")
                return None

            except Exception as e:
                logger.warning("[daily_basic] fetch failed: %s", e)
                return None

    def _get_cached_daily_vol_avg(self) -> Optional[Dict[str, float]]:
        """Get 5-day average volume for all stocks, cached for the entire day.

        Returns dict mapping ts_code -> avg 5-day volume in 手 (lots).
        Uses Tushare daily() API to fetch last 5 trading days of volume data.
        """
        if self._api is None:
            return None

        china_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        today_str = china_now.strftime("%Y%m%d")
        cache_key = (_DAILY_VOL_AVG_KEY, today_str)

        # Fast path: cache still valid for today
        cached = _daily_vol_avg_cache.get(cache_key)
        if cached is not None:
            return cached

        with _daily_vol_avg_lock:
            # Double-check
            cached = _daily_vol_avg_cache.get(cache_key)
            if cached is not None:
                return cached

            try:
                # Determine recent trade dates from daily_basic cache or trade_cal
                start_date = (china_now - pd.Timedelta(days=15)).strftime("%Y%m%d")
                self._check_rate_limit()
                df_cal = self._api.trade_cal(exchange="SSE", start_date=start_date, end_date=today_str)
                if df_cal is None or df_cal.empty:
                    logger.debug("[daily_vol_avg] trade_cal returned empty, cannot fetch volume data")
                    return None
                df_cal.columns = [c.lower() for c in df_cal.columns]
                open_dates = sorted(df_cal[df_cal["is_open"] == 1]["cal_date"].tolist(), reverse=True)
                if not open_dates:
                    logger.debug("[daily_vol_avg] no open trading dates found in trade_cal")
                    return None

                # We need 5 completed trading days (exclude today if market still open)
                # Take up to 7 candidates, skip the first if it's today and market not closed
                candidate_dates = open_dates[:7]
                if candidate_dates and candidate_dates[0] == today_str and china_now.hour < 15:
                    candidate_dates = candidate_dates[1:]
                trade_dates = candidate_dates[:5]

                if not trade_dates:
                    logger.warning("[daily_vol_avg] insufficient completed trade dates after filtering")
                    return None

                # Fetch daily vol for each trade date
                all_dfs = []
                for td in trade_dates:
                    self._check_rate_limit()
                    df = self._api.daily(trade_date=td, fields='ts_code,vol')
                    if df is not None and not df.empty:
                        df.columns = [c.lower() for c in df.columns]
                        all_dfs.append(df)

                if not all_dfs:
                    logger.warning("[daily_vol_avg] no daily data for recent trade dates")
                    return None

                # Compute average volume per stock
                combined = pd.concat(all_dfs, ignore_index=True)
                avg_vol = combined.groupby("ts_code")["vol"].mean()
                result = avg_vol.to_dict()

                _daily_vol_avg_cache.set(cache_key, result, _DAILY_TTL_SECONDS)
                logger.info(
                    "[daily_vol_avg] cached avg vol for %d stocks from %d trade days (dates: %s)",
                    len(result), len(all_dfs), ','.join(trade_dates[-1:0:-1]),  # show in reverse chronological order
                )
                return result

            except Exception as e:
                logger.warning("[daily_vol_avg] fetch failed: %s", e)
                return None

    @staticmethod
    def _calc_rt_k_volume_ratio(current_vol: float, avg_5d_vol: float) -> Optional[float]:
        """Calculate volume ratio for rt_k quotes considering trading session elapsed time.

        Same logic as stock_picker_service._calc_volume_ratio but returns None on
        invalid inputs instead of 0.0, so the caller can decide whether to set the field.

        Args:
            current_vol: Today's cumulative volume in 手.
            avg_5d_vol: 5-day average daily volume in 手.

        Returns:
            Volume ratio rounded to 2 decimals, or None when inputs are invalid.
        """
        if not avg_5d_vol or avg_5d_vol <= 0 or not current_vol or current_vol <= 0:
            return None

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        total_minutes = 240  # 9:30-11:30 (120 min) + 13:00-15:00 (120 min)

        # After market close: simple full-day ratio
        if now.hour >= 15:
            return round(current_vol / avg_5d_vol, 2)

        # Before market open
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            return None

        # Intraday: compute elapsed trading minutes (exclude lunch break)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        morning_close = now.replace(hour=11, minute=30, second=0, microsecond=0)
        afternoon_open = now.replace(hour=13, minute=0, second=0, microsecond=0)

        if now <= morning_close:
            elapsed = (now - market_open).total_seconds() / 60
        elif now < afternoon_open:
            elapsed = 120  # full morning session
        else:
            elapsed = 120 + (now - afternoon_open).total_seconds() / 60

        elapsed = max(1, min(elapsed, total_minutes))
        avg_per_min = avg_5d_vol / total_minutes
        current_per_min = current_vol / elapsed

        return round(current_per_min / avg_per_min, 2) if avg_per_min > 0 else None

    def _enrich_rt_k_quotes(self, quotes: Dict[str, UnifiedRealtimeQuote]):
        """Enrich rt_k quotes with daily_basic data (PE/PB/MV/turnover) and volume ratio.

        Modifies quotes in-place. Skips silently on failure.
        Market cap is recomputed using realtime price * shares for accuracy.
        Volume ratio is computed from rt_k realtime volume and 5-day avg volume.
        """
        try:
            df_basic = self._get_cached_daily_basic()
            if df_basic is None or df_basic.empty:
                return

            for _, row in df_basic.iterrows():
                code = str(row.get("ts_code", ""))
                if code not in quotes:
                    continue
                q = quotes[code]

                # Turnover rate from daily_basic (close enough for intraday)
                if q.turnover_rate is None or q.turnover_rate == 0:
                    q.turnover_rate = safe_float(row.get("turnover_rate"))

                # PE/PB from daily_basic
                if q.pe_ratio is None or q.pe_ratio == 0:
                    q.pe_ratio = safe_float(row.get("pe_ttm"))
                if q.pb_ratio is None or q.pb_ratio == 0:
                    q.pb_ratio = safe_float(row.get("pb"))

                # Market cap: use realtime price * shares for accuracy
                total_share = safe_float(row.get("total_share"))  # 万股
                float_share = safe_float(row.get("float_share"))  # 万股
                if q.price and q.price > 0:
                    if total_share and total_share > 0:
                        q.total_mv = q.price * total_share * 10000  # 元
                    if float_share and float_share > 0:
                        q.circ_mv = q.price * float_share * 10000  # 元

        except Exception as e:
            logger.warning("[rt_k] failed to enrich with daily_basic: %s", e)

        # --- Volume ratio enrichment (separate try-block to not block PE/PB/MV) ---
        try:
            vol_avg_map = self._get_cached_daily_vol_avg()
            if not vol_avg_map:
                logger.debug("[rt_k] volume_ratio cache unavailable, skipping enrichment")
                return

            enriched_count = 0
            for ts_code, q in quotes.items():
                avg_5d = vol_avg_map.get(ts_code)
                if avg_5d is None or avg_5d <= 0:
                    continue
                current_vol = q.volume
                if current_vol is None or current_vol <= 0:
                    continue
                vr = self._calc_rt_k_volume_ratio(current_vol, avg_5d)
                if vr is not None:
                    q.volume_ratio = vr
                    enriched_count += 1

            if enriched_count > 0:
                logger.debug("[rt_k] enriched volume_ratio for %d quotes", enriched_count)

        except Exception as e:
            logger.warning("[rt_k] failed to enrich volume_ratio: %s", e)

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        Get realtime quote for a single stock.

        Strategy (priority order):
        1. rt_k (Tushare native, stable overseas) – full-market snapshot with 30s cache.
        2. ts.realtime_list(src='dc') – 0-credit crawler, full-market snapshot
           with 30s cache.  Rich fields: price, pct_change, volume, amount,
           open, high, low, pre_close, etc.
        3. ts.realtime_quote() – 0-credit crawler, per-stock (legacy)
        4. ts.get_realtime_quotes() – old Sina-based API (legacy)
        5. Pro quotation API (requires credits)

        Args:
            stock_code: Stock code (6-digit or with exchange suffix)

        Returns:
            UnifiedRealtimeQuote object, or None on failure
        """
        if self._api is None:
            return None

        from ..realtime_types import RealtimeSource

        code_6 = stock_code.split('.')[0] if '.' in stock_code else stock_code

        # === Strategy 1: rt_k (Tushare native, stable overseas, cached) ===
        rt_k_quotes = self._fetch_realtime_rt_k()
        if rt_k_quotes:
            ts_code_full = self._convert_stock_code(stock_code)
            quote = rt_k_quotes.get(ts_code_full)
            if quote:
                # Return a copy with the original stock_code as code
                logger.debug("[RealTime] %s via rt_k (cached full-market)", stock_code)
                return UnifiedRealtimeQuote(
                    code=stock_code,
                    name=quote.name,
                    source=quote.source,
                    price=quote.price,
                    change_pct=quote.change_pct,
                    change_amount=quote.change_amount,
                    volume=quote.volume,
                    amount=quote.amount,
                    volume_ratio=quote.volume_ratio,
                    turnover_rate=quote.turnover_rate,
                    open_price=quote.open_price,
                    high=quote.high,
                    low=quote.low,
                    pre_close=quote.pre_close,
                    pe_ratio=quote.pe_ratio,
                    pb_ratio=quote.pb_ratio,
                    total_mv=quote.total_mv,
                    circ_mv=quote.circ_mv,
                )

        # === Strategy 2: realtime_list (full-market, cached) ===
        df_all = self._fetch_realtime_list()
        if df_all is not None and not df_all.empty:
            try:
                # realtime_list returns ts_code like '000001.SZ'
                ts_code_full = self._convert_stock_code(stock_code)
                row = df_all[df_all['ts_code'] == ts_code_full]
                if row.empty:
                    # Also try matching by pure 6-digit code prefix
                    row = df_all[df_all['ts_code'].str.startswith(code_6)]
                if not row.empty:
                    row = row.iloc[0]
                    _price = safe_float(row.get('price'))
                    _pre = safe_float(row.get('pre_close'))
                    _change_amt = safe_float(row.get('change'))
                    if _change_amt is None and _price is not None and _pre is not None and _pre != 0:
                        _change_amt = round(_price - _pre, 4)

                    # realtime_list(src='dc') returns rich fields including
                    # vol_ratio, turnover_rate, pe, pb, total_mv, float_mv, etc.
                    _vol_ratio = safe_float(row.get('vol_ratio'))
                    _turnover = safe_float(row.get('turnover_rate'))
                    _pe = safe_float(row.get('pe'))
                    _pb = safe_float(row.get('pb'))
                    # total_mv from realtime_list is in 元; keep as-is for UnifiedRealtimeQuote
                    _total_mv = safe_float(row.get('total_mv'))
                    _circ_mv = safe_float(row.get('float_mv'))

                    logger.debug(
                        f"[RealTime] {stock_code} via realtime_list (cached full-market), "
                        f"vol_ratio={_vol_ratio}"
                    )
                    return UnifiedRealtimeQuote(
                        code=stock_code,
                        name=str(row.get('name', '')),
                        source=RealtimeSource.TUSHARE,
                        price=_price,
                        change_pct=safe_float(row.get('pct_change')),
                        change_amount=_change_amt,
                        volume=safe_int(row.get('volume')),
                        amount=safe_float(row.get('amount')),
                        volume_ratio=_vol_ratio,
                        turnover_rate=_turnover,
                        high=safe_float(row.get('high')),
                        low=safe_float(row.get('low')),
                        open_price=safe_float(row.get('open')),
                        pre_close=_pre,
                        pe_ratio=_pe,
                        pb_ratio=_pb,
                        total_mv=_total_mv,
                        circ_mv=_circ_mv,
                    )
            except Exception as e:
                logger.debug(f"[RealTime] realtime_list lookup failed for {stock_code}: {e}")

        # === Strategy 3: ts.realtime_quote() – 0-credit crawler (per stock) ===
        try:
            import tushare as ts
            df = ts.realtime_quote(code_6)

            if df is not None and not df.empty:
                row = df.iloc[0]
                logger.debug(f"[RealTime] {stock_code} via realtime_quote (0-credit crawler)")
                change_pct = safe_float(row.get('changepercent')) or safe_float(row.get('change_pct'))
                _price = safe_float(row.get('price'))
                _pre = safe_float(row.get('pre_close')) or safe_float(row.get('settlement'))
                _change_amount = (
                    (_price - _pre) if (_price is not None and _pre is not None and _pre != 0) else None
                )
                return UnifiedRealtimeQuote(
                    code=stock_code,
                    name=str(row.get('name', '')),
                    source=RealtimeSource.TUSHARE,
                    price=_price,
                    change_pct=change_pct,
                    change_amount=_change_amount,
                    volume=safe_int(row.get('volume')),
                    amount=None,
                    high=None,
                    low=None,
                    open_price=None,
                    pre_close=_pre,
                    turnover_rate=None,
                    pe_ratio=None,
                    pb_ratio=None,
                    total_mv=None,
                )
        except Exception as e:
            logger.debug(f"[RealTime] realtime_quote failed: {e}")

        # === Strategy 4: legacy ts.get_realtime_quotes (Sina-based) ===
        try:
            import tushare as ts
            if code_6 == '000001':
                symbol = 'sh000001'
            elif code_6 == '399001':
                symbol = 'sz399001'
            elif code_6 == '399006':
                symbol = 'sz399006'
            elif code_6 == '000300':
                symbol = 'sh000300'
            elif is_bse_code(code_6):
                symbol = f"bj{code_6}"
            else:
                symbol = code_6

            df = ts.get_realtime_quotes(symbol)
            if df is not None and not df.empty:
                row = df.iloc[0]
                logger.debug(f"[RealTime] {stock_code} via get_realtime_quotes (legacy)")
                _price = safe_float(row.get('price'))
                _pre = safe_float(row.get('pre_close')) or safe_float(row.get('settlement'))
                _change_amount = (
                    (_price - _pre) if (_price is not None and _pre is not None and _pre != 0) else None
                )
                return UnifiedRealtimeQuote(
                    code=stock_code,
                    name=str(row.get('name', '')),
                    source=RealtimeSource.TUSHARE,
                    price=_price,
                    change_pct=safe_float(row.get('changepercent')),
                    change_amount=_change_amount,
                    volume=safe_int(row.get('volume')),
                    amount=None,
                    high=None,
                    low=None,
                    open_price=None,
                    pre_close=_pre,
                    turnover_rate=None,
                    pe_ratio=None,
                    pb_ratio=None,
                    total_mv=None,
                )
        except Exception as e:
            logger.debug(f"[RealTime] get_realtime_quotes failed: {e}")

        # === Strategy 5: Pro quotation API (requires credits) ===
        try:
            self._check_rate_limit()
            ts_code = self._convert_stock_code(stock_code)
            df = self._api.quotation(ts_code=ts_code)
            if df is not None and not df.empty:
                row = df.iloc[0]
                logger.debug(f"[RealTime] {stock_code} via Pro quotation API")
                return UnifiedRealtimeQuote(
                    code=stock_code,
                    name=str(row.get('name', '')),
                    source=RealtimeSource.TUSHARE,
                    price=safe_float(row.get('price')),
                    change_pct=safe_float(row.get('pct_chg')),
                    change_amount=safe_float(row.get('change')),
                    volume=safe_int(row.get('vol')),
                    amount=safe_float(row.get('amount')),
                    high=safe_float(row.get('high')),
                    low=safe_float(row.get('low')),
                    open_price=safe_float(row.get('open')),
                    pre_close=safe_float(row.get('pre_close')),
                    turnover_rate=safe_float(row.get('turnover_ratio')),
                    pe_ratio=safe_float(row.get('pe')),
                    pb_ratio=safe_float(row.get('pb')),
                    total_mv=safe_float(row.get('total_mv')),
                )
        except Exception as e:
            logger.debug(f"[RealTime] Pro quotation API failed: {e}")

        logger.warning(f"[RealTime] Unable to fetch realtime quote for {stock_code}")
        return None
