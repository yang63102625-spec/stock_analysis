# -*- coding: utf-8 -*-
"""Pure helpers to compose market recap LLM prompts (base and enhanced)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

from src.core.market_profile import MarketProfile
from src.core.market_strategy import MarketStrategyBlueprint

if TYPE_CHECKING:
    from src._enhanced_market_types import EnhancedMarketReport
    from src.market_analyzer import MarketOverview


def build_indices_section(overview: MarketOverview) -> str:
    """Format major index bullet lines for review prompts."""
    lines: List[str] = []
    for idx in overview.indices:
        direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
        lines.append(f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n")
    return "".join(lines)


def build_stats_section(region: str, profile: MarketProfile, overview: MarketOverview) -> str:
    """Build the market statistics markdown block for daily review prompts."""
    if region == "us":
        if profile.has_market_stats:
            return f"""## Market Overview
- Up: {overview.up_count} | Down: {overview.down_count} | Flat: {overview.flat_count}
- Limit up: {overview.limit_up_count} | Limit down: {overview.limit_down_count}
- Total volume (CNY bn): {overview.total_amount:.0f}"""
        return "## Market Overview\n(US market has no equivalent advance/decline stats.)"

    if profile.has_market_stats:
        return f"""## 市场概况
- 上涨: {overview.up_count} 家 | 下跌: {overview.down_count} 家 | 平盘: {overview.flat_count} 家
- 涨停: {overview.limit_up_count} 家 | 跌停: {overview.limit_down_count} 家
- 两市成交额: {overview.total_amount:.0f} 亿元"""
    return "## 市场概况\n（美股暂无涨跌家数等统计）"


def build_sector_section(region: str, profile: MarketProfile, overview: MarketOverview) -> str:
    """Build the sector performance markdown block for daily review prompts."""
    top_sectors_text = ", ".join(
        [f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.top_sectors[:3]]
    )
    bottom_sectors_text = ", ".join(
        [f"{s['name']}({s['change_pct']:+.2f}%)" for s in overview.bottom_sectors[:3]]
    )
    if region == "us":
        if profile.has_sector_rankings:
            return f"""## Sector Performance
Leading: {top_sectors_text if top_sectors_text else "N/A"}
Lagging: {bottom_sectors_text if bottom_sectors_text else "N/A"}"""
        return "## Sector Performance\n(US sector data not available.)"

    if profile.has_sector_rankings:
        return f"""## 板块表现
领涨: {top_sectors_text if top_sectors_text else "暂无数据"}
领跌: {bottom_sectors_text if bottom_sectors_text else "暂无数据"}"""
    return "## 板块表现\n（美股暂无板块涨跌数据）"


def build_news_section(news: List[Any], limit: int = 6) -> str:
    """Format headline news snippets for review prompts."""
    parts: List[str] = []
    for i, n in enumerate(news[:limit], 1):
        if hasattr(n, "title"):
            title = n.title[:50] if n.title else ""
            snippet = n.snippet[:100] if n.snippet else ""
        else:
            title = n.get("title", "")[:50]
            snippet = n.get("snippet", "")[:100]
        parts.append(f"{i}. {title}\n   {snippet}\n")
    return "".join(parts)


def _compose_review_prompt_us(
    date_str: str,
    indices_placeholder: str,
    stats_block: str,
    sector_block: str,
    news_placeholder: str,
    data_no_indices_hint_en: str,
    strategy_block: str,
) -> str:
    return f"""You are a professional US/A/H market analyst. Please produce a concise US market recap report based on the data below.

[Requirements]
- Output pure Markdown only
- No JSON
- No code blocks
- Use emoji sparingly in headings (at most one per heading)

---

# Today's Market Data

## Date
{date_str}

## Major Indices
{indices_placeholder}

{stats_block}

{sector_block}

## Market News
{news_placeholder}

{data_no_indices_hint_en}

{strategy_block}

---

# Output Template (follow this structure)

## {date_str} US Market Recap

### 1. Market Summary
(2-3 sentences on overall market performance, index moves, volume)

