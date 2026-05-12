# -*- coding: utf-8 -*-
"""Trend-analysis enums + ``TrendAnalysisResult`` data class.

Split out of :mod:`src.stock_analyzer` so that helper mixins can import
these symbols without forming a circular import with the main module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TrendStatus(Enum):
    """趋势状态枚举"""
    STRONG_BULL = "强势多头"      # MA5 > MA10 > MA20，且间距扩大
    BULL = "多头排列"             # MA5 > MA10 > MA20
    WEAK_BULL = "弱势多头"        # MA5 > MA10，但 MA10 < MA20
    CONSOLIDATION = "盘整"        # 均线缠绕
    WEAK_BEAR = "弱势空头"        # MA5 < MA10，但 MA10 > MA20
    BEAR = "空头排列"             # MA5 < MA10 < MA20
    STRONG_BEAR = "强势空头"      # MA5 < MA10 < MA20，且间距扩大


class VolumeStatus(Enum):
    """量能状态枚举"""
    HEAVY_VOLUME_UP = "放量上涨"       # 量价齐升
    HEAVY_VOLUME_DOWN = "放量下跌"     # 放量杀跌
    SHRINK_VOLUME_UP = "缩量上涨"      # 无量上涨
    SHRINK_VOLUME_DOWN = "缩量回调"    # 缩量回调（好）
    NORMAL = "量能正常"


class BuySignal(Enum):
    """买入信号枚举"""
    STRONG_BUY = "强烈买入"       # 多条件满足
    BUY = "买入"                  # 基本条件满足
    HOLD = "持有"                 # 已持有可继续
    WAIT = "观望"                 # 等待更好时机
    SELL = "卖出"                 # 趋势转弱
    STRONG_SELL = "强烈卖出"      # 趋势破坏


class MACDStatus(Enum):
    """MACD状态枚举"""
    GOLDEN_CROSS_ZERO = "零轴上金叉"      # DIF上穿DEA，且在零轴上方
    GOLDEN_CROSS = "金叉"                # DIF上穿DEA
    BULLISH = "多头"                    # DIF>DEA>0
    CROSSING_UP = "上穿零轴"             # DIF上穿零轴
    CROSSING_DOWN = "下穿零轴"           # DIF下穿零轴
    BEARISH = "空头"                    # DIF<DEA<0
    DEATH_CROSS = "死叉"                # DIF下穿DEA


class RSIStatus(Enum):
    """RSI状态枚举"""
    OVERBOUGHT = "超买"        # RSI > 70
    STRONG_BUY = "强势买入"    # 50 < RSI < 70
    NEUTRAL = "中性"          # 40 <= RSI <= 60
    WEAK = "弱势"             # 30 < RSI < 40
    OVERSOLD = "超卖"         # RSI < 30


@dataclass
class TrendAnalysisResult:
    """趋势分析结果"""
    code: str
    
    # 趋势判断
    trend_status: TrendStatus = TrendStatus.CONSOLIDATION
    ma_alignment: str = ""           # 均线排列描述
    trend_strength: float = 0.0      # 趋势强度 0-100
    
    # 均线数据
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    current_price: float = 0.0
    
    # 乖离率（与 MA5 的偏离度）
    bias_ma5: float = 0.0            # (Close - MA5) / MA5 * 100
    bias_ma10: float = 0.0
    bias_ma20: float = 0.0
    
    # 量能分析
    volume_status: VolumeStatus = VolumeStatus.NORMAL
    volume_ratio_5d: float = 0.0     # 当日成交量/5日均量
    volume_ratio_3d: float = 1.0     # Today volume / 3-day average
    volume_ratio_10d: float = 1.0    # Today volume / 10-day average
    volume_ratio_20d: float = 1.0    # Today volume / 20-day average
    volume_warning: str = ""         # Mega volume warning message
    volume_exhaustion: bool = False  # Volume exhaustion flag
    volume_trend: str = ""           # 量能趋势描述

    # ATR volatility
    atr_20: float = 0.0              # 20-day Average True Range

    # 支撑压力
    support_ma5: bool = False        # MA5 是否构成支撑
    support_ma10: bool = False       # MA10 是否构成支撑
    resistance_levels: List[float] = field(default_factory=list)
    support_levels: List[float] = field(default_factory=list)

    # MACD 指标
    macd_dif: float = 0.0          # DIF 快线
    macd_dea: float = 0.0          # DEA 慢线
    macd_bar: float = 0.0           # MACD 柱状图
    macd_status: MACDStatus = MACDStatus.BULLISH
    macd_signal: str = ""            # MACD 信号描述

    # RSI 指标
    rsi_6: float = 0.0              # RSI(6) 短期
    rsi_12: float = 0.0             # RSI(12) 中期
    rsi_24: float = 0.0             # RSI(24) 长期
    rsi_status: RSIStatus = RSIStatus.NEUTRAL
    rsi_signal: str = ""              # RSI 信号描述

    # Capital flow (external source, filled by caller)
    capital_flow_score: int = 0       # 0-10, capital flow score
    main_force_signal: str = ""       # Main force activity description
    north_signal: str = ""            # North-bound capital description

    # Valuation (optional, filled by caller for PE penalty)
    pe_ratio: float = 0.0             # 0 or NaN = unavailable, no penalty applied

    # 买入信号
    buy_signal: BuySignal = BuySignal.WAIT
    signal_score: int = 0            # 综合评分 0-100
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)

    # Market environment (broad market condition for score adjustment)
    market_environment: str = "neutral"  # 'strong_bull', 'bull', 'neutral', 'bear', 'strong_bear'

    # Per-dimension scores for backtesting effectiveness analysis
    dim_trend_score: int = 0           # 0-30
    dim_bias_score: int = 0            # 0-15
    dim_volume_score: int = 0          # 0-18
    dim_support_score: int = 0         # 0-6   (was 0-12; removed redundant MA5-support, kept MA10 + MA20-integrity)
    dim_macd_score: int = 0            # 0-13  (was 0-10; re-allocated from support)
    dim_rsi_score: int = 0             # 0-5
    dim_capital_flow_score: int = 0    # 0-13  (was 0-10; re-allocated from support; external source still 0-10)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'trend_status': self.trend_status.value,
            'ma_alignment': self.ma_alignment,
            'trend_strength': self.trend_strength,
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'ma60': self.ma60,
            'current_price': self.current_price,
            'bias_ma5': self.bias_ma5,
            'bias_ma10': self.bias_ma10,
            'bias_ma20': self.bias_ma20,
            'volume_status': self.volume_status.value,
            'volume_ratio_5d': self.volume_ratio_5d,
            'volume_ratio_3d': self.volume_ratio_3d,
            'volume_ratio_10d': self.volume_ratio_10d,
            'volume_ratio_20d': self.volume_ratio_20d,
            'volume_warning': self.volume_warning,
            'volume_exhaustion': self.volume_exhaustion,
            'volume_trend': self.volume_trend,
            'atr_20': self.atr_20,
            'support_ma5': self.support_ma5,
            'support_ma10': self.support_ma10,
            'buy_signal': self.buy_signal.value,
            'signal_score': self.signal_score,
            'signal_reasons': self.signal_reasons,
            'risk_factors': self.risk_factors,
            'macd_dif': self.macd_dif,
            'macd_dea': self.macd_dea,
            'macd_bar': self.macd_bar,
            'macd_status': self.macd_status.value,
            'macd_signal': self.macd_signal,
            'rsi_6': self.rsi_6,
            'rsi_12': self.rsi_12,
            'rsi_24': self.rsi_24,
            'rsi_status': self.rsi_status.value,
            'rsi_signal': self.rsi_signal,
            'capital_flow_score': self.capital_flow_score,
            'main_force_signal': self.main_force_signal,
            'north_signal': self.north_signal,
            'dim_trend_score': self.dim_trend_score,
            'dim_bias_score': self.dim_bias_score,
            'dim_volume_score': self.dim_volume_score,
            'dim_support_score': self.dim_support_score,
            'dim_macd_score': self.dim_macd_score,
            'dim_rsi_score': self.dim_rsi_score,
            'dim_capital_flow_score': self.dim_capital_flow_score,
            'market_environment': self.market_environment,
        }


