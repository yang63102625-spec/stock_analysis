# -*- coding: utf-8 -*-
"""
Quantitative screening engine (Stage 1) for the stock picker pipeline.

Contains the StockScreener class which applies multi-layer filters on full-market data.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import get_config
from src.services.picker.constants import (
    AMOUNT_MIN_LARGE_CAP,
    AMOUNT_MIN_SMALL_CAP,
    LIMIT_UP_PCT_KC_CY,
    LIMIT_UP_PCT_MAIN,
    MARKET_CAP_TIER_YI,
    PE_SCORE_PARTIAL_MAX,
    PICKER_TOP_N_PER_STRATEGY,
    TREND_DECAY_THRESHOLD_PCT,
    TURNOVER_MAX_PCT,
    TURNOVER_MIN_PCT,
    VOLUME_RATIO_MIN,
    MarketEnvironment,
    PickerModeParams,
    ScreenedStock,
    ScreenStats,
    _resolve_fallback_trade_date,
    get_tushare_api,
)
from src.services.picker.market_guard import check_market_environment
from src.services.picker import risk_filters
from data_provider.base import is_kc_cy_stock

logger = logging.getLogger(__name__)


class StockScreener:
    """Multi-layer quantitative screener using full-market spot data."""

    _EXCLUDE_NAME_KEYWORDS = ("ST", "*ST", "退市", "N ", "C ")
    _ETF_PREFIXES = ("51", "52", "56", "58", "15", "16", "18")

    def __init__(
        self,
        data_manager=None,
        picker_strategies: Optional[List[str]] = None,
        picker_mode: str = "balanced",
        turnover_min: Optional[float] = None,
        turnover_max: Optional[float] = None,
        enable_b_wave_filter: bool = True,
        allow_loss: bool = False,
        spot_timeout: Optional[int] = None,
    ):
        self._data_manager = data_manager
        self._spot_timeout = spot_timeout if spot_timeout is not None else int(
            os.getenv("PICKER_SPOT_TIMEOUT", "30")
        )
        self._as_of_date: Optional[str] = None  # YYYY-MM-DD for historical screening
        self._picker_strategies = picker_strategies if picker_strategies else ["buy_pullback"]
        self._picker_mode = (picker_mode or "balanced").lower()
        self._turnover_min = turnover_min if turnover_min is not None else TURNOVER_MIN_PCT
        self._turnover_max = turnover_max if turnover_max is not None else TURNOVER_MAX_PCT
        self._enable_b_wave_filter = enable_b_wave_filter
        self._allow_loss = allow_loss
        self._stock_basic_cache: Optional[pd.DataFrame] = None  # Reuse across days in backtest

    # Strategies that require daily spot data (fetched via _fetch_spot_data).
    # eod_buyback uses a dedicated realtime full-market path and does NOT need daily data.
    DAILY_DATA_STRATEGIES = {"buy_pullback", "breakout", "bottom_reversal"}

    # Strategies that benefit from sector strength filtering
    SECTOR_FILTER_STRATEGIES = {"buy_pullback", "breakout"}

    def _check_market_environment(self) -> Optional[MarketEnvironment]:
        """Check SSE index vs MA20 to determine market regime."""
        return check_market_environment(self._data_manager, self._as_of_date)

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
            if getattr(cfg, "picker_market_guard", True):
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

            # --- eod_buyback: dedicated realtime full-market screening path ---
            if "eod_buyback" in self._picker_strategies and self._data_manager:
                logger.info("[Screener] Running eod_buyback via realtime full-market screening...")
                eod_rt_cands = self._screen_eod_buyback_realtime()
                if eod_rt_cands:
                    candidates_per_strategy["eod_buyback"] = eod_rt_cands
                    logger.info(f"[Screener] eod_buyback (realtime path): {len(eod_rt_cands)} candidates")
                else:
                    candidates_per_strategy.pop("eod_buyback", None)
                    logger.info("[Screener] eod_buyback (realtime path): 0 candidates")

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

    # ── Risk filter delegation ────────────────────────────────────────────

    def _filter_by_bias(self, candidates, max_bias_pct=8.0, leader_bias_exempt_pct=0.0):
        return risk_filters.filter_by_bias(
            candidates, self._data_manager, self._as_of_date,
            self._fetch_daily_batch, max_bias_pct, leader_bias_exempt_pct,
        )

    def _filter_limit_up_streak(self, candidates, days=5, min_limit_up_days=2):
        return risk_filters.filter_limit_up_streak(
            candidates, self._data_manager, self._as_of_date,
            self._fetch_daily_batch, days, min_limit_up_days,
        )

    def _filter_consecutive_up_days(self, candidates, days=5, max_up_days=None):
        return risk_filters.filter_consecutive_up_days(
            candidates, self._data_manager, self._as_of_date,
            self._fetch_daily_batch, self._picker_mode, days, max_up_days,
        )

    def _filter_healthy_pullback(self, candidates, lookback_days=20, params=None, strategy_id=None):
        return risk_filters.filter_healthy_pullback(
            candidates, self._data_manager, self._as_of_date,
            self._fetch_daily_batch, self._picker_mode, lookback_days, params, strategy_id,
        )

    def _filter_b_wave_risk(self, candidates, lookback_days=20):
        return risk_filters.filter_b_wave_risk(
            candidates, self._data_manager, self._as_of_date,
            self._fetch_daily_batch, lookback_days,
        )

    @staticmethod
    def _is_leader_candidate(s: ScreenedStock) -> bool:
        """Check if stock qualifies for leader bias exemption."""
        return risk_filters.is_leader_candidate(s)

    # ── Utility methods ────────────────────────────────────────────

    @staticmethod
    def _first_col(df: pd.DataFrame, *names: str):
        """Return first column name that exists in df, or None."""
        for n in names:
            if n in df.columns:
                return n
        return None

    @staticmethod
    def _calc_volume_ratio(current_vol: float, avg_5d_vol: float) -> float:
        """Calculate volume ratio considering trading session elapsed time."""
        if not avg_5d_vol or avg_5d_vol <= 0 or not current_vol or current_vol <= 0:
            return 0.0

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        total_minutes = 240  # 9:30-11:30 (120 min) + 13:00-15:00 (120 min)

        # After market close: simple full-day ratio
        if now.hour >= 15:
            return round(current_vol / avg_5d_vol, 2)

        # Before market open
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            return 0.0

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

        return round(current_per_min / avg_per_min, 2) if avg_per_min > 0 else 0.0

    @staticmethod
    def _trade_date_to_iso(trade_date: str) -> str:
        """Convert YYYYMMDD to YYYY-MM-DD."""
        if not trade_date or len(trade_date) != 8:
            return trade_date
        return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

    def _fetch_daily_batch(
        self,
        requests: List[Tuple[str, Optional[str], Optional[str], int]],
        max_workers: int = 5,
        total_timeout: float = 120.0,
    ) -> Dict[Tuple[str, str, str, int], Tuple[pd.DataFrame, str]]:
        """Fetch get_daily_data for multiple (code, start, end, days) in parallel."""
        from concurrent.futures import as_completed, TimeoutError as FuturesTimeout
        if not self._data_manager or not requests:
            return {}

        def _key(c: str, s: Optional[str], e: Optional[str], d: int) -> Tuple[str, str, str, int]:
            return (c, s or "", e or "", d)

        def _fetch(args: Tuple[str, Optional[str], Optional[str], int]):
            code, start, end, days = args
            try:
                df, src = self._data_manager.get_daily_data(
                    code, start_date=start, end_date=end, days=days
                )
                if df is not None:
                    return (_key(code, start, end, days), (df, src))
            except Exception as e:
                logger.debug(f"[Screener] Batch fetch failed {code}: {e}")
            return None

        unique_requests = list(dict.fromkeys(requests))
        results: Dict[Tuple[str, str, str, int], Tuple[pd.DataFrame, str]] = {}
        pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="screener_fetch")
        futures = {pool.submit(_fetch, req): req for req in unique_requests}
        try:
            for future in as_completed(futures, timeout=total_timeout):
                try:
                    res = future.result()
                except Exception as e:
                    code = futures[future][0]
                    logger.debug(f"[Screener] Batch fetch future error {code}: {e}")
                    continue
                if res:
                    results[res[0]] = res[1]
        except FuturesTimeout:
            pending = [futures[f][0] for f in futures if not f.done()]
            logger.warning(
                f"[Screener] _fetch_daily_batch global timeout ({total_timeout}s), "
                f"{len(pending)} pending: {pending[:10]}"
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return results

    # ── Data fetching ────────────────────────────────────────────

    _UA_LIST = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    ]

    def _fetch_spot_data(self, trade_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """Fetch full A-share data for Phase-1 fast screening.
        Priority: Tushare(daily, fast bulk scan) -> AkShare(spot, fallback) -> efinance(quotes, last resort).
        """
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        # Historical mode: only Tushare supports dated queries
        if trade_date:
            df = self._try_tushare(trade_date=trade_date)
            if df is not None and not df.empty:
                logger.info(f"[Screener] Historical mode - Using Tushare data: {len(df)} stocks")
                return df
            logger.warning("[Screener] Historical mode - Tushare returned empty, no data available")
            return None

        # --- 1. Tushare daily - fast bulk scan for Phase-1 ---
        logger.info(
            "[Screener] Trying Tushare daily (priority 1/3) - "
            "fast bulk scan for Phase-1; realtime precision deferred to Phase-2"
        )
        df = self._try_tushare(trade_date=None)
        if df is not None and not df.empty:
            logger.info(f"[Screener] Using Tushare daily data: {len(df)} stocks (Phase-1 fast path)")
            return df
        logger.warning("[Screener] Tushare daily unavailable, trying AkShare realtime fallback")

        # --- 2. AkShare realtime ---
        def _try_akshare() -> pd.DataFrame:
            import random
            import requests as _req
            ua = random.choice(self._UA_LIST)
            orig = _req.utils.default_headers
            _req.utils.default_headers = lambda: _req.structures.CaseInsensitiveDict({"User-Agent": ua})
            try:
                import akshare as ak
                return ak.stock_zh_a_spot_em()
            finally:
                _req.utils.default_headers = orig

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="screener") as pool:
            logger.info(
                f"[Screener] Trying AkShare realtime spot (wall timeout={self._spot_timeout}s) - "
                "priority 2/3 fallback"
            )
            t0 = time.time()
            try:
                fut = pool.submit(_try_akshare)
                df = fut.result(timeout=self._spot_timeout)
                logger.info(
                    f"[Screener] Using AkShare realtime data: {len(df)} stocks in {time.time()-t0:.1f}s"
                )
                return df
            except FuturesTimeout:
                logger.warning(f"[Screener] AkShare hard-timeout after {self._spot_timeout}s, trying next source")
                fut.cancel()
            except Exception as e:
                logger.warning(f"[Screener] AkShare failed: {e}, trying next source")

        # --- 3. efinance realtime ---
        def _try_efinance() -> pd.DataFrame:
            import efinance as ef
            return ef.stock.get_realtime_quotes()

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="screener") as pool:
            logger.info(
                f"[Screener] Trying efinance realtime quotes (wall timeout={self._spot_timeout}s) - "
                "priority 3/3 last resort"
            )
            t0 = time.time()
            try:
                fut = pool.submit(_try_efinance)
                df = fut.result(timeout=self._spot_timeout)
                logger.info(
                    f"[Screener] Using efinance realtime data: {len(df)} stocks in {time.time()-t0:.1f}s"
                )
                return self._normalize_efinance_df(df)
            except FuturesTimeout:
                logger.warning(f"[Screener] efinance hard-timeout after {self._spot_timeout}s")
                fut.cancel()
            except Exception as e:
                logger.warning(f"[Screener] efinance failed: {e}")

        logger.error("[Screener] All data sources exhausted - no spot data available")
        return None

    def _try_tushare(self, trade_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """Fetch full-market daily data via Tushare Pro (daily + daily_basic + stock_basic)."""
        tushare_api = self._get_tushare_api()
        if tushare_api is None:
            logger.info("[Screener] Tushare API not available (TUSHARE_TOKEN unset or init failed)")
            return None

        try:
            china_now = datetime.now(ZoneInfo("Asia/Shanghai"))
            is_historical = trade_date is not None
            if trade_date is None:
                trade_date = china_now.strftime("%Y%m%d")

            logger.info(f"[Screener] Fetching via Tushare (trade_date={trade_date})...")
            t0 = time.time()

            df_daily = tushare_api.daily(trade_date=trade_date)
            if (df_daily is None or df_daily.empty) and not is_historical:
                fallback_date = _resolve_fallback_trade_date(china_now)
                logger.info(f"[Screener] No data for {trade_date}, trying last trading day {fallback_date}...")
                df_daily = tushare_api.daily(trade_date=fallback_date)
                trade_date = fallback_date

            if df_daily is None or df_daily.empty:
                logger.warning("[Screener] Tushare daily returned empty")
                return None

            df_daily.columns = [c.lower() for c in df_daily.columns]

            # Fetch valuation metrics
            df_basic = tushare_api.daily_basic(
                trade_date=trade_date,
                fields="ts_code,pe,pb,turnover_rate,volume_ratio,total_mv",
            )
            if df_basic is not None and not df_basic.empty:
                df_basic.columns = [c.lower() for c in df_basic.columns]
                df_daily = df_daily.merge(df_basic, on="ts_code", how="left")

            # Fetch stock names (cache for backtest: same for all days)
            if self._stock_basic_cache is not None:
                df_names = self._stock_basic_cache
            else:
                df_names = tushare_api.stock_basic(fields="ts_code,symbol,name,industry")
                if df_names is not None and not df_names.empty:
                    df_names.columns = [c.lower() for c in df_names.columns]
                    self._stock_basic_cache = df_names
            if df_names is not None and not df_names.empty:
                df_daily = df_daily.merge(df_names, on="ts_code", how="left")

            # Normalize columns to match AkShare convention used by filters
            df_daily["代码"] = df_daily.get("symbol", df_daily["ts_code"].str[:6])
            df_daily["名称"] = df_daily.get("name", "")
            df_daily["最新价"] = df_daily["close"]
            df_daily["涨跌幅"] = df_daily.get("pct_chg", 0)
            df_daily["市盈率-动态"] = df_daily.get("pe", pd.NA)
            vr_stale = pd.to_numeric(df_daily.get("volume_ratio", pd.NA), errors="coerce")
            df_daily["量比"] = vr_stale.fillna(1.0)
            df_daily["换手率"] = df_daily.get("turnover_rate", pd.NA)
            df_daily["成交额"] = df_daily.get("amount", 0).astype(float) * 1000  # 千元->元
            df_daily["市净率"] = df_daily.get("pb", pd.NA)
            df_daily["总市值"] = df_daily.get("total_mv", 0).astype(float) * 1e4  # 万元->元

            # Compute 60-day change
            df_daily = self._add_tushare_60d_change(df_daily, tushare_api, trade_date)

            # Overlay realtime data
            if not is_historical:
                try:
                    from data_provider.tushare_fetcher import _realtime_list_cache
                    import data_provider.tushare_fetcher as _ts_mod
                    _realtime_list_cache['timestamp'] = 0.0
                    _ts_mod._rt_k_cache_time = 0.0
                    logger.debug("[Screener] Forced realtime cache expiry before supplement")
                except (ImportError, KeyError) as e:
                    logger.warning(f"[Screener] Could not force cache expiry: {e}")
                df_daily = self._supplement_realtime_data(df_daily)

            elapsed = time.time() - t0
            logger.info(f"[Screener] Tushare returned {len(df_daily)} stocks in {elapsed:.1f}s")
            return df_daily

        except Exception as e:
            logger.warning(f"[Screener] Tushare failed: {e}")
            return None

    def _get_tushare_api(self):
        """Get Tushare API instance from data_manager or create one."""
        return get_tushare_api(self._data_manager)

    def _supplement_realtime_data(self, df_daily: pd.DataFrame) -> pd.DataFrame:
        """Overlay realtime fields onto the Tushare daily DataFrame.

        Primary source: Tushare rt_k (full-market realtime daily bars).
        Fallback source: realtime_list(src='dc') when rt_k is unavailable.
        """
        try:
            tushare_fetcher = None
            for fetcher in getattr(self._data_manager, '_fetchers', []):
                if type(fetcher).__name__ == 'TushareFetcher':
                    tushare_fetcher = fetcher
                    break

            if tushare_fetcher is None:
                logger.debug("[Screener] TushareFetcher not available, skipping realtime supplement")
                return df_daily

            # --- Primary source: rt_k ---
            df_rt = None
            try:
                rt_k_quotes = tushare_fetcher._fetch_realtime_rt_k()
                if rt_k_quotes:
                    rt_data = []
                    for ts_code, quote in rt_k_quotes.items():
                        rt_data.append({
                            'ts_code': ts_code,
                            'price': quote.price,
                            'pct_change': quote.change_pct,
                            'vol_ratio': quote.volume_ratio,
                            'turnover_rate': quote.turnover_rate,
                            'pe': quote.pe_ratio,
                            'pb': quote.pb_ratio,
                            'total_mv': quote.total_mv,
                            'amount': quote.amount,
                        })
                    if rt_data:
                        df_rt = pd.DataFrame(rt_data)
                        logger.info("[Screener] Realtime data source: rt_k (%d quotes)", len(df_rt))
            except Exception as e:
                logger.debug("[Screener] rt_k fetch error: %s", e)

            # --- Fallback: realtime_list ---
            if df_rt is None or df_rt.empty:
                logger.info("[Screener] rt_k unavailable, falling back to realtime_list")
                df_rt = tushare_fetcher._fetch_realtime_list()

            if df_rt is None or df_rt.empty:
                logger.warning(
                    "[Screener] Both rt_k and realtime_list returned empty/failed, "
                    "falling back to daily_basic (T-1) data"
                )
                return df_daily

            # Build a lookup by 6-digit code
            rt = df_rt.copy()
            if 'ts_code' in rt.columns:
                rt['_code6'] = rt['ts_code'].str.split('.').str[0]
            else:
                logger.debug("[Screener] realtime_list has no ts_code column, skipping supplement")
                return df_daily

            rt = rt.drop_duplicates(subset='_code6', keep='first').set_index('_code6')

            # Map daily df codes to 6-digit for joining
            if '代码' in df_daily.columns:
                code_series = df_daily['代码'].astype(str).str[:6]
            elif 'ts_code' in df_daily.columns:
                code_series = df_daily['ts_code'].str.split('.').str[0]
            else:
                logger.debug("[Screener] Cannot determine code column for realtime join")
                return df_daily

            updated_count = 0

            # -- vol_ratio --
            if 'vol_ratio' in rt.columns:
                rt_vr = code_series.map(rt['vol_ratio'])
                rt_vr = pd.to_numeric(rt_vr, errors='coerce')
                valid = rt_vr.notna() & (rt_vr > 0)
                if valid.any():
                    df_daily.loc[valid, '量比'] = rt_vr[valid]
                    updated_count += valid.sum()
                    logger.info(
                        "[Screener] Realtime vol_ratio supplemented for %d/%d stocks",
                        valid.sum(), len(df_daily),
                    )

            # -- turnover_rate --
            if 'turnover_rate' in rt.columns:
                rt_tr = code_series.map(rt['turnover_rate'])
                rt_tr = pd.to_numeric(rt_tr, errors='coerce')
                valid = rt_tr.notna() & (rt_tr > 0)
                if valid.any():
                    df_daily['换手率'] = df_daily.get('换手率', pd.NA)
                    df_daily.loc[valid, '换手率'] = rt_tr[valid]

            # -- pe --
            if 'pe' in rt.columns:
                rt_pe = code_series.map(rt['pe'])
                rt_pe = pd.to_numeric(rt_pe, errors='coerce')
                valid = rt_pe.notna()
                if valid.any():
                    df_daily.loc[valid, '市盈率-动态'] = rt_pe[valid]

            # -- pb --
            if 'pb' in rt.columns:
                rt_pb = code_series.map(rt['pb'])
                rt_pb = pd.to_numeric(rt_pb, errors='coerce')
                valid = rt_pb.notna()
                if valid.any():
                    df_daily.loc[valid, '市净率'] = rt_pb[valid]

            # -- total_mv --
            if 'total_mv' in rt.columns:
                rt_mv = code_series.map(rt['total_mv'])
                rt_mv = pd.to_numeric(rt_mv, errors='coerce')
                valid = rt_mv.notna() & (rt_mv > 0)
                if valid.any():
                    df_daily.loc[valid, '总市值'] = rt_mv[valid]

            # -- price --
            if 'price' in rt.columns:
                rt_price = code_series.map(rt['price'])
                rt_price = pd.to_numeric(rt_price, errors='coerce')
                valid = rt_price.notna() & (rt_price > 0)
                if valid.any():
                    df_daily.loc[valid, '最新价'] = rt_price[valid]

            # -- pct_change --
            if 'pct_change' in rt.columns:
                rt_chg = code_series.map(rt['pct_change'])
                rt_chg = pd.to_numeric(rt_chg, errors='coerce')
                valid = rt_chg.notna()
                if valid.any():
                    df_daily.loc[valid, '涨跌幅'] = rt_chg[valid]

            # -- amount --
            if 'amount' in rt.columns:
                rt_amt = code_series.map(rt['amount'])
                rt_amt = pd.to_numeric(rt_amt, errors='coerce')
                valid = rt_amt.notna() & (rt_amt > 0)
                if valid.any():
                    df_daily.loc[valid, '成交额'] = rt_amt[valid]

            # -- 60day --
            col_60d = None
            for candidate_col in ('60day', '60_day'):
                if candidate_col in rt.columns:
                    col_60d = candidate_col
                    break
            if col_60d:
                rt_60d = code_series.map(rt[col_60d])
                rt_60d = pd.to_numeric(rt_60d, errors='coerce')
                valid = rt_60d.notna()
                if valid.any():
                    df_daily.loc[valid, '60日涨跌幅'] = rt_60d[valid]
                    logger.info(
                        "[Screener] Realtime 60d change supplemented for %d stocks", valid.sum()
                    )

            logger.info("[Picker] Supplemented %d stocks with realtime data", updated_count)
            logger.info("[Screener] Realtime data supplement complete (%d rows)", len(rt))

        except Exception as e:
            logger.warning("[Screener] Failed to supplement realtime data: %s", e)

        # --- Fallback: compute volume ratio for stocks still missing it ---
        try:
            self._fill_missing_volume_ratio(df_daily)
        except Exception as e:
            logger.warning("[Screener] Failed to fill missing volume ratio: %s", e)

        return df_daily

    def _fill_missing_volume_ratio(self, df_daily: pd.DataFrame) -> None:
        """Compute volume ratio for stocks where it is missing or stale."""
        if '量比' not in df_daily.columns or not self._data_manager:
            return

        vr_col = pd.to_numeric(df_daily['量比'], errors='coerce')
        needs_calc = vr_col.isna() | (vr_col <= 0) | (vr_col == 1.0)
        if not needs_calc.any():
            return

        if '代码' in df_daily.columns:
            code_series = df_daily['代码'].astype(str).str[:6]
        elif 'ts_code' in df_daily.columns:
            code_series = df_daily['ts_code'].str.split('.').str[0]
        else:
            return

        vol_col = self._first_col(df_daily, 'vol', 'volume', '成交量')
        if vol_col is None:
            return

        filled = 0
        for idx in df_daily.index[needs_calc]:
            code = str(code_series.get(idx, ''))
            if not code:
                continue
            today_vol = pd.to_numeric(df_daily.at[idx, vol_col], errors='coerce')
            if pd.isna(today_vol) or today_vol <= 0:
                continue
            try:
                df_hist, _src = self._data_manager.get_daily_data(code, days=6)
                if df_hist is None or len(df_hist) < 2:
                    continue
                hist_vol_col = self._first_col(df_hist, 'vol', 'volume', '成交量')
                if hist_vol_col is None:
                    continue
                hist_vol = pd.to_numeric(df_hist[hist_vol_col], errors='coerce').iloc[:-1]
                avg_5d = hist_vol.mean()
                if pd.isna(avg_5d) or avg_5d <= 0:
                    continue
                vr = self._calc_volume_ratio(float(today_vol), float(avg_5d))
                if vr > 0:
                    df_daily.at[idx, '量比'] = vr
                    filled += 1
            except Exception:
                continue

        if filled > 0:
            logger.info(
                "[Screener] Computed volume ratio for %d/%d stocks (5-day avg fallback)",
                filled, int(needs_calc.sum()),
            )

    def _add_tushare_60d_change(
        self, df_daily: pd.DataFrame, tushare_api, trade_date: str
    ) -> pd.DataFrame:
        """Add 60d change for Tushare data by fetching close from 60 trading days ago."""
        try:
            start = (pd.Timestamp(trade_date) - pd.Timedelta(days=120)).strftime("%Y%m%d")
            df_cal = tushare_api.trade_cal(exchange="SSE", start_date=start, end_date=trade_date)
            if df_cal is None or df_cal.empty:
                logger.warning("[Screener] Tushare trade_cal returned empty, 60d change skipped")
                df_daily["60日涨跌幅"] = 0
                return df_daily

            df_cal.columns = [c.lower() for c in df_cal.columns]
            df_cal = df_cal[df_cal["is_open"] == 1].sort_values("cal_date")
            dates = df_cal["cal_date"].tolist()
            if trade_date not in dates:
                idx = 0
            else:
                idx = dates.index(trade_date)
            if idx < 60:
                logger.warning("[Screener] Not enough trading days for 60d change, skipped")
                df_daily["60日涨跌幅"] = 0
                return df_daily

            date_60d = dates[idx - 60]
            df_60d = tushare_api.daily(trade_date=date_60d)
            if df_60d is None or df_60d.empty:
                df_daily["60日涨跌幅"] = 0
                return df_daily

            df_60d.columns = [c.lower() for c in df_60d.columns]
            close_60d_map = df_60d.set_index("ts_code")["close"]
            close_today = pd.to_numeric(df_daily["close"], errors="coerce")
            close_60d = df_daily["ts_code"].map(close_60d_map)
            close_60d = pd.to_numeric(close_60d, errors="coerce")
            mask = (close_60d > 0) & close_today.notna() & close_60d.notna()
            pct_60d = pd.Series(0.0, index=df_daily.index)
            pct_60d.loc[mask] = (close_today.loc[mask] - close_60d.loc[mask]) / close_60d.loc[mask] * 100
            df_daily["60日涨跌幅"] = pct_60d.values
            logger.info(f"[Screener] Added 60d change for {mask.sum()} stocks (ref date {date_60d})")
        except Exception as e:
            logger.warning(f"[Screener] Failed to add 60d change: {e}")
            df_daily["60日涨跌幅"] = 0
        return df_daily

    @staticmethod
    def _normalize_efinance_df(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize efinance column names to match AkShare's convention."""
        col_map = {
            "股票代码": "代码", "股票名称": "名称",
            "最新价": "最新价", "涨跌幅": "涨跌幅",
            "成交量": "成交量", "成交额": "成交额",
            "换手率": "换手率", "量比": "量比",
            "动态市盈率": "市盈率-动态", "市净率": "市净率",
            "总市值": "总市值", "流通市值": "流通市值",
        }
        renamed = {}
        for old, new in col_map.items():
            if old in df.columns:
                renamed[old] = new
        return df.rename(columns=renamed)

    # ── Basic filters ────────────────────────────────────────────

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

    # ── EOD Buyback ────────────────────────────────────────────

    def _screen_eod_buyback_realtime(self) -> List[ScreenedStock]:
        """Screen eod_buyback via Tushare batch realtime quotes."""
        import tushare as ts
        from src.services.picker_strategies import is_mainboard_stock

        if not self._data_manager:
            logger.warning("[EOD-RT] No data_manager")
            return []

        t0 = time.time()
        all_codes: list = []
        for fetcher in self._data_manager._fetchers:
            if hasattr(fetcher, "get_stock_list"):
                try:
                    df_list = fetcher.get_stock_list()
                    if df_list is not None and not df_list.empty:
                        all_codes = df_list["code"].tolist()
                        logger.info(
                            f"[EOD-RT] Got {len(all_codes)} stock codes from {type(fetcher).__name__}"
                        )
                        break
                except Exception as e:
                    logger.debug(f"[EOD-RT] get_stock_list failed from {type(fetcher).__name__}: {e}")

        if not all_codes:
            logger.warning("[EOD-RT] Failed to get stock code list")
            return []

        # Batch query realtime quotes (200 per batch)
        BATCH_SIZE = 200
        all_dfs: list = []
        for i in range(0, len(all_codes), BATCH_SIZE):
            batch = all_codes[i: i + BATCH_SIZE]
            try:
                df_batch = ts.get_realtime_quotes(batch)
                if df_batch is not None and not df_batch.empty:
                    all_dfs.append(df_batch)
            except Exception as e:
                logger.debug(f"[EOD-RT] Batch {i // BATCH_SIZE} failed: {e}")

        if not all_dfs:
            logger.warning("[EOD-RT] No realtime data from any batch")
            return []

        df = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"[EOD-RT] Fetched realtime quotes for {len(df)} stocks in {time.time() - t0:.1f}s")

        # Supplement turnover_rate and total_mv from Tushare Pro daily_basic
        try:
            tushare_fetcher = None
            for fetcher in self._data_manager._fetchers:
                if type(fetcher).__name__ == "TushareFetcher":
                    tushare_fetcher = fetcher
                    break

            if tushare_fetcher and tushare_fetcher._api:
                from src.core.trading_calendar import get_last_trading_day as _get_ltd

                now_sh_sup = datetime.now(ZoneInfo("Asia/Shanghai"))
                trade_day = _get_ltd("cn", now_sh_sup.date())
                if trade_day is None:
                    from datetime import timedelta as _td
                    for offset in (0, 1, 2):
                        candidate = (now_sh_sup.date() - _td(days=offset)).strftime("%Y%m%d")
                        tushare_fetcher._check_rate_limit()
                        _df_try = tushare_fetcher._api.daily_basic(
                            trade_date=candidate, fields="ts_code,turnover_rate,total_mv"
                        )
                        if _df_try is not None and not _df_try.empty:
                            trade_day = (now_sh_sup.date() - _td(days=offset))
                            break

                if trade_day is not None:
                    trade_date_str = trade_day.strftime("%Y%m%d")
                    tushare_fetcher._check_rate_limit()
                    df_basic = tushare_fetcher._api.daily_basic(
                        trade_date=trade_date_str,
                        fields="ts_code,turnover_rate,total_mv,pe_ttm,pb",
                    )
                    if df_basic is not None and not df_basic.empty:
                        df_basic["code"] = df_basic["ts_code"].str.split(".").str[0]
                        df_basic["total_mv_yi"] = df_basic["total_mv"] / 1e4
                        df = df.merge(
                            df_basic[["code", "turnover_rate", "total_mv_yi", "pe_ttm", "pb"]],
                            on="code", how="left",
                        )
                        logger.info(
                            f"[EOD-RT] Supplemented turnover/mv from daily_basic({trade_date_str}): "
                            f"{df['turnover_rate'].notna().sum()} turnover, "
                            f"{df['total_mv_yi'].notna().sum()} market_cap"
                        )
                    else:
                        logger.warning(f"[EOD-RT] daily_basic returned empty for {trade_date_str}")
                else:
                    logger.warning("[EOD-RT] Could not determine latest trading day for daily_basic")
            else:
                logger.debug("[EOD-RT] TushareFetcher not available, skipping daily_basic supplement")
        except Exception as e:
            logger.warning(f"[EOD-RT] Failed to supplement from daily_basic: {e}")

        logger.debug(f"[EOD-RT] DataFrame columns after supplement: {list(df.columns)}")

        # Compute change_pct from price and pre_close
        df["price"] = pd.to_numeric(df.get("price", pd.Series(dtype=float)), errors="coerce")
        pre_close_col = "pre_close" if "pre_close" in df.columns else "settlement"
        df["pre_close"] = pd.to_numeric(df.get(pre_close_col, pd.Series(dtype=float)), errors="coerce")
        df["calc_change_pct"] = (
            (df["price"] - df["pre_close"]) / df["pre_close"].replace(0, float("nan"))
        ) * 100

        # One-pass filter
        mask = pd.Series(True, index=df.index)
        code_col = "code"
        if code_col in df.columns:
            mask &= df[code_col].apply(lambda c: is_mainboard_stock(str(c)))
        if "name" in df.columns:
            mask &= ~df["name"].str.contains("ST", na=False, case=False)
        mask &= (df["calc_change_pct"] >= 3.0) & (df["calc_change_pct"] <= 6.0)

        # Turnover filter
        turnover_col = None
        for col_name in ["turnover", "turnover_rate"]:
            if col_name in df.columns:
                turnover_col = col_name
                break
        if turnover_col:
            turnover = pd.to_numeric(df[turnover_col], errors="coerce")
            has_turnover = turnover.notna() & (turnover > 0)
            if has_turnover.any():
                mask &= ~has_turnover | ((turnover >= 5.0) & (turnover <= 12.0))
                logger.info(
                    f"[EOD-RT] Turnover filter applied via '{turnover_col}' "
                    f"({has_turnover.sum()} stocks had data)"
                )
            else:
                logger.info("[EOD-RT] Turnover data unavailable, skipping filter")
        else:
            logger.info("[EOD-RT] No turnover column, skipping filter")

        # Market cap filter
        mktcap_col = None
        mktcap_already_yi = False
        for col_name in ["mktcap", "nmc", "market_cap"]:
            if col_name in df.columns:
                mktcap_col = col_name
                break
        if mktcap_col is None and "total_mv_yi" in df.columns:
            mktcap_col = "total_mv_yi"
            mktcap_already_yi = True
        if mktcap_col:
            mktcap = pd.to_numeric(df[mktcap_col], errors="coerce")
            mktcap_yi = mktcap if mktcap_already_yi else mktcap / 1e4
            has_mktcap = mktcap.notna() & (mktcap > 0)
            if has_mktcap.any():
                mask &= ~has_mktcap | ((mktcap_yi >= 60.0) & (mktcap_yi <= 300.0))
                logger.info(
                    f"[EOD-RT] Market cap filter applied via '{mktcap_col}' "
                    f"({has_mktcap.sum()} stocks had data)"
                )
            else:
                logger.info("[EOD-RT] Market cap data unavailable, skipping filter")
        else:
            logger.info("[EOD-RT] No market cap column, skipping filter")

        # VWAP filter
        if "volume" in df.columns and "amount" in df.columns:
            rt_volume_vwap = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
            rt_amount_vwap = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
            vwap_valid = (rt_volume_vwap > 0) & (rt_amount_vwap > 0)
            vwap = rt_amount_vwap / rt_volume_vwap.replace(0, float("nan"))
            vwap_mask = ~vwap_valid | (df["price"] >= vwap)
            mask &= vwap_mask
            logger.info(f"[EOD-RT] VWAP filter applied ({vwap_valid.sum()} stocks had data)")
        else:
            logger.info("[EOD-RT] VWAP skipped (no volume/amount columns)")

        df_filtered = df[mask].copy()
        logger.info(f"[EOD-RT] After all filters: {len(df_filtered)} stocks")

        if df_filtered.empty:
            return []

        # Volume ratio computation
        now_sh = datetime.now(ZoneInfo("Asia/Shanghai"))
        is_after_close = now_sh.hour >= 15
        vol_ratio_map: Dict[str, float] = {}

        # Try realtime_list first for today's live vol_ratio
        try:
            tushare_fetcher = None
            for fetcher in getattr(self._data_manager, '_fetchers', []):
                if type(fetcher).__name__ == 'TushareFetcher':
                    tushare_fetcher = fetcher
                    break
            if tushare_fetcher:
                df_rt = tushare_fetcher._fetch_realtime_list()
                if df_rt is not None and not df_rt.empty and 'vol_ratio' in df_rt.columns:
                    rt = df_rt.copy()
                    if 'ts_code' in rt.columns:
                        rt['_code6'] = rt['ts_code'].str.split('.').str[0]
                        rt = rt.drop_duplicates(subset='_code6', keep='first')
                        rt_vr_lookup = dict(
                            zip(rt['_code6'], pd.to_numeric(rt['vol_ratio'], errors='coerce'))
                        )
                        for _, row in df_filtered.iterrows():
                            code = str(row.get("code", ""))
                            vr = rt_vr_lookup.get(code)
                            if vr is not None and not pd.isna(vr) and vr > 0:
                                vol_ratio_map[code] = float(vr)
                        logger.info(
                            "[EOD-RT] Realtime vol_ratio loaded for %d/%d candidates from realtime_list",
                            len(vol_ratio_map), len(df_filtered),
                        )
        except Exception as e:
            logger.debug("[EOD-RT] Failed to load realtime vol_ratio: %s", e)

        if is_after_close and "volume" in df_filtered.columns:
            logger.info("[EOD-RT] Post-close mode: computing volume ratio from 5-day avg")
            rt_vol = pd.to_numeric(df_filtered["volume"], errors="coerce")
            keep_idx: list = []
            for idx, row in df_filtered.iterrows():
                code = str(row.get("code", ""))
                if code in vol_ratio_map:
                    vr_rt = vol_ratio_map[code]
                    if 2.5 <= vr_rt <= 4.0:
                        keep_idx.append(idx)
                    else:
                        logger.debug(f"[EOD-RT] {code} realtime vol_ratio={vr_rt:.2f} out of [2.5,4], dropped")
                    continue
                today_vol = float(rt_vol.get(idx, 0) or 0)
                if today_vol <= 0:
                    keep_idx.append(idx)
                    continue
                try:
                    df_daily_vr, _src = self._data_manager.get_daily_data(code, days=6)
                    if df_daily_vr is None or len(df_daily_vr) < 2:
                        keep_idx.append(idx)
                        continue
                    vol_col = self._first_col(df_daily_vr, "vol", "volume", "成交量")
                    if vol_col is None:
                        keep_idx.append(idx)
                        continue
                    hist_vol = pd.to_numeric(df_daily_vr[vol_col], errors="coerce").iloc[:-1]
                    avg_5d = hist_vol.mean()
                    if avg_5d <= 0 or pd.isna(avg_5d):
                        keep_idx.append(idx)
                        continue
                    vol_ratio = today_vol / avg_5d
                    vol_ratio_map[code] = vol_ratio
                    if 2.5 <= vol_ratio <= 4.0:
                        keep_idx.append(idx)
                    else:
                        logger.debug(f"[EOD-RT] {code} vol_ratio={vol_ratio:.2f} out of [2.5,4], dropped")
                except Exception as e:
                    logger.debug(f"[EOD-RT] vol_ratio calc error for {code}: {e}")
                    keep_idx.append(idx)
            before_cnt = len(df_filtered)
            df_filtered = df_filtered.loc[keep_idx]
            logger.info(f"[EOD-RT] Volume ratio filter: {before_cnt} -> {len(df_filtered)} stocks")
        elif not is_after_close and "volume" in df_filtered.columns:
            if not vol_ratio_map:
                logger.info("[EOD-RT] Intraday: realtime_list vol_ratio unavailable, computing from 5-day avg")
                rt_vol = pd.to_numeric(df_filtered["volume"], errors="coerce")
                for idx, row in df_filtered.iterrows():
                    code = str(row.get("code", ""))
                    if code in vol_ratio_map:
                        continue
                    today_vol = float(rt_vol.get(idx, 0) or 0)
                    if today_vol <= 0:
                        continue
                    try:
                        df_hist, _src = self._data_manager.get_daily_data(code, days=6)
                        if df_hist is None or len(df_hist) < 2:
                            continue
                        hvc = self._first_col(df_hist, "vol", "volume", "成交量")
                        if hvc is None:
                            continue
                        hist_vol = pd.to_numeric(df_hist[hvc], errors="coerce").iloc[:-1]
                        avg_5d = hist_vol.mean()
                        if pd.isna(avg_5d) or avg_5d <= 0:
                            continue
                        vr = self._calc_volume_ratio(float(today_vol), float(avg_5d))
                        if vr > 0:
                            vol_ratio_map[code] = vr
                    except Exception:
                        continue
                logger.info(
                    "[EOD-RT] Intraday vol_ratio computed for %d/%d candidates",
                    len(vol_ratio_map), len(df_filtered),
                )
            else:
                logger.info(
                    "[EOD-RT] Intraday mode: using %d realtime vol_ratio values from realtime_list",
                    len(vol_ratio_map),
                )

        if df_filtered.empty:
            return []

        # Compute 60d change for candidate stocks
        change_60d_map: Dict[str, float] = {}
        tushare_api = self._get_tushare_api()
        if tushare_api:
            try:
                candidate_codes = [str(row.get("code", "")) for _, row in df_filtered.iterrows()]
                from src.core.trading_calendar import get_last_trading_day as _get_ltd_60
                now_sh_60 = datetime.now(ZoneInfo("Asia/Shanghai"))
                td_60 = _get_ltd_60("cn", now_sh_60.date())
                if td_60 is not None:
                    td_str = td_60.strftime("%Y%m%d")
                    start_60 = (pd.Timestamp(td_str) - pd.Timedelta(days=120)).strftime("%Y%m%d")
                    df_cal = tushare_api.trade_cal(exchange="SSE", start_date=start_60, end_date=td_str)
                    if df_cal is not None and not df_cal.empty:
                        df_cal.columns = [c.lower() for c in df_cal.columns]
                        df_cal = df_cal[df_cal["is_open"] == 1].sort_values("cal_date")
                        dates_60 = df_cal["cal_date"].tolist()
                        if td_str in dates_60:
                            idx_60 = dates_60.index(td_str)
                        else:
                            idx_60 = len(dates_60) - 1
                        if idx_60 >= 60:
                            date_60d_ago = dates_60[idx_60 - 60]
                            df_60d = tushare_api.daily(trade_date=date_60d_ago)
                            if df_60d is not None and not df_60d.empty:
                                df_60d.columns = [c.lower() for c in df_60d.columns]
                                close_60d_lookup = dict(
                                    zip(
                                        df_60d["ts_code"].str.split(".").str[0],
                                        pd.to_numeric(df_60d["close"], errors="coerce"),
                                    )
                                )
                                for _, row in df_filtered.iterrows():
                                    code = str(row.get("code", ""))
                                    cur_price = float(row.get("price", 0) or 0)
                                    old_close = close_60d_lookup.get(code)
                                    if old_close and old_close > 0 and cur_price > 0:
                                        change_60d_map[code] = (cur_price - old_close) / old_close * 100
                                logger.info(
                                    f"[EOD-RT] 60d change computed for {len(change_60d_map)} candidates"
                                )
                            else:
                                logger.debug("[EOD-RT] Not enough trading days for 60d change")
            except Exception as e:
                logger.warning(f"[EOD-RT] Failed to compute 60d change: {e}")

        # Build ScreenedStock list
        candidates_pre: list = []
        for _, row in df_filtered.iterrows():
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            price = float(row.get("price", 0) or 0)
            chg = float(row.get("calc_change_pct", 0) or 0)
            raw_tr = row.get("turnover_rate") if "turnover_rate" in df_filtered.columns else None
            if raw_tr is None or pd.isna(raw_tr):
                raw_tr = row.get("turnover", 0)
            turnover_val = float(pd.to_numeric(raw_tr, errors="coerce") or 0)
            amount_val = float(pd.to_numeric(row.get("amount", 0), errors="coerce") or 0)
            raw_mc = row.get("total_mv_yi") if "total_mv_yi" in df_filtered.columns else None
            mktcap_val = float(pd.to_numeric(raw_mc, errors="coerce") or 0) if raw_mc is not None else 0.0

            candidates_pre.append(ScreenedStock(
                code=code, name=name, price=price,
                change_pct=chg,
                volume_ratio=vol_ratio_map.get(code, 0.0),
                turnover_rate=turnover_val,
                pe=float(pd.to_numeric(row.get("pe_ttm"), errors="coerce") or 0)
                if "pe_ttm" in df_filtered.columns else 0.0,
                pb=float(pd.to_numeric(row.get("pb"), errors="coerce") or 0)
                if "pb" in df_filtered.columns else 0.0,
                market_cap=mktcap_val,
                amount=amount_val / 1e8 if amount_val else 0.0,
                change_pct_60d=change_60d_map.get(code, 0.0),
                score=0.0,
                strategies=["eod_buyback"],
            ))

        # Sector strength bonus
        _sector_top20_codes: Set[str] = set()
        _sector_top50_codes: Set[str] = set()
        try:
            from src.services.sector_strength_service import SectorStrengthService
            _eod_sector_svc = SectorStrengthService()
            _sector_top20_codes = _eod_sector_svc.get_strong_sector_codes(top_pct=0.20)
            _sector_top50_codes = _eod_sector_svc.get_strong_sector_codes(top_pct=0.50)
            logger.info(
                "[EOD-RT] Sector strength loaded: top20%%=%d codes, top50%%=%d codes",
                len(_sector_top20_codes), len(_sector_top50_codes),
            )
        except Exception as e:
            logger.warning("[EOD-RT] Sector strength data unavailable, skipping bonus: %s", e)

        # Filter consecutive up days
        from src.services.picker_strategies import EOD_BUYBACK_PARAMS as _eod_params
        max_consec = _eod_params.max_consecutive_up_days
        candidates_pre = self._filter_consecutive_up_days(candidates_pre, max_up_days=max_consec)
        logger.info(
            f"[EOD-RT] After consecutive-up-days filter (max={max_consec}): {len(candidates_pre)} candidates"
        )

        # Score candidates
        logger.info(f"[EOD-RT] Scoring {len(candidates_pre)} candidates with today limit-up signal...")
        final: list = []
        for s in candidates_pre:
            try:
                base_score = (
                    10.0
                    + min(s.change_pct, 6.0) * 2
                    + (5.0 if 100 <= s.market_cap <= 200 else 0.0)
                )
                today_change = s.change_pct
                if today_change >= 5.5:
                    base_score += 15.0
                    logger.debug("[EOD] %s strong band momentum (%.1f%%), +15 pts", s.code, today_change)
                elif today_change >= 4.5:
                    base_score += 8.0
                    logger.debug("[EOD] %s moderate band momentum (%.1f%%), +8 pts", s.code, today_change)

                if _sector_top20_codes or _sector_top50_codes:
                    if s.code in _sector_top20_codes:
                        base_score += 10.0
                        logger.debug("[EOD] %s sector top 20%%, +10 pts", s.code)
                    elif s.code in _sector_top50_codes:
                        base_score += 5.0
                        logger.debug("[EOD] %s sector top 50%%, +5 pts", s.code)
                    else:
                        base_score -= 10.0
                        logger.debug("[EOD] %s sector bottom 50%%, -10 pts", s.code)

                s.score = base_score
                final.append(s)
            except Exception as e:
                logger.debug(f"[EOD-RT] scoring error for {s.code}: {e}")

        logger.info(f"[EOD-RT] Final eod_buyback candidates: {len(final)}")

        # Deduplicate by code
        seen_codes: set = set()
        deduped: list = []
        for s in final:
            if s.code not in seen_codes:
                seen_codes.add(s.code)
                deduped.append(s)
        if len(deduped) < len(final):
            logger.info(f"[EOD-RT] Deduplicated: {len(final)} -> {len(deduped)} candidates")
        return deduped

    def _has_recent_limit_up_check(self, code: str, days: int = 20) -> bool:
        """Check if stock had limit-up within recent N trading days.
        NOTE: Currently unused. Retained for potential future strategies.
        """
        try:
            if not self._data_manager:
                return False
            df, _src = self._data_manager.get_daily_data(code, days=days)
            if df is None or df.empty:
                return False
            limit_pct = LIMIT_UP_PCT_KC_CY if is_kc_cy_stock(code) else LIMIT_UP_PCT_MAIN
            chg_col = self._first_col(df, "pct_chg", "涨跌幅", "change_pct")
            if chg_col is None:
                return False
            pct = pd.to_numeric(df[chg_col], errors="coerce")
            return bool((pct >= limit_pct).any())
        except Exception as e:
            logger.debug(f"[EOD-RT] _has_recent_limit_up_check error for {code}: {e}")
            return False