### 2. Index Commentary
(Analyse S&P 500, Nasdaq, Dow and other major index moves.)

### 3. Fund Flows
(Interpret volume and flow implications)

### 4. Sector/Theme Highlights
(Analyze drivers behind leading/lagging sectors)

### 5. Outlook
(Short-term view based on price action and news)

### 6. Risk Alerts
(Key risks to watch)

### 7. Strategy Plan
(Provide risk-on/neutral/risk-off stance, position sizing guideline, and one invalidation trigger.)

---

Output the report content directly, no extra commentary.
"""


def _compose_review_prompt_cn(
    date_str: str,
    indices_placeholder: str,
    stats_block: str,
    sector_block: str,
    news_placeholder: str,
    data_no_indices_hint: str,
    strategy_block: str,
    prompt_index_hint: str,
) -> str:
    return f"""你是一位专业的A/H/美股市场分析师，请根据以下数据生成一份简洁的大盘复盘报告。

【重要】输出要求：
- 必须输出纯 Markdown 文本格式
- 禁止输出 JSON 格式
- 禁止输出代码块
- emoji 仅在标题处少量使用（每个标题最多1个）

---

# 今日市场数据

## 日期
{date_str}

## 主要指数
{indices_placeholder}

{stats_block}

{sector_block}

## 市场新闻
{news_placeholder}

{data_no_indices_hint}

{strategy_block}

---

# 输出格式模板（请严格按此格式输出）

## {date_str} 大盘复盘

### 一、市场总结
（2-3句话概括今日市场整体表现，包括指数涨跌、成交量变化）

### 二、指数点评
（{prompt_index_hint}）

### 三、资金动向
（解读成交额流向的含义）

### 四、热点解读
（分析领涨领跌板块背后的逻辑和驱动因素）

### 五、后市展望
（结合当前走势和新闻，给出明日市场预判）

### 六、风险提示
（需要关注的风险点）

### 七、策略计划
（给出进攻/均衡/防守结论，对应仓位建议，并给出一个触发失效条件；最后补充“建议仅供参考，不构成投资建议”。）

---

请直接输出复盘报告内容，不要输出其他说明文字。
"""


def compose_review_prompt(
    profile: MarketProfile,
    strategy: MarketStrategyBlueprint,
    region: str,
    overview: MarketOverview,
    news: List[Any],
) -> str:
    """Assemble the full daily market review LLM prompt."""
    indices_text = build_indices_section(overview)
    news_text = build_news_section(news)
    stats_block = build_stats_section(region, profile, overview)
    sector_block = build_sector_section(region, profile, overview)
    data_no_indices_hint = (
        "注意：由于行情数据获取失败，请主要根据【市场新闻】进行定性分析和总结，不要编造具体的指数点位。"
        if not indices_text
        else ""
    )
    indices_placeholder = (
        indices_text
        if indices_text
        else ("No index data (API error)" if region == "us" else "暂无指数数据（接口异常）")
    )
    news_placeholder = (
        news_text if news_text else ("No relevant news" if region == "us" else "暂无相关新闻")
    )
    strategy_block = strategy.to_prompt_block()
    if region == "us":
        data_no_indices_hint_en = (
            "Note: Market data fetch failed. Rely mainly on [Market News] for qualitative analysis. "
            "Do not invent index levels."
            if not indices_text
            else ""
        )
        return _compose_review_prompt_us(
            overview.date,
            indices_placeholder,
            stats_block,
            sector_block,
            news_placeholder,
            data_no_indices_hint_en,
            strategy_block,
        )
    return _compose_review_prompt_cn(
        overview.date,
        indices_placeholder,
        stats_block,
        sector_block,
        news_placeholder,
        data_no_indices_hint,
        strategy_block,
        profile.prompt_index_hint,
    )


def build_enhanced_indices_section(data: EnhancedMarketReport) -> str:
    """Format index lines for enhanced recap prompts."""
    lines: List[str] = []
    for idx in data.basic_overview.indices:
        direction = "↑" if idx.change_pct > 0 else "↓" if idx.change_pct < 0 else "-"
        lines.append(f"- {idx.name}: {idx.current:.2f} ({direction}{abs(idx.change_pct):.2f}%)\n")
    return "".join(lines)


def build_enhanced_sentiment_section(data: EnhancedMarketReport) -> str:
    """Format sentiment analysis for enhanced recap prompts."""
    sa = data.sentiment_analysis
    return f"""
