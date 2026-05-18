# -*- coding: utf-8 -*-
"""Unit tests for backtest engine v2 (signal-driven, trade_levels-aware)."""

import unittest
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from src.core.backtest_engine import (
    AnalysisSnapshot,
    BacktestEngine,
    EvaluationConfig,
)


@dataclass
class Bar:
    """Test bar with optional ma10/ma20/atr (consumed by simulate_forward_trade)."""

    date: date
    high: float
    low: float
    close: float
    ma10: float = 0.0
    ma20: float = 0.0
    atr: float = 0.0
    pct_chg: Optional[float] = None


def _make_bars(start: date, closes, highs=None, lows=None):
    highs = highs or closes
    lows = lows or closes
    return [
        Bar(date=start + timedelta(days=i + 1), high=highs[i], low=lows[i], close=c)
        for i, c in enumerate(closes)
    ]


def _snapshot(buy_signal: Optional[str], **overrides) -> AnalysisSnapshot:
    base = dict(
        code="600000",
        operation_advice=None,
        signal_score=80,
        buy_signal=buy_signal,
        market_environment="sideways",
        strategy_id="buy_pullback",
        ideal_buy=None,
        stop_loss=None,
        take_profit=None,
        risk_reward=None,
        position_pct=None,
        trend_score=20,
        bias_score=10,
        volume_score=12,
        support_score=4,
        macd_score=8,
        rsi_score=3,
        capital_flow_score=8,
    )
    base.update(overrides)
    return AnalysisSnapshot(**base)


