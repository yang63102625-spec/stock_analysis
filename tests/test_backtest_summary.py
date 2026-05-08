# -*- coding: utf-8 -*-
"""Unit tests for BacktestEngine.compute_summary() (v2)."""

import unittest
from dataclasses import dataclass
from typing import Optional

from src.core.backtest_engine import BacktestEngine


@dataclass
class FakeRow:
    eval_status: str = "completed"
    position_recommendation: Optional[str] = "long"
    outcome: Optional[str] = "win"
    direction_correct: Optional[bool] = True
    stock_return_pct: Optional[float] = 1.0
    simulated_return_pct: Optional[float] = 1.0
    hit_stop_loss: Optional[bool] = False
    hit_take_profit: Optional[bool] = False
    first_hit: Optional[str] = "neither"
    first_hit_trading_days: Optional[int] = None
    operation_advice: Optional[str] = None
    # v2 fields
    signal_score_at_eval: Optional[int] = 80
    buy_signal_at_eval: Optional[str] = "BUY"
    market_environment_at_eval: Optional[str] = "sideways"
    strategy_id: Optional[str] = "buy_pullback"
    exit_reason: Optional[str] = "window_end"
    hold_days: Optional[int] = 5


class BacktestSummaryTestCase(unittest.TestCase):
    def test_trigger_rates_use_applicable_denominators(self) -> None:
        # One row has stop-loss configured, one row doesn't.
        rows = [
            FakeRow(hit_stop_loss=True, hit_take_profit=None, first_hit="stop_loss"),
            FakeRow(hit_stop_loss=None, hit_take_profit=True, first_hit="take_profit"),
        ]

        summary = BacktestEngine.compute_summary(
            results=rows,
            scope="stock",
            code="600519",
            eval_window_days=3,
        )

        self.assertEqual(summary["stop_loss_trigger_rate"], 100.0)
        self.assertEqual(summary["take_profit_trigger_rate"], 100.0)
        self.assertEqual(summary["ambiguous_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
