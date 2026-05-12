# -*- coding: utf-8 -*-
"""Dataclasses + enums consumed by ``src.enhanced_market_analyzer``.

Extracted from ``enhanced_market_analyzer.py`` to keep that module
under the 800-line ceiling (rule §1). Public re-exports are still
available via ``src.enhanced_market_analyzer`` so existing call sites
keep working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple

from src.market_analyzer import MarketOverview


class MarketSentiment(Enum):
    """市场情绪枚举"""
    EXTREME_FEAR = "极度恐慌"
    FEAR = "恐慌"
    NEUTRAL = "中性"
    GREED = "贪婪"
    EXTREME_GREED = "极度贪婪"


@dataclass
class SentimentAnalysis:
    """市场情绪分析数据"""
    sentiment: MarketSentiment = MarketSentiment.NEUTRAL
    fear_greed_index: float = 50.0
    market_heat: float = 0.0
    fund_flow_trend: str = "平衡"
    volatility_level: str = "正常"

    volume_ratio: float = 1.0
    turnover_rate: float = 0.0
    new_high_low_ratio: float = 0.0

    def get_sentiment_description(self) -> str:
        """获取情绪描述"""
        descriptions = {
            MarketSentiment.EXTREME_FEAR: "市场极度恐慌，抄底机会可能出现",
            MarketSentiment.FEAR: "市场情绪偏向恐慌，谨慎观望为主",
            MarketSentiment.NEUTRAL: "市场情绪相对平稳，观察方向选择",
            MarketSentiment.GREED: "市场情绪偏向乐观，注意风险控制",
            MarketSentiment.EXTREME_GREED: "市场极度乐观，警惕回调风险",
        }
        return descriptions.get(self.sentiment, "情绪中性")


@dataclass
class SectorHotspot:
    """板块热点分析"""
    name: str
    change_pct: float
    fund_inflow: float = 0.0
    leading_stocks: List[str] = field(default_factory=list)
    concept_tags: List[str] = field(default_factory=list)
    sustainability: str = "待观察"
    catalyst: str = ""
    risk_warning: str = ""


@dataclass
class ExternalEnvironment:
    """外界环境分析"""
    policy_impact: str = ""
    international_market: str = ""
    macro_data: str = ""
    currency_trend: str = ""
    commodity_trend: str = ""

    us_futures: Dict[str, float] = field(default_factory=dict)
    asia_markets: Dict[str, float] = field(default_factory=dict)
    vix_index: float = 0.0


@dataclass
class TechnicalAnalysis:
    """技术面分析"""
    key_support: float = 0.0
    key_resistance: float = 0.0
    trend_direction: str = "震荡"
    volume_price_relation: str = ""
    market_structure: str = ""

    ma_alignment: str = ""
    macd_signal: str = ""
    rsi_level: float = 50.0

    def get_trend_emoji(self) -> str:
        """获取趋势 emoji"""
        trend_map = {
            "强势上涨": "🚀",
            "温和上涨": "📈",
            "震荡整理": "🔄",
            "温和下跌": "📉",
            "快速下跌": "💥",
        }
        return trend_map.get(self.trend_direction, "🔄")


@dataclass
class EnhancedMarketReport:
    """增强版市场报告"""
    date: str
    basic_overview: MarketOverview
    sentiment_analysis: SentimentAnalysis
    sector_hotspots: List[SectorHotspot] = field(default_factory=list)
    external_environment: ExternalEnvironment = field(default_factory=ExternalEnvironment)
    technical_analysis: TechnicalAnalysis = field(default_factory=TechnicalAnalysis)
    market_news: List[Dict] = field(default_factory=list)

    strategy_advice: str = ""
    position_suggestion: str = ""
    risk_level: str = "中等"

    def get_overall_rating(self) -> Tuple[str, str]:
        """获取整体评级和建议"""
        sentiment_score = self.sentiment_analysis.fear_greed_index
        if sentiment_score >= 80:
            return "高风险", "建议减仓观望，警惕回调"
        if sentiment_score >= 60:
            return "中高风险", "适度参与，控制仓位"
        if sentiment_score >= 40:
            return "中性", "均衡配置，观察方向"
        if sentiment_score >= 20:
            return "中低风险", "可适度加仓，精选个股"
        return "低风险", "积极布局，关注反弹机会"


__all__ = [
    "EnhancedMarketReport",
    "ExternalEnvironment",
    "MarketSentiment",
    "SectorHotspot",
    "SentimentAnalysis",
    "TechnicalAnalysis",
]
