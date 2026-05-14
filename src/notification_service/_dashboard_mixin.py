# -*- coding: utf-8 -*-
"""``_DashboardMixin``: dashboard / WeChat-dashboard report generators.

Split out of :mod:`.aggregator` to keep each file ≤ 800 lines per
``code-quality.mdc`` rule §1.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.analyzer import AnalysisResult
from src.config import get_config
from src.enums import ReportType
from src.utils.data_processing import normalize_model_used

logger = logging.getLogger(__name__)


class _DashboardMixin:
    """Dashboard-style report generation methods for NotificationService."""

    def generate_dashboard_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        Generate decision dashboard format daily report.

        Format: market overview + important info + core conclusion + data perspective + battle plan

        Args:
            results: Analysis results list
            report_date: Report date (default today)

        Returns:
            Markdown formatted decision dashboard report
        """
        config = get_config()
        if results:
            from src.services.report_renderer import render
            out = render(
                platform='markdown',
                results=results,
                report_date=report_date,
                summary_only=self._report_summary_only,
                extra_context=self._get_history_compare_context(results),
            )
            if out:
                return out

        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))

        report_lines = [
            f"# 🎯 {report_date} 决策仪表盘",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}",
        ]

        # Analysis summary (Issue #112)
        if results:
            report_lines.extend([
                "",
                "## 📊 分析结果摘要",
            ])
            for r in sorted_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                display_name = self._escape_md(r.name)
                report_lines.append(
                    f"{signal_emoji} **{display_name}({r.code})**: {r.operation_advice} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction}"
                )
            report_lines.extend(["---", ""])

        # Per-stock decision dashboard (Issue #262: skip details in summary_only mode)
        if not self._report_summary_only:
            for result in sorted_results:
                signal_text, signal_emoji, signal_tag = self._get_signal_level(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}

                raw_name = (
                    result.name if result.name and not result.name.startswith('股票')
                    else f'股票{result.code}'
                )
                stock_name = self._escape_md(raw_name)

                report_lines.extend([
                    "",
                    f"## {signal_emoji} {stock_name} ({result.code})",
                ])

                # Intelligence section
                intel = dashboard.get('intelligence', {}) if dashboard else {}
                if intel:
                    report_lines.append("### 📰 重要信息速览")
                    if intel.get('sentiment_summary'):
                        report_lines.append(f"**💭 舆情情绪**: {intel['sentiment_summary']}")
                    if intel.get('earnings_outlook'):
                        report_lines.append(f"**📊 业绩预期**: {intel['earnings_outlook']}")
                    risk_alerts = intel.get('risk_alerts', [])
                    if risk_alerts:
                        report_lines.append("**🚨 风险警报**:")
                        for alert in risk_alerts:
                            report_lines.append(f"- {alert}")
                    catalysts = intel.get('positive_catalysts', [])
                    if catalysts:
                        report_lines.append("**✨ 利好催化**:")
                        for cat in catalysts:
                            report_lines.append(f"- {cat}")
                    if intel.get('latest_news'):
                        report_lines.append(f"**📢 最新动态**: {intel['latest_news']}")

                # Core conclusion
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                one_sentence = core.get('one_sentence', result.analysis_summary)
                time_sense = core.get('time_sensitivity', '本周内')
                pos_advice = core.get('position_advice', {})

                report_lines.extend([
                    "### 📌 核心结论",
                    f"**{signal_emoji} {signal_text}** | {result.trend_prediction}",
                    "",
                    f"> **一句话决策**: {one_sentence}",
                    "",
                    f"⏰ **时效性**: {time_sense}",
                ])
                if pos_advice:
                    report_lines.extend([
                        "",
                        "| 持仓情况 | 操作建议 |",
                        "|---------|---------|" ,
                        f"| 🆕 **空仓者** | {pos_advice.get('no_position', result.operation_advice)} |",
                        f"| 💼 **持仓者** | {pos_advice.get('has_position', '继续持有')} |",
                    ])

                self._append_market_snapshot(report_lines, result)

                # Data perspective
                data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
                if data_persp:
                    trend_data = data_persp.get('trend_status', {})
                    price_data = data_persp.get('price_position', {})
                    vol_data = data_persp.get('volume_analysis', {})
                    chip_data = data_persp.get('chip_structure', {})

                    report_lines.append("### 📊 数据透视")
                    if trend_data:
                        is_bullish = "✅ 是" if trend_data.get('is_bullish', False) else "❌ 否"
                        report_lines.append(
                            f"**均线排列**: {trend_data.get('ma_alignment', 'N/A')} | "
                            f"多头排列: {is_bullish} | 趋势强度: {trend_data.get('trend_score', 'N/A')}/100"
                        )
                    if price_data:
                        bias_status = price_data.get('bias_status', 'N/A')
                        bias_emoji = (
                            "✅" if bias_status == "安全"
                            else ("⚠️" if bias_status == "警戒" else "🚨")
                        )
                        report_lines.extend([
                            "",
                            "| 价格指标 | 数值 |",
                            "|---------|------|",
                            f"| 当前价 | {price_data.get('current_price', 'N/A')} |",
                            f"| MA5 | {price_data.get('ma5', 'N/A')} |",
                            f"| MA10 | {price_data.get('ma10', 'N/A')} |",
                            f"| MA20 | {price_data.get('ma20', 'N/A')} |",
                            f"| 乖离率(MA5) | {price_data.get('bias_ma5', 'N/A')}% {bias_emoji}{bias_status} |",
                            f"| 支撑位 | {price_data.get('support_level', 'N/A')} |",
                            f"| 压力位 | {price_data.get('resistance_level', 'N/A')} |",
                        ])
                    if vol_data:
                        report_lines.extend([
                            f"**量能**: 量比 {vol_data.get('volume_ratio', 'N/A')} "
                            f"({vol_data.get('volume_status', '')}) | "
                            f"换手率 {vol_data.get('turnover_rate', 'N/A')}%",
                            f"💡 *{vol_data.get('volume_meaning', '')}*",
                        ])
                    if chip_data:
                        chip_health = chip_data.get('chip_health', 'N/A')
                        chip_emoji = (
                            "✅" if chip_health == "健康"
                            else ("⚠️" if chip_health == "一般" else "🚨")
                        )
                        report_lines.append(
                            f"**筹码**: 获利比例 {chip_data.get('profit_ratio', 'N/A')} | "
                            f"平均成本 {chip_data.get('avg_cost', 'N/A')} | "
                            f"集中度 {chip_data.get('concentration', 'N/A')} {chip_emoji}{chip_health}"
                        )

                # Battle plan
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                if battle:
                    report_lines.append("### 🎯 作战计划")
                    sniper = battle.get('sniper_points', {})
                    if sniper:
                        report_lines.extend([
                            "**📍 狙击点位**",
                            "| 点位类型 | 价格 |",
                            "|---------|------|",
                            f"| 🎯 理想买入点 | {self._clean_sniper_value(sniper.get('ideal_buy', 'N/A'))} |",
                            f"| 🔵 次优买入点 | {self._clean_sniper_value(sniper.get('secondary_buy', 'N/A'))} |",
                            f"| 🛑 止损位 | {self._clean_sniper_value(sniper.get('stop_loss', 'N/A'))} |",
                            f"| 🎊 目标位 | {self._clean_sniper_value(sniper.get('take_profit', 'N/A'))} |",
                        ])
                    position = battle.get('position_strategy', {})
                    if position:
                        report_lines.extend([
                            f"**💰 仓位建议**: {position.get('suggested_position', 'N/A')}",
                            f"- 建仓策略: {position.get('entry_plan', 'N/A')}",
                            f"- 风控策略: {position.get('risk_control', 'N/A')}",
                        ])
                    checklist = battle.get('action_checklist', []) if battle else []
                    if checklist:
                        report_lines.append("**✅ 检查清单**")
                        for item in checklist:
                            report_lines.append(f"- {item}")

                if not dashboard:
                    pass

                report_lines.append("---")

        report_lines.append(f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        # Post-process: collapse multiple blank lines into one
        result = "\n".join(report_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip()

    def generate_wechat_dashboard(self, results: List[AnalysisResult]) -> str:
        """
        Generate compact WeChat decision dashboard (within 4000 chars).

        Only keeps core conclusion and sniper points.

        Args:
            results: Analysis results list

        Returns:
            Compact decision dashboard
        """
        config = get_config()
        if results:
            from src.services.report_renderer import render
            out = render(
                platform='wechat',
                results=results,
                report_date=datetime.now().strftime('%Y-%m-%d'),
                summary_only=self._report_summary_only,
            )
            if out:
                return out

        report_date = datetime.now().strftime('%Y-%m-%d')

        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))

        lines = [
            f"## 🎯 {report_date} 决策仪表盘",
            "",
            f"> {len(results)}只股票 | 🟢买入:{buy_count} 🟡观望:{hold_count} 🔴卖出:{sell_count}",
            "",
        ]

        # Issue #262: summary_only mode
        if self._report_summary_only:
            lines.append("**📊 分析结果摘要**")
            lines.append("")
            for r in sorted_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                stock_name = self._escape_md(
                    r.name if r.name and not r.name.startswith('股票') else f'股票{r.code}'
                )
                lines.append(
                    f"{signal_emoji} **{stock_name}({r.code})**: {r.operation_advice} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction}"
                )
        else:
            for result in sorted_results:
                signal_text, signal_emoji, _ = self._get_signal_level(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                intel = dashboard.get('intelligence', {}) if dashboard else {}

                stock_name = (
                    result.name if result.name and not result.name.startswith('股票')
                    else f'股票{result.code}'
                )
                stock_name = self._escape_md(stock_name)

                # Title: emoji + name + signal + score
                lines.append(
                    f"{signal_emoji} {stock_name}({result.code}) | {signal_text} | "
                    f"{result.sentiment_score}分"
                )

                # One-sentence decision
                one_sentence = (
                    core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
                )
                if one_sentence:
                    lines.append(f"📌 {one_sentence[:80]}")

                # Intelligence: earnings + sentiment in one line
                info_parts = []
                if intel.get('earnings_outlook'):
                    info_parts.append(f"📊 业绩:{intel['earnings_outlook'][:40]}")
                if intel.get('sentiment_summary'):
                    info_parts.append(f"💭 舆情:{intel['sentiment_summary'][:35]}")
                if info_parts:
                    lines.append(" | ".join(info_parts))

                # Risks: compact single line (comma-separated)
                risks = intel.get('risk_alerts', []) if intel else []
                if risks:
                    risk_items = [r[:30] for r in risks[:3]]
                    lines.append(f"🚨 {', '.join(risk_items)}")

                # Catalysts: compact single line (comma-separated)
                catalysts = intel.get('positive_catalysts', []) if intel else []
                if catalysts:
                    cat_items = [c[:30] for c in catalysts[:3]]
                    lines.append(f"✨ {', '.join(cat_items)}")

                # Sniper points + position size in one line
                sniper = battle.get('sniper_points', {}) if battle else {}
                if sniper:
                    ideal_buy = sniper.get('ideal_buy', '')
                    stop_loss = sniper.get('stop_loss', '')
                    take_profit = sniper.get('take_profit', '')
                    points = []
                    if ideal_buy:
                        points.append(f"🎯买:{ideal_buy[:12]}")
                    if stop_loss:
                        points.append(f"🛑损:{stop_loss[:12]}")
                    if take_profit:
                        points.append(f"🎊标:{take_profit[:12]}")
                    if points:
                        lines.append(" | ".join(points))

                # Position advice: compact single line
                pos_advice = core.get('position_advice', {}) if core else {}
                if pos_advice:
                    pos_parts = []
                    no_pos = pos_advice.get('no_position', '')
                    has_pos = pos_advice.get('has_position', '')
                    if no_pos:
                        pos_parts.append(f"🆕 {no_pos[:40]}")
                    if has_pos:
                        pos_parts.append(f"💼 {has_pos[:40]}")
                    if pos_parts:
                        lines.append(" | ".join(pos_parts))

                # Checklist: only show failed items, inline
                checklist = battle.get('action_checklist', []) if battle else []
                if checklist:
                    failed_checks = [c for c in checklist if c.startswith('❌') or c.startswith('⚠️')]
                    if failed_checks:
                        lines.append("⚠️ " + "; ".join(c[:30] for c in failed_checks[:3]))

                # Compact separator between stocks
                lines.append("────")

        lines.append(f"*生成时间: {datetime.now().strftime('%H:%M')}*")
        models = self._collect_models_used(results)
        if models:
            lines.append(f"*分析模型: {', '.join(models)}*")

        content = "\n".join(lines)

        return content

