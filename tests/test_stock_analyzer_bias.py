# -*- coding: utf-8 -*-
"""
Unit tests for StockTrendAnalyzer._generate_signal bias and strong-trend relief logic (Issue #296).
"""

import math
import unittest

import numpy as np
import pandas as pd

from src.stock_analyzer import (
    StockTrendAnalyzer,
    TrendAnalysisResult,
    TrendStatus,
    VolumeStatus,
    MACDStatus,
    RSIStatus,
)


def _make_result(
    code: str = "000001",
    trend_status: TrendStatus = TrendStatus.BULL,
    trend_strength: float = 50.0,
    bias_ma5: float = 0.0,
    volume_status: VolumeStatus = VolumeStatus.NORMAL,
    macd_status: MACDStatus = MACDStatus.BULLISH,
    rsi_status: RSIStatus = RSIStatus.NEUTRAL,
    support_ma5: bool = False,
    support_ma10: bool = False,
) -> TrendAnalysisResult:
    """Build TrendAnalysisResult with defaults for _generate_signal bias branch testing."""
    return TrendAnalysisResult(
        code=code,
        trend_status=trend_status,
        ma_alignment="",
        trend_strength=trend_strength,
        ma5=10.0,
        ma10=9.5,
        ma20=9.0,
        ma60=8.5,
        current_price=10.0,
        bias_ma5=bias_ma5,
        bias_ma10=0.0,
        bias_ma20=0.0,
        volume_status=volume_status,
        volume_ratio_5d=1.0,
        volume_trend="",
        support_ma5=support_ma5,
        support_ma10=support_ma10,
        macd_status=macd_status,
        rsi_status=rsi_status,
    )


