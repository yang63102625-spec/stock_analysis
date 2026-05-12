# -*- coding: utf-8 -*-
"""``_SignalsMixin``: signal-generation + format-analysis methods.

Split out of :mod:`src.stock_analyzer` to keep that file ≤ 800 lines per
``code-quality.mdc`` rule §1.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from ._stock_analyzer_types import (
    BuySignal,
    MACDStatus,
    RSIStatus,
    TrendAnalysisResult,
    TrendStatus,
    VolumeStatus,
)

logger = logging.getLogger(__name__)


class _SignalsMixin:
    """Buy-signal scoring and human-readable formatter."""

    def _generate_signal(self, df: pd.DataFrame, result: TrendAnalysisResult) -> None:
        """
        Generate buy signal based on comprehensive scoring system.

        Scoring dimensions (total 100, rebalanced to remove MA5-support
        redundancy with bias dimension):
        - Trend (30): bullish alignment scores high
        - Bias (15): close to MA5 scores high (already captures "MA5 support")
        - Volume (18): shrink pullback scores high
        - Support (6): MA10 support (5) + MA20 trend integrity (1)
        - MACD (13): golden cross scores high (re-allocated from support)
        - RSI (5): oversold with stabilization scores high
        - Capital flow (13): main force + north-bound inflow (re-allocated from support)
        """
        score = 0
        reasons = []
        risks = []

        # === 趋势评分（30分）===
        trend_scores = {
            TrendStatus.STRONG_BULL: 30,
            TrendStatus.BULL: 26,
            TrendStatus.WEAK_BULL: 18,
            TrendStatus.CONSOLIDATION: 12,
            TrendStatus.WEAK_BEAR: 8,
            TrendStatus.BEAR: 4,
            TrendStatus.STRONG_BEAR: 0,
        }
        trend_score = trend_scores.get(result.trend_status, 12)
        score += trend_score

        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            reasons.append(f"✅ {result.trend_status.value}，顺势做多")
        elif result.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
            risks.append(f"⚠️ {result.trend_status.value}，不宜做多")

        # === 乖离率评分（15分，强势趋势补偿）===
        score_before_bias = score
        bias = result.bias_ma5
        if bias != bias or bias is None:  # NaN or None defense
            bias = 0.0
        # Bias threshold: 5% for normal, consistent with LLM prompt "bias>5% no chasing"
        base_threshold = 5.0

        # Dynamic bias threshold based on ATR volatility
        if result.atr_20 and result.atr_20 > 0:
            current_price = result.current_price
            if current_price > 0:
                atr_pct = (result.atr_20 / current_price) * 100
                # Dynamic threshold: scale by volatility ratio
                # High volatility stocks (ATR%>3%) get wider threshold
                # Low volatility stocks (ATR%<1.5%) get tighter threshold
                volatility_factor = atr_pct / 2.0  # Normalize: ATR%=2% -> factor=1.0
                dynamic_threshold = base_threshold * max(0.7, min(1.5, volatility_factor))
                base_threshold = round(dynamic_threshold, 2)

        # Calculate trend stage metrics from df for bias threshold adjustment
        gain_20d = 0.0
        consecutive_up_days = 0
        if df is not None and len(df) >= 20:
            # 20-day cumulative gain
            close_20d_ago = df['close'].iloc[-20]
            gain_20d = (df['close'].iloc[-1] - close_20d_ago) / close_20d_ago * 100
            # Consecutive up days (from most recent)
            for i in range(len(df) - 1, 0, -1):
                if df['close'].iloc[i] > df['close'].iloc[i - 1]:
                    consecutive_up_days += 1
                else:
                    break

        # Bias threshold by trend stage (phase-based, not one-size-fits-all)
        is_strong_trend = False
        if result.trend_status in (TrendStatus.STRONG_BULL, TrendStatus.BULL):
            if gain_20d > 30 or consecutive_up_days >= 5:
                # Acceleration phase: highest topping risk, tightest threshold
                effective_threshold = 3.5
                is_strong_trend = True
            elif gain_20d > 15:
                # Main rally phase: standard threshold
                effective_threshold = base_threshold  # 5.0
                is_strong_trend = True
            else:
                # Early stage: allow slightly more room for trend tracking
                effective_threshold = 6.0
                is_strong_trend = True
        else:
            effective_threshold = base_threshold  # 5.0 for non-bull trends

        if bias < 0:
            # Price below MA5 (pullback)
            if bias > -3:
                score += 15
                reasons.append(f"✅ 价格略低于MA5({bias:.1f}%)，回踩买点")
            elif bias > -5:
                score += 12
                reasons.append(f"✅ 价格回踩MA5({bias:.1f}%)，观察支撑")
            else:
                # Check MA20 direction to distinguish oversold bounce vs trend breakdown
                if len(df) >= 5 and 'MA20' in df.columns:
                    ma20_today = float(df.iloc[-1]['MA20'])
                    ma20_5days_ago = float(df.iloc[-5]['MA20'])

                    if ma20_today > ma20_5days_ago:
                        # MA20 still rising - oversold bounce opportunity
                        score += 11
                        reasons.append(f"⭐ 超跌回踩({bias:.1f}%)但MA20仍上行，超跌反弹机会")
                    else:
                        # MA20 declining - trend breakdown, limit score
                        score += 4
                        risks.append(f"⚠️ 乖离率大({bias:.1f}%)且MA20下行，趋势可能破坏")
                else:
                    # Fix #7: linear interp instead of flat 6 (avoids dead-zone
                    # discontinuity when MA20 history unavailable). bias=-5 → 9,
                    # bias=-10 → 4, bias <= -15 → 2.
                    fallback = max(2, int(round(9 + (bias + 5) * 1.0)))
                    score += min(11, fallback)
                    risks.append(f"⚠️ 乖离率过大({bias:.1f}%)，缺 MA20 数据兜底")
        elif bias < 2:
            score += 14
            reasons.append(f"✅ 价格贴近MA5({bias:.1f}%)，介入好时机")
        elif bias > effective_threshold:
            # Check effective_threshold BEFORE base_threshold (effective can be < base in acceleration)
            if effective_threshold <= 3.5:
                score += 0
                risks.append(
                    f"🚫 加速见顶阶段(20日涨{gain_20d:.0f}%)，乖离率{bias:.1f}%过高，严禁追高！"
                )
            elif effective_threshold >= 6.0:
                score += 3
                risks.append(
                    f"⚠️ 趋势启动期乖离率偏高({bias:.1f}%>{effective_threshold:.1f}%)，追高需设严格止损"
                )
            else:
                score += 0
                risks.append(
                    f"🚫 乖离率过高({bias:.1f}%>{effective_threshold:.1f}%)，严禁追高！"
                )
        elif bias < base_threshold:
            score += 11
            reasons.append(f"⚡ 价格略高于MA5({bias:.1f}%)，可小仓介入")
        elif bias > base_threshold and is_strong_trend:
            if effective_threshold >= 6.0:
                score += 8
                reasons.append(
                    f"✅ 趋势启动期乖离率({bias:.1f}%)在容许范围内，可轻仓追踪"
                )
            else:
                score += 3
                risks.append(
                    f"⚠️ 强势趋势中乖离率偏高({bias:.1f}%)，追高风险大，注意止盈"
                )
        else:
            score += 3
            risks.append(
                f"❌ 乖离率过高({bias:.1f}%>{base_threshold:.1f}%)，严禁追高！"
            )

        # === Volume scoring (18 pts) ===
        bias_score_local = score - score_before_bias
        volume_scores = {
            VolumeStatus.SHRINK_VOLUME_DOWN: 18,  # Shrink pullback - adjusted below by market condition
            VolumeStatus.HEAVY_VOLUME_UP: 14,     # Heavy volume up - good
            VolumeStatus.NORMAL: 11,              # Normal volume
            VolumeStatus.SHRINK_VOLUME_UP: 7,     # Shrink volume up - weak
            VolumeStatus.HEAVY_VOLUME_DOWN: 0,    # Heavy volume down - worst
        }
        # Adjust SHRINK_VOLUME_DOWN score based on market trend
        if result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            if result.trend_status in (TrendStatus.STRONG_BEAR, TrendStatus.BEAR):
                vol_score = 0   # Bear market: shrink decline is normal trend, NOT a buy signal at all
            elif result.trend_status == TrendStatus.CONSOLIDATION:
                vol_score = 10  # Sideways: direction unclear, further discount
            else:
                vol_score = 18  # Bull market: healthy shrink pullback (washout)
        else:
            vol_score = volume_scores.get(result.volume_status, 9)

        # Fix #5: HEAVY_VOLUME_UP in late-acceleration phase is often distribution,
        # not real demand. Demote 14 → 6 when gain_20d>30 or 5+ consecutive up days.
        if (
            result.volume_status == VolumeStatus.HEAVY_VOLUME_UP
            and (gain_20d > 30 or consecutive_up_days >= 5)
        ):
            vol_score = 6
            risks.append("⚠️ 加速期放量上涨可能是出货，谨慎对待")

        # Fix #6: SHRINK_VOLUME_UP in strong/bull trends is 滞涨缩量 (top divergence),
        # not bullish. Demote 7 → 3.
        if (
            result.volume_status == VolumeStatus.SHRINK_VOLUME_UP
            and result.trend_status in (TrendStatus.STRONG_BULL, TrendStatus.BULL)
        ):
            vol_score = 3
            risks.append("⚠️ 强势趋势中缩量上涨为滞涨信号")

        # Penalty for volume exhaustion and abnormal volume
        if result.volume_exhaustion:
            vol_score = max(0, vol_score - 5)  # Volume exhaustion penalty
            risks.append("⚠️ 量能衰竭，上涨动力不足")
        if result.volume_warning:
            vol_score = max(0, vol_score - 15)  # Extreme volume warning (天量见顶)
            risks.append("🚫 天量警告！极可能见顶，严禁追高")

        score += vol_score

        if result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            reasons.append("✅ 缩量回调，主力洗盘")
        elif result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
            risks.append("⚠️ 放量下跌，注意风险")

        # === Support scoring (6 pts, was 12) ===
        # Issue-fix: MA5 support is structurally redundant with bias_ma5 dimension
        # (both measure "close to MA5"). Removed to avoid triple-counting "healthy
        # pullback" theme (bias 14 + volume 18 + ma5_support 7 = 40% of score on
        # one signal cluster). MA10 + MA20 retained as genuinely independent
        # multi-timeframe checks. 6 freed points redistributed to MACD and capital
        # flow (the two genuinely-independent under-weighted dimensions).
        score_before_support = score
        if result.support_ma10:
            score += 5
            reasons.append("✅ MA10支撑有效")
        # MA20 trend-integrity: price above rising MA20 = trend still intact.
        if df is not None and len(df) >= 5 and 'MA20' in df.columns:
            try:
                ma20_now = float(df.iloc[-1]['MA20'])
                ma20_prev = float(df.iloc[-5]['MA20'])
                if result.current_price > ma20_now and ma20_now > ma20_prev:
                    score += 1
                    reasons.append("✅ 价格站上上行 MA20，趋势完整")
            except (ValueError, KeyError):
                pass
        support_score_local = score - score_before_support

        # === MACD scoring (10 pts) ===
        # MACD ladder rescaled 10→13 (re-allocated from removed MA5-support).
        # Smoother gap: GOLDEN_CROSS_ZERO 13 → BULLISH 8 (was 10→6).
        macd_scores = {
            MACDStatus.GOLDEN_CROSS_ZERO: 13,  # Golden cross above zero - strongest
            MACDStatus.GOLDEN_CROSS: 11,       # Golden cross
            MACDStatus.CROSSING_UP: 10,        # Crossing above zero
            MACDStatus.BULLISH: 8,             # DIF>DEA>0
            MACDStatus.BEARISH: 1,             # Bearish
            MACDStatus.CROSSING_DOWN: 0,       # Crossing below zero
            MACDStatus.DEATH_CROSS: 0,         # Death cross
        }
        macd_score = macd_scores.get(result.macd_status, 4)
        score += macd_score

        if result.macd_status in [MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.GOLDEN_CROSS]:
            reasons.append(f"✅ {result.macd_signal}")
        elif result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.CROSSING_DOWN]:
            risks.append(f"⚠️ {result.macd_signal}")
        else:
            reasons.append(result.macd_signal)

        # === RSI scoring (5 pts) ===
        rsi_scores = {
            RSIStatus.OVERSOLD: 5,        # Oversold with stabilization - best
            RSIStatus.STRONG_BUY: 4,      # Strong momentum
            RSIStatus.NEUTRAL: 3,         # Neutral
            RSIStatus.WEAK: 2,            # Weak
            RSIStatus.OVERBOUGHT: 0,      # Overbought - worst
        }
        rsi_score = rsi_scores.get(result.rsi_status, 3)
        score += rsi_score

        if result.rsi_status in [RSIStatus.OVERSOLD, RSIStatus.STRONG_BUY]:
            reasons.append(f"✅ {result.rsi_signal}")
        elif result.rsi_status == RSIStatus.OVERBOUGHT:
            risks.append(f"⚠️ {result.rsi_signal}")
        else:
            reasons.append(result.rsi_signal)

        # === Capital flow scoring (13 pts, was 10) — score comes from external analysis ===
        # External contract stays 0-10 (no upstream change needed); we rescale ×1.3
        # internally to reflect higher weight in total score (re-allocated from
        # removed MA5-support). Fix #4 clip retained to defend against bad inputs.
        cf_raw = max(0, min(10, int(result.capital_flow_score or 0)))
        result.capital_flow_score = cf_raw   # Keep external-facing field at 0-10
        cf_score = round(cf_raw * 1.3)        # Internal weighted contribution 0-13
        score += cf_score
        if result.main_force_signal:
            if result.capital_flow_score >= 6:
                reasons.append(f"✅ {result.main_force_signal}")
            elif result.capital_flow_score >= 2:
                reasons.append(f"⚡ {result.main_force_signal}")
            elif result.main_force_signal and result.main_force_signal != "资金流向数据暂不可用":
                risks.append(f"⚠️ {result.main_force_signal}")
        if result.north_signal and result.north_signal != "北向资金数据暂不可用":
            reasons.append(result.north_signal)

        # Persist per-dimension scores for backtesting effectiveness analysis
        result.dim_trend_score = trend_score
        result.dim_bias_score = bias_score_local
        result.dim_volume_score = vol_score
        result.dim_support_score = support_score_local
        result.dim_macd_score = macd_score
        result.dim_rsi_score = rsi_score
        result.dim_capital_flow_score = cf_score   # Weighted 0-13 (raw 0-10 stays in result.capital_flow_score)

        # === Fix #3: Valuation penalty (PE) ===
        pe = float(result.pe_ratio or 0)
        if pe < 0:
            score -= 5
            risks.append(f"⚠️ 亏损股(PE={pe:.0f})，估值惩罚 -5")
        elif pe > 200:
            score -= 15
            risks.append(f"🚫 估值泡沫(PE={pe:.0f}>200)，惩罚 -15")
        elif pe > 100:
            score -= 8
            risks.append(f"⚠️ 估值偏高(PE={pe:.0f}>100)，惩罚 -8")

        # === Fix #1: Market environment adjustment with HARD CAPS ===
        # Multipliers tightened (strong_bear 0.85→0.75) AND hard score caps added so
        # a "perfect" stock in a bear market cannot trigger BUY signals via the
        # classifier (defense-in-depth alongside Fix #2 threshold bumps).
        market_env = result.market_environment
        if market_env == 'strong_bear':
            score = int(score * 0.75)
            score = min(score, 60)   # Hard cap: never reach BUY/STRONG_BUY in strong bear
            risks.append("⚠️ 大盘环境极弱，个股做多难度极大")
        elif market_env == 'bear':
            score = int(score * 0.85)
            score = min(score, 75)   # Hard cap: rarely reach STRONG_BUY in bear
            risks.append("⚠️ 大盘环境偏弱，个股做多难度加大")
        elif market_env == 'strong_bull':
            score = min(100, int(score * 1.05))
            reasons.append("✅ 大盘环境强势，顺势做多概率更高")
        # bull / neutral: no adjustment

        # Final clamp to [0, 100] (PE penalty may push below 0).
        score = max(0, min(100, score))

        # === 综合判断 ===
        result.signal_score = score
        result.signal_reasons = reasons
        result.risk_factors = risks

        # Classify buy signal using regime-aware unified logic (Fix #2)
        result.buy_signal = self.classify_buy_signal(
            score, result.trend_status, market_env
        )
    
    def format_analysis(self, result: TrendAnalysisResult) -> str:
        """
        格式化分析结果为文本

        Args:
            result: 分析结果

        Returns:
            格式化的分析文本
        """
        lines = [
            f"=== {result.code} 趋势分析 ===",
            f"",
            f"📊 趋势判断: {result.trend_status.value}",
            f"   均线排列: {result.ma_alignment}",
            f"   趋势强度: {result.trend_strength}/100",
            f"",
            f"📈 均线数据:",
            f"   现价: {result.current_price:.2f}",
            f"   MA5:  {result.ma5:.2f} (乖离 {result.bias_ma5:+.2f}%)",
            f"   MA10: {result.ma10:.2f} (乖离 {result.bias_ma10:+.2f}%)",
            f"   MA20: {result.ma20:.2f} (乖离 {result.bias_ma20:+.2f}%)",
            f"",
            f"📊 量能分析: {result.volume_status.value}",
            f"   量比(vs5日): {result.volume_ratio_5d:.2f}",
            f"   量能趋势: {result.volume_trend}",
            f"",
            f"📈 MACD指标: {result.macd_status.value}",
            f"   DIF: {result.macd_dif:.4f}",
            f"   DEA: {result.macd_dea:.4f}",
            f"   MACD: {result.macd_bar:.4f}",
            f"   信号: {result.macd_signal}",
            f"",
            f"📊 RSI指标: {result.rsi_status.value}",
            f"   RSI(6): {result.rsi_6:.1f}",
            f"   RSI(12): {result.rsi_12:.1f}",
            f"   RSI(24): {result.rsi_24:.1f}",
            f"   信号: {result.rsi_signal}",
            f"",
            f"💰 资金面: {result.capital_flow_score}/10",
            f"   主力: {result.main_force_signal or 'N/A'}",
            f"   北向: {result.north_signal or 'N/A'}",
            f"",
            f"🎯 操作建议: {result.buy_signal.value}",
            f"   综合评分: {result.signal_score}/100",
        ]

        if result.signal_reasons:
            lines.append(f"")
            lines.append(f"✅ 买入理由:")
            for reason in result.signal_reasons:
                lines.append(f"   {reason}")

        if result.risk_factors:
            lines.append(f"")
            lines.append(f"⚠️ 风险因素:")
            for risk in result.risk_factors:
                lines.append(f"   {risk}")

        return "\n".join(lines)
