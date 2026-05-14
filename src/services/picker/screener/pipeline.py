# -*- coding: utf-8 -*-
"""
The orchestrator: ``screen()`` runs the full multi-layer pipeline, while
``screen_as_of()`` is a thin date-clamped wrapper used by the backtest harness.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from src.config import get_config
from src.services.picker.constants import (
    PICKER_MAX_BIAS_PCT,
    PICKER_TOP_N_PER_STRATEGY,
    PICKER_MODE_PARAMS,
    ScreenedStock,
    ScreenStats,
)

logger = logging.getLogger(__name__)


class _PipelineMixin:
    """Mixin: ``screen()`` and ``screen_as_of()``."""

    def screen(
        self, trade_date: Optional[str] = None
    ) -> Tuple[List[ScreenedStock], ScreenStats, Dict[str, List[ScreenedStock]]]:
        """Run the full screening pipeline. Returns (candidates, stats, candidates_per_strategy).
        When trade_date is provided (YYYYMMDD), run historical screening (Tushare only).
        Uses multi-strategy when picker_strategies has multiple entries."""
        stats = ScreenStats()
        self._as_of_date = self._trade_date_to_iso(trade_date) if trade_date else None

        # Preserve original strategies -- restored in finally block
        original_strategies = list(self._picker_strategies)

        try:
            # -- Market environment guard --
            cfg = get_config()
            # Always evaluate market_env (used downstream for regime-aware position
            # scaling even when picker_market_guard is disabled).
            market_env = self._check_market_environment()
            # EOD_VARIANT bypasses market guard (variants have own regime logic)
            import os as _os
            _bypass_guard = bool(_os.environ.get("EOD_VARIANT", "").strip())
            if getattr(cfg, "picker_market_guard", True) and not _bypass_guard:
                if market_env and not market_env.is_strong:
                    raw_action = getattr(cfg, "picker_weak_market_action", "limit")
                    action = (raw_action or "limit").strip().lower()
                    if action not in ("skip", "limit"):
                        logger.warning(
                            "[MarketGuard] Invalid picker_weak_market_action=%r, fallback to 'limit'",
                            raw_action,
                        )
                        action = "limit"
                    logger.warning(
                        "[MarketGuard] Weak market (regime=%s), action=%s",
                        market_env.regime, action,
                    )
                    if action == "skip":
                        logger.warning(
                            "[MarketGuard] Weak market detected, skipping all strategies"
                        )
                        return [], stats, {}
                    elif action == "limit":
                        allowed_str = getattr(cfg, "picker_weak_market_strategies", "bottom_reversal")
                        allowed = [s.strip() for s in allowed_str.split(",") if s.strip()]
                        original = list(self._picker_strategies)
                        self._picker_strategies = [s for s in self._picker_strategies if s in allowed]
                        if not self._picker_strategies:
                            logger.warning(
                                "[MarketGuard] Weak market, no allowed strategies remain "
                                "(original: %s, allowed: %s)", original, allowed,
                            )
                            return [], stats, {}
                        logger.warning(
                            "[MarketGuard] Weak market, limiting to strategies: %s",
                            self._picker_strategies,
                        )

            # Determine which strategies need daily data vs realtime-only path
            daily_strategies = [s for s in self._picker_strategies if s in self.DAILY_DATA_STRATEGIES]
            realtime_only_strategies = [s for s in self._picker_strategies if s not in self.DAILY_DATA_STRATEGIES]
            needs_daily = len(daily_strategies) > 0

            if daily_strategies:
                logger.info(f"[Screener] Daily-data strategies: {daily_strategies}")
            if realtime_only_strategies:
                logger.info(f"[Screener] Realtime-only strategies (skip daily fetch): {realtime_only_strategies}")

            from src.services.picker_strategies import (
                get_strategy_params,
                filter_momentum,
                filter_volume,
                score_and_rank,
                merge_candidates_by_code,
            )

            candidates_per_strategy: Dict[str, List[ScreenedStock]] = {}

            # --- Daily-data pipeline: only fetch spot data when at least one strategy needs it ---
            if needs_daily:
                df = self._fetch_spot_data(trade_date)
                if df is None or df.empty:
                    logger.warning("[Screener] No spot data available for daily strategies")
                    # Daily strategies cannot proceed, but realtime strategies may still run below
                    df = None
                else:
                    stats.total_stocks = len(df)
                    logger.info(
                        f"[Screener] Starting daily pipeline with {stats.total_stocks} stocks, "
                        f"strategies={daily_strategies}"
                    )

                    # Layer 1: Basic quality filter (shared, pe_max=100)
                    df = self._filter_basic_for_strategies(df)
                    stats.after_basic = len(df)
                    logger.info(f"[Screener] After basic filter: {len(df)}")

                    # Layer 1.2: Fundamental hard-veto (P1-A)
                    df = self._filter_hard_veto(df, stats)
                    if stats.after_veto == 0:
                        stats.after_veto = stats.after_basic

                    # Layer 1.5: Prepare sector strength data
                    _sector_strong_codes: Set[str] = set()
                    _need_sector = any(s in self.SECTOR_FILTER_STRATEGIES for s in daily_strategies)
                    if getattr(cfg, "picker_sector_filter", True) and _need_sector:
                        try:
                            from src.services.sector_strength_service import SectorStrengthService
                            sector_svc = SectorStrengthService()
                            sector_top_pct = getattr(cfg, "picker_sector_top_pct", 30) / 100.0
                            from concurrent.futures import ThreadPoolExecutor as _TPE
                            with _TPE(max_workers=1) as _executor:
                                _future = _executor.submit(
                                    sector_svc.get_strong_sector_codes,
                                    top_pct=sector_top_pct,
                                    trade_date=trade_date,
                                )
                                try:
                                    _sector_strong_codes = _future.result(timeout=180)
                                except Exception as _te:
                                    logger.warning(
                                        "[Screener] Sector codes fetch timed out or failed (%s), "
                                        "skipping sector filter", _te,
                                    )
                                    _sector_strong_codes = set()
                            if _sector_strong_codes:
                                logger.info(
                                    "[Screener] Sector data ready: %d codes from top %.0f%% sectors",
                                    len(_sector_strong_codes), sector_top_pct * 100,
                                )
                            else:
                                logger.warning("[Screener] Sector filter: no sector data available")
                        except Exception as e:
                            logger.warning("[Screener] Sector filter error: %s", e)
                    elif not _need_sector:
                        logger.info(
                            "[Screener] No strategy requires sector filter, skipping sector data fetch"
                        )

                    # Run each daily-data strategy
                    for strategy_id in daily_strategies:
                        params = get_strategy_params(strategy_id)

                        # Apply sector filter for applicable strategies
                        df_s = df.copy()
                        if _sector_strong_codes and strategy_id in self.SECTOR_FILTER_STRATEGIES:
                            code_col = None
                            for col in ['code', '代码', 'ts_code']:
                                if col in df_s.columns:
                                    code_col = col
                                    break
                            if code_col:
                                before_sector = len(df_s)
                                df_s_codes = df_s[code_col].astype(str).str[:6]
                                df_s = df_s[df_s_codes.isin(_sector_strong_codes)]
                                logger.info(
                                    "[Screener] %s: sector filter %d -> %d",
                                    strategy_id, before_sector, len(df_s),
                                )

                        df_s = filter_momentum(df_s, params)
                        stats.after_momentum = len(df_s)
                        df_s = filter_volume(df_s, params)
                        stats.after_volume = len(df_s)

                        logger.debug(
                            f"[Screener] {strategy_id}: after filter_momentum={stats.after_momentum}, "
                            f"after filter_volume={stats.after_volume}"
                        )

                        cands = score_and_rank(df_s, strategy_id, params, top_n=PICKER_TOP_N_PER_STRATEGY)
                        cands = self._filter_by_bias(
                            cands,
                            max_bias_pct=params.max_bias_pct,
                            leader_bias_exempt_pct=getattr(params, "leader_bias_exempt_pct", 0.0),
                        )
                        cands = self._filter_limit_up_streak(cands)
                        cands = self._filter_consecutive_up_days(cands, max_up_days=params.max_consecutive_up_days)
                        cands = self._filter_healthy_pullback(cands, params=params, strategy_id=strategy_id)
                        if self._enable_b_wave_filter:
                            cands = self._filter_b_wave_risk(cands)

                        if cands:
                            candidates_per_strategy[strategy_id] = cands
                            logger.info(f"[Screener] {strategy_id}: {len(cands)} candidates")
                            if logger.isEnabledFor(10):  # DEBUG level
                                top5 = cands[:5]
                                top5_str = ", ".join(f"{c.code}({c.score:.1f})" for c in top5)
                                logger.debug(f"[Screener] {strategy_id} top-5: {top5_str}")
            else:
                logger.info("[Screener] Skipping daily data fetch (only realtime strategies selected)")

            # --- eod_buyback: dedicated full-market screening path ---
            # Historical mode (`screen_as_of(td)`) MUST go through Tushare daily so
            # each backtest date sees that date's candidates, not today's. Live mode
            # keeps the realtime fast path unchanged.
            if "eod_buyback" in self._picker_strategies and self._data_manager:
                if self._as_of_date:
                    logger.info(
                        f"[Screener] Running eod_buyback via Tushare daily historical path "
                        f"(as_of={self._as_of_date})..."
                    )
                    eod_cands = self._screen_eod_buyback_historical(self._as_of_date)
                    path_label = "historical"
                else:
                    logger.info("[Screener] Running eod_buyback via realtime full-market screening...")
                    eod_cands = self._screen_eod_buyback_realtime()
                    path_label = "realtime"
                if eod_cands:
                    candidates_per_strategy["eod_buyback"] = eod_cands
                    logger.info(f"[Screener] eod_buyback ({path_label} path): {len(eod_cands)} candidates")
                else:
                    candidates_per_strategy.pop("eod_buyback", None)
                    logger.info(f"[Screener] eod_buyback ({path_label} path): 0 candidates")

            if not candidates_per_strategy:
                stats.final_pool = 0
                logger.warning("[Screener] No candidates from any strategy")
                return [], stats, {}

            candidates = merge_candidates_by_code(candidates_per_strategy)

            # Auto-reweight underperforming strategies (P1-B). Off by default.
            if getattr(cfg, "strategy_auto_reweight", False):
                try:
                    from src.services.strategy_attribution_service import (
                        get_strategy_weights,
                    )
                    from src.storage import get_db
                    weights = get_strategy_weights(
                        db=get_db(),
                        data_manager=self._data_manager,
                    )
                    if weights:
                        for s in candidates:
                            sids = s.strategies or []
                            if sids:
                                w = min((weights.get(sid, 1.0) for sid in sids), default=1.0)
                                if w < 1.0:
                                    s.score *= w
                        candidates.sort(key=lambda s: s.score, reverse=True)
                        bad = [sid for sid, w in weights.items() if w < 1.0]
                        if bad:
                            logger.info(
                                "[Screener] Auto-reweight applied. Penalised strategies: %s",
                                bad,
                            )
                except Exception as exc:
                    logger.warning("[Screener] Auto-reweight failed (skipped): %s", exc)

            # -- Industry concentration cap (E2) --
            INDUSTRY_TOP_N = int(getattr(cfg, "picker_industry_top_n", 2) or 2)
            if candidates and INDUSTRY_TOP_N > 0:
                tagged = [s for s in candidates if getattr(s, "industry", "")]
                if tagged:
                    candidates.sort(key=lambda s: s.score, reverse=True)
                    seen: Dict[str, int] = {}
                    kept: List[ScreenedStock] = []
                    dropped = 0
                    for s in candidates:
                        ind = getattr(s, "industry", "") or ""
                        if not ind:
                            kept.append(s)
                            continue
                        if seen.get(ind, 0) >= INDUSTRY_TOP_N:
                            dropped += 1
                            continue
                        seen[ind] = seen.get(ind, 0) + 1
                        kept.append(s)
                    if dropped > 0:
                        logger.info(
                            "[Screener] Industry concentration cap (top %d/industry): "
                            "dropped %d, kept %d",
                            INDUSTRY_TOP_N, dropped, len(kept),
                        )
                    candidates = kept

            # -- Regime-aware position scaling (E1) --
            if market_env is not None and candidates:
                regime_scale = {"weak": 0.6, "neutral": 0.85, "strong": 1.0}.get(
                    market_env.regime, 1.0
                )
                if regime_scale < 1.0:
                    for s in candidates:
                        if getattr(s, "position_pct", 0) > 0:
                            s.position_pct = round(s.position_pct * regime_scale, 3)
                    logger.info(
                        "[Screener] Regime=%s, position scaled x%.2f",
                        market_env.regime, regime_scale,
                    )

            stats.final_pool = len(candidates)
            logger.info(
                f"[Screener] Merged {stats.final_pool} candidates from "
                f"{len(candidates_per_strategy)} strategies"
            )
            return candidates, stats, candidates_per_strategy
        finally:
            # Always restore original strategies after this call
            self._picker_strategies = original_strategies

    def screen_as_of(
        self, trade_date: str
    ) -> Tuple[List[ScreenedStock], ScreenStats, Dict[str, List[ScreenedStock]]]:
        """Run screening as of a specific trade date (YYYYMMDD). For backtest use."""
        return self.screen(trade_date=trade_date)
