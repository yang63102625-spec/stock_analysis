# -*- coding: utf-8 -*-
"""Backtesting evaluation engine v2 (signal-driven, trade_levels-aware).

This engine evaluates each historical analysis using:
- The system-computed `buy_signal` / `signal_score` (NOT LLM operation_advice text)
- The unified `simulate_forward_trade` rules (same engine as picker backtest:
  staged exits, trailing MA10/ATR, slippage, limit-up entry filter)

It is intentionally DB-agnostic: it operates on plain values or objects that
look like daily OHLC bars (and exposes the same `BacktestResultLike` Protocol
required by `compute_summary` for aggregation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

# NOTE: simulate_forward_trade is imported lazily inside evaluate_single() to
# avoid circular imports via src.services.__init__ (which loads BacktestService
# which loads this module).

logger = logging.getLogger(__name__)


OVERALL_SENTINEL_CODE = "__overall__"

# buy_signal -> position. STRONG_BUY/BUY enter long; everything else stays in cash.
LONG_SIGNALS = ("STRONG_BUY", "BUY")
AVOID_SIGNALS = ("AVOID", "STRONG_AVOID")

# Score buckets for breakdown analytics.
SCORE_BUCKETS = (
    ("ge_80", lambda s: s >= 80),
    ("70_80", lambda s: 70 <= s < 80),
    ("60_70", lambda s: 60 <= s < 70),
    ("lt_60", lambda s: s < 60),
)


class DailyBarLike(Protocol):
    """Protocol for objects representing a daily OHLC bar."""

    date: date
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]


class BacktestResultLike(Protocol):
    """Protocol for objects that behave like a stored BacktestResult row."""

    eval_status: str
    position_recommendation: Optional[str]
    outcome: Optional[str]
    direction_correct: Optional[bool]
    stock_return_pct: Optional[float]
    simulated_return_pct: Optional[float]
    hit_stop_loss: Optional[bool]
    hit_take_profit: Optional[bool]
    first_hit: Optional[str]
    first_hit_trading_days: Optional[int]
    operation_advice: Optional[str]
    # v2 additions (Optional so legacy rows still satisfy Protocol)
    signal_score_at_eval: Optional[int]
    buy_signal_at_eval: Optional[str]
    market_environment_at_eval: Optional[str]
    strategy_id: Optional[str]
    exit_reason: Optional[str]
    hold_days: Optional[int]


@dataclass(frozen=True)
class EvaluationConfig:
    eval_window_days: int
    # Kept for backward compat with stored rows; current engine ignores this band.
    neutral_band_pct: float = 2.0


@dataclass(frozen=True)
class AnalysisSnapshot:
    """Snapshot of v3.0+ AnalysisHistory fields needed for v2 evaluation."""

    code: str
    operation_advice: Optional[str]
    signal_score: Optional[int]
    buy_signal: Optional[str]
    market_environment: Optional[str]
    strategy_id: str  # default "buy_pullback" when picker context absent
    ideal_buy: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward: Optional[float]
    position_pct: Optional[float]
    # Dim scores (for breakdown analytics)
    trend_score: Optional[int]
    bias_score: Optional[int]
    volume_score: Optional[int]
    support_score: Optional[int]
    macd_score: Optional[int]
    rsi_score: Optional[int]
    capital_flow_score: Optional[int]


class BacktestEngine:
    """v2 long-only daily-bar engine driven by buy_signal + trade_levels."""

    @classmethod
    def position_from_signal(cls, buy_signal: Optional[str]) -> str:
        """STRONG_BUY/BUY -> long; HOLD/AVOID/STRONG_AVOID/None -> cash."""
        if not buy_signal:
            return "cash"
        return "long" if buy_signal.upper() in LONG_SIGNALS else "cash"

    @classmethod
    def direction_expected_from_signal(cls, buy_signal: Optional[str]) -> str:
        """Map buy_signal to expected direction for direction-accuracy metrics."""
        if not buy_signal:
            return "flat"
        sig = buy_signal.upper()
        if sig in LONG_SIGNALS:
            return "up"
        if sig in AVOID_SIGNALS:
            return "down"
        # HOLD: bullish enough not to short, but no strong directional bet
        return "not_down"

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
        """Evaluate one historical analysis against forward daily bars."""

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
            # Pre-v2 analysis records lack the system signal. Skip.
            return {**base_meta, "eval_status": "missing_signal"}

        if len(forward_bars) < eval_days:
            return {**base_meta, "eval_status": "insufficient_data", "eval_window_days": eval_days}

        window_bars = list(forward_bars[:eval_days])
        end_close = window_bars[-1].close
        highs = [b.high for b in window_bars if b.high is not None]
        lows = [b.low for b in window_bars if b.low is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None

        stock_return_pct: Optional[float]
        if end_close is None:
            stock_return_pct = None
        else:
            stock_return_pct = (end_close - start_price) / start_price * 100

        outcome, direction_correct = cls._classify_outcome(
            stock_return_pct=stock_return_pct,
            direction_expected=direction_expected,
        )

        # ── Simulated execution via unified trade_levels engine ─────────
        sim: Dict[str, Any] = {}
        simulated_entry_price: Optional[float] = None
        simulated_exit_price: Optional[float] = None
        simulated_exit_reason = "cash"
        simulated_return_pct: Optional[float] = 0.0 if position != "long" else None
        hold_days: Optional[int] = None

        if position == "long":
            from src.services.trade_levels import simulate_forward_trade  # lazy import (see top)
            simulated_entry_price = start_price
            sim_bars = cls._bars_to_sim_dicts(window_bars)
            try:
                sim = simulate_forward_trade(
                    strategy_id=analysis.strategy_id,
                    entry_price=float(start_price),
                    market_cap_yi=0.0,  # not available at eval time; rules degrade gracefully
                    bars=sim_bars,
                    apply_slippage=True,
                    apply_limit_up_filter=True,
                    is_kc_cy=cls._is_kc_cy(analysis.code),
                )
            except Exception as exc:
                logger.debug("[BacktestEngine] simulate_forward_trade failed for %s: %s", analysis.code, exc)
                sim = {"skipped": True, "skip_reason": "sim_error"}

            if sim.get("skipped"):
                simulated_return_pct = None
                simulated_exit_reason = sim.get("skip_reason") or "skipped"
            else:
                simulated_exit_price = sim.get("exit_price")
                simulated_return_pct = sim.get("return_pct")
                simulated_exit_reason = sim.get("exit_reason") or "window_end"
                hold_days = sim.get("hold_days")

        # ── Target-hit fields kept for backward-compat (best-effort) ────
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
            "simulated_entry_price": simulated_entry_price,
            "simulated_exit_price": simulated_exit_price,
            "simulated_exit_reason": simulated_exit_reason,
            "simulated_return_pct": simulated_return_pct,
            "exit_reason": simulated_exit_reason if position == "long" else None,
            "hold_days": hold_days,
        }

    # ── Aggregation ──────────────────────────────────────────────────────

    @classmethod
    def compute_summary(
        cls,
        *,
        results: Iterable[BacktestResultLike],
        scope: str,
        code: Optional[str],
        eval_window_days: int,
    ) -> Dict[str, Any]:
        results_list = list(results)
        total = len(results_list)
        completed = [r for r in results_list if (r.eval_status or "") == "completed"]
        insufficient_count = sum(1 for r in results_list if (r.eval_status or "") == "insufficient_data")

        long_count = sum(1 for r in completed if (r.position_recommendation or "") == "long")
        cash_count = sum(1 for r in completed if (r.position_recommendation or "") == "cash")

        win_count = sum(1 for r in completed if (r.outcome or "") == "win")
        loss_count = sum(1 for r in completed if (r.outcome or "") == "loss")
        neutral_count = sum(1 for r in completed if (r.outcome or "") == "neutral")

        direction_denominator = sum(1 for r in completed if r.direction_correct is not None)
        direction_numerator = sum(1 for r in completed if r.direction_correct is True)
        direction_accuracy_pct = (
            round(direction_numerator / direction_denominator * 100, 2) if direction_denominator else None
        )

        win_loss_denominator = win_count + loss_count
        win_rate_pct = round(win_count / win_loss_denominator * 100, 2) if win_loss_denominator else None
        neutral_rate_pct = round(neutral_count / len(completed) * 100, 2) if completed else None

        avg_stock_return_pct = cls._average([r.stock_return_pct for r in completed])
        avg_simulated_return_pct = cls._average([r.simulated_return_pct for r in completed])

        # Long-only diagnostics (target-hit fields kept for back-compat dashboards)
        long_completed = [r for r in completed if (r.position_recommendation or "") == "long"]
        stop_applicable = [r for r in long_completed if r.hit_stop_loss is not None]
        stop_loss_trigger_rate = (
            round(sum(1 for r in stop_applicable if r.hit_stop_loss is True) / len(stop_applicable) * 100, 2)
            if stop_applicable else None
        )
        take_profit_applicable = [r for r in long_completed if r.hit_take_profit is not None]
        take_profit_trigger_rate = (
            round(sum(1 for r in take_profit_applicable if r.hit_take_profit is True)
                  / len(take_profit_applicable) * 100, 2)
            if take_profit_applicable else None
        )
        any_target_applicable = [
            r for r in long_completed
            if r.hit_stop_loss is not None or r.hit_take_profit is not None
        ]
        ambiguous_rate = (
            round(sum(1 for r in any_target_applicable if (r.first_hit or "") == "ambiguous")
                  / len(any_target_applicable) * 100, 2)
            if any_target_applicable else None
        )
        avg_days_to_first_hit = cls._average(
            [
                float(r.first_hit_trading_days)
                for r in any_target_applicable
                if r.first_hit_trading_days is not None
                and (r.first_hit or "") in ("stop_loss", "take_profit", "ambiguous")
            ]
        )

        return {
            "scope": scope,
            "code": code,
            "eval_window_days": int(eval_window_days),
            "total_evaluations": total,
            "completed_count": len(completed),
            "insufficient_count": insufficient_count,
            "long_count": long_count,
            "cash_count": cash_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "neutral_count": neutral_count,
            "direction_accuracy_pct": direction_accuracy_pct,
            "win_rate_pct": win_rate_pct,
            "neutral_rate_pct": neutral_rate_pct,
            "avg_stock_return_pct": avg_stock_return_pct,
            "avg_simulated_return_pct": avg_simulated_return_pct,
            "stop_loss_trigger_rate": stop_loss_trigger_rate,
            "take_profit_trigger_rate": take_profit_trigger_rate,
            "ambiguous_rate": ambiguous_rate,
            "avg_days_to_first_hit": avg_days_to_first_hit,
            # Per-bucket breakdowns
            "signal_breakdown": cls._bucket_breakdown(
                completed, key=lambda r: (r.buy_signal_at_eval or "UNKNOWN").upper()
            ),
            "score_bucket_breakdown": cls._bucket_breakdown(
                completed, key=cls._score_bucket_key
            ),
            "exit_reason_breakdown": cls._bucket_breakdown(
                long_completed, key=lambda r: r.exit_reason or "(none)"
            ),
            "regime_breakdown": cls._bucket_breakdown(
                completed, key=lambda r: r.market_environment_at_eval or "(unknown)"
            ),
            "strategy_breakdown": cls._bucket_breakdown(
                completed, key=lambda r: r.strategy_id or "(unknown)"
            ),
            "diagnostics": cls._compute_diagnostics(results_list),
        }

    # ── Internals ────────────────────────────────────────────────────────

    @staticmethod
    def _is_kc_cy(code: str) -> bool:
        return code.startswith("688") or code.startswith("30")

    @staticmethod
    def _bars_to_sim_dicts(window_bars: Sequence[DailyBarLike]) -> List[Dict[str, Any]]:
        """Convert DailyBarLike sequence to dicts consumable by simulate_forward_trade.

        MA10/MA20/ATR fields default to 0.0 when unavailable (rules degrade
        gracefully — trailing branch simply won't trigger).
        """
        out: List[Dict[str, Any]] = []
        for b in window_bars:
            if b.close is None:
                continue
            out.append({
                "close": float(b.close),
                "high": float(b.high) if b.high is not None else float(b.close),
                "low": float(b.low) if b.low is not None else float(b.close),
                "ma10": float(getattr(b, "ma10", 0.0) or 0.0),
                "ma20": float(getattr(b, "ma20", 0.0) or 0.0),
                "atr": float(getattr(b, "atr", 0.0) or 0.0),
                "pct_chg": getattr(b, "pct_chg", None),
            })
        return out

    @classmethod
    def _classify_outcome(
        cls, *, stock_return_pct: Optional[float], direction_expected: str
    ) -> tuple[Optional[str], Optional[bool]]:
        """v2 outcome rule (no neutral band): aligned with buy_signal direction."""
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
        # flat / unknown
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
        """Best-effort target-hit detection (kept for back-compat columns)."""
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

    @staticmethod
    def _average(values: Iterable[Optional[float]]) -> Optional[float]:
        items = [float(v) for v in values if v is not None]
        if not items:
            return None
        return round(sum(items) / len(items), 4)

    @staticmethod
    def _score_bucket_key(row: BacktestResultLike) -> str:
        s = row.signal_score_at_eval
        if s is None:
            return "unknown"
        for label, predicate in SCORE_BUCKETS:
            if predicate(int(s)):
                return label
        return "unknown"

    @staticmethod
    def _bucket_breakdown(rows: Sequence[BacktestResultLike], *, key) -> Dict[str, Any]:
        """Group rows by `key(row)` and compute per-bucket counts + win_rate."""
        breakdown: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            try:
                k = key(row) or "(none)"
            except Exception:
                k = "(none)"
            bucket = breakdown.setdefault(str(k), {"total": 0, "win": 0, "loss": 0, "neutral": 0})
            bucket["total"] += 1
            outcome = (row.outcome or "").strip()
            if outcome in ("win", "loss", "neutral"):
                bucket[outcome] += 1
        for k, b in breakdown.items():
            denom = b["win"] + b["loss"]
            b["win_rate_pct"] = round(b["win"] / denom * 100, 2) if denom else None
        return breakdown

    @staticmethod
    def _compute_diagnostics(results: Sequence[BacktestResultLike]) -> Dict[str, Any]:
        status_counts: Dict[str, int] = {}
        first_hit_counts: Dict[str, int] = {}
        for row in results:
            status = (row.eval_status or "").strip() or "(unknown)"
            status_counts[status] = status_counts.get(status, 0) + 1
            first_hit = (row.first_hit or "").strip() or "(none)"
            first_hit_counts[first_hit] = first_hit_counts.get(first_hit, 0) + 1
        return {"eval_status": status_counts, "first_hit": first_hit_counts}