class BacktestEngineV2TestCase(unittest.TestCase):
    # ── Position / direction mapping ────────────────────────────────

    def test_strong_buy_maps_to_long_up(self):
        self.assertEqual(BacktestEngine.position_from_signal("STRONG_BUY"), "long")
        self.assertEqual(BacktestEngine.direction_expected_from_signal("STRONG_BUY"), "up")

    def test_buy_maps_to_long_up(self):
        self.assertEqual(BacktestEngine.position_from_signal("BUY"), "long")
        self.assertEqual(BacktestEngine.direction_expected_from_signal("BUY"), "up")

    def test_hold_maps_to_cash_not_down(self):
        self.assertEqual(BacktestEngine.position_from_signal("HOLD"), "cash")
        self.assertEqual(BacktestEngine.direction_expected_from_signal("HOLD"), "not_down")

    def test_avoid_maps_to_cash_down(self):
        self.assertEqual(BacktestEngine.position_from_signal("AVOID"), "cash")
        self.assertEqual(BacktestEngine.direction_expected_from_signal("AVOID"), "down")

    def test_strong_avoid_maps_to_cash_down(self):
        self.assertEqual(BacktestEngine.position_from_signal("STRONG_AVOID"), "cash")
        self.assertEqual(BacktestEngine.direction_expected_from_signal("STRONG_AVOID"), "down")

    def test_none_signal_defaults_to_cash_flat(self):
        self.assertEqual(BacktestEngine.position_from_signal(None), "cash")
        self.assertEqual(BacktestEngine.direction_expected_from_signal(None), "flat")

    # ── Evaluate single ─────────────────────────────────────────────

    def test_buy_signal_winning_trade(self):
        cfg = EvaluationConfig(eval_window_days=3)
        bars = _make_bars(date(2024, 1, 1), [102, 104, 105], highs=[103, 105, 106], lows=[101, 103, 104])
        res = BacktestEngine.evaluate_single(
            analysis=_snapshot("BUY"),
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            config=cfg,
        )
        self.assertEqual(res["eval_status"], "completed")
        self.assertEqual(res["position_recommendation"], "long")
        self.assertEqual(res["direction_expected"], "up")
        self.assertEqual(res["outcome"], "win")
        self.assertTrue(res["direction_correct"])

    def test_avoid_signal_in_cash_when_down(self):
        cfg = EvaluationConfig(eval_window_days=3)
        bars = _make_bars(date(2024, 1, 1), [98, 97, 96], highs=[99, 98, 97], lows=[97, 96, 95])
        res = BacktestEngine.evaluate_single(
            analysis=_snapshot("AVOID"),
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            config=cfg,
        )
        self.assertEqual(res["position_recommendation"], "cash")
        self.assertEqual(res["outcome"], "win")  # AVOID expected down, stock went down
        self.assertEqual(res["simulated_return_pct"], 0.0)
        self.assertEqual(res["first_hit"], "not_applicable")

    def test_missing_signal_skipped(self):
        """Pre-v2 analyses without buy_signal should yield missing_signal status."""
        cfg = EvaluationConfig(eval_window_days=3)
        bars = _make_bars(date(2024, 1, 1), [102, 104, 105])
        res = BacktestEngine.evaluate_single(
            analysis=_snapshot(None),
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            config=cfg,
        )
        self.assertEqual(res["eval_status"], "missing_signal")

    def test_insufficient_data(self):
        cfg = EvaluationConfig(eval_window_days=5)
        bars = _make_bars(date(2024, 1, 1), [100, 101])
        res = BacktestEngine.evaluate_single(
            analysis=_snapshot("BUY"),
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            config=cfg,
        )
        self.assertEqual(res["eval_status"], "insufficient_data")

    def test_buy_loss_when_down(self):
        cfg = EvaluationConfig(eval_window_days=3)
        bars = _make_bars(date(2024, 1, 1), [98, 96, 95], highs=[99, 97, 96], lows=[97, 95, 94])
        res = BacktestEngine.evaluate_single(
            analysis=_snapshot("BUY"),
            analysis_date=date(2024, 1, 1),
            start_price=100,
            forward_bars=bars,
            config=cfg,
        )
        self.assertEqual(res["outcome"], "loss")
        self.assertFalse(res["direction_correct"])

    def test_signal_snapshot_propagates_to_result(self):
        cfg = EvaluationConfig(eval_window_days=3)
        bars = _make_bars(date(2024, 1, 1), [102, 104, 105], highs=[103, 105, 106], lows=[101, 103, 104])
        snap = _snapshot("STRONG_BUY", signal_score=92, market_environment="bull", strategy_id="buy_pullback")
        res = BacktestEngine.evaluate_single(
            analysis=snap, analysis_date=date(2024, 1, 1),
            start_price=100, forward_bars=bars, config=cfg,
        )
        self.assertEqual(res["signal_score_at_eval"], 92)
        self.assertEqual(res["buy_signal_at_eval"], "STRONG_BUY")
        self.assertEqual(res["market_environment_at_eval"], "bull")
        self.assertEqual(res["strategy_id"], "buy_pullback")
        # dim score snapshots
        self.assertEqual(res["macd_score_at_eval"], 8)
        self.assertEqual(res["capital_flow_score_at_eval"], 8)

    def test_long_position_uses_simulate_forward_trade_exit_reason(self):
        """When position=long, exit_reason should be populated by trade_levels engine."""
        cfg = EvaluationConfig(eval_window_days=5)
        # Strong rally → trailing stays unactivated, exits at window_end
        bars = _make_bars(
            date(2024, 1, 1),
            [101, 102, 103, 104, 105],
            highs=[102, 103, 104, 105, 106],
            lows=[100, 101, 102, 103, 104],
        )
        res = BacktestEngine.evaluate_single(
            analysis=_snapshot("BUY"),
            analysis_date=date(2024, 1, 1),
            start_price=100, forward_bars=bars, config=cfg,
        )
        self.assertEqual(res["eval_status"], "completed")
        self.assertEqual(res["position_recommendation"], "long")
        # exit_reason populated for long; one of stop_loss / window_end / trailing_* / stage_*
        self.assertIsNotNone(res["exit_reason"])
        self.assertIsNotNone(res["hold_days"])

    # ── Aggregation / breakdowns ────────────────────────────────────

    def test_compute_summary_breakdowns(self):
        @dataclass
        class FakeRow:
            eval_status: str = "completed"
            position_recommendation: Optional[str] = "long"
            outcome: Optional[str] = "win"
            direction_correct: Optional[bool] = True
            stock_return_pct: Optional[float] = 5.0
            simulated_return_pct: Optional[float] = 4.0
            hit_stop_loss: Optional[bool] = None
            hit_take_profit: Optional[bool] = None
            first_hit: Optional[str] = "neither"
            first_hit_trading_days: Optional[int] = None
            operation_advice: Optional[str] = None
            signal_score_at_eval: Optional[int] = 85
            buy_signal_at_eval: Optional[str] = "STRONG_BUY"
            market_environment_at_eval: Optional[str] = "bull"
            strategy_id: Optional[str] = "buy_pullback"
            exit_reason: Optional[str] = "window_end"
            hold_days: Optional[int] = 5

        rows = [
            FakeRow(buy_signal_at_eval="STRONG_BUY", outcome="win", signal_score_at_eval=90),
            FakeRow(buy_signal_at_eval="STRONG_BUY", outcome="loss", signal_score_at_eval=85, direction_correct=False),
            FakeRow(buy_signal_at_eval="BUY", outcome="win", signal_score_at_eval=72),
            FakeRow(buy_signal_at_eval="BUY", outcome="win", signal_score_at_eval=65, exit_reason="trailing_below_ma10"),
        ]
        summary = BacktestEngine.compute_summary(
            results=rows, scope="overall", code="__overall__", eval_window_days=5,
        )
        self.assertEqual(summary["total_evaluations"], 4)
        self.assertEqual(summary["win_count"], 3)
        self.assertEqual(summary["loss_count"], 1)
        # signal breakdown
        sb = summary["signal_breakdown"]
        self.assertIn("STRONG_BUY", sb)
        self.assertEqual(sb["STRONG_BUY"]["total"], 2)
        self.assertEqual(sb["STRONG_BUY"]["win_rate_pct"], 50.0)
        # score bucket breakdown
        scb = summary["score_bucket_breakdown"]
        self.assertIn("ge_80", scb)
        self.assertEqual(scb["ge_80"]["total"], 2)
        self.assertIn("70_80", scb)
        self.assertEqual(scb["70_80"]["total"], 1)
        self.assertIn("60_70", scb)
        # exit reason breakdown (long-only)
        erb = summary["exit_reason_breakdown"]
        self.assertIn("window_end", erb)
        self.assertIn("trailing_below_ma10", erb)
        # regime breakdown
        self.assertIn("bull", summary["regime_breakdown"])
        # strategy breakdown
        self.assertIn("buy_pullback", summary["strategy_breakdown"])


if __name__ == "__main__":
    unittest.main()
