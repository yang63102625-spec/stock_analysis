# -*- coding: utf-8 -*-
"""Aggregation helpers for `BacktestEngine` (extracted to keep the engine
module under the 800-line cap and `compute_summary` under 80 lines per fn).

Mixed into `BacktestEngine`; not meant to be used standalone.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

# Score buckets for breakdown analytics.
SCORE_BUCKETS = (
    ("ge_80", lambda s: s >= 80),
    ("70_80", lambda s: 70 <= s < 80),
    ("60_70", lambda s: 60 <= s < 70),
    ("lt_60", lambda s: s < 60),
)

# Risk-reward buckets — chosen so 1:1 / 1:2 / 1:3 plans land in
# distinct cells while leaving fat tails captured in ge_4.
RR_BUCKETS = (
    ("ge_4", lambda r: r >= 4.0),
    ("2_5_4", lambda r: 2.5 <= r < 4.0),
    ("1_5_2_5", lambda r: 1.5 <= r < 2.5),
    ("lt_1_5", lambda r: r < 1.5),
)


class _AggregationMixin:
    """Provides `compute_summary` + per-bucket / drawdown / R-multiple helpers."""

    @classmethod
    def compute_summary(
        cls,
        *,
        results: Iterable[Any],
        scope: str,
        code: Optional[str],
        eval_window_days: int,
    ) -> Dict[str, Any]:
        results_list = list(results)
        completed = [r for r in results_list if (r.eval_status or "") == "completed"]
        long_completed = [r for r in completed if (r.position_recommendation or "") == "long"]

        signal = cls._compute_signal_layer(completed)
        exec_ = cls._compute_execution_layer(long_completed)
        diag = cls._compute_diagnostic_layer(long_completed, exec_["filled"])

        return {
            "scope": scope,
            "code": code,
            "eval_window_days": int(eval_window_days),
            "total_evaluations": len(results_list),
            "completed_count": len(completed),
            "insufficient_count": sum(
                1 for r in results_list if (r.eval_status or "") == "insufficient_data"
            ),
            "long_count": len(long_completed),
            "cash_count": sum(1 for r in completed if (r.position_recommendation or "") == "cash"),
            **signal,
            **{k: v for k, v in exec_.items() if k != "filled"},
            **diag,
            "signal_breakdown": cls._bucket_breakdown(
                completed, key=lambda r: (r.buy_signal_at_eval or "UNKNOWN").upper()
            ),
            "score_bucket_breakdown": cls._bucket_breakdown(completed, key=cls._score_bucket_key),
            "risk_reward_breakdown": cls._bucket_breakdown(
                long_completed, key=cls._risk_reward_bucket_key,
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
            "diagnostics": cls._compute_status_diagnostics(results_list),
        }

    # ── Layer 1: signal-direction outcomes ───────────────────────────────

    @classmethod
    def _compute_signal_layer(cls, completed: Sequence[Any]) -> Dict[str, Any]:
        win_count = sum(1 for r in completed if (r.outcome or "") == "win")
        loss_count = sum(1 for r in completed if (r.outcome or "") == "loss")
        neutral_count = sum(1 for r in completed if (r.outcome or "") == "neutral")
        win_loss_denom = win_count + loss_count
        direction_denom = sum(1 for r in completed if r.direction_correct is not None)
        direction_num = sum(1 for r in completed if r.direction_correct is True)
        return {
            "win_count": win_count,
            "loss_count": loss_count,
            "neutral_count": neutral_count,
            "win_rate_pct": round(win_count / win_loss_denom * 100, 2) if win_loss_denom else None,
            "neutral_rate_pct": round(neutral_count / len(completed) * 100, 2) if completed else None,
            "direction_accuracy_pct": (
                round(direction_num / direction_denom * 100, 2) if direction_denom else None
            ),
            "avg_stock_return_pct": cls._average([r.stock_return_pct for r in completed]),
        }

    # ── Layer 2: trade-execution metrics (long-only, after frictions) ───

    @classmethod
    def _compute_execution_layer(cls, long_completed: Sequence[Any]) -> Dict[str, Any]:
        filled = [r for r in long_completed if cls._entry_status(r) == "filled"]
        not_filled = [r for r in long_completed if cls._entry_status(r) == "not_filled"]
        not_filled_limit_up = [
            r for r in long_completed if cls._entry_status(r) == "not_filled_limit_up"
        ]
        fill_rate_pct = (
            round(len(filled) / len(long_completed) * 100, 2) if long_completed else None
        )

        trade_returns = [r.simulated_return_pct for r in filled if r.simulated_return_pct is not None]
        wins = [v for v in trade_returns if v > 0]
        losses = [v for v in trade_returns if v < 0]
        sum_losses_abs = abs(sum(losses)) if losses else 0.0
        # Profit factor degenerates when there are no losses; report None instead of inf
        # so downstream serialization (JSON / Pydantic) doesn't choke.
        profit_factor = round(sum(wins) / sum_losses_abs, 3) if sum_losses_abs > 0 else None

        r_values = [
            float(getattr(r, "r_multiple", None))
            for r in filled
            if getattr(r, "r_multiple", None) is not None
        ]
        avg_trade_return_pct = cls._average(trade_returns)

        return {
            "filled": filled,  # sieved out by caller before serializing
            "fill_rate_pct": fill_rate_pct,
            "filled_count": len(filled),
            "not_filled_count": len(not_filled) + len(not_filled_limit_up),
            "not_filled_limit_up_count": len(not_filled_limit_up),
            "trade_win_rate_pct": (
                round(len(wins) / (len(wins) + len(losses)) * 100, 2) if (wins or losses) else None
            ),
            "avg_simulated_return_pct": avg_trade_return_pct,
            # Expectancy = avg trade return after frictions; same number as
            # avg_simulated_return_pct, exposed under a more standard name.
            "expectancy_pct": avg_trade_return_pct,
            "avg_r_multiple": round(sum(r_values) / len(r_values), 4) if r_values else None,
            "profit_factor": profit_factor,
            "max_drawdown_pct": cls._max_drawdown_pct(filled),
            "avg_mae_pct": cls._average([getattr(r, "mae_pct", None) for r in filled]),
            "avg_mfe_pct": cls._average([getattr(r, "mfe_pct", None) for r in filled]),
        }

    # ── Layer 3: ambiguity + legacy target-hit diagnostics ──────────────

    @classmethod
    def _compute_diagnostic_layer(
        cls, long_completed: Sequence[Any], filled: Sequence[Any],
    ) -> Dict[str, Any]:
        ambiguous_count = sum(1 for r in filled if (r.exit_reason or "") == "stop_loss_ambiguous")

        stop_applicable = [r for r in long_completed if cls._hit_stop_loss(r) is not None]
        tp_applicable = [r for r in long_completed if cls._hit_take_profit(r) is not None]
        any_target = [
            r for r in long_completed
            if cls._first_hit(r) in ("stop_loss", "take_profit", "ambiguous")
        ]

        return {
            "ambiguous_count": ambiguous_count,
            "ambiguous_rate": round(ambiguous_count / len(filled) * 100, 2) if filled else None,
            "stop_loss_trigger_rate": cls._rate(
                stop_applicable, lambda r: cls._hit_stop_loss(r) is True
            ),
            "take_profit_trigger_rate": cls._rate(
                tp_applicable, lambda r: cls._hit_take_profit(r) is True
            ),
            "avg_days_to_first_hit": cls._average(
                [
                    float(cls._first_hit_days(r))
                    for r in any_target
                    if cls._first_hit_days(r) is not None
                ]
            ),
        }

    # ── Drawdown / R-multiple primitives ────────────────────────────────

    @staticmethod
    def _max_drawdown_pct(filled: Sequence[Any]) -> Optional[float]:
        """Compound trade returns chronologically; report worst peak-to-trough drawdown.

        Uses each trade's `simulated_return_pct` (already net of frictions).
        Returns None when nothing to compute.
        """
        rows = [r for r in filled if r.simulated_return_pct is not None]
        if not rows:
            return None

        def _ts(r: Any):
            ts = getattr(r, "evaluated_at", None) or getattr(r, "analysis_date", None)
            return (ts is None, ts)

        try:
            rows = sorted(rows, key=_ts)
        except TypeError:
            pass  # mixed types — leave insertion order

        equity = peak = 1.0
        max_dd = 0.0
        for r in rows:
            equity *= 1 + (float(r.simulated_return_pct) / 100)
            peak = max(peak, equity)
            max_dd = min(max_dd, (equity - peak) / peak)
        return round(max_dd * 100, 2)

    # ── Per-bucket breakdowns ───────────────────────────────────────────

    @staticmethod
    def _bucket_breakdown(rows: Sequence[Any], *, key) -> Dict[str, Any]:
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
        for b in breakdown.values():
            denom = b["win"] + b["loss"]
            b["win_rate_pct"] = round(b["win"] / denom * 100, 2) if denom else None
        return breakdown

    @staticmethod
    def _score_bucket_key(row: Any) -> str:
        s = row.signal_score_at_eval
        if s is None:
            return "unknown"
        for label, predicate in SCORE_BUCKETS:
            if predicate(int(s)):
                return label
        return "unknown"

    @staticmethod
    def _risk_reward_bucket_key(row: Any) -> str:
        rr = getattr(row, "risk_reward_at_eval", None)
        if rr is None:
            return "unknown"
        try:
            rr_f = float(rr)
        except (TypeError, ValueError):
            return "unknown"
        if rr_f <= 0:
            return "unknown"
        for label, predicate in RR_BUCKETS:
            if predicate(rr_f):
                return label
        return "unknown"

    @staticmethod
    def _compute_status_diagnostics(results: Sequence[Any]) -> Dict[str, Any]:
        status_counts: Dict[str, int] = {}
        entry_status_counts: Dict[str, int] = {}
        for row in results:
            status = (row.eval_status or "").strip() or "(unknown)"
            status_counts[status] = status_counts.get(status, 0) + 1
            es = getattr(row, "entry_status", None) or "(none)"
            entry_status_counts[es] = entry_status_counts.get(es, 0) + 1
        return {"eval_status": status_counts, "entry_status": entry_status_counts}

    # ── Row-attribute accessors (centralized for back-compat with old rows) ──

    @staticmethod
    def _entry_status(row: Any) -> str:
        return getattr(row, "entry_status", None) or ""

    @staticmethod
    def _hit_stop_loss(row: Any) -> Optional[bool]:
        return getattr(row, "hit_stop_loss", None)

    @staticmethod
    def _hit_take_profit(row: Any) -> Optional[bool]:
        return getattr(row, "hit_take_profit", None)

    @staticmethod
    def _first_hit(row: Any) -> str:
        return (getattr(row, "first_hit", None) or "").strip()

    @staticmethod
    def _first_hit_days(row: Any) -> Optional[int]:
        return getattr(row, "first_hit_trading_days", None)

    @staticmethod
    def _rate(applicable: Sequence[Any], predicate) -> Optional[float]:
        if not applicable:
            return None
        return round(sum(1 for r in applicable if predicate(r)) / len(applicable) * 100, 2)

    @staticmethod
    def _average(values: Iterable[Optional[float]]) -> Optional[float]:
        items: List[float] = [float(v) for v in values if v is not None]
        if not items:
            return None
        return round(sum(items) / len(items), 4)
