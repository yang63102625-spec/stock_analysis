# -*- coding: utf-8 -*-
"""
Report aggregation mixin for NotificationService.

Contains all report generation methods (daily report, dashboard report,
wechat summary, brief report, single stock report, etc.).
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.analyzer import AnalysisResult
from src.config import get_config
from src.enums import ReportType
from src.utils.data_processing import normalize_model_used

logger = logging.getLogger(__name__)


class ReportAggregatorMixin:
    """
    Mixin that provides all report generation methods.

    Expects the host class to have:
      - self._report_summary_only: bool
      - self._history_compare_cache: dict
    """

    # Display name mapping for realtime data sources
    _SOURCE_DISPLAY_NAMES = {
        "tencent": "腾讯财经",
        "akshare_em": "东方财富",
        "akshare_sina": "新浪财经",
        "akshare_qq": "腾讯财经",
        "efinance": "东方财富(efinance)",
        "tushare": "Tushare Pro",
        "sina": "新浪财经",
        "fallback": "降级兜底",
    }

    def _normalize_report_type(self, report_type: Any) -> ReportType:
        """Normalize string/enum input into ReportType."""
        if isinstance(report_type, ReportType):
            return report_type
        return ReportType.from_str(report_type)

    def _get_history_compare_context(self, results: List[AnalysisResult]) -> Dict[str, Any]:
        """Fetch and cache history comparison data for markdown rendering."""
        config = get_config()
        history_compare_n = getattr(config, 'report_history_compare_n', 0)
        if history_compare_n <= 0 or not results:
            return {"history_by_code": {}}

        cache_key = (
            history_compare_n,
            tuple(sorted((r.code, getattr(r, 'query_id', '') or '') for r in results)),
        )
        if cache_key in self._history_compare_cache:
            return {"history_by_code": self._history_compare_cache[cache_key]}

        try:
            from src.services.history_comparison_service import get_signal_changes_batch

            exclude_ids = {
                r.code: r.query_id
                for r in results
                if getattr(r, 'query_id', None)
            }
            codes = list(dict.fromkeys(r.code for r in results))
            history_by_code = get_signal_changes_batch(
                codes,
                limit=history_compare_n,
                exclude_query_ids=exclude_ids,
            )
        except Exception as e:
            logger.debug("History comparison skipped: %s", e)
            history_by_code = {}

        self._history_compare_cache[cache_key] = history_by_code
        return {"history_by_code": history_by_code}

    def generate_aggregate_report(
        self,
        results: List[AnalysisResult],
        report_type: Any,
        report_date: Optional[str] = None,
    ) -> str:
        """Generate the aggregate report content used by merge/save/push paths."""
        normalized_type = self._normalize_report_type(report_type)
        if normalized_type == ReportType.BRIEF:
            return self.generate_brief_report(results, report_date=report_date)
        return self.generate_dashboard_report(results, report_date=report_date)

    def _collect_models_used(self, results: List[AnalysisResult]) -> List[str]:
        models: List[str] = []
        for result in results:
            model = normalize_model_used(getattr(result, "model_used", None))
            if model:
                models.append(model)
        return list(dict.fromkeys(models))

    @staticmethod
    def _escape_md(name: str) -> str:
        """Escape markdown special characters in stock names (e.g. *ST -> \\*ST)."""
        return name.replace('*', r'\*') if name else name

    @staticmethod
    def _clean_sniper_value(value: Any) -> str:
        """Normalize sniper point values and remove redundant label prefixes."""
        if value is None:
            return 'N/A'
        if isinstance(value, (int, float)):
            return str(value)
        if not isinstance(value, str):
            return str(value)
        if not value or value == 'N/A':
            return value
        prefixes = ['理想买入点：', '次优买入点：', '止损位：', '目标位：',
                     '理想买入点:', '次优买入点:', '止损位:', '目标位:']
        for prefix in prefixes:
            if value.startswith(prefix):
                return value[len(prefix):]
        return value

    def _get_signal_level(self, result: AnalysisResult) -> tuple:
        """
        Get signal level and color based on operation advice.

        Priority: advice string takes precedence over score.
        Score-based fallback is used only when advice doesn't match
        any known value.

        Returns:
            (signal_text, emoji, color_tag)
        """
        advice = result.operation_advice
        score = result.sentiment_score

        # Advice-first lookup (exact match takes priority)
        advice_map = {
            '强烈买入': ('强烈买入', '💚', '强买'),
            '买入': ('买入', '🟢', '买入'),
            '加仓': ('买入', '🟢', '买入'),
            '持有': ('持有', '🟡', '持有'),
            '观望': ('观望', '⚪', '观望'),
            '减仓': ('减仓', '🟠', '减仓'),
            '卖出': ('卖出', '🔴', '卖出'),
            '强烈卖出': ('卖出', '🔴', '卖出'),
        }
        if advice in advice_map:
            return advice_map[advice]

        # Score-based fallback when advice is unrecognized
        if score >= 80:
            return ('强烈买入', '💚', '强买')
        elif score >= 65:
            return ('买入', '🟢', '买入')
        elif score >= 55:
            return ('持有', '🟡', '持有')
        elif score >= 45:
            return ('观望', '⚪', '观望')
        elif score >= 35:
            return ('减仓', '🟠', '减仓')
        elif score < 35:
            return ('卖出', '🔴', '卖出')
        else:
            return ('观望', '⚪', '观望')

    def _append_market_snapshot(self, lines: List[str], result: AnalysisResult) -> None:
        snapshot = getattr(result, 'market_snapshot', None)
        if not snapshot:
            return

        lines.extend([
            "### 📈 当日行情",
            "",
            "| 收盘 | 昨收 | 开盘 | 最高 | 最低 | 涨跌幅 | 涨跌额 | 振幅 | 成交量 | 成交额 |",
            "|------|------|------|------|------|-------|-------|------|--------|--------|",
            f"| {snapshot.get('close', 'N/A')} | {snapshot.get('prev_close', 'N/A')} | "
            f"{snapshot.get('open', 'N/A')} | {snapshot.get('high', 'N/A')} | "
            f"{snapshot.get('low', 'N/A')} | {snapshot.get('pct_chg', 'N/A')} | "
            f"{snapshot.get('change_amount', 'N/A')} | {snapshot.get('amplitude', 'N/A')} | "
            f"{snapshot.get('volume', 'N/A')} | {snapshot.get('amount', 'N/A')} |",
        ])

        if "price" in snapshot:
            raw_source = snapshot.get('source', 'N/A')
            display_source = self._SOURCE_DISPLAY_NAMES.get(raw_source, raw_source)
            lines.extend([
                "",
                "| 当前价 | 量比 | 换手率 | 行情来源 |",
                "|-------|------|--------|----------|",
                f"| {snapshot.get('price', 'N/A')} | {snapshot.get('volume_ratio', 'N/A')} | "
                f"{snapshot.get('turnover_rate', 'N/A')} | {display_source} |",
            ])

        lines.append("")

    # ------------------------------------------------------------------
    # Report generators
    # ------------------------------------------------------------------

    def generate_daily_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        Generate detailed daily report in Markdown format.

        Args:
            results: Analysis results list
            report_date: Report date (default today)

        Returns:
            Markdown formatted daily report
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        report_lines = [
            f"# 📅 {report_date} 股票智能分析报告",
            "",
            f"> 共分析 **{len(results)}** 只股票 | 报告生成时间：{datetime.now().strftime('%H:%M:%S')}",
            "",
            "---",
            "",
        ]

        sorted_results = sorted(
            results,
            key=lambda x: x.sentiment_score,
            reverse=True
        )

        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0

        report_lines.extend([
            "## 📊 操作建议汇总",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 🟢 建议买入/加仓 | **{buy_count}** 只 |",
            f"| 🟡 建议持有/观望 | **{hold_count}** 只 |",
            f"| 🔴 建议减仓/卖出 | **{sell_count}** 只 |",
            f"| 📈 平均看多评分 | **{avg_score:.1f}** 分 |",
            "",
            "---",
            "",
        ])

        # Issue #262: summary_only mode
        if self._report_summary_only:
            report_lines.extend(["## 📊 分析结果摘要", ""])
            for r in sorted_results:
                emoji = r.get_emoji()
                report_lines.append(
                    f"{emoji} **{r.name}({r.code})**: {r.operation_advice} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction}"
                )
        else:
            report_lines.extend(["## 📈 个股详细分析", ""])
            for result in sorted_results:
                emoji = result.get_emoji()
                confidence_stars = (
                    result.get_confidence_stars() if hasattr(result, 'get_confidence_stars') else '⭐⭐'
                )

                report_lines.extend([
                    f"### {emoji} {result.name} ({result.code})",
                    "",
                    f"**操作建议：{result.operation_advice}** | **综合评分：{result.sentiment_score}分** | "
                    f"**趋势预测：{result.trend_prediction}** | **置信度：{confidence_stars}**",
                    "",
                ])

                self._append_market_snapshot(report_lines, result)

                if result.analysis_summary:
                    report_lines.extend([
                        "#### 📝 综合分析",
                        result.analysis_summary,
                        "",
                    ])

                if hasattr(result, 'search_performed') and result.search_performed:
                    report_lines.append("*🔍 已执行联网搜索*")
                if hasattr(result, 'data_sources') and result.data_sources:
                    report_lines.append(f"*📋 数据来源：{result.data_sources}*")

                if not result.success and result.error_message:
                    report_lines.extend([
                        "",
                        f"❌ **分析异常**：{result.error_message[:100]}",
                    ])

                report_lines.extend([
                    "",
                    "---",
                    "",
                ])

        report_lines.extend([
            "",
            f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        return "\n".join(report_lines)

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
        if getattr(config, 'report_renderer_enabled', False) and results:
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
            "",
        ]

        # Analysis summary (Issue #112)
        if results:
            report_lines.extend([
                "## 📊 分析结果摘要",
                "",
            ])
            for r in sorted_results:
                _, signal_emoji, _ = self._get_signal_level(r)
                display_name = self._escape_md(r.name)
                report_lines.append(
                    f"{signal_emoji} **{display_name}({r.code})**: {r.operation_advice} | "
                    f"评分 {r.sentiment_score} | {r.trend_prediction}"
                )
            report_lines.extend([
                "",
                "---",
                "",
            ])

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
                    f"## {signal_emoji} {stock_name} ({result.code})",
                    "",
                ])

                # Intelligence section
                intel = dashboard.get('intelligence', {}) if dashboard else {}
                if intel:
                    report_lines.extend([
                        "### 📰 重要信息速览",
                        "",
                    ])
                    if intel.get('sentiment_summary'):
                        report_lines.append(f"**💭 舆情情绪**: {intel['sentiment_summary']}")
                    if intel.get('earnings_outlook'):
                        report_lines.append(f"**📊 业绩预期**: {intel['earnings_outlook']}")
                    risk_alerts = intel.get('risk_alerts', [])
                    if risk_alerts:
                        report_lines.append("")
                        report_lines.append("**🚨 风险警报**:")
                        for alert in risk_alerts:
                            report_lines.append(f"- {alert}")
                    catalysts = intel.get('positive_catalysts', [])
                    if catalysts:
                        report_lines.append("")
                        report_lines.append("**✨ 利好催化**:")
                        for cat in catalysts:
                            report_lines.append(f"- {cat}")
                    if intel.get('latest_news'):
                        report_lines.append("")
                        report_lines.append(f"**📢 最新动态**: {intel['latest_news']}")
                    report_lines.append("")

                # Core conclusion
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                one_sentence = core.get('one_sentence', result.analysis_summary)
                time_sense = core.get('time_sensitivity', '本周内')
                pos_advice = core.get('position_advice', {})

                report_lines.extend([
                    "### 📌 核心结论",
                    "",
                    f"**{signal_emoji} {signal_text}** | {result.trend_prediction}",
                    "",
                    f"> **一句话决策**: {one_sentence}",
                    "",
                    f"⏰ **时效性**: {time_sense}",
                    "",
                ])
                if pos_advice:
                    report_lines.extend([
                        "| 持仓情况 | 操作建议 |",
                        "|---------|---------|",
                        f"| 🆕 **空仓者** | {pos_advice.get('no_position', result.operation_advice)} |",
                        f"| 💼 **持仓者** | {pos_advice.get('has_position', '继续持有')} |",
                        "",
                    ])

                self._append_market_snapshot(report_lines, result)

                # Data perspective
                data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
                if data_persp:
                    trend_data = data_persp.get('trend_status', {})
                    price_data = data_persp.get('price_position', {})
                    vol_data = data_persp.get('volume_analysis', {})
                    chip_data = data_persp.get('chip_structure', {})

                    report_lines.extend([
                        "### 📊 数据透视",
                        "",
                    ])
                    if trend_data:
                        is_bullish = "✅ 是" if trend_data.get('is_bullish', False) else "❌ 否"
                        report_lines.extend([
                            f"**均线排列**: {trend_data.get('ma_alignment', 'N/A')} | "
                            f"多头排列: {is_bullish} | 趋势强度: {trend_data.get('trend_score', 'N/A')}/100",
                            "",
                        ])
                    if price_data:
                        bias_status = price_data.get('bias_status', 'N/A')
                        bias_emoji = (
                            "✅" if bias_status == "安全"
                            else ("⚠️" if bias_status == "警戒" else "🚨")
                        )
                        report_lines.extend([
                            "| 价格指标 | 数值 |",
                            "|---------|------|",
                            f"| 当前价 | {price_data.get('current_price', 'N/A')} |",
                            f"| MA5 | {price_data.get('ma5', 'N/A')} |",
                            f"| MA10 | {price_data.get('ma10', 'N/A')} |",
                            f"| MA20 | {price_data.get('ma20', 'N/A')} |",
                            f"| 乖离率(MA5) | {price_data.get('bias_ma5', 'N/A')}% {bias_emoji}{bias_status} |",
                            f"| 支撑位 | {price_data.get('support_level', 'N/A')} |",
                            f"| 压力位 | {price_data.get('resistance_level', 'N/A')} |",
                            "",
                        ])
                    if vol_data:
                        report_lines.extend([
                            f"**量能**: 量比 {vol_data.get('volume_ratio', 'N/A')} "
                            f"({vol_data.get('volume_status', '')}) | "
                            f"换手率 {vol_data.get('turnover_rate', 'N/A')}%",
                            f"💡 *{vol_data.get('volume_meaning', '')}*",
                            "",
                        ])
                    if chip_data:
                        chip_health = chip_data.get('chip_health', 'N/A')
                        chip_emoji = (
                            "✅" if chip_health == "健康"
                            else ("⚠️" if chip_health == "一般" else "🚨")
                        )
                        report_lines.extend([
                            f"**筹码**: 获利比例 {chip_data.get('profit_ratio', 'N/A')} | "
                            f"平均成本 {chip_data.get('avg_cost', 'N/A')} | "
                            f"集中度 {chip_data.get('concentration', 'N/A')} {chip_emoji}{chip_health}",
                            "",
                        ])

                # Battle plan
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                if battle:
                    report_lines.extend([
                        "### 🎯 作战计划",
                        "",
                    ])
                    sniper = battle.get('sniper_points', {})
                    if sniper:
                        report_lines.extend([
                            "**📍 狙击点位**",
                            "",
                            "| 点位类型 | 价格 |",
                            "|---------|------|",
                            f"| 🎯 理想买入点 | {self._clean_sniper_value(sniper.get('ideal_buy', 'N/A'))} |",
                            f"| 🔵 次优买入点 | {self._clean_sniper_value(sniper.get('secondary_buy', 'N/A'))} |",
                            f"| 🛑 止损位 | {self._clean_sniper_value(sniper.get('stop_loss', 'N/A'))} |",
                            f"| 🎊 目标位 | {self._clean_sniper_value(sniper.get('take_profit', 'N/A'))} |",
                            "",
                        ])
                    position = battle.get('position_strategy', {})
                    if position:
                        report_lines.extend([
                            f"**💰 仓位建议**: {position.get('suggested_position', 'N/A')}",
                            f"- 建仓策略: {position.get('entry_plan', 'N/A')}",
                            f"- 风控策略: {position.get('risk_control', 'N/A')}",
                            "",
                        ])
                    checklist = battle.get('action_checklist', []) if battle else []
                    if checklist:
                        report_lines.extend([
                            "**✅ 检查清单**",
                            "",
                        ])
                        for item in checklist:
                            report_lines.append(f"- {item}")
                        report_lines.append("")

                if not dashboard:
                    pass

                report_lines.extend([
                    "---",
                    "",
                ])

        report_lines.extend([
            "",
            f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        return "\n".join(report_lines)

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
        if getattr(config, 'report_renderer_enabled', False) and results:
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

                lines.append(f"### {signal_emoji} **{signal_text}** | {stock_name}({result.code})")
                lines.append("")

                one_sentence = (
                    core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
                )
                if one_sentence:
                    lines.append(f"📌 **{one_sentence[:80]}**")
                    lines.append("")

                info_lines = []
                if intel.get('earnings_outlook'):
                    outlook = intel['earnings_outlook'][:60]
                    info_lines.append(f"📊 业绩: {outlook}")
                if intel.get('sentiment_summary'):
                    sentiment = intel['sentiment_summary'][:50]
                    info_lines.append(f"💭 舆情: {sentiment}")
                if info_lines:
                    lines.extend(info_lines)
                    lines.append("")

                risks = intel.get('risk_alerts', []) if intel else []
                if risks:
                    lines.append("🚨 **风险**:")
                    for risk in risks[:2]:
                        risk_text = risk[:50] + "..." if len(risk) > 50 else risk
                        lines.append(f"   • {risk_text}")
                    lines.append("")

                catalysts = intel.get('positive_catalysts', []) if intel else []
                if catalysts:
                    lines.append("✨ **利好**:")
                    for cat in catalysts[:2]:
                        cat_text = cat[:50] + "..." if len(cat) > 50 else cat
                        lines.append(f"   • {cat_text}")
                    lines.append("")

                sniper = battle.get('sniper_points', {}) if battle else {}
                if sniper:
                    ideal_buy = sniper.get('ideal_buy', '')
                    stop_loss = sniper.get('stop_loss', '')
                    take_profit = sniper.get('take_profit', '')
                    points = []
                    if ideal_buy:
                        points.append(f"🎯买点:{ideal_buy[:15]}")
                    if stop_loss:
                        points.append(f"🛑止损:{stop_loss[:15]}")
                    if take_profit:
                        points.append(f"🎊目标:{take_profit[:15]}")
                    if points:
                        lines.append(" | ".join(points))
                        lines.append("")

                pos_advice = core.get('position_advice', {}) if core else {}
                if pos_advice:
                    no_pos = pos_advice.get('no_position', '')
                    has_pos = pos_advice.get('has_position', '')
                    if no_pos:
                        lines.append(f"🆕 空仓者: {no_pos[:50]}")
                    if has_pos:
                        lines.append(f"💼 持仓者: {has_pos[:50]}")
                    lines.append("")

                checklist = battle.get('action_checklist', []) if battle else []
                if checklist:
                    failed_checks = [c for c in checklist if c.startswith('❌') or c.startswith('⚠️')]
                    if failed_checks:
                        lines.append("**检查未通过项**:")
                        for check in failed_checks[:3]:
                            lines.append(f"   {check[:40]}")
                        lines.append("")

                lines.append("---")
                lines.append("")

        lines.append(f"*生成时间: {datetime.now().strftime('%H:%M')}*")
        models = self._collect_models_used(results)
        if models:
            lines.append(f"*分析模型: {', '.join(models)}*")

        content = "\n".join(lines)

        return content

    def generate_wechat_summary(self, results: List[AnalysisResult]) -> str:
        """
        Generate compact WeChat daily report (within 4000 chars).

        Args:
            results: Analysis results list

        Returns:
            Compact Markdown content
        """
        report_date = datetime.now().strftime('%Y-%m-%d')

        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0

        lines = [
            f"## 📅 {report_date} 股票分析报告",
            "",
            f"> 共 **{len(results)}** 只 | 🟢买入:{buy_count} 🟡持有:{hold_count} 🔴卖出:{sell_count} | 均分:{avg_score:.0f}",
            "",
        ]

        for result in sorted_results:
            emoji = result.get_emoji()
            lines.append(f"### {emoji} {result.name}({result.code})")
            lines.append(f"**{result.operation_advice}** | 评分:{result.sentiment_score} | {result.trend_prediction}")
            lines.append("")

        # Footer (model line before ---, Issue #528)
        models = self._collect_models_used(results)
        if models:
            lines.append(f"*分析模型: {', '.join(models)}*")
        lines.extend([
            "---",
            "*AI生成，仅供参考，不构成投资建议*",
            f"*详细报告见 reports/report_{report_date.replace('-', '')}.md*"
        ])

        content = "\n".join(lines)

        return content

    def generate_brief_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None,
    ) -> str:
        """
        Generate brief report (3-5 sentences per stock) for mobile/push.

        Args:
            results: Analysis results list (use [result] for single stock).
            report_date: Report date (default: today).

        Returns:
            Brief markdown content.
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')
        config = get_config()
        if getattr(config, 'report_renderer_enabled', False) and results:
            from src.services.report_renderer import render
            out = render(
                platform='brief',
                results=results,
                report_date=report_date,
                summary_only=False,
            )
            if out:
                return out
        # Fallback: brief summary from dashboard report
        if not results:
            return f"# {report_date} 决策简报\n\n无分析结果"
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        buy_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'buy')
        sell_count = sum(1 for r in results if getattr(r, 'decision_type', '') == 'sell')
        hold_count = sum(1 for r in results if getattr(r, 'decision_type', '') in ('hold', ''))
        lines = [
            f"# {report_date} 决策简报",
            "",
            f"> {len(results)}只 | 🟢{buy_count} 🟡{hold_count} 🔴{sell_count}",
            "",
        ]
        for r in sorted_results:
            _, emoji, _ = self._get_signal_level(r)
            name = r.name if r.name and not r.name.startswith('股票') else f'股票{r.code}'
            dash = r.dashboard or {}
            core = dash.get('core_conclusion', {}) or {}
            one = (core.get('one_sentence') or r.analysis_summary or '')[:60]
            lines.append(
                f"**{self._escape_md(name)}({r.code})** {emoji} {r.operation_advice} | "
                f"评分{r.sentiment_score} | {one}"
            )
        lines.append("")
        lines.append(f"*{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return "\n".join(lines)

    def generate_single_stock_report(self, result: AnalysisResult) -> str:
        """
        Generate single stock analysis report (for per-stock push mode #55).

        Compact yet complete, suitable for immediate push after each stock is analyzed.

        Args:
            result: Single stock analysis result

        Returns:
            Markdown formatted single stock report
        """
        report_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        signal_text, signal_emoji, _ = self._get_signal_level(result)
        dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
        core = dashboard.get('core_conclusion', {}) if dashboard else {}
        battle = dashboard.get('battle_plan', {}) if dashboard else {}
        intel = dashboard.get('intelligence', {}) if dashboard else {}

        raw_name = result.name if result.name and not result.name.startswith('股票') else f'股票{result.code}'
        stock_name = self._escape_md(raw_name)

        lines = [
            f"## {signal_emoji} {stock_name} ({result.code})",
            "",
            f"> {report_date} | 评分: **{result.sentiment_score}** | {result.trend_prediction}",
            "",
        ]

        self._append_market_snapshot(lines, result)

        one_sentence = core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
        if one_sentence:
            lines.extend([
                "### 📌 核心结论",
                "",
                f"**{signal_text}**: {one_sentence}",
                "",
            ])

        info_added = False
        if intel:
            if intel.get('earnings_outlook'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append(f"📊 **业绩预期**: {intel['earnings_outlook'][:100]}")

            if intel.get('sentiment_summary'):
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append(f"💭 **舆情情绪**: {intel['sentiment_summary'][:80]}")

            risks = intel.get('risk_alerts', [])
            if risks:
                if not info_added:
                    lines.append("### 📰 重要信息")
                    lines.append("")
                    info_added = True
                lines.append("")
                lines.append("🚨 **风险警报**:")
                for risk in risks[:3]:
                    lines.append(f"- {risk[:60]}")

            catalysts = intel.get('positive_catalysts', [])
            if catalysts:
                lines.append("")
                lines.append("✨ **利好催化**:")
                for cat in catalysts[:3]:
                    lines.append(f"- {cat[:60]}")

        if info_added:
            lines.append("")

        sniper = battle.get('sniper_points', {}) if battle else {}
        if sniper:
            lines.extend([
                "### 🎯 操作点位",
                "",
                "| 买点 | 止损 | 目标 |",
                "|------|------|------|",
            ])
            ideal_buy = sniper.get('ideal_buy', '-')
            stop_loss = sniper.get('stop_loss', '-')
            take_profit = sniper.get('take_profit', '-')
            lines.append(f"| {ideal_buy} | {stop_loss} | {take_profit} |")
            lines.append("")

        pos_advice = core.get('position_advice', {}) if core else {}
        if pos_advice:
            lines.extend([
                "### 💼 持仓建议",
                "",
                f"- 🆕 **空仓者**: {pos_advice.get('no_position', result.operation_advice)}",
                f"- 💼 **持仓者**: {pos_advice.get('has_position', '继续持有')}",
                "",
            ])

        lines.append("---")
        model_used = normalize_model_used(getattr(result, "model_used", None))
        if model_used:
            lines.append(f"*分析模型: {model_used}*")
        lines.append("*AI生成，仅供参考，不构成投资建议*")

        return "\n".join(lines)
