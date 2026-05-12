# -*- coding: utf-8 -*-
"""
Basic filtering (price/PE/turnover/volume/momentum/hard veto) and the
scoring + ranking helpers that produce the Stage 1 candidate list.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import pandas as pd

from data_provider.base import is_kc_cy_stock
from src.services.picker.constants import (
    AMOUNT_MIN_LARGE_CAP,
    AMOUNT_MIN_SMALL_CAP,
    LIMIT_UP_PCT_KC_CY,
    LIMIT_UP_PCT_MAIN,
    MARKET_CAP_TIER_YI,
    PE_SCORE_PARTIAL_MAX,
    PICKER_TOP_N_PER_STRATEGY,
    TREND_DECAY_THRESHOLD_PCT,
    VOLUME_RATIO_MIN,
    PickerModeParams,
    ScreenedStock,
    ScreenStats,
    get_tushare_api,
)

logger = logging.getLogger(__name__)


class _FilterScoringMixin:
    """Mixin: hard veto / basic filter / momentum / volume / scoring."""

    def _filter_basic(self, df: pd.DataFrame, pe_max: Optional[float] = None) -> pd.DataFrame:
        """Layer 1: Remove ST, new listings, ETFs, and unprofitable (PE filter)."""
        pe_max = pe_max if pe_max is not None else PickerModeParams.for_mode(self._picker_mode).pe_max
        return self._filter_basic_impl(df, pe_max)

    def _filter_hard_veto(
        self, df: pd.DataFrame, stats: Optional[ScreenStats] = None
    ) -> pd.DataFrame:
        """Apply fundamental hard-veto filter using fundamentals_fetcher."""
        if df is None or df.empty:
            return df

        try:
            from data_provider.fundamentals_fetcher import (
                evaluate_vetoes,
                get_veto_summary,
            )
        except Exception as exc:
            logger.debug("[Screener] fundamentals_fetcher unavailable: %s", exc)
            return df

        api = get_tushare_api(self._data_manager)
        if api is None:
            return df

        if "ts_code" in df.columns:
            ts_codes = df["ts_code"].astype(str).tolist()
        elif "代码" in df.columns:
            def _to_ts_code(c: str) -> str:
                c = str(c).strip()
                if "." in c:
                    return c
                if c.startswith("6"):
                    return f"{c}.SH"
                if c.startswith(("4", "8")):
                    return f"{c}.BJ"
                return f"{c}.SZ"
            ts_codes = [_to_ts_code(c) for c in df["代码"]]
            df = df.copy()
            df["_veto_ts_code"] = ts_codes
        else:
            return df

        try:
            verdicts = evaluate_vetoes(api, ts_codes)
        except Exception as exc:
            logger.warning("[Screener] hard-veto evaluation failed: %s", exc)
            return df

        vetoed_codes = {ts for ts, v in verdicts.items() if v.is_vetoed}
        if not vetoed_codes:
            if stats is not None:
                stats.after_veto = len(df)
            return df

        if "ts_code" in df.columns:
            mask = ~df["ts_code"].astype(str).isin(vetoed_codes)
        else:
            mask = ~df["_veto_ts_code"].isin(vetoed_codes)
        filtered = df[mask].copy()
        if "_veto_ts_code" in filtered.columns:
            filtered = filtered.drop(columns=["_veto_ts_code"])

        if stats is not None:
            stats.after_veto = len(filtered)
            stats.veto_reasons = get_veto_summary(verdicts)
        logger.info(
            "[Screener] Hard-veto filter: %d -> %d (removed %d). Reasons: %s",
            len(df), len(filtered), len(vetoed_codes),
            get_veto_summary(verdicts),
        )
        return filtered

    def _filter_basic_for_strategies(self, df: pd.DataFrame) -> pd.DataFrame:
        """Basic filter for multi-strategy (shared pe_max=100)."""
        return self._filter_basic_impl(df, pe_max=100.0)

    def _filter_basic_impl(self, df: pd.DataFrame, pe_max: float) -> pd.DataFrame:
        """Shared implementation for basic filter."""
        name_col = "名称"
        if name_col in df.columns:
            mask = pd.Series(True, index=df.index)
            for kw in self._EXCLUDE_NAME_KEYWORDS:
                mask &= ~df[name_col].str.contains(kw, na=False, regex=False)
            df = df[mask]

        code_col = "代码"
        if code_col in df.columns:
            df = df[~df[code_col].str[:2].isin(self._ETF_PREFIXES)]

        if "市盈率-动态" in df.columns:
            pe = pd.to_numeric(df["市盈率-动态"], errors="coerce")
            if self._allow_loss:
                df = df[pe < pe_max]
            else:
                df = df[(pe > 0) & (pe < pe_max)]

        return df

    # ── Scoring (legacy single-strategy; multi-strategy uses picker_strategies module) ──

    def _filter_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 2: Pullback entry filter."""
        mode_params = PickerModeParams.for_mode(self._picker_mode)
        if "涨跌幅" in df.columns:
            pct = pd.to_numeric(df["涨跌幅"], errors="coerce")
            df = df[(pct >= mode_params.daily_change_min) & (pct <= mode_params.daily_change_max)]
        if "60日涨跌幅" in df.columns:
            pct60 = pd.to_numeric(df["60日涨跌幅"], errors="coerce")
            df = df[pct60 > 5]
        return df

    def _filter_volume(self, df: pd.DataFrame) -> pd.DataFrame:
        """Layer 3: Volume activity filter."""
        if "量比" in df.columns:
            vr = pd.to_numeric(df["量比"], errors="coerce")
            df = df[vr > VOLUME_RATIO_MIN]
        if "换手率" in df.columns:
            tr = pd.to_numeric(df["换手率"], errors="coerce")
            df = df[(tr > self._turnover_min) & (tr < self._turnover_max)]
        if "成交额" in df.columns and "总市值" in df.columns:
            amt = pd.to_numeric(df["成交额"], errors="coerce")
            cap_yi = pd.to_numeric(df["总市值"], errors="coerce") / 1e8
            ok_small = (cap_yi < MARKET_CAP_TIER_YI) & (amt > AMOUNT_MIN_SMALL_CAP)
            ok_large = (cap_yi >= MARKET_CAP_TIER_YI) & (amt > AMOUNT_MIN_LARGE_CAP)
            df = df[ok_small | ok_large]
        elif "成交额" in df.columns:
            amt = pd.to_numeric(df["成交额"], errors="coerce")
            df = df[amt > AMOUNT_MIN_SMALL_CAP]
        return df

    def _score_trend(self, pct_60d: float) -> float:
        """Score trend strength."""
        if pct_60d <= 0:
            return 0.0
        if pct_60d <= TREND_DECAY_THRESHOLD_PCT:
            return min(pct_60d, 25.0)
        decay = 30 - (pct_60d - TREND_DECAY_THRESHOLD_PCT) * 0.5
        return max(0.0, decay)

    def _score_momentum(self, change_pct: float) -> float:
        """Score today's momentum - pullback strategy."""
        if change_pct < -2:
            return -5.0
        if -2 <= change_pct <= 1:
            return 20.0
        if 1 < change_pct <= 3:
            return 15.0
        if 3 < change_pct <= 5:
            return 8.0
        return max(0.0, 8.0 - (change_pct - 5) * 3)

    def _score_volume(self, vol_ratio: float) -> float:
        """Score volume confirmation."""
        if 1.0 <= vol_ratio <= 3.0:
            return 20.0
        if vol_ratio > 3.0:
            return 15.0
        return 10.0 if vol_ratio > 0.8 else 0.0

    def _score_turnover(self, turnover: float) -> float:
        """Score turnover health."""
        if 2 <= turnover <= 8:
            return 10.0
        if 1 <= turnover < 2:
            return 5.0
        return 3.0 if 8 < turnover <= self._turnover_max else 0.0

    def _score_pe(self, pe: float) -> float:
        """Score valuation."""
        p = PickerModeParams.for_mode(self._picker_mode)
        if p.pe_ideal_low < pe < p.pe_ideal_high:
            return 10.0
        if 5 < pe <= p.pe_ideal_low or p.pe_ideal_high <= pe < PE_SCORE_PARTIAL_MAX:
            return 5.0
        return 0.0

    def _score_and_rank(self, df: pd.DataFrame, top_n: int = 30) -> List[ScreenedStock]:
        """Score remaining stocks and return top N."""
        records = []
        for _, row in df.iterrows():
            try:
                code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                price = float(pd.to_numeric(row.get("最新价", 0), errors="coerce") or 0)
                change_pct = float(pd.to_numeric(row.get("涨跌幅", 0), errors="coerce") or 0)
                vol_ratio = float(pd.to_numeric(row.get("量比", 0), errors="coerce") or 0)
                turnover = float(pd.to_numeric(row.get("换手率", 0), errors="coerce") or 0)
                pe = float(pd.to_numeric(row.get("市盈率-动态", 0), errors="coerce") or 0)
                pb = float(pd.to_numeric(row.get("市净率", 0), errors="coerce") or 0)
                total_mv = float(pd.to_numeric(row.get("总市值", 0), errors="coerce") or 0)
                amount = float(pd.to_numeric(row.get("成交额", 0), errors="coerce") or 0)
                pct_60d = float(pd.to_numeric(row.get("60日涨跌幅", 0), errors="coerce") or 0)

                score = (
                    self._score_trend(pct_60d)
                    + self._score_momentum(change_pct)
                    + self._score_volume(vol_ratio)
                    + self._score_turnover(turnover)
                    + self._score_pe(pe)
                    + (5.0 if 50e8 < total_mv < 500e8 else 0.0)
                )

                records.append(ScreenedStock(
                    code=code, name=name, price=price,
                    change_pct=change_pct, volume_ratio=vol_ratio,
                    turnover_rate=turnover, pe=pe, pb=pb,
                    market_cap=total_mv / 1e8,
                    amount=amount / 1e8,
                    change_pct_60d=pct_60d, score=score,
                ))
            except Exception:
                continue

        records.sort(key=lambda s: s.score, reverse=True)
        return records[:top_n]
