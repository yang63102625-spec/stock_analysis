# -*- coding: utf-8 -*-
"""Reversal breakout: deep-bottom + right-side breakout confirmation.

Strategy id: ``reversal_breakout`` ("反转突破").

Sister to ``bottom_reversal`` (the left-side "still consolidating, about
to launch" screener) but the entry semantics are inverted. Where
``bottom_reversal`` is a watchlist for manual analysis ("which stocks
sit in a real bottom right now?"), ``reversal_breakout`` is an
actionable buy signal triggered only after the market has already
voted with a real breakout.

v2 was a *left-side* bet — buy the consolidation, hope it launches.
Backtest (2024-07 ~ 2025-04, including the 9/24 rally): WR 13%, CAGR
-97%, alpha vs HS300 = -9%. The "about-to-launch" pattern is a
liar in A-shares: most "tight consolidations near range top" are
just stair-step declines.

v3 flips to a right-side breakout strategy:

    PRE-REQ (the base must already exist):
      1. Real prior decline: 180d max drawdown ≥ 25%
      2. Recent consolidation: last 40d range ≤ 25%
      3. MA60 not falling (slope_20d ≥ -1%)

    TODAY'S TRIGGER (market has voted with real money):
      4. Today's close breaks 40d high by ≥ 1% (but not limit-up:
         pct_chg in [3%, 7%] — leave room for follow-through)
      5. Today's volume ≥ 60d avg × 2.0 (decisive expansion)
      6. Today's main-force net inflow > 0  AND
         main-net / today's amount ≥ 5%  (institutions are buying
         the breakout, not selling into it)

    LIVE BONUS (offline-safe):
      7. Sector in today's top tier (silently skipped in backtest
         when sector API is unreachable)

Hold ~20 trading days with tight trailing (MA10 or ATR×2). Target
WR 40-50%, payoff ≥ 1.5×.

LocalDB is the canonical source for 180d bars *and* moneyflow.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from src.services.picker.constants import ScreenedStock

logger = logging.getLogger(__name__)


# Window sizes (trading days).
_LOOKBACK_DAYS = 180          # full history pulled per candidate
_DEEP_BASE_WIN = 180          # drawdown reference window
_BOTTOM_WIN = 120             # "low base" window
_CONSOL_WIN = 40              # consolidation / range window
_MA_LONG = 60                 # long-term MA used for trend filter
_VOL_SHORT = 5                # short volume average
_VOL_LONG = 60                # long volume average

# v3 thresholds. Each is overridable via env without code changes.
_DEFAULTS = {
    # --- base pre-requisites (must exist before today's trigger) ---
    "MIN_DRAWDOWN_PCT": 25.0,    # 180d max DD: real prior fall (v2: 35)
    "MAX_RANGE_PCT": 25.0,       # 40d consolidation tightness (v2: 22)
    "MA60_SLOPE_MIN_PCT": -1.0,  # MA60 not falling hard (v2: 0)
    # --- today's trigger (right-side confirmation) ---
    "BREAKOUT_VS_40D_HIGH_MIN_PCT": 1.0,  # close ≥ 40d high × 1.01
    "TRIGGER_PCT_MIN": 3.0,      # today's pct_chg lower bound
    "TRIGGER_PCT_MAX": 7.0,      # ... upper bound (avoid limit-up chases)
    "TRIGGER_VOL_RATIO_MIN": 2.0,  # today's vol vs 60d avg vol
    "TRIGGER_MAIN_NET_TO_AMT_MIN": 0.05,  # main_net / today's amt ≥ 5%
    # --- universe filters ---
    "MAX_PB": 4.0,
    "MARKET_CAP_MIN_YI": 30.0,
    "MARKET_CAP_MAX_YI": 300.0,
    "COARSE_60D_MIN_PCT": -50.0,
    "COARSE_60D_MAX_PCT": 30.0,   # widened (was 10) — early-stage rebounds qualify
    "MIN_AMOUNT_YUAN": 80_000_000.0,
    "TOP_N": 30,
    "MAX_PARALLEL": 16,
    # --- sector leadership (live-only, no-op offline) ---
    "REQUIRE_SECTOR_STRONG": 1,
}


def _envf(key: str) -> float:
    raw = os.environ.get(f"REVERSAL_BREAKOUT_{key}")
    if raw is None:
        return float(_DEFAULTS[key])
    try:
        return float(raw)
    except ValueError:
        return float(_DEFAULTS[key])


def _envi(key: str) -> int:
    return int(_envf(key))


class _ReversalBreakoutMixin:
    """Mixin: ``_screen_reversal_breakout``."""

    def _screen_reversal_breakout(
        self,
        spot_df: Optional[pd.DataFrame],
        trade_date_yyyymmdd: Optional[str] = None,
        sector_strong_codes: Optional[Set[str]] = None,
    ) -> List[ScreenedStock]:
        if spot_df is None or spot_df.empty:
            logger.info("[ReversalBreakout] no spot data")
            return []

        candidates = self._reversal_breakout_coarse_filter(spot_df)
        if not candidates:
            logger.info("[ReversalBreakout] coarse filter dropped everything")
            return []
        logger.info("[ReversalBreakout] coarse pool: %d candidates", len(candidates))

        # Sector leadership gate — drop candidates whose industry isn't
        # in today's top tier. When the upstream couldn't load sector
        # data (offline / kill-switch), silently keep all candidates.
        if _envi("REQUIRE_SECTOR_STRONG") == 1 and sector_strong_codes:
            before = len(candidates)
            candidates = [c for c in candidates
                          if str(c.get("代码", "")) in sector_strong_codes]
            logger.info("[ReversalBreakout] sector filter: %d -> %d", before, len(candidates))
            if not candidates:
                return []

        as_of = trade_date_yyyymmdd or getattr(self, "_as_of_date", None)
        if as_of and "-" in as_of:
            as_of = as_of.replace("-", "")

        # Same-day main-force net inflow — v3's right-side trigger.
        # Loaded once for the whole candidate pool (1 LocalDB read).
        same_day_flow = self._reversal_breakout_load_moneyflow_single(as_of)

        survivors = self._reversal_breakout_deep_filter(
            candidates, as_of_yyyymmdd=as_of, same_day_flow=same_day_flow,
        )
        if not survivors:
            logger.info("[ReversalBreakout] base+trigger filter dropped everything")
            return []

        top_n = _envi("TOP_N")
        survivors.sort(key=lambda s: s.score, reverse=True)
        out = survivors[:top_n]
        logger.info("[ReversalBreakout] final: %d picks (top %d of %d survivors)",
                    len(out), top_n, len(survivors))
        return out

    # ------------------------------------------------------------------
    # Coarse: keep ~hundreds of candidates from the 5495-row spot frame.
    # ------------------------------------------------------------------

    def _reversal_breakout_coarse_filter(self, df: pd.DataFrame) -> List[dict]:
        if df is None or df.empty:
            return []
        panel = df.copy()

        # Drop ST / 退市 / *ST
        if "名称" in panel.columns:
            panel = panel[~panel["名称"].astype(str).str.contains(
                r"ST|退|\*", regex=True, na=False,
            )]
        # Drop BSE (same convention as small_cap)
        if "代码" in panel.columns:
            code_str = panel["代码"].astype(str)
            panel = panel[~code_str.str.startswith(("8", "4", "92"))]

        # PB cap (skip rows without PB by default)
        if "市净率" in panel.columns:
            pb = pd.to_numeric(panel["市净率"], errors="coerce")
            panel = panel[pb.notna() & (pb > 0) & (pb <= _envf("MAX_PB"))]

        # Market cap band (in yuan; convert to 亿 for thresholds)
        if "总市值" in panel.columns:
            mv_yi = pd.to_numeric(panel["总市值"], errors="coerce") / 1e8
            panel = panel[(mv_yi >= _envf("MARKET_CAP_MIN_YI"))
                          & (mv_yi <= _envf("MARKET_CAP_MAX_YI"))]

        # Liquidity floor (今日 成交额)
        if "成交额" in panel.columns:
            amt = pd.to_numeric(panel["成交额"], errors="coerce").fillna(0)
            panel = panel[amt >= _envf("MIN_AMOUNT_YUAN")]

        # 60d change band (already on the spot frame after _add_tushare_60d_change)
        if "60日涨跌幅" in panel.columns:
            ch60 = pd.to_numeric(panel["60日涨跌幅"], errors="coerce")
            panel = panel[ch60.notna()
                          & (ch60 >= _envf("COARSE_60D_MIN_PCT"))
                          & (ch60 <= _envf("COARSE_60D_MAX_PCT"))]

        # Exclude limit-up / limit-down on entry day (can't fill cleanly)
        if "涨跌幅" in panel.columns:
            day = pd.to_numeric(panel["涨跌幅"], errors="coerce").fillna(0)
            panel = panel[(day > -9.5) & (day < 9.5)]

        if panel.empty:
            return []

        # Materialise the rows we need (avoid passing DataFrame slices to
        # worker threads).
        keep = ["代码", "名称", "最新价", "涨跌幅", "量比", "换手率",
                "市盈率-动态", "市净率", "总市值", "成交额", "60日涨跌幅"]
        keep = [c for c in keep if c in panel.columns]
        rows = panel[keep].to_dict(orient="records")
        return rows

    # ------------------------------------------------------------------
    # Catalyst: same-day main-force net inflow (right-side confirmation).
    # ------------------------------------------------------------------

    def _reversal_breakout_load_moneyflow_single(
        self, as_of_yyyymmdd: Optional[str],
    ) -> Dict[str, Dict[str, float]]:
        """Load market-wide moneyflow for ``as_of_yyyymmdd``.
        Returns ``{code: {main_net, retail_net}}`` (empty dict on
        any failure — judge then skips the moneyflow gate).
        """
        if not as_of_yyyymmdd:
            from datetime import date as _date
            as_of_yyyymmdd = _date.today().strftime("%Y%m%d")

        local_db = self._reversal_breakout_get_local_db()
        df = None
        if local_db is not None:
            try:
                df = local_db.get_market_moneyflow(as_of_yyyymmdd)
            except Exception as e:
                logger.debug("[ReversalBreakout] local moneyflow failed: %s", e)
                df = None

        if df is None or df.empty:
            api = self._get_tushare_api() if hasattr(self, "_get_tushare_api") else None
            if api is None:
                try:
                    from src.services.picker import get_tushare_api as _get_api
                    api = _get_api(self._data_manager) if getattr(self, "_data_manager", None) else None
                except Exception:
                    api = None
            if api is not None:
                try:
                    from data_provider.moneyflow_fetcher import MoneyflowFetcher
                    df = MoneyflowFetcher(api).get_market_moneyflow(as_of_yyyymmdd)
                except Exception as e:
                    logger.debug("[ReversalBreakout] api moneyflow failed: %s", e)
                    df = None
        if df is None or df.empty:
            return {}
        return self._reversal_breakout_normalize_flow(df)

    @staticmethod
    def _reversal_breakout_normalize_flow(
        df: pd.DataFrame,
    ) -> Dict[str, Dict[str, float]]:
        if "ts_code" not in df.columns:
            return {}
        df = df.copy()
        df["code"] = df["ts_code"].astype(str).str.split(".").str[0]
        for col in ("buy_lg_amount", "buy_elg_amount",
                    "sell_lg_amount", "sell_elg_amount",
                    "buy_sm_amount", "buy_md_amount",
                    "sell_sm_amount", "sell_md_amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            else:
                df[col] = 0
        df["main_net"] = (df["buy_lg_amount"] + df["buy_elg_amount"]
                          - df["sell_lg_amount"] - df["sell_elg_amount"])
        df["retail_net"] = (df["buy_sm_amount"] + df["buy_md_amount"]
                            - df["sell_sm_amount"] - df["sell_md_amount"])
        return df.set_index("code")[["main_net", "retail_net"]].to_dict("index")

    @staticmethod
    def _reversal_breakout_get_local_db():
        try:
            from src.services.local_db.store import LocalStockDB
            return LocalStockDB()
        except Exception as e:
            logger.debug("[ReversalBreakout] LocalStockDB unavailable: %s", e)
            return None

    @staticmethod
    def _reversal_breakout_recent_trade_days(
        as_of_yyyymmdd: str, n_days: int, local_db=None,
    ) -> List[str]:
        if local_db is not None:
            try:
                cal = local_db.get_trade_cal(
                    start_date=None, end_date=as_of_yyyymmdd,
                )
                if cal is not None and not cal.empty:
                    if "is_open" in cal.columns:
                        cal = cal[cal["is_open"].astype(str) == "1"]
                    days = cal["cal_date"].astype(str).sort_values().tolist()
                    days = [d for d in days if d <= as_of_yyyymmdd]
                    if days:
                        return days[-n_days:]
            except Exception as e:
                logger.debug("[ReversalBreakout] local trade_cal failed: %s", e)
        return []

    # ------------------------------------------------------------------
    # Deep: multi-window geometric check per candidate, parallel.
    # ------------------------------------------------------------------

    def _reversal_breakout_deep_filter(
        self, candidates: List[dict], as_of_yyyymmdd: Optional[str],
        same_day_flow: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> List[ScreenedStock]:
        try:
            from src.services.local_db import default_db
        except Exception as e:
            logger.warning("[ReversalBreakout] LocalDB unavailable: %s", e)
            return []
        db = default_db()

        # Resolve the as_of date — falls back to today if not given.
        if not as_of_yyyymmdd:
            from datetime import date as _date
            as_of_yyyymmdd = _date.today().strftime("%Y%m%d")
        try:
            as_of_ts = pd.Timestamp(as_of_yyyymmdd)
        except Exception:
            return []
        # Pull ~270 calendar days to be safe for 180 trading days.
        start_yyyymmdd = (as_of_ts - pd.Timedelta(days=270)).strftime("%Y%m%d")

        max_workers = max(1, _envi("MAX_PARALLEL"))
        results: List[ScreenedStock] = []

        def _judge(row: dict) -> Optional[ScreenedStock]:
            code = str(row.get("代码", "") or "").strip()
            if not code:
                return None
            ts_code = code if "." in code else (
                f"{code}.SH" if code.startswith(("6", "9")) else f"{code}.SZ"
            )
            try:
                bars = db.get_daily(ts_code, start_yyyymmdd, as_of_yyyymmdd)
            except Exception:
                return None
            if bars is None or bars.empty or len(bars) < _CONSOL_WIN + 5:
                return None
            flow = None
            if same_day_flow:
                flow = same_day_flow.get(code)
            return self._reversal_breakout_judge_one(row, bars, flow)

        with ThreadPoolExecutor(max_workers=max_workers,
                                thread_name_prefix="reversal_breakout") as pool:
            futs = [pool.submit(_judge, r) for r in candidates]
            for fut in as_completed(futs):
                try:
                    s = fut.result()
                except Exception:
                    s = None
                if s is not None:
                    results.append(s)
        return results

    # ------------------------------------------------------------------
    # Per-symbol judgement — the actual geometry.
    # ------------------------------------------------------------------

    @staticmethod
    def _reversal_breakout_judge_one(
        row: dict, bars: pd.DataFrame,
        same_day_flow: Optional[Dict[str, float]] = None,
    ) -> Optional[ScreenedStock]:
        """v3 logic: base prerequisite + today's right-side trigger.

        Base (must already be in place):
          - 180d max DD ≥ MIN_DRAWDOWN_PCT
          - 40d range ≤ MAX_RANGE_PCT (the consolidation)
          - MA60 not falling hard

        Trigger (today's bar must vote):
          - Today's close ≥ 40d high × (1 + BREAKOUT_VS_40D_HIGH_MIN_PCT/100)
            and the prior 40-day window (excluding today) was below
            that high — i.e. real new high
          - Today's pct_chg in [TRIGGER_PCT_MIN, TRIGGER_PCT_MAX]
            (avoid limit-up chase)
          - Today's vol ≥ TRIGGER_VOL_RATIO_MIN × 60d avg vol
          - Today's main_net / today's amt ≥ TRIGGER_MAIN_NET_TO_AMT_MIN
            (skipped silently when moneyflow data is unavailable —
             can't punish offline runs)
        """
        if bars is None or bars.empty:
            return None
        bars = bars.sort_values("trade_date").reset_index(drop=True)
        if len(bars) < _CONSOL_WIN + 5:
            return None

        close = bars["close"].astype(float).values
        high = bars["high"].astype(float).values
        low = bars["low"].astype(float).values
        vol = bars["vol"].astype(float).values
        amount = bars["amount"].astype(float).values if "amount" in bars.columns else None
        pct_chg_series = bars["pct_chg"].astype(float).values if "pct_chg" in bars.columns else None

        current = float(close[-1])
        if current <= 0:
            return None

        # ===== BASE =====
        win_180 = close[-_DEEP_BASE_WIN:] if len(close) >= _DEEP_BASE_WIN else close
        peak = float(np.max(win_180))
        trough = float(np.min(win_180))
        if peak <= 0:
            return None
        max_dd_pct = (peak - trough) / peak * 100.0
        if max_dd_pct < _envf("MIN_DRAWDOWN_PCT"):
            return None

        # 40d consolidation, excluding today so the breakout itself
        # doesn't blow up the range.
        if len(high) < _CONSOL_WIN + 1:
            return None
        win_40_high_prior = high[-(_CONSOL_WIN + 1):-1]
        win_40_low_prior = low[-(_CONSOL_WIN + 1):-1]
        rng_high_prior = float(np.max(win_40_high_prior))
        rng_low_prior = float(np.min(win_40_low_prior))
        if rng_low_prior <= 0:
            return None
        range_pct = (rng_high_prior - rng_low_prior) / rng_low_prior * 100.0
        if range_pct > _envf("MAX_RANGE_PCT"):
            return None

        # MA60 slope (now vs 20 bars ago)
        if len(close) >= _MA_LONG + 20:
            ma60_series = pd.Series(close).rolling(_MA_LONG).mean().values
            ma60_now = float(ma60_series[-1])
            ma60_20ago = float(ma60_series[-21])
            if ma60_now <= 0 or ma60_20ago <= 0:
                return None
            ma60_slope_pct = (ma60_now - ma60_20ago) / ma60_20ago * 100.0
            if ma60_slope_pct < _envf("MA60_SLOPE_MIN_PCT"):
                return None
        else:
            ma60_slope_pct = 0.0

        # ===== TRIGGER =====
        # 1. New 40d high by ≥ X%
        breakout_pct = (current / rng_high_prior - 1.0) * 100.0
        if breakout_pct < _envf("BREAKOUT_VS_40D_HIGH_MIN_PCT"):
            return None

        # 2. Today's pct_chg sanity band (skip if not available)
        today_pct = None
        if pct_chg_series is not None and len(pct_chg_series) > 0:
            today_pct = float(pct_chg_series[-1])
            if not (_envf("TRIGGER_PCT_MIN") <= today_pct <= _envf("TRIGGER_PCT_MAX")):
                return None
        else:
            prev = float(close[-2]) if len(close) >= 2 else current
            if prev > 0:
                today_pct = (current / prev - 1.0) * 100.0
                if not (_envf("TRIGGER_PCT_MIN") <= today_pct <= _envf("TRIGGER_PCT_MAX")):
                    return None

        # 3. Volume expansion vs 60d
        vol_today = float(vol[-1])
        vol_long = float(np.mean(vol[-_VOL_LONG:])) if len(vol) >= _VOL_LONG else \
            float(np.mean(vol))
        if vol_long <= 0:
            return None
        vol_ratio_today = vol_today / vol_long
        if vol_ratio_today < _envf("TRIGGER_VOL_RATIO_MIN"):
            return None

        # 4. Same-day smart-money confirmation (best-effort)
        main_net_ratio = 0.0
        if same_day_flow and amount is not None:
            main_net = float(same_day_flow.get("main_net", 0.0))
            amt_today = float(amount[-1])
            if amt_today > 0:
                # LocalDB moneyflow amounts are in 万元 while daily.amount
                # is in 千元 — normalise both to yuan.
                main_net_yuan = main_net * 10_000.0
                amt_today_yuan = amt_today * 1_000.0
                main_net_ratio = main_net_yuan / amt_today_yuan
                if main_net_ratio < _envf("TRIGGER_MAIN_NET_TO_AMT_MIN"):
                    return None

        # ===== SCORE =====
        score = 0.0
        score += min(25.0, max_dd_pct * 0.4)               # deep base
        score += min(20.0, breakout_pct * 4.0)             # how far above range
        score += min(20.0, (vol_ratio_today - 1.0) * 10.0) # volume conviction
        score += min(15.0, max(0.0, ma60_slope_pct * 3))   # MA60 turning up
        score += 20.0 * (1.0 - min(1.0, range_pct / 25.0)) # tighter base = better
        if same_day_flow and main_net_ratio > 0:
            score += min(10.0, main_net_ratio * 100.0)     # smart-money bonus
        score = round(score, 2)

        code = str(row.get("代码", "") or "")
        price = float(pd.to_numeric(row.get("最新价", current), errors="coerce") or current)
        return ScreenedStock(
            code=code,
            name=str(row.get("名称", "") or ""),
            price=price,
            change_pct=float(pd.to_numeric(row.get("涨跌幅", 0), errors="coerce") or 0),
            volume_ratio=float(pd.to_numeric(row.get("量比", 0), errors="coerce") or 0),
            turnover_rate=float(pd.to_numeric(row.get("换手率", 0), errors="coerce") or 0),
            pe=float(pd.to_numeric(row.get("市盈率-动态", 0), errors="coerce") or 0),
            pb=float(pd.to_numeric(row.get("市净率", 0), errors="coerce") or 0),
            market_cap=float(pd.to_numeric(row.get("总市值", 0), errors="coerce") or 0) / 1e8,
            amount=float(pd.to_numeric(row.get("成交额", 0), errors="coerce") or 0) / 1e8,
            change_pct_60d=float(pd.to_numeric(row.get("60日涨跌幅", 0), errors="coerce") or 0),
            score=score,
            strategies=["reversal_breakout"],
        )
