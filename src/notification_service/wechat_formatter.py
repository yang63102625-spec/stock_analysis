# -*- coding: utf-8 -*-
"""
WeChat public account formatting module.

Responsibilities:
1. Format review reports for WeChat public account publishing
2. Add WeChat-specific elements (follow prompts, disclaimers, etc.)
3. Optimize layout and visual effects
4. Support multiple publishing platform formats (WeChat, Xiaohongshu, etc.)
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PublishPlatform(Enum):
    """Publishing platform enum."""
    WECHAT = "wechat"           # WeChat public account
    XIAOHONGSHU = "xiaohongshu" # Xiaohongshu
    WEIBO = "weibo"             # Weibo
    ZHIHU = "zhihu"             # Zhihu


@dataclass
class WechatConfig:
    """WeChat public account config."""
    account_name: str = "A股智能分析"
    slogan: str = "AI驱动的股市复盘，让投资更智能"
    qr_code_text: str = "扫码关注获取每日复盘"

    # Style config
    use_emoji: bool = True
    use_dividers: bool = True
    add_footer: bool = True
    add_disclaimer: bool = True

    # Content config
    max_length: int = 8000      # Max characters
    include_data_tables: bool = True
    include_charts_placeholder: bool = True


class WechatFormatter:
    """
    WeChat public account formatter.

    Features:
    1. Format review reports for WeChat public account
    2. Add follow prompts and interactive elements
    3. Optimize layout and visual effects
    4. Ensure compliance
    """

    def __init__(self, config: Optional[WechatConfig] = None):
        self.config = config or WechatConfig()

    def format_market_review(
        self,
        report: str,
        platform: PublishPlatform = PublishPlatform.WECHAT,
        add_interactive_elements: bool = True
    ) -> str:
        """
        Format market review report.

        Args:
            report: Original review report
            platform: Publishing platform
            add_interactive_elements: Whether to add interactive elements

        Returns:
            str: Formatted report
        """
        if platform == PublishPlatform.WECHAT:
            return self._format_for_wechat(report, add_interactive_elements)
        elif platform == PublishPlatform.XIAOHONGSHU:
            return self._format_for_xiaohongshu(report)
        else:
            return self._format_for_general(report)

    def _format_for_wechat(self, report: str, add_interactive: bool = True) -> str:
        """Format for WeChat public account."""

        # 1. Add title and intro
        formatted_report = self._add_wechat_header(report)

        # 2. Optimize body format
        formatted_report = self._optimize_wechat_content(formatted_report)

        # 3. Add chart placeholders
        if self.config.include_charts_placeholder:
            formatted_report = self._add_chart_placeholders(formatted_report)

        # 4. Add interactive elements
        if add_interactive:
            formatted_report = self._add_interactive_elements(formatted_report)

        # 5. Add footer
        if self.config.add_footer:
            formatted_report = self._add_wechat_footer(formatted_report)

        # 6. Length control
        formatted_report = self._control_length(formatted_report)

        return formatted_report

    def _add_wechat_header(self, report: str) -> str:
        """Add public account title and intro."""
        today = datetime.now().strftime('%Y年%m月%d日')

        title_match = re.search(r'##\s*📊\s*(\d{4}-\d{2}-\d{2})\s*A股智能复盘', report)
        if title_match:
            date_str = title_match.group(1)
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                today = date_obj.strftime('%Y年%m月%d日')
            except Exception:
                pass

        header = f"""# 📊 {today} A股智能复盘

> 🤖 **AI驱动的专业分析** | 📈 **数据说话，理性投资**
> 
> {self.config.slogan}

---

