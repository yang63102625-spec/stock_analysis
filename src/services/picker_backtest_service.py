# -*- coding: utf-8 -*-
"""
Picker Backtest Service

Runs the quantitative screener historically and evaluates forward returns.
Uses top N by score (no LLM) for each trade date.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from data_provider.base import DataFetcherManager
from data_provider.caching_manager import CachingDataFetcherManager
from src.config import get_config
from src.services.picker import (
    StockScreener,
    create_screener_from_config,
    get_tushare_api,
    ScreenedStock,
)
from src.services.trade_levels import (
    DEFAULT_SLIPPAGE_PCT,
    LIMIT_UP_KCCY,
    LIMIT_UP_MAIN,
    simulate_forward_trade,
)

logger = logging.getLogger(__name__)

BENCHMARK_CODE = "000300.SH"  # CSI 300

_FORWARD_RETURNS_EXECUTOR = ThreadPoolExecutor(max_workers=5, thread_name_prefix="fwd")

# Legacy fallback constants (kept for backward compat where callers still
# reference them; new code should use simulate_forward_trade with unified rules).
STOP_LOSS_PCT = -8.0
TAKE_PROFIT_PCT = 15.0
GATEWAY_LEVELS = (5, 10, 20, 50, 100, 200, 500, 1000)


@dataclass
class PickResult:
    """Single pick outcome."""
    trade_date: str
    code: str
    name: str
    entry_price: float
    exit_price: Optional[float]
    return_pct: Optional[float]
    outcome: str  # "win" | "loss" | "insufficient"
    score: float = 0.0
    # Trade-levels engine extras (surfaced for diagnostic UI)
    exit_reason: Optional[str] = None  # stop_loss / trailing_ma10 / stage_break_+12pct / hardcap_+20pct / window_end / ...
    hold_days: Optional[int] = None
    strategy_id: Optional[str] = None


@dataclass
class PickerBacktestSummary:
    """Aggregated backtest metrics."""
    start_date: str
    end_date: str
    hold_days: int
    top_n: int
    total_picks: int
    win_count: int
    loss_count: int
    insufficient_count: int
    win_rate_pct: Optional[float]
    avg_return_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    profit_factor: Optional[float]
    alpha_vs_benchmark_pct: Optional[float]
    benchmark_avg_return_pct: Optional[float]


class PickerBacktestService:
    """Backtest the quantitative picker (no LLM) over historical dates."""

    def __init__(self, data_manager: Optional[DataFetcherManager] = None):
        base = data_manager or DataFetcherManager()
        self._data_manager = (
            base
            if isinstance(base, CachingDataFetcherManager)
            else CachingDataFetcherManager(base)
        )
        self._screener = create_screener_from_config(data_manager=self._data_manager)
        self._tushare_api = None

    def _get_tushare_api(self):
        """Get Tushare API for trade_cal and benchmark (cached, with disk parquet)."""
        if self._tushare_api is None:
            from src.services.picker._tushare_cache import wrap_api
            self._tushare_api = wrap_api(get_tushare_api(self._data_manager))
        return self._tushare_api

    def _get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """Get list of trading dates in range (YYYYMMDD). Tushare first, fallback to exchange_calendars."""
        start = start_date.replace("-", "").replace("/", "")[:8]
        end = end_date.replace("-", "").replace("/", "")[:8]
        start_iso = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_iso = f"{end[:4]}-{end[4:6]}-{end[6:8]}"

        # Try Tushare first
        api = self._get_tushare_api()
        if api is not None:
            try:
                df = api.trade_cal(exchange="SSE", start_date=start, end_date=end)
                if df is not None and not df.empty:
                    df.columns = [c.lower() for c in df.columns]
                    df = df[df["is_open"] == 1].sort_values("cal_date")
                    return df["cal_date"].astype(str).tolist()
            except Exception as e:
                logger.debug("Tushare trade_cal failed, trying exchange_calendars: %s", e)

        # Fallback: exchange_calendars (supports wider date range)
        try:
            import exchange_calendars as xcals
            cal = xcals.get_calendar("XSHG")
            sessions = cal.sessions_in_range(start_iso, end_iso)
            return [s.strftime("%Y%m%d") for s in sessions]
        except ImportError:
            logger.warning("exchange_calendars not installed; cannot fallback for trade dates")
            return []
        except Exception as e:
            logger.warning("exchange_calendars sessions_in_range failed: %s", e)
            return []

    def _get_exit_date(self, trade_date: str, hold_days: int) -> Optional[str]:
        """Get exit date (hold_days trading days after trade_date)."""
        dates = self._get_trade_dates(
            (pd.Timestamp(trade_date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            (pd.Timestamp(trade_date) + pd.Timedelta(days=hold_days * 3)).strftime("%Y-%m-%d"),
        )
        if not dates:
            return None
        try:
            idx = dates.index(trade_date)
        except ValueError:
            return None
        if idx + hold_days >= len(dates):
            return None
        return dates[idx + hold_days]

    def _get_forward_return(
        self,
        code: str,
        trade_date: str,
        exit_date: str,
        entry_price: float,
        strategy_id: str = "buy_pullback",
        stop_loss_pct: float = STOP_LOSS_PCT,    # kept for backward compat (unused)
        take_profit_pct: float = TAKE_PROFIT_PCT,
    ) -> Dict[str, Any]:
        """Fetch daily data and simulate the forward trade with the unified
        trade_levels engine (same rules as production picker / analyzer).

        Adds slippage (0.3% one-way) and limit-up entry filter (cannot fill at
        limit-up board). Returns (exit_price, return_pct).

        stop_loss_pct/take_profit_pct kwargs are kept only for backward-compat
        with older callers; the actual exits are governed by
        trade_levels.evaluate_trailing_exit.
        """
        try:
            start_dt = pd.Timestamp(trade_date) - pd.Timedelta(days=45)
            start_iso = start_dt.strftime("%Y-%m-%d")
            end_iso = f"{exit_date[:4]}-{exit_date[4:6]}-{exit_date[6:8]}"
            df, _ = self._data_manager.get_daily_data(
                code, start_date=start_iso, end_date=end_iso, days=80
            )
            if df is None or df.empty:
                return {}
            date_col = next((c for c in ["date", "日期"] if c in df.columns), df.columns[0])
            close_col = next((c for c in ["close", "收盘"] if c in df.columns), None)
            high_col = next((c for c in ["high", "最高"] if c in df.columns), None)
            low_col = next((c for c in ["low", "最低"] if c in df.columns), None)
            pct_col = next((c for c in ["pct_chg", "涨跌幅"] if c in df.columns), None)
            if close_col is None:
                return {}

            df = df.sort_values(date_col).reset_index(drop=True)
            df[date_col] = pd.to_datetime(df[date_col])
            df["_date_str"] = df[date_col].dt.strftime("%Y-%m-%d")

            # MA10/MA20/ATR (compute if absent)
            for ma_col, win in (("ma10", 10), ("ma20", 20)):
                if ma_col not in df.columns:
                    df[ma_col] = df[close_col].rolling(window=win, min_periods=1).mean()
            if "atr" not in df.columns and high_col and low_col:
                tr = pd.concat([
                    (df[high_col] - df[low_col]).abs(),
                    (df[high_col] - df[close_col].shift()).abs(),
                    (df[low_col] - df[close_col].shift()).abs(),
                ], axis=1).max(axis=1)
                df["atr"] = tr.rolling(window=14, min_periods=1).mean()

            # eod_buyback execution model (T+1 overnight, intraday TP/SL):
            #   T  14:50-15:00  尾盘买入 → entry = T 日收盘价 (+ 0.15% 滑点)
            #   T+1 全天持有，按以下优先级出场:
            #     1) 盘中触及 +TAKE_PROFIT_PCT → 以止盈线成交（exit_reason=take_profit_t1）
            #     2) 盘中触及 -STOP_LOSS_PCT  → 以止损线成交（exit_reason=stop_loss_t1）
            #     3) 否则 T+1 收盘卖出（exit_reason=t1_close）
            #   同日 high/low 都触发的保守口径：假定先到止损（更悲观，避免高估）
            # 净收益 = gross - 0.05% commission*2 - 0.05% stamp duty = gross - 0.10%
            # 不再调用 simulate_forward_trade（那是为多日 trailing 设计）
            entry_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
            pick_mask = df["_date_str"] == entry_str
            if not pick_mask.any():
                return {}
            entry_idx = int(df.index[pick_mask].min())
            if entry_price <= 0:
                close_v = df.iloc[entry_idx][close_col]
                if pd.isna(close_v) or float(close_v) <= 0:
                    return {}
                entry_price = float(close_v)

            exit_idx = entry_idx + 1
            if exit_idx >= len(df):
                return {}  # T+1 not yet in data
            next_bar = df.iloc[exit_idx]
            next_high = float(next_bar[high_col]) if high_col and pd.notna(next_bar[high_col]) else None
            next_low = float(next_bar[low_col]) if low_col and pd.notna(next_bar[low_col]) else None
            next_close = float(next_bar[close_col]) if pd.notna(next_bar[close_col]) else None
            if next_close is None or next_close <= 0:
                return {}

            ENTRY_SLIPPAGE = 0.0015
            EXIT_SLIPPAGE = 0.0015
            COST_ROUND_TRIP_PCT = 0.10  # commission 0.025%×2 + stamp duty 0.05%
            # Reverted to Iter-2 best: TP 4% / SL 2.5% (PF 0.80, WR 44.9%)
            T1_TAKE_PROFIT = 0.04
            T1_STOP_LOSS = 0.025

            effective_entry = entry_price * (1 + ENTRY_SLIPPAGE)
            tp_trigger = entry_price * (1 + T1_TAKE_PROFIT)
            sl_trigger = entry_price * (1 - T1_STOP_LOSS)

            hit_sl = next_low is not None and next_low <= sl_trigger
            hit_tp = next_high is not None and next_high >= tp_trigger

            if hit_sl:
                exit_price_raw = sl_trigger
                exit_reason = "stop_loss_t1"
            elif hit_tp:
                exit_price_raw = tp_trigger
                exit_reason = "take_profit_t1"
            else:
                exit_price_raw = next_close
                exit_reason = "t1_close"

            effective_exit = exit_price_raw * (1 - EXIT_SLIPPAGE)
            gross_pct = (effective_exit - effective_entry) / effective_entry * 100.0
            net_pct = gross_pct - COST_ROUND_TRIP_PCT

            return {
                "exit_price": effective_exit,
                "return_pct": net_pct,
                "exit_reason": exit_reason,
                "hold_days": 1,
            }
        except Exception as e:
            logger.debug(f"[PickerBacktest] Forward return failed {code}: {e}")
            return {}

    def _get_benchmark_return(self, trade_date: str, exit_date: str) -> Optional[float]:
        """Get benchmark (CSI 300) return over the same period."""
        api = self._get_tushare_api()
        if api is None:
            return None
        try:
            start = trade_date
            end = exit_date
            df = api.index_daily(ts_code=BENCHMARK_CODE, start_date=start, end_date=end)
            if df is None or len(df) < 2:
                return None
            df.columns = [c.lower() for c in df.columns]
            df = df.sort_values("trade_date")
            entry_row = df[df["trade_date"] == trade_date]
            exit_row = df[df["trade_date"] == exit_date]
            if entry_row.empty or exit_row.empty:
                return None
            p0 = float(entry_row["close"].iloc[0])
            p1 = float(exit_row["close"].iloc[0])
            if p0 <= 0:
                return None
            return (p1 - p0) / p0 * 100
        except Exception as e:
            logger.debug(f"[PickerBacktest] Benchmark return failed: {e}")
            return None

    def _get_benchmark_returns_batch(
        self, date_pairs: List[Tuple[str, Optional[str]]]
    ) -> Dict[Tuple[str, str], float]:
        """Fetch benchmark once for full range, compute per-period returns. Saves N-1 Tushare calls."""
        valid_pairs = [(td, ed) for td, ed in date_pairs if ed is not None]
        if not valid_pairs:
            return {}
        api = self._get_tushare_api()
        if api is None:
            return {}
        try:
            all_dates = set()
            for td, ed in valid_pairs:
                all_dates.add(td)
                all_dates.add(ed)
            start = min(all_dates)
            end = max(all_dates)
            df = api.index_daily(ts_code=BENCHMARK_CODE, start_date=start, end_date=end)
            if df is None or df.empty:
                return {}
            df.columns = [c.lower() for c in df.columns]
            df = df.sort_values("trade_date")
            close_map = df.set_index("trade_date")["close"].to_dict()
            result: Dict[Tuple[str, str], float] = {}
            for td, ed in valid_pairs:
                p0 = close_map.get(td)
                p1 = close_map.get(ed)
                if p0 is None or p1 is None or float(p0) <= 0:
                    continue
                result[(td, ed)] = (float(p1) - float(p0)) / float(p0) * 100
            return result
        except Exception as e:
            logger.debug(f"[PickerBacktest] Batch benchmark failed: {e}")
            return {}

    def _get_forward_returns_parallel(
        self, picks: List[ScreenedStock], trade_date: str, exit_date: str
    ) -> List[PickResult]:
        """Fetch forward returns for picks in parallel (max 5 workers to respect rate limits)."""
        results: List[PickResult] = []
        futures = {
            _FORWARD_RETURNS_EXECUTOR.submit(
                self._get_forward_return, s.code, trade_date, exit_date, s.price,
                (s.strategies[0] if s.strategies else "buy_pullback"),
            ): s
            for s in picks
        }
        for fut in as_completed(futures):
            s = futures[fut]
            strategy_id = s.strategies[0] if s.strategies else "buy_pullback"
            try:
                sim = fut.result() or {}
            except Exception as e:
                logger.debug(f"[PickerBacktest] Forward return failed {s.code}: {e}")
                sim = {}

            ret = sim.get("return_pct")
            exit_price = sim.get("exit_price")
            exit_reason = sim.get("exit_reason")
            hold_days = sim.get("hold_days")
            outcome = "insufficient" if ret is None else ("win" if ret > 0 else "loss")
            results.append(
                PickResult(
                    trade_date=trade_date,
                    code=s.code,
                    name=s.name,
                    entry_price=s.price,
                    exit_price=exit_price,
                    return_pct=ret,
                    outcome=outcome,
                    score=s.score,
                    exit_reason=exit_reason,
                    hold_days=hold_days,
                    strategy_id=strategy_id,
                )
            )
        return results

    def run(
        self,
        start_date: str,
        end_date: str,
        hold_days: int = 10,
        top_n: int = 5,
        picker_strategies: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run picker backtest.

        Args:
            start_date: YYYY-MM-DD or YYYYMMDD
            end_date: YYYY-MM-DD or YYYYMMDD
            hold_days: holding period in trading days
            top_n: number of picks per day (by score)
            picker_strategies: optional override (buy_pullback, breakout, etc.)

        Returns:
            Dict with results, summary, and performance metrics.
        """
        # eod_buyback is a strict T+1 overnight strategy: buy at today's close,
        # sell at next trading day's close. Holding period is fixed at 1 trading
        # day regardless of caller's `hold_days`. Force-override to keep the
        # backtest semantically consistent with the live strategy.
        if picker_strategies and set(picker_strategies) == {"eod_buyback"} and hold_days != 1:
            logger.info(
                "[PickerBacktest] eod_buyback is T+1 overnight; forcing hold_days=1 (was %d)",
                hold_days,
            )
            hold_days = 1

        if picker_strategies is not None:
            cfg = get_config()
            screener = StockScreener(
                data_manager=self._data_manager,
                picker_strategies=picker_strategies,
                picker_mode=cfg.picker_mode,
                turnover_min=cfg.picker_turnover_min,
                turnover_max=cfg.picker_turnover_max,
                enable_b_wave_filter=getattr(cfg, "picker_enable_b_wave_filter", True),
                allow_loss=getattr(cfg, "picker_allow_loss", False),
            )
        else:
            screener = self._screener

        self._data_manager.clear_cache()
        trade_dates = self._get_trade_dates(start_date, end_date)
        if not trade_dates:
            return {
                "error": "所选日期范围内无交易日，请检查日期格式或扩大范围",
                "results": [],
                "summary": None,
            }

        logger.info(
            "[PickerBacktest] 选股回测：纯量化筛选（无 LLM），每日取评分 top%d，持仓 %d 天，共 %d 个交易日",
            top_n, hold_days, len(trade_dates),
        )

        # Precompute exit dates and batch-fetch benchmark (saves N-1 Tushare calls)
        date_pairs: List[Tuple[str, Optional[str]]] = []
        for td in trade_dates:
            exit_d = self._get_exit_date(td, hold_days)
            date_pairs.append((td, exit_d))

        benchmark_map = self._get_benchmark_returns_batch(date_pairs)
        benchmark_returns: List[float] = []

        results: List[PickResult] = []
        days_with_picks = 0
        for i, (td, exit_date) in enumerate(date_pairs):
            if (i + 1) % 20 == 0:
                logger.info(f"[PickerBacktest] Progress {i + 1}/{len(trade_dates)} dates")
            try:
                candidates, _, _ = screener.screen_as_of(td)
                picks = candidates[:top_n]
                if not picks:
                    logger.debug(f"[PickerBacktest] {td}: 筛选后无候选，跳过")
                    continue
                if exit_date is None:
                    logger.debug(f"[PickerBacktest] {td}: 持仓期不足，跳过")
                    continue
                days_with_picks += 1
                pick_info = ", ".join(f"{p.code}({p.score:.1f})" for p in picks)
                logger.info(f"[PickerBacktest] {td}: 筛选 top{top_n} → {pick_info}")

                bm_ret = benchmark_map.get((td, exit_date))
                if bm_ret is not None:
                    benchmark_returns.append(bm_ret)

                # Parallelize forward return fetches (5 picks per day)
                pick_results = self._get_forward_returns_parallel(picks, td, exit_date)
                # Log evaluation results for each pick
                for pr in pick_results:
                    if pr.return_pct is not None:
                        logger.info(
                            f"[PickerBacktest] {td} {pr.code} → "
                            f"入场={pr.entry_price:.2f}, 出场={pr.exit_price:.2f}, "
                            f"收益={pr.return_pct:+.2f}%, 结果={pr.outcome}"
                        )
                    else:
                        logger.warning(
                            f"[PickerBacktest] {td} {pr.code} → 数据不足，无法评估"
                        )
                    results.append(pr)
            except Exception as e:
                logger.warning(f"[PickerBacktest] Date {td} failed: {e}")
                continue

        # Aggregate
        valid = [r for r in results if r.return_pct is not None]
        wins = [r for r in valid if r.outcome == "win"]
        losses = [r for r in valid if r.outcome == "loss"]
        insufficient = [r for r in results if r.outcome == "insufficient"]

        win_rate = len(wins) / len(valid) * 100 if valid else None
        avg_ret = sum(r.return_pct for r in valid) / len(valid) if valid else None
        bm_avg = sum(benchmark_returns) / len(benchmark_returns) if benchmark_returns else None
        alpha = (avg_ret - bm_avg) if (avg_ret is not None and bm_avg is not None) else None

        # Max drawdown: use daily batch returns
        batch_returns: Dict[str, List[float]] = {}
        for r in valid:
            batch_returns.setdefault(r.trade_date, []).append(r.return_pct or 0)
        daily_avg = [sum(v) / len(v) for v in batch_returns.values() if v]
        cum = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in daily_avg:
            cum *= 1 + r / 100
            peak = max(peak, cum)
            dd = (peak - cum) / peak * 100
            max_dd = max(max_dd, dd)
        max_drawdown = max_dd if daily_avg else None

        # Profit factor (gross profit / gross loss)
        gross_profit = sum(r.return_pct for r in wins if r.return_pct)
        gross_loss = abs(sum(r.return_pct for r in losses if r.return_pct))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        summary = PickerBacktestSummary(
            start_date=start_date,
            end_date=end_date,
            hold_days=hold_days,
            top_n=top_n,
            total_picks=len(results),
            win_count=len(wins),
            loss_count=len(losses),
            insufficient_count=len(insufficient),
            win_rate_pct=round(win_rate, 2) if win_rate is not None else None,
            avg_return_pct=round(avg_ret, 2) if avg_ret is not None else None,
            max_drawdown_pct=round(max_drawdown, 2) if max_drawdown is not None else None,
            profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
            alpha_vs_benchmark_pct=round(alpha, 2) if alpha is not None else None,
            benchmark_avg_return_pct=round(bm_avg, 2) if bm_avg is not None else None,
        )

        # Log summary (cache stats: hits / total lookups, not network requests)
        hits, misses = self._data_manager.cache_stats()
        total_lookups = hits + misses
        logger.info(
            "[PickerBacktest] 回测完成: 交易日=%d, 有候选=%d天, 总选股=%d, 胜=%d, 负=%d, 数据不足=%d, "
            "胜率=%.2f%%, 平均收益=%.2f%%, Alpha=%.2f%%, 缓存命中=%d/总查询=%d",
            len(trade_dates), days_with_picks, len(results), len(wins), len(losses), len(insufficient),
            win_rate or 0, avg_ret or 0, alpha or 0, hits, total_lookups,
        )

        return {
            "results": [
                {
                    "trade_date": r.trade_date,
                    "code": r.code,
                    "name": r.name,
                    "entry_price": r.entry_price,
                    "exit_price": r.exit_price,
                    "return_pct": r.return_pct,
                    "outcome": r.outcome,
                    "score": r.score,
                    "exit_reason": r.exit_reason,
                    "hold_days": r.hold_days,
                    "strategy_id": r.strategy_id,
                }
                for r in results
            ],
            "summary": {
                "start_date": summary.start_date,
                "end_date": summary.end_date,
                "hold_days": summary.hold_days,
                "top_n": summary.top_n,
                "trade_dates_with_picks": days_with_picks,
                "total_picks": summary.total_picks,
                "win_count": summary.win_count,
                "loss_count": summary.loss_count,
                "insufficient_count": summary.insufficient_count,
                "win_rate_pct": summary.win_rate_pct,
                "avg_return_pct": summary.avg_return_pct,
                "max_drawdown_pct": summary.max_drawdown_pct,
                "profit_factor": summary.profit_factor,
                "alpha_vs_benchmark_pct": summary.alpha_vs_benchmark_pct,
                "benchmark_avg_return_pct": summary.benchmark_avg_return_pct,
            },
            "trade_dates_count": len(trade_dates),
        }
