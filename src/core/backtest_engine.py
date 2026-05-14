# -*- coding: utf-8 -*-
"""Backtest evaluation engine v3 (AI-plan execution).

Strict execution model: each historical analysis carries its own trade plan
(`ideal_buy`, `stop_loss`, `take_profit`). The engine replays those levels
against forward daily bars and reports what would have happened. No external
strategy override, no synthetic trailing rules — what the AI told the user
to do is what gets simulated.

Key choices (see project discussion 2026-05-14):
- Fill rate, win rate and expectancy are reported as separate layers; signals
  that never get filled are NOT counted into win/loss but show up in `fill_rate`.
- When a single bar straddles both the stop-loss and take-profit (we can't see
  intraday order on daily bars), the trade is closed at the stop (conservative)
  AND tagged ambiguous so users can audit.
- A-share frictions: 0.05% slippage on entry/exit + 0.025% commission both ways
  + 0.05% stamp duty on the sell side. Configurable via EvaluationConfig.
- Prior-day limit-up filter: if the previous bar was a one-character limit-up
  (close == high == low and pct_chg >= 9.8%), buy orders that day are recorded
  as `not_filled_limit_up` because retail can't get filled in queue-based
  matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional, Protocol, Sequence

from src.core._backtest_aggregation_mixin import _AggregationMixin

OVERALL_SENTINEL_CODE = "__overall__"

LONG_SIGNALS = ("STRONG_BUY", "BUY")
AVOID_SIGNALS = ("AVOID", "STRONG_AVOID")

# Default A-share frictions (in fractions, NOT percent).
DEFAULT_SLIPPAGE = 0.0005          # 5 bps each side
DEFAULT_COMMISSION = 0.00025       # 2.5 bps each side
DEFAULT_STAMP_DUTY_SELL = 0.0005   # 5 bps on sell only

# Limit-up threshold for the prior-day filter.
LIMIT_UP_PCT = 9.8


class DailyBarLike(Protocol):
    date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]


class BacktestResultLike(Protocol):
    """Stored row protocol used by `compute_summary` for aggregation."""

    eval_status: str
    position_recommendation: Optional[str]
    outcome: Optional[str]
    direction_correct: Optional[bool]
    stock_return_pct: Optional[float]
    simulated_return_pct: Optional[float]
    operation_advice: Optional[str]
    signal_score_at_eval: Optional[int]
    buy_signal_at_eval: Optional[str]
    market_environment_at_eval: Optional[str]
    risk_reward_at_eval: Optional[float]
    strategy_id: Optional[str]
    exit_reason: Optional[str]
    hold_days: Optional[int]
    # v3 additions (Optional so legacy rows still satisfy Protocol)
    entry_status: Optional[str]
    r_multiple: Optional[float]
    mae_pct: Optional[float]
    mfe_pct: Optional[float]


@dataclass(frozen=True)
class EvaluationConfig:
    eval_window_days: int
    slippage: float = DEFAULT_SLIPPAGE
    commission: float = DEFAULT_COMMISSION
    stamp_duty_sell: float = DEFAULT_STAMP_DUTY_SELL
    apply_limit_up_filter: bool = True
    # Kept for backward compat with stored legacy rows; current engine ignores it.
    neutral_band_pct: float = 2.0


@dataclass(frozen=True)
class AnalysisSnapshot:
    """Snapshot of AnalysisHistory fields needed for v3 evaluation."""

    code: str
    operation_advice: Optional[str]
    signal_score: Optional[int]
    buy_signal: Optional[str]
    market_environment: Optional[str]
    strategy_id: str
    ideal_buy: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward: Optional[float]
    position_pct: Optional[float]
    trend_score: Optional[int]
    bias_score: Optional[int]
    volume_score: Optional[int]
    support_score: Optional[int]
    macd_score: Optional[int]
    rsi_score: Optional[int]
    capital_flow_score: Optional[int]


@dataclass
class _ExecutionTrace:
    entry_status: str = "not_filled"
    entry_idx: Optional[int] = None
    entry_price: Optional[float] = None
    entry_reason: str = ""
    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    ambiguous: bool = False
    max_high_after_entry: Optional[float] = None
    min_low_after_entry: Optional[float] = None


class BacktestEngine(_AggregationMixin):
    """v3 long-only daily-bar engine that replays the AI's own trade plan.

    Per-trade execution lives in this class; cross-trade aggregation lives in
    `_AggregationMixin` (see `_backtest_aggregation_mixin.py`).
    """

    @classmethod
    def position_from_signal(cls, buy_signal: Optional[str]) -> str:
        if not buy_signal:
            return "cash"
        return "long" if buy_signal.upper() in LONG_SIGNALS else "cash"

    @classmethod
    def direction_expected_from_signal(cls, buy_signal: Optional[str]) -> str:
        if not buy_signal:
            return "flat"
        sig = buy_signal.upper()
        if sig in LONG_SIGNALS:
            return "up"
        if sig in AVOID_SIGNALS:
            return "down"
        return "not_down"

    # ── Core single-record evaluation ────────────────────────────────────

    @classmethod
    def evaluate_single(
        cls,
        *,
        analysis: AnalysisSnapshot,
        analysis_date: date,
        start_price: float,
        forward_bars: Sequence[DailyBarLike],
        config: EvaluationConfig,
    ) -> Dict[str, Any]:
        position = cls.position_from_signal(analysis.buy_signal)
        direction_expected = cls.direction_expected_from_signal(analysis.buy_signal)

        base_meta: Dict[str, Any] = {
            "analysis_date": analysis_date,
            "operation_advice": analysis.operation_advice,
            "position_recommendation": position,
            "direction_expected": direction_expected,
            "signal_score_at_eval": analysis.signal_score,
            "buy_signal_at_eval": analysis.buy_signal,
            "market_environment_at_eval": analysis.market_environment,
            "strategy_id": analysis.strategy_id,
            "risk_reward_at_eval": analysis.risk_reward,
            "position_pct_at_eval": analysis.position_pct,
            "trend_score_at_eval": analysis.trend_score,
            "bias_score_at_eval": analysis.bias_score,
            "volume_score_at_eval": analysis.volume_score,
            "support_score_at_eval": analysis.support_score,
            "macd_score_at_eval": analysis.macd_score,
            "rsi_score_at_eval": analysis.rsi_score,
            "capital_flow_score_at_eval": analysis.capital_flow_score,
        }

        if start_price is None or start_price <= 0:
            return {**base_meta, "eval_status": "error"}

        eval_days = int(config.eval_window_days)
        if eval_days <= 0:
            raise ValueError("eval_window_days must be positive")

        if analysis.buy_signal is None:
            return {**base_meta, "eval_status": "missing_signal"}

        if len(forward_bars) < eval_days:
            return {**base_meta, "eval_status": "insufficient_data", "eval_window_days": eval_days}

        window_bars = list(forward_bars[:eval_days])
        end_close = window_bars[-1].close
        highs = [b.high for b in window_bars if b.high is not None]
        lows = [b.low for b in window_bars if b.low is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None

        stock_return_pct: Optional[float] = (
            (end_close - start_price) / start_price * 100 if end_close is not None else None
        )

        outcome, direction_correct = cls._classify_outcome(
            stock_return_pct=stock_return_pct, direction_expected=direction_expected,
        )

        # Defaults for cash positions (HOLD / AVOID): no execution, only direction outcome.
        trace = _ExecutionTrace()
        sim_return_pct: Optional[float] = 0.0 if position != "long" else None
        r_multiple: Optional[float] = None
        mae_pct: Optional[float] = None
        mfe_pct: Optional[float] = None
        hold_days: Optional[int] = None

        if position == "long":
            trace = cls._execute_plan(
                ideal_buy=analysis.ideal_buy,
                stop_loss=analysis.stop_loss,
                take_profit=analysis.take_profit,
                start_price=float(start_price),
                window_bars=window_bars,
                config=config,
            )
            if trace.entry_status == "filled" and trace.entry_price is not None and trace.exit_price is not None:
                gross = (trace.exit_price - trace.entry_price) / trace.entry_price
                fees = (
                    config.slippage * 2
                    + config.commission * 2
                    + config.stamp_duty_sell
                )
                sim_return_pct = (gross - fees) * 100
                if analysis.stop_loss is not None and trace.entry_price > analysis.stop_loss:
                    risk_per_share = trace.entry_price - float(analysis.stop_loss)
                    if risk_per_share > 0:
                        r_multiple = round(
                            (trace.exit_price - trace.entry_price) / risk_per_share, 4
                        )
                if trace.entry_idx is not None and trace.exit_idx is not None:
                    hold_days = trace.exit_idx - trace.entry_idx
                if trace.max_high_after_entry is not None:
                    mfe_pct = (trace.max_high_after_entry - trace.entry_price) / trace.entry_price * 100
                if trace.min_low_after_entry is not None:
                    mae_pct = (trace.min_low_after_entry - trace.entry_price) / trace.entry_price * 100
            else:
                # Not filled: still report an explicit return of 0 so aggregations
                # can distinguish "didn't trade" from "missing data".
                sim_return_pct = 0.0

        # Legacy target-hit diagnostics (kept for backward-compatibility columns).
        hit_sl, hit_tp, first_hit, first_hit_date, first_hit_days = cls._target_hit_diagnostics(
            position=position,
            stop_loss=analysis.stop_loss,
            take_profit=analysis.take_profit,
            window_bars=window_bars,
        )

        return {
            **base_meta,
            "eval_window_days": eval_days,
            "eval_status": "completed",
            "start_price": start_price,
            "end_close": end_close,
            "max_high": max_high,
            "min_low": min_low,
            "stock_return_pct": stock_return_pct,
            "direction_correct": direction_correct,
            "outcome": outcome,
            "stop_loss": analysis.stop_loss,
            "take_profit": analysis.take_profit,
            "hit_stop_loss": hit_sl,
            "hit_take_profit": hit_tp,
            "first_hit": first_hit,
            "first_hit_date": first_hit_date,
            "first_hit_trading_days": first_hit_days,
            # v3: AI-plan execution
            "entry_status": trace.entry_status,
            "simulated_entry_price": trace.entry_price,
            "simulated_exit_price": trace.exit_price,
            "simulated_exit_reason": trace.exit_reason or ("not_filled" if position == "long" else "cash"),
            "simulated_return_pct": sim_return_pct,
            "exit_reason": trace.exit_reason or ("not_filled" if position == "long" else None),
            "hold_days": hold_days,
            "r_multiple": r_multiple,
            "mae_pct": round(mae_pct, 4) if mae_pct is not None else None,
            "mfe_pct": round(mfe_pct, 4) if mfe_pct is not None else None,
        }

    # ── Trade execution (single AI plan, daily-bar replay) ──────────────

    @classmethod
    def _execute_plan(
        cls,
        *,
        ideal_buy: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        start_price: float,
        window_bars: Sequence[DailyBarLike],
        config: EvaluationConfig,
    ) -> _ExecutionTrace:
        trace = _ExecutionTrace()

        # ── Entry ──────────────────────────────────────────────────────
        if ideal_buy is not None and ideal_buy > 0:
            entry_price, entry_idx, reason = cls._scan_for_limit_entry(
                ideal_buy=float(ideal_buy),
                window_bars=window_bars,
                apply_limit_up_filter=config.apply_limit_up_filter,
            )
            if entry_price is None:
                trace.entry_status = "not_filled"
                trace.entry_reason = reason or "ideal_buy_not_touched"
                trace.exit_reason = "not_filled"
                return trace
            trace.entry_status = "filled"
            trace.entry_idx = entry_idx
            trace.entry_price = entry_price * (1 + config.slippage)
            trace.entry_reason = reason
        else:
            # No ideal_buy → fall back to "buy at the first available bar's open"
            # because the AI still issued a long signal. Same prev-day limit-up
            # filter applies for fairness.
            for idx, bar in enumerate(window_bars):
                if config.apply_limit_up_filter and cls._prev_bar_is_limit_up(window_bars, idx):
                    if idx == len(window_bars) - 1:
                        trace.entry_status = "not_filled_limit_up"
                        trace.entry_reason = "all_bars_blocked_by_limit_up"
                        trace.exit_reason = "not_filled_limit_up"
                        return trace
                    continue
                bar_open = getattr(bar, "open", None)
                price = bar_open if bar_open is not None else bar.close
                if price is None or price <= 0:
                    continue
                trace.entry_status = "filled"
                trace.entry_idx = idx
                trace.entry_price = float(price) * (1 + config.slippage)
                trace.entry_reason = "market_open" if bar_open is not None else "market_close"
                break
            if trace.entry_status != "filled":
                trace.entry_status = "not_filled"
                trace.entry_reason = "no_valid_open_bar"
                trace.exit_reason = "not_filled"
                return trace

        assert trace.entry_idx is not None and trace.entry_price is not None

        # ── Exit scan (from entry bar onwards; same-bar SL/TP allowed) ──
        running_high: Optional[float] = None
        running_low: Optional[float] = None
        for idx in range(trace.entry_idx, len(window_bars)):
            bar = window_bars[idx]
            if bar.high is not None:
                running_high = bar.high if running_high is None else max(running_high, bar.high)
            if bar.low is not None:
                running_low = bar.low if running_low is None else min(running_low, bar.low)

            sl_hit = (
                stop_loss is not None
                and bar.low is not None
                and bar.low <= float(stop_loss)
            )
            tp_hit = (
                take_profit is not None
                and bar.high is not None
                and bar.high >= float(take_profit)
            )

            # On the entry bar itself, the entry already consumed the open;
            # only consider stop/target if intraday range still extends past
            # entry price in that direction.
            if idx == trace.entry_idx:
                if sl_hit and stop_loss is not None and stop_loss >= trace.entry_price:
                    sl_hit = False
                if tp_hit and take_profit is not None and take_profit <= trace.entry_price:
                    tp_hit = False

            if sl_hit and tp_hit:
                # Conservative: assume stop hit first, but flag for audit.
                trace.exit_idx = idx
                trace.exit_price = float(stop_loss) * (1 - config.slippage)
                trace.exit_reason = "stop_loss_ambiguous"
                trace.ambiguous = True
                break
            if sl_hit:
                trace.exit_idx = idx
                trace.exit_price = float(stop_loss) * (1 - config.slippage)
                trace.exit_reason = "stop_loss"
                break
            if tp_hit:
                trace.exit_idx = idx
                trace.exit_price = float(take_profit) * (1 - config.slippage)
                trace.exit_reason = "take_profit"
                break

        if trace.exit_idx is None:
            last = window_bars[-1]
            close = last.close if last.close is not None else trace.entry_price
            trace.exit_idx = len(window_bars) - 1
            trace.exit_price = float(close) * (1 - config.slippage)
            trace.exit_reason = "time_exit"

        trace.max_high_after_entry = running_high
        trace.min_low_after_entry = running_low
        return trace

    @classmethod
    def _scan_for_limit_entry(
        cls,
        *,
        ideal_buy: float,
        window_bars: Sequence[DailyBarLike],
        apply_limit_up_filter: bool,
    ) -> tuple[Optional[float], Optional[int], str]:
        for idx, bar in enumerate(window_bars):
            if bar.low is None or bar.high is None:
                continue
            if not (bar.low <= ideal_buy <= bar.high):
                continue
            if apply_limit_up_filter and cls._prev_bar_is_limit_up(window_bars, idx):
                # Blocked: keep scanning later bars (price might come back).
                continue
            # Conservative fill: the worse of (open, ideal_buy). If open gapped
            # below the limit, we'd actually buy at the open; if it gapped above,
            # we wait for the pullback to ideal_buy.
            bar_open = getattr(bar, "open", None)
            if bar_open is not None and bar_open <= ideal_buy:
                return float(bar_open), idx, "gap_through_ideal_buy"
            return float(ideal_buy), idx, "limit_filled"
        return None, None, "ideal_buy_not_touched"

    @staticmethod
    def _prev_bar_is_limit_up(window_bars: Sequence[DailyBarLike], idx: int) -> bool:
        if idx == 0:
            return False
        prev = window_bars[idx - 1]
        if prev.close is None or prev.high is None or prev.low is None:
            return False
        # One-character limit up: open == high == low == close AND ≥ +9.8%.
        pct_chg = getattr(prev, "pct_chg", None)
        if pct_chg is None:
            return False
        try:
            return (
                float(pct_chg) >= LIMIT_UP_PCT
                and abs(prev.high - prev.low) < 1e-6
                and abs(prev.high - prev.close) < 1e-6
            )
        except (TypeError, ValueError):
            return False


    @classmethod
    def _classify_outcome(
        cls, *, stock_return_pct: Optional[float], direction_expected: str
    ) -> tuple[Optional[str], Optional[bool]]:
        if stock_return_pct is None:
            return None, None
        r = float(stock_return_pct)

        if direction_expected == "up":
            if r > 0:
                return "win", True
            if r < 0:
                return "loss", False
            return "neutral", None
        if direction_expected == "down":
            if r < 0:
                return "win", True
            if r > 0:
                return "loss", False
            return "neutral", None
        if direction_expected == "not_down":
            if r >= 0:
                return "win", True
            return "loss", False
        return "neutral", None

    @classmethod
    def _target_hit_diagnostics(
        cls,
        *,
        position: str,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        window_bars: Sequence[DailyBarLike],
    ) -> tuple[Optional[bool], Optional[bool], str, Optional[date], Optional[int]]:
        if position != "long":
            return None, None, "not_applicable", None, None
        if stop_loss is None and take_profit is None:
            return None, None, "neither", None, None

        hit_sl: Optional[bool] = None if stop_loss is None else False
        hit_tp: Optional[bool] = None if take_profit is None else False
        first_hit = "neither"
        first_hit_date: Optional[date] = None
        first_hit_days: Optional[int] = None

        for idx, bar in enumerate(window_bars, start=1):
            sl_hit = stop_loss is not None and bar.low is not None and bar.low <= stop_loss
            tp_hit = take_profit is not None and bar.high is not None and bar.high >= take_profit
            if sl_hit:
                hit_sl = True
            if tp_hit:
                hit_tp = True
            if not sl_hit and not tp_hit:
                continue
            first_hit_date = bar.date
            first_hit_days = idx
            if sl_hit and tp_hit:
                first_hit = "ambiguous"
            elif sl_hit:
                first_hit = "stop_loss"
            else:
                first_hit = "take_profit"
            break
        return hit_sl, hit_tp, first_hit, first_hit_date, first_hit_days