"""

        report = re.sub(r'##\s*📊.*?A股智能复盘\n*', '', report)

        return header + report

    def _optimize_wechat_content(self, content: str) -> str:
        """Optimize public account content format."""

        content = self._optimize_headings(content)
        content = self._optimize_quotes(content)
        content = self._optimize_lists(content)

        if self.config.use_dividers:
            content = self._add_section_dividers(content)

        content = self._optimize_tables(content)

        return content

    def _optimize_headings(self, content: str) -> str:
        """Optimize heading format."""
        content = re.sub(
            r'###\s*(🎯|📈|🔥|🌍|📊|💡|⚠️)\s*([一二三四五六七八九十]+、.*?)(?=\n)',
            r'### \1 **\2**',
            content
        )

        section_patterns = [
            (r'(### 🎯 \*\*一、.*?\*\*)', r'\n> \1\n'),
            (r'(### 📈 \*\*二、.*?\*\*)', r'\n> \1\n'),
            (r'(### 🔥 \*\*三、.*?\*\*)', r'\n> \1\n'),
        ]

        for pattern, replacement in section_patterns:
            content = re.sub(pattern, replacement, content)

        return content

    def _optimize_quotes(self, content: str) -> str:
        """Optimize quote block format."""
        content = re.sub(
            r'>\s*📊\s*\*\*市场数据速览\*\*',
            '> 📊 **【市场数据速览】**',
            content
        )

        content = re.sub(
            r'>\s*🎭\s*\*\*情绪指标\*\*',
            '> 🎭 **【情绪温度计】**',
            content
        )

        content = re.sub(
            r'>\s*🔥\s*\*\*热点板块\*\*',
            '> 🔥 **【今日热点追踪】**',
            content
        )

        return content

    def _optimize_lists(self, content: str) -> str:
        """Optimize list format."""
        content = re.sub(
            r'^-\s*\*\*(.*?)\*\*:\s*(.*?)$',
            r'📌 **\1**: \2',
            content,
            flags=re.MULTILINE
        )

        return content

    def _add_section_dividers(self, content: str) -> str:
        """Add section dividers."""
        content = re.sub(
            r'(### 🎯.*?\n.*?)(\n### 📈)',
            r'\1\n\n---\n\2',
            content,
            flags=re.DOTALL
        )

        content = re.sub(
            r'(### 📈.*?\n.*?)(\n### 🔥)',
            r'\1\n\n---\n\2',
            content,
            flags=re.DOTALL
        )

        content = re.sub(
            r'(### 🔥.*?\n.*?)(\n### 🌍)',
            r'\1\n\n---\n\2',
            content,
            flags=re.DOTALL
        )

        return content

    def _optimize_tables(self, content: str) -> str:
        """Optimize table format."""
        content = re.sub(
            r'(\| 指数 \| 最新 \| 涨跌幅 \| 成交额\(亿\) \|)',
            r'**📊 主要指数表现**\n\n\1',
            content
        )

        return content

    def _add_chart_placeholders(self, content: str) -> str:
        """Add chart placeholders."""
        chart_placeholder = """
> 📈 **【情绪指数走势图】**
> 
> *（此处插入恐慌贪婪指数走势图）*

"""

        content = re.sub(
            r'(### 📈.*?情绪解读.*?\n.*?)(\n---\n|\n### 🔥)',
            r'\1\n' + chart_placeholder + r'\2',
            content,
            flags=re.DOTALL
        )

        return content

    def _add_interactive_elements(self, content: str) -> str:
        """Add interactive elements."""
        interactive_section = """

---

## 💬 互动时间

**💭 你觉得明日市场会如何走？**

A. 继续上涨 📈  
B. 震荡整理 🔄  
C. 调整回落 📉

**在评论区留下你的观点，我们一起讨论！**

**📱 想要获取更多实时分析？**
- 点击"在看"支持我们
- 转发给需要的朋友  
- 留言互动获得回复

"""

        content = re.sub(
            r'(\n### ⚠️.*?风险提示)',
            interactive_section + r'\1',
            content
        )

        return content

    def _add_wechat_footer(self, content: str) -> str:
        """Add public account footer."""
        footer = f"""

---

## 📢 关于我们

**{self.config.account_name}** - {self.config.slogan}

🔹 **每日复盘**: 专业AI分析，数据驱动决策  
🔹 **实时提醒**: 重要市场变化及时通知  
🔹 **策略分享**: 量化选股，理性投资  

**📱 {self.config.qr_code_text}**

*（此处插入公众号二维码）*

---

## ⚠️ 免责声明

本文内容仅供学习研究，不构成任何投资建议。股市有风险，投资需谨慎。投资者应当根据自身情况独立做出投资决策，并承担相应风险。

**📊 数据来源**: 公开市场数据  
**🤖 分析工具**: AI智能分析系统  
**📅 发布时间**: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}

---

*如果觉得有用，请点击"在看"并转发支持！*

