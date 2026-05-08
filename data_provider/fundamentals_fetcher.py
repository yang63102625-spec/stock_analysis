# -*- coding: utf-8 -*-
"""
Fundamentals Fetcher
=====================

Lightweight wrapper around Tushare Pro APIs that hard-veto filters need:

| Endpoint            | Purpose                                  | Cache TTL |
|---------------------|------------------------------------------|-----------|
| pledge_stat         | Controlling shareholder pledge ratio     | 7 days    |
| fina_indicator      | Goodwill / total assets, ROE             | 30 days   |
| stk_holdertrade     | Recent shareholder reduction (>2%)       | 1 day     |
| forecast / express  | Earnings preview / variance flips        | 7 days    |

The fetcher returns simple, cached dicts indexed by ts_code so picker filters
can do O(1) lookups without per-stock Tushare calls in the hot path.

Designed to fail closed: when Tushare is unavailable or rate-limited, the
returned dict is empty and the picker veto filter degrades to a no-op (i.e.
candidates pass through). This protects production reliability.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


# Veto thresholds (centralised so picker layer can tune without code changes).
VETO_PLEDGE_RATIO = 50.0       # %: controlling shareholder pledge above this
                                # (tightened 60→50: most A-share pledge blow-ups occur >50%)
VETO_GOODWILL_RATIO = 30.0     # %: goodwill / total_assets above this
VETO_REDUCTION_PCT = 1.0       # %: any holder reduction >= 1% in window (was 2%)
VETO_REDUCTION_DAYS = 10        # window of recent days (was 5: insider-selling
                                # negative impact persists 2-3 weeks)
VETO_FORECAST_NEGATIVE_TYPES: Set[str] = {
    "预亏", "预减", "首亏", "续亏", "增亏", "扭亏",  # last is positive but means past loss
}


@dataclass
class FundamentalsCache:
    """In-memory cache (per-process). For multi-process backtests use disk cache."""

    pledge: Dict[str, float] = field(default_factory=dict)        # ts_code -> pledge%
    pledge_ts: float = 0.0
    goodwill_ratio: Dict[str, float] = field(default_factory=dict)
    goodwill_ts: float = 0.0
    recent_reductions: Set[str] = field(default_factory=set)      # ts_codes with recent reductions
    reductions_ts: float = 0.0
    forecast_negative: Set[str] = field(default_factory=set)      # ts_codes with negative forecast
    forecast_ts: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_cache = FundamentalsCache()
_TTL_PLEDGE = 7 * 86400
_TTL_GOODWILL = 30 * 86400
_TTL_REDUCTION = 1 * 86400
_TTL_FORECAST = 7 * 86400


def _ensure_pledge(api: Any) -> Dict[str, float]:
    """Return ts_code -> pledge ratio (latest)."""
    now = time.time()
    if _cache.pledge and (now - _cache.pledge_ts) < _TTL_PLEDGE:
        return _cache.pledge
    with _cache.lock:
        if _cache.pledge and (now - _cache.pledge_ts) < _TTL_PLEDGE:
            return _cache.pledge
        try:
            df = api.pledge_stat()  # latest snapshot, all stocks
            if df is None or df.empty:
                return {}
            df.columns = [c.lower() for c in df.columns]
            # pledge_ratio is typically a fraction in some tushare versions; normalise to percent
            ratio_col = next((c for c in ("pledge_ratio", "p_total_ratio", "total_ratio") if c in df.columns), None)
            code_col = "ts_code" if "ts_code" in df.columns else df.columns[0]
            if ratio_col is None:
                return {}
            mapping: Dict[str, float] = {}
            df_sorted = df.sort_values("end_date", ascending=False) if "end_date" in df.columns else df
            for _, row in df_sorted.iterrows():
                code = str(row.get(code_col, ""))
                if not code or code in mapping:
                    continue
                v = row.get(ratio_col)
                try:
                    val = float(v) if v is not None else None
                    if val is None:
                        continue
                    # If <= 1.5 assume fraction; multiply.
                    if val <= 1.5:
                        val *= 100.0
                    mapping[code] = val
                except (TypeError, ValueError):
                    continue
            _cache.pledge = mapping
            _cache.pledge_ts = now
            logger.info("[fundamentals] Loaded pledge_stat for %d stocks", len(mapping))
            return mapping
        except Exception as exc:
            logger.warning("[fundamentals] pledge_stat fetch failed: %s", exc)
            return {}


def _ensure_goodwill(api: Any) -> Dict[str, float]:
    """Return ts_code -> (goodwill / total_assets) percent (latest period)."""
    now = time.time()
    if _cache.goodwill_ratio and (now - _cache.goodwill_ts) < _TTL_GOODWILL:
        return _cache.goodwill_ratio
    with _cache.lock:
        if _cache.goodwill_ratio and (now - _cache.goodwill_ts) < _TTL_GOODWILL:
            return _cache.goodwill_ratio
        try:
            # fina_indicator: per-stock; bulk fetch via empty period not supported
            # Instead use balancesheet for goodwill; gracefully skip on error.
            df = api.balancesheet_vip(fields="ts_code,end_date,goodwill,total_assets")  # may not be available
            if df is None or df.empty:
                return {}
            df.columns = [c.lower() for c in df.columns]
            df = df.sort_values(["ts_code", "end_date"], ascending=[True, False])
            mapping: Dict[str, float] = {}
            for code, group in df.groupby("ts_code"):
                row = group.iloc[0]
                gw = row.get("goodwill")
                ta = row.get("total_assets")
                try:
                    if gw and ta and float(ta) > 0:
                        mapping[str(code)] = float(gw) / float(ta) * 100.0
                except (TypeError, ValueError):
                    continue
            _cache.goodwill_ratio = mapping
            _cache.goodwill_ts = now
            logger.info("[fundamentals] Loaded goodwill ratio for %d stocks", len(mapping))
            return mapping
        except Exception as exc:
            logger.warning("[fundamentals] goodwill fetch failed (pro API privilege required): %s", exc)
            return {}


def _ensure_recent_reductions(api: Any, days: int = VETO_REDUCTION_DAYS) -> Set[str]:
    """Return set of ts_codes with shareholder reduction >= 2% in last N days."""
    now = time.time()
    if _cache.recent_reductions and (now - _cache.reductions_ts) < _TTL_REDUCTION:
        return _cache.recent_reductions
    with _cache.lock:
        if _cache.recent_reductions and (now - _cache.reductions_ts) < _TTL_REDUCTION:
            return _cache.recent_reductions
        try:
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            df = api.stk_holdertrade(start_date=start, end_date=end)
            if df is None or df.empty:
                return set()
            df.columns = [c.lower() for c in df.columns]
            in_de_col = next((c for c in ("in_de", "type") if c in df.columns), None)
            ratio_col = next((c for c in ("change_ratio", "ratio", "after_ratio") if c in df.columns), None)
            code_col = "ts_code" if "ts_code" in df.columns else df.columns[0]
            codes: Set[str] = set()
            for _, row in df.iterrows():
                if in_de_col and str(row.get(in_de_col, "")).upper() not in ("DE", "REDUCE", "减持"):
                    continue
                ratio = row.get(ratio_col) if ratio_col else None
                try:
                    if ratio is not None and abs(float(ratio)) >= VETO_REDUCTION_PCT:
                        codes.add(str(row.get(code_col, "")))
                except (TypeError, ValueError):
                    continue
            _cache.recent_reductions = codes
            _cache.reductions_ts = now
            logger.info("[fundamentals] Loaded recent reductions: %d stocks flagged", len(codes))
            return codes
        except Exception as exc:
            logger.warning("[fundamentals] stk_holdertrade fetch failed: %s", exc)
            return set()


def _ensure_negative_forecasts(api: Any) -> Set[str]:
    """Return set of ts_codes with recent (last 6 months) negative forecast."""
    now = time.time()
    if _cache.forecast_negative and (now - _cache.forecast_ts) < _TTL_FORECAST:
        return _cache.forecast_negative
    with _cache.lock:
        if _cache.forecast_negative and (now - _cache.forecast_ts) < _TTL_FORECAST:
            return _cache.forecast_negative
        try:
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
            df = api.forecast(start_date=start, end_date=end)
            if df is None or df.empty:
                return set()
            df.columns = [c.lower() for c in df.columns]
            type_col = next((c for c in ("type", "forecast_type") if c in df.columns), None)
            code_col = "ts_code" if "ts_code" in df.columns else df.columns[0]
            codes: Set[str] = set()
            if type_col is None:
                return set()
            for _, row in df.iterrows():
                t = str(row.get(type_col, "")).strip()
                if t in VETO_FORECAST_NEGATIVE_TYPES and t != "扭亏":
                    codes.add(str(row.get(code_col, "")))
            _cache.forecast_negative = codes
            _cache.forecast_ts = now
            logger.info("[fundamentals] Loaded negative forecasts: %d stocks flagged", len(codes))
            return codes
        except Exception as exc:
            logger.warning("[fundamentals] forecast fetch failed: %s", exc)
            return set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class VetoVerdict:
    """Aggregated veto verdict for a single stock."""

    ts_code: str
    is_vetoed: bool = False
    reasons: List[str] = field(default_factory=list)


def evaluate_vetoes(api: Any, ts_codes: List[str]) -> Dict[str, VetoVerdict]:
    """Evaluate veto conditions for a batch of ts_codes.

    Returns mapping from ts_code -> VetoVerdict. Stocks not flagged on any
    dimension still receive a verdict with is_vetoed=False.

    All four lookups are cached at the module level. When Tushare is
    unavailable (api=None) or any lookup fails, that dimension is silently
    skipped (fail-closed → permissive). The picker layer treats this as
    "no veto data, proceed" rather than blocking.
    """
    verdicts: Dict[str, VetoVerdict] = {code: VetoVerdict(ts_code=code) for code in ts_codes}
    if not ts_codes or api is None:
        return verdicts

    pledge_map = _ensure_pledge(api)
    goodwill_map = _ensure_goodwill(api)
    reduction_set = _ensure_recent_reductions(api)
    forecast_set = _ensure_negative_forecasts(api)

    for code in ts_codes:
        v = verdicts[code]
        # 1. Pledge
        pr = pledge_map.get(code)
        if pr is not None and pr > VETO_PLEDGE_RATIO:
            v.is_vetoed = True
            v.reasons.append(f"质押率 {pr:.1f}% > {VETO_PLEDGE_RATIO:.0f}%")
        # 2. Goodwill
        gw = goodwill_map.get(code)
        if gw is not None and gw > VETO_GOODWILL_RATIO:
            v.is_vetoed = True
            v.reasons.append(f"商誉占比 {gw:.1f}% > {VETO_GOODWILL_RATIO:.0f}%")
        # 3. Recent reduction
        if code in reduction_set:
            v.is_vetoed = True
            v.reasons.append(f"近期 ≥{VETO_REDUCTION_PCT:.0f}% 大额减持")
        # 4. Negative forecast
        if code in forecast_set:
            v.is_vetoed = True
            v.reasons.append("业绩预减/预亏")

    return verdicts


def get_veto_summary(verdicts: Dict[str, VetoVerdict]) -> Dict[str, int]:
    """Aggregate veto reasons across a batch for stats display."""
    summary: Dict[str, int] = {}
    for v in verdicts.values():
        if v.is_vetoed:
            for r in v.reasons:
                key = r.split(" ")[0] if " " in r else r
                summary[key] = summary.get(key, 0) + 1
    return summary


def reset_cache() -> None:
    """Reset module-level cache (used by tests)."""
    _cache.pledge.clear()
    _cache.pledge_ts = 0.0
    _cache.goodwill_ratio.clear()
    _cache.goodwill_ts = 0.0
    _cache.recent_reductions.clear()
    _cache.reductions_ts = 0.0
    _cache.forecast_negative.clear()
    _cache.forecast_ts = 0.0