情绪等级: {sa.sentiment.value}
恐慌贪婪指数: {sa.fear_greed_index:.1f}/100
市场热度: {sa.market_heat:.1f}/100
资金流向: {sa.fund_flow_trend}
"""


def build_enhanced_hotspots_section(data: EnhancedMarketReport) -> str:
    """Format sector hotspot lines for enhanced recap prompts."""
    parts: List[str] = []
    for hotspot in data.sector_hotspots[:5]:
        parts.append(f"- {hotspot.name}: {hotspot.change_pct:+.2f}% ({hotspot.sustainability})\n")
        if hotspot.concept_tags:
            parts.append(f"  概念: {', '.join(hotspot.concept_tags)}\n")
    return "".join(parts)


def build_enhanced_environment_section(data: EnhancedMarketReport) -> str:
    """Format external environment fields for enhanced recap prompts."""
    env = data.external_environment
    return f"""
政策面: {env.policy_impact}
国际市场: {env.international_market}
宏观数据: {env.macro_data}
"""


def build_enhanced_technical_section(data: EnhancedMarketReport) -> str:
    """Format technical analysis fields for enhanced recap prompts."""
    ta = data.technical_analysis
    return f"""
趋势方向: {ta.trend_direction}
关键支撑: {ta.key_support:.0f}
关键阻力: {ta.key_resistance:.0f}
量价关系: {ta.volume_price_relation}
市场结构: {ta.market_structure}
"""


def compose_enhanced_prompt(data: EnhancedMarketReport) -> str:
    """Assemble the enhanced (wechat-oriented) market recap LLM prompt."""
    indices_text = build_enhanced_indices_section(data)
    sentiment_text = build_enhanced_sentiment_section(data)
    hotspots_text = build_enhanced_hotspots_section(data)
    env_text = build_enhanced_environment_section(data)
    tech_text = build_enhanced_technical_section(data)
    bo = data.basic_overview
    return f"""你是一位资深的A股市场分析师，请根据以下全面的市场数据生成一份专业的大盘复盘报告，适合在公众号发布。

【重要】输出要求：
- 必须输出纯 Markdown 文本格式
- 语言风格要专业但易懂，适合普通投资者阅读
- 重点突出市场情绪、板块热点、外界环境等关键信息
- 给出明确的策略建议和风险提示

---

# 今日市场全面数据

## 日期
{data.date}

## 基础指数行情
{indices_text}

## 市场统计
- 上涨: {bo.up_count} 家 | 下跌: {bo.down_count} 家
- 涨停: {bo.limit_up_count} 家 | 跌停: {bo.limit_down_count} 家  
- 成交额: {bo.total_amount:.0f} 亿元

## 市场情绪分析
{sentiment_text}

## 板块热点分析
{hotspots_text}

## 外界环境分析
{env_text}

## 技术面分析
{tech_text}

---

# 输出格式模板（请严格按此格式输出）

## 📊 {data.date} A股智能复盘

### 🎯 一、市场概况
（用2-3句话概括今日市场整体表现，结合指数涨跌和成交量）

### 📈 二、情绪解读
（基于恐慌贪婪指数和市场热度，分析当前市场情绪状态及其含义）

### 🔥 三、热点聚焦
（深度解读领涨板块，分析背后的逻辑和催化剂，评估持续性）

### 🌍 四、外围影响
（分析政策面、国际市场等外界因素对A股的影响）

### 📊 五、技术研判
（从技术角度分析趋势、关键位置和量价关系）

### 💡 六、策略建议
（给出明确的操作建议，包括仓位配置和重点关注方向）

### ⚠️七、风险提示
（指出需要重点关注的风险点和应对策略）

---

请直接输出复盘报告内容，语言要专业权威，适合公众号读者。
"""