"""

        return content + footer

    def _control_length(self, content: str) -> str:
        """Control content length."""
        if len(content) <= self.config.max_length:
            return content

        logger.warning(f"内容长度 {len(content)} 超过限制 {self.config.max_length}，进行裁剪")

        content = re.sub(r'\n---\n', '\n', content)
        content = re.sub(r'\*（此处插入.*?）\*\n?', '', content)

        if len(content) > self.config.max_length:
            content = content[:self.config.max_length - 100] + "\n\n...\n\n*内容过长，完整版请查看原文*"

        return content

    def _format_for_xiaohongshu(self, report: str) -> str:
        """Format for Xiaohongshu."""
        report = re.sub(r'##\s*📊.*?A股智能复盘', '📊今日A股复盘来啦！', report)

        xiaohongshu_header = """📊今日A股复盘来啦！

姐妹们！今天的股市表现如何？
让AI来给大家分析分析～

#A股复盘 #股市分析 #投资理财 #AI分析

---

"""

        report = re.sub(r'### 🎯 \*\*一、市场概况\*\*', '🎯 市场表现', report)
        report = re.sub(r'### 📈 \*\*二、情绪解读\*\*', '📈 市场情绪', report)
        report = re.sub(r'### 🔥 \*\*三、热点聚焦\*\*', '🔥 今日热点', report)

        xiaohongshu_footer = """

---

💕 觉得有用记得点赞收藏哦～
📝 有问题欢迎评论区讨论！
🔔 关注我，每日复盘不错过！

#理财小白 #股票入门 #投资笔记

⚠️ 投资有风险，仅供参考学习～

"""

        return xiaohongshu_header + report + xiaohongshu_footer

    def _format_for_general(self, report: str) -> str:
        """General formatting."""
        return report

    def create_title_suggestions(self, report: str) -> List[str]:
        """
        Generate title suggestions based on report content.

        Args:
            report: Review report content

        Returns:
            List[str]: Title suggestions list
        """
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', report)
        date_str = date_match.group(1) if date_match else datetime.now().strftime('%Y-%m-%d')

        market_keywords = []
        if "上涨" in report:
            market_keywords.append("上涨")
        if "下跌" in report:
            market_keywords.append("下跌")
        if "震荡" in report:
            market_keywords.append("震荡")
        if "放量" in report:
            market_keywords.append("放量")
        if "缩量" in report:
            market_keywords.append("缩量")

        sector_matches = re.findall(r'(\w+板块|\w+概念)', report)
        hot_sectors = list(set(sector_matches))[:3]

        titles = [
            f"📊 {date_str} A股复盘：AI深度解析市场走势",
            f"🎯 今日复盘 | {' '.join(market_keywords[:2])}行情全解析",
            f"📈 A股智能复盘：{date_str} 市场情绪与热点追踪",
        ]

        if hot_sectors:
            titles.append(f"🔥 {date_str} 复盘：{hot_sectors[0]}领涨，后市如何？")

        if "恐慌" in report:
            titles.append("⚠️ 市场恐慌情绪升温，现在该如何操作？")
        elif "贪婪" in report:
            titles.append("🚨 市场贪婪情绪高涨，注意风险控制！")

        return titles[:5]

    def generate_summary(self, report: str, max_length: int = 200) -> str:
        """
        Generate report summary.

        Args:
            report: Full report
            max_length: Max length

        Returns:
            str: Report summary
        """
        market_summary = ""
        market_match = re.search(r'### 🎯.*?市场概况.*?\n(.*?)(?=\n###|\n---|\Z)', report, re.DOTALL)
        if market_match:
            market_summary = market_match.group(1).strip()[:100]

        strategy_summary = ""
        strategy_match = re.search(r'### 💡.*?策略建议.*?\n(.*?)(?=\n###|\n---|\Z)', report, re.DOTALL)
        if strategy_match:
            strategy_summary = strategy_match.group(1).strip()[:100]

        summary_parts = []
        if market_summary:
            summary_parts.append(market_summary)
        if strategy_summary:
            summary_parts.append(strategy_summary)

        summary = "。".join(summary_parts)

        if len(summary) > max_length:
            summary = summary[:max_length - 3] + "..."

        return summary or "AI智能分析今日A股市场表现，提供专业投资建议。"
