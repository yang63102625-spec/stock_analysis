# -*- coding: utf-8 -*-
"""Slow-bull screener — 30° pattern, long-term holdings.

Selects stocks that show a sustainable, low-volatility uptrend with
rising lows over the last ~250 trading days. This is *not* a short
swing strategy; it is a watchlist / long-only entry tool tuned for
quarterly-or-longer holds. See ``scripts/scan_slow_bull.py`` for the
research notebook this is derived from.

Pattern criteria (all must pass):

  1. ≥300 trading days of history (excludes new listings)
  2. MA20 > MA60 > MA120 > MA250 (full bullish stack), price > MA60
  3. Annualised MA60 log-slope ∈ [SLOPE_MIN, SLOPE_MAX] (default 10%–60%)
  4. Three rising 90-day lows (higher-lows structure)
  5. 60d ATR / price ≤ VOL_MAX (default 3.5%)
  6. 250d max drawdown ≤ DD_MAX (default 25%)
  7. Distance to 250d high ≤ DIST_HIGH_MAX (default 8%, near new high)
  8. Distance to 250d low ≥ DIST_LOW_MIN (default 30%, already out of bottom)
  9. PE ∈ [PE_MIN, PE_MAX] (default 5–80) and total_mv ≥ MCAP_MIN_YI (default 100亿)
 10. Exclude ST / 退 / *ST / BSE (8/4/92x prefix)

Single execution path: iterates the LocalDB universe in both live and
historical modes since live "spot" data only carries 60d history,
which is insufficient to evaluate this pattern. In live mode we treat
"today" as the most recent LocalDB trade date.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from src.services.picker.constants import ScreenedStock

logger = logging.getLogger(__name__)


# Defaults mirror scripts/scan_slow_bull.py loose-PE preset.
_D = {
    "TOP_N": 20,
    "MIN_HISTORY_DAYS": 300,
    "SLOPE_MIN_ANN": 0.10,
    "SLOPE_MAX_ANN": 0.60,
    "VOL_MAX": 0.035,
    "DD_MAX": 0.25,
    "DIST_HIGH_MAX": 0.08,
    "DIST_LOW_MIN": 0.30,
    "PE_MIN": 5.0,
    "PE_MAX": 80.0,
    "MCAP_MIN_YI": 100.0,
}


def _envf(key: str) -> float:
    """Read SLOW_BULL_<KEY> env override, fallback to default."""
    try:
        return float(os.environ.get(f"SLOW_BULL_{key}", _D[key]))
    except (ValueError, TypeError):
        return float(_D[key])


def _envi(key: str) -> int:
    return int(_envf(key))


def slow_bull_top_n() -> int:
    return max(1, _envi("TOP_N"))


def _slope_pct_per_year(series: pd.Series) -> float:
    y = np.log(series.values.astype(float))
    n = len(y)
    if n < 2 or not np.all(np.isfinite(y)):
        return float("nan")
    x = np.arange(n, dtype=float)
    return float(np.polyfit(x, y, 1)[0]) * 250.0


def _evaluate_slow_bull(df_daily: pd.DataFrame) -> Optional[dict]:
    """Return per-stock metrics dict if pattern passes, else None."""
    min_hist = _envi("MIN_HISTORY_DAYS")
    if df_daily is None or len(df_daily) < min_hist:
        return None
    df = df_daily.sort_values("trade_date").tail(260)
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    if len(close) < 250:
        return None

    last = float(close.iloc[-1])
    high250 = float(high.max())
    low250 = float(low.min())
    if last <= 0 or high250 <= 0 or low250 <= 0:
        return None

    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma120 = close.rolling(120).mean().iloc[-1]
    ma250 = close.rolling(250).mean().iloc[-1]
    if not all(np.isfinite([ma20, ma60, ma120, ma250])):
        return None
    if not (ma20 > ma60 > ma120 > ma250 and last > ma60):
        return None

    ma60_series = close.rolling(60).mean().dropna().tail(60)
    if len(ma60_series) < 30:
        return None
    slope_ann = _slope_pct_per_year(ma60_series)
    if not (_envf("SLOPE_MIN_ANN") <= slope_ann <= _envf("SLOPE_MAX_ANN")):
        return None

    seg3 = low.iloc[-90:].min()
    seg2 = low.iloc[-180:-90].min()
    seg1 = low.iloc[-260:-180].min() if len(low) >= 260 else low.iloc[:max(1, len(low) - 180)].min()
    if not (seg3 > seg2 > seg1):
        return None

    tr = pd.concat([
        (high - low).abs(),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr60 = tr.rolling(60).mean().iloc[-1]
    vol_pct = atr60 / last if last else float("nan")
    if not (np.isfinite(vol_pct) and vol_pct <= _envf("VOL_MAX")):
        return None

    roll_max = close.rolling(250, min_periods=50).max()
    dd_series = (close / roll_max) - 1.0
    dd250 = float(-dd_series.tail(250).min()) if dd_series.notna().any() else float("nan")
    if not (np.isfinite(dd250) and dd250 <= _envf("DD_MAX")):
        return None

    dist_high = (high250 - last) / high250
    dist_low = (last - low250) / low250
    if dist_high > _envf("DIST_HIGH_MAX") or dist_low < _envf("DIST_LOW_MIN"):
        return None

    return {
        "last": last,
        "slope_ann": float(slope_ann),
        "vol_pct": float(vol_pct),
        "dd250": float(dd250),
        "dist_high": float(dist_high),
        "dist_low": float(dist_low),
    }


def _slow_bull_score(m: dict) -> float:
    """Composite: reward 25%/y slope, low vol, low DD."""
    slope_pct = m["slope_ann"] * 100
    vol_pct = m["vol_pct"] * 100
    dd_pct = m["dd250"] * 100
    slope_term = max(0.0, 10.0 - abs(slope_pct - 25.0) / 3.5)
    vol_term = max(0.0, (3.5 - vol_pct)) * 5.0
    dd_term = max(0.0, (25.0 - dd_pct)) * 0.4
    return slope_term + vol_term + dd_term


class _SlowBullMixin:
    """Mixin: ``_screen_slow_bull``."""

    def _screen_slow_bull(
        self,
        trade_date_yyyymmdd: Optional[str] = None,
        top_n: int = None,
    ) -> List[ScreenedStock]:
        top_n = top_n or slow_bull_top_n()
        try:
            from src.services.local_db import default_db
        except Exception as e:
            logger.warning("[SlowBull] LocalStockDB unavailable: %s", e)
            return []

        db = default_db()
        td = trade_date_yyyymmdd  # may be None in live mode

        sb = db.get_stock_basic()
        if sb is None or sb.empty:
            logger.warning("[SlowBull] stock_basic empty")
            return []

        # Universe exclusions (ST / 退 / BSE)
        sb = self._slow_bull_universe(sb)
        if sb.empty:
            return []

        # Snapshot for PE / market_cap filter
        snapshot_td = self._slow_bull_latest_basic_date(db, td)
        basic = pd.DataFrame()
        if snapshot_td:
            try:
                b = db.get_market_daily_basic(snapshot_td)
                if b is not None and not b.empty:
                    basic = b[["ts_code", "pe_ttm", "total_mv"]].copy()
                    basic["total_mv_yi"] = basic["total_mv"] / 1e4
            except Exception as e:
                logger.warning("[SlowBull] daily_basic %s failed: %s", snapshot_td, e)

        pe_min, pe_max = _envf("PE_MIN"), _envf("PE_MAX")
        mcap_min = _envf("MCAP_MIN_YI")

        results: List[Tuple[str, str, dict]] = []
        for row in sb.itertuples(index=False):
            ts_code = getattr(row, "ts_code", None)
            name = getattr(row, "name", "")
            if not ts_code:
                continue
            try:
                df_d = db.get_daily(ts_code, end_date=td) if td else db.get_daily(ts_code)
            except Exception:
                continue
            m = _evaluate_slow_bull(df_d)
            if m is None:
                continue
            results.append((ts_code, name, m))

        if not results:
            logger.info("[SlowBull] no geometric hits as_of=%s", td or "live")
            return []

        df_hits = pd.DataFrame([
            {"ts_code": ts, "name": nm, **m} for ts, nm, m in results
        ])
        if not basic.empty:
            df_hits = df_hits.merge(basic, on="ts_code", how="left")
            df_hits = df_hits[
                df_hits["pe_ttm"].between(pe_min, pe_max, inclusive="both")
                & (df_hits["total_mv_yi"] >= mcap_min)
            ]
        if df_hits.empty:
            logger.info("[SlowBull] no candidates after PE/mcap filter")
            return []

        df_hits["score"] = df_hits.apply(
            lambda r: _slow_bull_score({
                "slope_ann": r["slope_ann"],
                "vol_pct": r["vol_pct"],
                "dd250": r["dd250"],
            }), axis=1,
        )
        df_hits = df_hits.sort_values("score", ascending=False).head(top_n)

        picks: List[ScreenedStock] = []
        for rec in df_hits.to_dict(orient="records"):
            ts_code = str(rec.get("ts_code", ""))
            code = ts_code.split(".")[0] if "." in ts_code else ts_code
            picks.append(ScreenedStock(
                code=code,
                name=str(rec.get("name", "")),
                price=float(rec.get("last", 0.0)),
                change_pct=0.0,
                volume_ratio=0.0,
                turnover_rate=0.0,
                pe=float(rec.get("pe_ttm", 0.0) or 0.0),
                pb=0.0,
                market_cap=float(rec.get("total_mv_yi", 0.0) or 0.0),
                amount=0.0,
                change_pct_60d=float(rec.get("slope_ann", 0.0)) * 100,
                score=float(rec.get("score", 0.0)),
                strategies=["slow_bull"],
            ))
        logger.info("[SlowBull] %d candidates (as_of=%s)", len(picks), td or "live")
        return picks

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _slow_bull_universe(sb: pd.DataFrame) -> pd.DataFrame:
        if sb is None or sb.empty:
            return sb
        name_mask = sb["name"].astype(str).str.contains(r"ST|退|\*", regex=True, na=False)
        ts_str = sb["ts_code"].astype(str)
        bse_mask = ts_str.str.startswith(("8", "4", "92"))
        return sb[~(name_mask | bse_mask)].copy()

    @staticmethod
    def _slow_bull_latest_basic_date(db, td: Optional[str]) -> Optional[str]:
        """Find a recent date with non-empty daily_basic (within 14 days)."""
        anchor = pd.Timestamp(td) if td else pd.Timestamp.now()
        for delta in range(0, 14):
            cand = (anchor - pd.Timedelta(days=delta)).strftime("%Y%m%d")
            try:
                b = db.get_market_daily_basic(cand)
                if b is not None and not b.empty:
                    return cand
            except Exception:
                continue
        return None