class StockAnalyzerBiasTestCase(unittest.TestCase):
    """Tests for bias_ma5 and strong-trend relief in _generate_signal."""

    def setUp(self) -> None:
        self.analyzer = StockTrendAnalyzer()

    def _make_dummy_df(self, ma20_rising: bool = True, rows: int = 5) -> pd.DataFrame:
        """Create a minimal DataFrame with MA20 column for _generate_signal."""
        if ma20_rising:
            ma20_values = np.linspace(10.0, 11.0, rows)  # Rising MA20
        else:
            ma20_values = np.linspace(11.0, 10.0, rows)  # Declining MA20
        return pd.DataFrame({"MA20": ma20_values, "close": ma20_values * 1.05})

    def _assert_contains(self, items: list, substring: str) -> None:
        """Assert at least one item contains the substring."""
        self.assertTrue(
            any(substring in s for s in items),
            msg=f"Expected substring '{substring}' in {items}",
        )

    def _assert_not_contains(self, items: list, substring: str) -> None:
        """Assert no item contains the substring."""
        self.assertFalse(
            any(substring in s for s in items),
            msg=f"Did not expect substring '{substring}' in {items}",
        )

    def test_bias_nan_defense(self) -> None:
        """bias_ma5=NaN should be treated as 0.0 without exception."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=float("nan"),
        )
        df = self._make_dummy_df(ma20_rising=True)
        self.analyzer._generate_signal(df, result)
        self.assertIsInstance(result.signal_score, (int, float))
        self.assertFalse(math.isnan(result.signal_score))

    def test_bias_negative_pullback(self) -> None:
        """bias=-2% should yield '回踩买点'."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=-2.0,
        )
        df = self._make_dummy_df(ma20_rising=True)
        self.analyzer._generate_signal(df, result)
        self._assert_contains(result.signal_reasons, "回踩买点")

    def test_bias_close_to_ma5(self) -> None:
        """bias=1.5% should yield '介入好时机'."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=1.5,
        )
        df = self._make_dummy_df(ma20_rising=True)
        self.analyzer._generate_signal(df, result)
        self._assert_contains(result.signal_reasons, "介入好时机")

    def test_bias_slightly_high(self) -> None:
        """bias=4% (< base_threshold=5%) should yield '可小仓介入'."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=4.0,
        )
        df = self._make_dummy_df(ma20_rising=True)
        self.analyzer._generate_signal(df, result)
        self._assert_contains(result.signal_reasons, "可小仓介入")

    def _make_phase_df(self, gain_pct: float = 0.0, consecutive_up: int = 3, rows: int = 25) -> pd.DataFrame:
        """Create a DataFrame with specific 20-day gain and consecutive up days for phase testing."""
        if rows < 20:
            rows = 20
        base_price = 10.0
        target_price = base_price * (1 + gain_pct / 100)
        # Build prices with controlled consecutive up days at the end
        non_consecutive_len = rows - consecutive_up
        prices = []
        # Non-consecutive section: alternate up/down to keep consecutive_up < 2
        for i in range(non_consecutive_len):
            progress = i / max(non_consecutive_len - 1, 1)
            mid_target = base_price + (target_price - base_price) * 0.7 * progress
            if i % 2 == 1:
                # Down bar: slightly lower than previous
                prices.append(prices[-1] - 0.02)
            else:
                prices.append(mid_target)
        # Consecutive up section: strictly ascending to target
        if consecutive_up > 0:
            start_val = prices[-1] if prices else base_price
            for i in range(1, consecutive_up + 1):
                prices.append(start_val + (target_price - start_val) * i / consecutive_up)
        # Fix prices[-20] = base_price to control gain_20d
        if len(prices) >= 20:
            prices[-20] = base_price
        ma20_values = np.linspace(9.0, target_price * 0.95, rows)
        return pd.DataFrame({"MA20": ma20_values, "close": prices})

    def test_strong_trend_acceleration_phase(self) -> None:
        """STRONG_BULL + 20d gain>30% + bias=4% -> acceleration phase, '严禁追高'."""
        result = _make_result(
            trend_status=TrendStatus.STRONG_BULL,
            trend_strength=75.0,
            bias_ma5=4.0,
        )
        # Create df with >30% gain to trigger acceleration phase (threshold=3.5)
        df = self._make_phase_df(gain_pct=35.0, consecutive_up=6, rows=25)
        self.analyzer._generate_signal(df, result)
        self._assert_contains(result.risk_factors, "加速见顶阶段")
        self._assert_contains(result.risk_factors, "严禁追高")

    def test_early_stage_bias_within_tolerance(self) -> None:
        """BULL + early stage (gain<15%) + bias=5.5% -> within 6% tolerance, '轻仓追踪'."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=5.5,
        )
        # Early stage: gain_20d < 15%, effective_threshold=6.0
        df = self._make_phase_df(gain_pct=10.0, rows=25)
        self.analyzer._generate_signal(df, result)
        self._assert_contains(result.signal_reasons, "趋势启动期")

    def test_early_stage_bias_exceed(self) -> None:
        """BULL + early stage + bias=7% -> exceeds 6% threshold, '追高需设严格止损'."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=7.0,
        )
        df = self._make_phase_df(gain_pct=10.0, rows=25)
        self.analyzer._generate_signal(df, result)
        self._assert_contains(result.risk_factors, "趋势启动期乖离率偏高")

    def test_main_rally_phase_exceed(self) -> None:
        """BULL + main rally (gain 15-30%) + bias=6% -> exceeds 5% threshold, '严禁追高'."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=6.0,
        )
        # Main rally phase: gain_20d > 15, effective_threshold=base_threshold (~5.0)
        df = self._make_phase_df(gain_pct=20.0, rows=25)
        self.analyzer._generate_signal(df, result)
        self._assert_contains(result.risk_factors, "严禁追高")

    def test_boundary_at_base_threshold(self) -> None:
        """bias=5.0% at exact base_threshold boundary with early stage -> '趋势启动期'."""
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=5.0,
        )
        # Early stage: effective_threshold=6.0, bias=5.0 is between base(5.0) and effective(6.0)
        # But 5.0 > 5.0 is False, so it falls to else branch
        df = self._make_dummy_df(ma20_rising=True)
        self.analyzer._generate_signal(df, result)
        # bias=5.0: not < base_threshold(5.0), not > effective(6.0), not > base(5.0)
        # Falls to else: "乖离率过高"
        self._assert_contains(result.risk_factors, "乖离率过高")
