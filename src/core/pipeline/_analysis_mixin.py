# -*- coding: utf-8 -*-
"""``_AnalysisMixin``: per-stock analysis (analyze_stock + context + agent).

This mixin owns the bulk of the per-stock workflow:

- ``analyze_stock`` and its supporting helpers
- ``_enhance_context`` (prompt context assembly)
- ``_analyze_with_agent`` (agent-mode invocation) and result conversion
- Small static utilities (``_safe_int``, ``_compute_ma_status`` …)
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from data_provider.realtime_types import ChipDistribution
from src.analyzer import AnalysisResult, GeminiAnalyzer, fill_chip_structure_if_needed
from src.config import Config, get_config
from src.data.stock_mapping import STOCK_NAME_MAP
from src.enums import ReportType
from src.search_service import SearchService
from src.stock_analyzer import (
    BuySignal,
    StockTrendAnalyzer,
    TrendAnalysisResult,
    TrendStatus,
)

logger = logging.getLogger(__name__)


class _AnalysisMixin:
    """Per-stock analysis methods for :class:`StockAnalysisPipeline`."""

    def analyze_stock(self, code: str, report_type: ReportType, query_id: str) -> Optional[AnalysisResult]:
        """
        分析单只股票（增强版：含量比、换手率、筹码分析、多维度情报）
        
        流程：
        1. 获取实时行情（量比、换手率）- 通过 DataFetcherManager 自动故障切换
        2. 获取筹码分布 - 通过 DataFetcherManager 带熔断保护
        3. 进行趋势分析（基于交易理念）
        4. 多维度情报搜索（最新消息+风险排查+业绩预期）
        5. 从数据库获取分析上下文
        6. 调用 AI 进行综合分析
        
        Args:
            query_id: 查询链路关联 id
            code: 股票代码
            report_type: 报告类型
            
        Returns:
            AnalysisResult 或 None（如果分析失败）
        """
        try:
            # 获取股票名称（优先从实时行情获取真实名称）
            stock_name = self.fetcher_manager.get_stock_name(code)

            # Step 1: 获取实时行情（量比、换手率等）- 使用统一入口，自动故障切换
            realtime_quote = None
            try:
                realtime_quote = self.fetcher_manager.get_realtime_quote(code)
                if realtime_quote:
                    # 使用实时行情返回的真实股票名称
                    if realtime_quote.name:
                        stock_name = realtime_quote.name
                    # 兼容不同数据源的字段（有些数据源可能没有 volume_ratio）
                    volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
                    turnover_rate = getattr(realtime_quote, 'turnover_rate', None)
                    logger.info(f"{stock_name}({code}) 实时行情: 价格={realtime_quote.price}, "
                              f"量比={volume_ratio}, 换手率={turnover_rate}% "
                              f"(来源: {realtime_quote.source.value if hasattr(realtime_quote, 'source') else 'unknown'})")
                else:
                    logger.info(f"{stock_name}({code}) 实时行情获取失败或已禁用，将使用历史数据进行分析")
            except Exception as e:
                logger.warning(f"{stock_name}({code}) 获取实时行情失败: {e}")

            # 如果还是没有名称，使用代码作为名称
            if not stock_name:
                stock_name = f'股票{code}'

            # Step 2: 获取筹码分布 - 使用统一入口，带熔断保护
            chip_data = None
            try:
                chip_data = self.fetcher_manager.get_chip_distribution(code)
                if chip_data:
                    logger.info(f"{stock_name}({code}) 筹码分布: 获利比例={chip_data.profit_ratio:.1%}, "
                              f"90%集中度={chip_data.concentration_90:.2%}")
                else:
                    logger.debug(f"{stock_name}({code}) 筹码分布获取失败或已禁用")
            except Exception as e:
                logger.warning(f"{stock_name}({code}) 获取筹码分布失败: {e}")

            # If agent mode is enabled, or specific agent skills are configured, use the Agent analysis pipeline
            use_agent = getattr(self.config, 'agent_mode', False)
            if not use_agent:
                # Auto-enable agent mode when specific skills are configured (e.g., scheduled task with strategy)
                configured_skills = getattr(self.config, 'agent_skills', [])
                if configured_skills and configured_skills != ['all']:
                    use_agent = True
                    logger.info(f"{stock_name}({code}) Auto-enabled agent mode due to configured skills: {configured_skills}")

            if use_agent:
                logger.info(f"{stock_name}({code}) 启用 Agent 模式进行分析")
                return self._analyze_with_agent(code, report_type, query_id, stock_name, realtime_quote, chip_data)
            
            # Step 3: 趋势分析（基于交易理念）
            trend_result: Optional[TrendAnalysisResult] = None
            try:
                end_date = date.today()
                start_date = end_date - timedelta(days=89)  # ~60 trading days for MA60
                historical_bars = self.db.get_data_range(code, start_date, end_date)
                if historical_bars:
                    df = pd.DataFrame([bar.to_dict() for bar in historical_bars])
                    # Issue #234: Augment with realtime for intraday MA calculation
                    if self.config.enable_realtime_quote and realtime_quote:
                        df = self._augment_historical_with_realtime(df, realtime_quote, code)
                    # Get broad market environment for score adjustment
                    market_env = self._get_market_environment()
                    pe_for_score = getattr(realtime_quote, 'pe_ratio', None) if realtime_quote else None
                    trend_result = self.trend_analyzer.analyze(
                        df, code, market_environment=market_env, pe_ratio=pe_for_score,
                    )
                    logger.info(f"{stock_name}({code}) 趋势分析: {trend_result.trend_status.value}, "
                              f"买入信号={trend_result.buy_signal.value}, 评分={trend_result.signal_score}"
                              f", 大盘={trend_result.market_environment}")
            except Exception as e:
                logger.warning(f"{stock_name}({code}) 趋势分析失败: {e}", exc_info=True)

            # Step 3.5: Integrate capital flow score into trend analysis result
            if trend_result:
                try:
                    token = self.config.tushare_token
                    if token:
                        try:
                            import tushare as ts
                            from data_provider.moneyflow_fetcher import MoneyflowFetcher

                            if getattr(self, '_mf_fetcher', None) is None:
                                pro = ts.pro_api(token)
                                self._mf_fetcher = MoneyflowFetcher(pro)

                            mf_fetcher = self._mf_fetcher
                            # Convert code to ts_code format (e.g., "000001" -> "000001.SZ")
                            ts_code = code
                        except ImportError:
                            logger.warning(f"{stock_name}({code}) Tushare package not installed, skipping capital flow analysis")
                            mf_fetcher = None
                            ts_code = None

                        if mf_fetcher and ts_code:
                            if len(code) == 6 and code.isdigit():
                                if code.startswith(('6', '9')):
                                    ts_code = f"{code}.SH"
                                else:
                                    ts_code = f"{code}.SZ"

                            cap_result = mf_fetcher.analyze_capital_flow(ts_code, days=5)
                            if cap_result and cap_result.get("total_capital_score", 0) > 0:
                                cf_raw = max(0, min(10, int(cap_result["total_capital_score"])))
                                trend_result.capital_flow_score = cf_raw
                                trend_result.main_force_signal = cap_result["main_force_signal"]
                                trend_result.north_signal = cap_result["north_signal"]
                                # Apply same 0-10 → 0-13 weighting as _generate_signal,
                                # then re-clamp and re-classify so regime caps stay valid.
                                cf_weighted = round(cf_raw * 1.3)
                                trend_result.signal_score = max(
                                    0, min(100, trend_result.signal_score + cf_weighted)
                                )
                                trend_result.dim_capital_flow_score = cf_weighted
                                trend_result.buy_signal = self.trend_analyzer.classify_buy_signal(
                                    trend_result.signal_score,
                                    trend_result.trend_status,
                                    trend_result.market_environment,
                                )
                                # Append capital flow reasons/risks
                                if trend_result.capital_flow_score >= 6:
                                    trend_result.signal_reasons.append(
                                        f"✅ {cap_result['main_force_signal']}"
                                    )
                                elif trend_result.capital_flow_score >= 2:
                                    trend_result.signal_reasons.append(
                                        f"⚡ {cap_result['main_force_signal']}"
                                    )
                                elif (cap_result["main_force_signal"]
                                      and cap_result["main_force_signal"] != "资金流向数据暂不可用"):
                                    trend_result.risk_factors.append(
                                        f"⚠️ {cap_result['main_force_signal']}"
                                    )
                                if (cap_result["north_signal"]
                                        and cap_result["north_signal"] != "北向资金数据暂不可用"):
                                    trend_result.signal_reasons.append(cap_result["north_signal"])
                                # Re-evaluate buy_signal with updated score
                                self._reevaluate_buy_signal(trend_result)
                                logger.info(
                                    f"{stock_name}({code}) 资金面评分: "
                                    f"{trend_result.capital_flow_score}/10, "
                                    f"主力: {trend_result.main_force_signal}"
                                )
                except Exception as e:
                    logger.warning(
                        f"{stock_name}({code}) Capital flow analysis failed, score defaults to 0: {e}"
                    )

            # Step 4: 多维度情报搜索（最新消息+风险排查+业绩预期）
            news_context = None
            if self.search_service.is_available:
                logger.info(f"{stock_name}({code}) 开始多维度情报搜索...")

                # 使用多维度搜索（最多5次搜索）
                intel_results = self.search_service.search_comprehensive_intel(
                    stock_code=code,
                    stock_name=stock_name,
                    max_searches=5
                )

                # 格式化情报报告
                if intel_results:
                    news_context = self.search_service.format_intel_report(intel_results, stock_name)
                    total_results = sum(
                        len(r.results) for r in intel_results.values() if r.success
                    )
                    logger.info(f"{stock_name}({code}) 情报搜索完成: 共 {total_results} 条结果")
                    logger.debug(f"{stock_name}({code}) 情报搜索结果:\n{news_context}")

                    # 保存新闻情报到数据库（用于后续复盘与查询）
                    try:
                        query_context = self._build_query_context(query_id=query_id)
                        for dim_name, response in intel_results.items():
                            if response and response.success and response.results:
                                self.db.save_news_intel(
                                    code=code,
                                    name=stock_name,
                                    dimension=dim_name,
                                    query=response.query,
                                    response=response,
                                    query_context=query_context
                                )
                    except Exception as e:
                        logger.warning(f"{stock_name}({code}) 保存新闻情报失败: {e}")
            else:
                logger.info(f"{stock_name}({code}) 搜索服务不可用，跳过情报搜索")

            # Step 5: 获取分析上下文（技术面数据）
            context = self.db.get_analysis_context(code)

            if context is None:
                logger.warning(f"{stock_name}({code}) 无法获取历史行情数据，将仅基于新闻和实时行情分析")
                context = {
                    'code': code,
                    'stock_name': stock_name,
                    'date': date.today().isoformat(),
                    'data_missing': True,
                    'today': {},
                    'yesterday': {}
                }
            
            # Step 6: 增强上下文数据（添加实时行情、筹码、趋势分析结果、股票名称）
            enhanced_context = self._enhance_context(
                context, 
                realtime_quote, 
                chip_data, 
                trend_result,
                stock_name  # 传入股票名称
            )
            
            # Step 7: 调用 AI 分析（传入增强的上下文和新闻）
            result = self.analyzer.analyze(enhanced_context, news_context=news_context)

            # Step 7.5: 填充分析时的价格信息到 result
            if result:
                result.query_id = query_id
                realtime_data = enhanced_context.get('realtime', {})
                result.current_price = realtime_data.get('price')
                result.change_pct = realtime_data.get('change_pct')

            # Step 7.6: chip_structure fallback (Issue #589)
            if result and chip_data:
                fill_chip_structure_if_needed(result, chip_data)

            # Step 8: 保存分析历史记录
            if result:
                try:
                    context_snapshot = self._build_context_snapshot(
                        enhanced_context=enhanced_context,
                        news_content=news_context,
                        realtime_quote=realtime_quote,
                        chip_data=chip_data
                    )
                    self.db.save_analysis_history(
                        result=result,
                        query_id=query_id,
                        report_type=report_type.value,
                        news_content=news_context,
                        context_snapshot=context_snapshot,
                        save_snapshot=self.save_context_snapshot
                    )
                except Exception as e:
                    logger.warning(f"{stock_name}({code}) 保存分析历史失败: {e}")

            return result

        except Exception as e:
            logger.error(f"{stock_name}({code}) 分析失败: {e}")
            logger.exception(f"{stock_name}({code}) 详细错误信息:")
            return None
    
    def _enhance_context(
        self,
        context: Dict[str, Any],
        realtime_quote,
        chip_data: Optional[ChipDistribution],
        trend_result: Optional[TrendAnalysisResult],
        stock_name: str = ""
    ) -> Dict[str, Any]:
        """
        增强分析上下文
        
        将实时行情、筹码分布、趋势分析结果、股票名称添加到上下文中
        
        Args:
            context: 原始上下文
            realtime_quote: 实时行情数据（UnifiedRealtimeQuote 或 None）
            chip_data: 筹码分布数据
            trend_result: 趋势分析结果
            stock_name: 股票名称
            
        Returns:
            增强后的上下文
        """
        enhanced = context.copy()
        
        # 添加股票名称
        if stock_name:
            enhanced['stock_name'] = stock_name
        elif realtime_quote and getattr(realtime_quote, 'name', None):
            enhanced['stock_name'] = realtime_quote.name
        
        # 添加实时行情（兼容不同数据源的字段差异）
        if realtime_quote:
            # 使用 getattr 安全获取字段，缺失字段返回 None 或默认值
            volume_ratio = getattr(realtime_quote, 'volume_ratio', None)
            enhanced['realtime'] = {
                'name': getattr(realtime_quote, 'name', ''),
                'price': getattr(realtime_quote, 'price', None),
                'change_pct': getattr(realtime_quote, 'change_pct', None),
                'volume_ratio': volume_ratio,
                'volume_ratio_desc': self._describe_volume_ratio(volume_ratio) if volume_ratio else '无数据',
                'turnover_rate': getattr(realtime_quote, 'turnover_rate', None),
                'pe_ratio': getattr(realtime_quote, 'pe_ratio', None),
                'pb_ratio': getattr(realtime_quote, 'pb_ratio', None),
                'total_mv': getattr(realtime_quote, 'total_mv', None),
                'circ_mv': getattr(realtime_quote, 'circ_mv', None),
                'change_60d': getattr(realtime_quote, 'change_60d', None),
                'source': getattr(realtime_quote, 'source', None),
            }
            # 移除 None 值以减少上下文大小
            enhanced['realtime'] = {k: v for k, v in enhanced['realtime'].items() if v is not None}
        
        # 添加筹码分布
        if chip_data:
            current_price = getattr(realtime_quote, 'price', 0) if realtime_quote else 0
            enhanced['chip'] = {
                'profit_ratio': chip_data.profit_ratio,
                'avg_cost': chip_data.avg_cost,
                'concentration_90': chip_data.concentration_90,
                'concentration_70': chip_data.concentration_70,
                'chip_status': chip_data.get_chip_status(current_price or 0),
            }
        
        # Compute trade_levels (system-calculated entry/stop/target points)
        # Strategy default: buy_pullback (single-stock analysis context).
        # Caller (e.g. picker) may override by setting context['picker_strategy_id'].
        try:
            from src.services.trade_levels import compute_trade_levels

            today = enhanced.get('today') or {}
            rt = enhanced.get('realtime') or {}
            current_price = float(rt.get('price') or today.get('close') or 0)
            ma5 = float((trend_result.ma5 if trend_result else None) or today.get('ma5') or 0)
            ma10 = float((trend_result.ma10 if trend_result else None) or today.get('ma10') or 0)
            ma20 = float((trend_result.ma20 if trend_result else None) or today.get('ma20') or 0)
            atr = float((trend_result.atr_20 if trend_result else None) or 0)
            total_mv = rt.get('total_mv') or 0
            market_cap_yi = float(total_mv) / 1e8 if total_mv else 0.0
            strategy_id = enhanced.get('picker_strategy_id') or 'buy_pullback'

            if current_price > 0:
                tl = compute_trade_levels(
                    code=enhanced.get('code', ''),
                    strategy_id=strategy_id,
                    current_price=current_price,
                    ma5=ma5, ma10=ma10, ma20=ma20, atr=atr,
                    market_cap_yi=market_cap_yi,
                )
                tl_dict = tl.to_dict()
                tl_dict['strategy_id'] = strategy_id
                enhanced['trade_levels'] = tl_dict
        except Exception as exc:
            logger.debug("[trade_levels] enhance_context skipped: %s", exc)

        # 添加趋势分析结果
        if trend_result:
            enhanced['trend_analysis'] = {
                'trend_status': trend_result.trend_status.value,
                'ma_alignment': trend_result.ma_alignment,
                'trend_strength': trend_result.trend_strength,
                'bias_ma5': trend_result.bias_ma5,
                'bias_ma10': trend_result.bias_ma10,
                'volume_status': trend_result.volume_status.value,
                'volume_trend': trend_result.volume_trend,
                'buy_signal': trend_result.buy_signal.value,
                'signal_score': trend_result.signal_score,
                'signal_reasons': trend_result.signal_reasons,
                'risk_factors': trend_result.risk_factors,
                'market_environment': trend_result.market_environment,
                # Per-dimension scores for backtesting effectiveness analysis
                'dim_trend_score': trend_result.dim_trend_score,
                'dim_bias_score': trend_result.dim_bias_score,
                'dim_volume_score': trend_result.dim_volume_score,
                'dim_support_score': trend_result.dim_support_score,
                'dim_macd_score': trend_result.dim_macd_score,
                'dim_rsi_score': trend_result.dim_rsi_score,
                'dim_capital_flow_score': trend_result.dim_capital_flow_score,
            }

        # Issue #234: Override today with realtime OHLC + trend MA for intraday analysis
        # Guard: trend_result.ma5 > 0 ensures MA calculation succeeded (data sufficient)
        if realtime_quote and trend_result and trend_result.ma5 > 0:
            price = getattr(realtime_quote, 'price', None)
            if price is not None and price > 0:
                yesterday_close = None
                if enhanced.get('yesterday') and isinstance(enhanced['yesterday'], dict):
                    yesterday_close = enhanced['yesterday'].get('close')
                orig_today = enhanced.get('today') or {}
                open_p = getattr(realtime_quote, 'open_price', None) or getattr(
                    realtime_quote, 'pre_close', None
                ) or yesterday_close or orig_today.get('open') or price
                high_p = getattr(realtime_quote, 'high', None) or price
                low_p = getattr(realtime_quote, 'low', None) or price
                vol = getattr(realtime_quote, 'volume', None)
                amt = getattr(realtime_quote, 'amount', None)
                pct = getattr(realtime_quote, 'change_pct', None)
                realtime_today = {
                    'close': price,
                    'open': open_p,
                    'high': high_p,
                    'low': low_p,
                    'ma5': trend_result.ma5,
                    'ma10': trend_result.ma10,
                    'ma20': trend_result.ma20,
                }
                if vol is not None:
                    realtime_today['volume'] = vol
                if amt is not None:
                    realtime_today['amount'] = amt
                if pct is not None:
                    realtime_today['pct_chg'] = pct
                for k, v in orig_today.items():
                    if k not in realtime_today and v is not None:
                        realtime_today[k] = v
                enhanced['today'] = realtime_today
                enhanced['ma_status'] = self._compute_ma_status(
                    price, trend_result.ma5, trend_result.ma10, trend_result.ma20
                )
                enhanced['date'] = date.today().isoformat()
                if yesterday_close is not None:
                    try:
                        yc = float(yesterday_close)
                        if yc > 0:
                            enhanced['price_change_ratio'] = round(
                                (price - yc) / yc * 100, 2
                            )
                    except (TypeError, ValueError):
                        pass
                if vol is not None and enhanced.get('yesterday'):
                    yest_vol = enhanced['yesterday'].get('volume') if isinstance(
                        enhanced['yesterday'], dict
                    ) else None
                    if yest_vol is not None:
                        try:
                            yv = float(yest_vol)
                            if yv > 0:
                                enhanced['volume_change_ratio'] = round(
                                    float(vol) / yv, 2
                                )
                        except (TypeError, ValueError):
                            pass

        # ETF/index flag for analyzer prompt (Fixes #274)
        enhanced['is_index_etf'] = SearchService.is_index_or_etf(
            context.get('code', ''), enhanced.get('stock_name', stock_name)
        )

        return enhanced

    def _analyze_with_agent(
        self, 
        code: str, 
        report_type: ReportType, 
        query_id: str,
        stock_name: str,
        realtime_quote: Any,
        chip_data: Optional[ChipDistribution]
    ) -> Optional[AnalysisResult]:
        """
        使用 Agent 模式分析单只股票。
        """
        try:
            from src.agent.factory import build_agent_executor

            # Build executor from shared factory (ToolRegistry and SkillManager prototype are cached)
            executor = build_agent_executor(self.config, getattr(self.config, 'agent_skills', None) or None)

            # Build initial context to avoid redundant tool calls
            initial_context = {
                "stock_code": code,
                "stock_name": stock_name,
                "report_type": report_type.value,
            }
            
            if realtime_quote:
                initial_context["realtime_quote"] = self._safe_to_dict(realtime_quote)
            if chip_data:
                initial_context["chip_distribution"] = self._safe_to_dict(chip_data)

            # 运行 Agent
            message = f"请分析股票 {code} ({stock_name})，并生成决策仪表盘报告。"
            agent_result = executor.run(message, context=initial_context)

            # 转换为 AnalysisResult
            result = self._agent_result_to_analysis_result(agent_result, code, stock_name, report_type, query_id)
            if result:
                result.query_id = query_id

            # Populate price data and market snapshot from realtime quote (Fixes #18)
            if result and realtime_quote:
                result.current_price = getattr(realtime_quote, 'price', None)
                result.change_pct = getattr(realtime_quote, 'change_pct', None)
                result.market_snapshot = {
                    'price': getattr(realtime_quote, 'price', None),
                    'open': getattr(realtime_quote, 'open_price', None),
                    'high': getattr(realtime_quote, 'high', None),
                    'low': getattr(realtime_quote, 'low', None),
                    'volume': getattr(realtime_quote, 'volume', None),
                    'amount': getattr(realtime_quote, 'amount', None),
                    'change_pct': getattr(realtime_quote, 'change_pct', None),
                    'turnover_rate': getattr(realtime_quote, 'turnover_rate', None),
                    'volume_ratio': getattr(realtime_quote, 'volume_ratio', None),
                }
                # Remove None values to keep snapshot clean
                result.market_snapshot = {k: v for k, v in result.market_snapshot.items() if v is not None}

            # Determine if search was performed during agent execution
            if result:
                tool_log = getattr(agent_result, 'tool_calls_log', []) or []
                result.search_performed = any(
                    'search' in str(tc.get('tool', '')).lower() or 'news' in str(tc.get('tool', '')).lower()
                    for tc in tool_log
                )

            # Agent weak integrity: placeholder fill only, no LLM retry
            if result and getattr(self.config, "report_integrity_enabled", False):
                from src.analyzer import check_content_integrity, apply_placeholder_fill

                pass_integrity, missing = check_content_integrity(result)
                if not pass_integrity:
                    apply_placeholder_fill(result, missing)
                    logger.info(
                        "[LLM完整性] integrity_mode=agent_weak 必填字段缺失 %s，已占位补全",
                        missing,
                    )
            # chip_structure fallback (Issue #589), before save_analysis_history
            if result and chip_data:
                fill_chip_structure_if_needed(result, chip_data)

            resolved_stock_name = result.name if result and result.name else stock_name

            # 保存新闻情报到数据库（Agent 工具结果仅用于 LLM 上下文，未持久化，Fixes #396）
            # 使用 search_stock_news（与 Agent 工具调用逻辑一致），仅 1 次 API 调用，无额外延迟
            if self.search_service.is_available:
                try:
                    news_response = self.search_service.search_stock_news(
                        stock_code=code,
                        stock_name=resolved_stock_name,
                        max_results=5
                    )
                    if news_response.success and news_response.results:
                        query_context = self._build_query_context(query_id=query_id)
                        self.db.save_news_intel(
                            code=code,
                            name=resolved_stock_name,
                            dimension="latest_news",
                            query=news_response.query,
                            response=news_response,
                            query_context=query_context
                        )
                        logger.info(f"[{code}] Agent 模式: 新闻情报已保存 {len(news_response.results)} 条")
                except Exception as e:
                    logger.warning(f"[{code}] Agent 模式保存新闻情报失败: {e}")

            # Ensure dimension scores are available for backtest evaluation
            if result and "enhanced_context" not in initial_context:
                try:
                    end_date = date.today()
                    start_date = end_date - timedelta(days=89)
                    historical_bars = self.db.get_data_range(code, start_date, end_date)
                    if historical_bars:
                        df = pd.DataFrame([bar.to_dict() for bar in historical_bars])
                        if self.config.enable_realtime_quote and realtime_quote:
                            df = self._augment_historical_with_realtime(df, realtime_quote, code)
                        market_env = self._get_market_environment()
                        pe_for_score = getattr(realtime_quote, 'pe_ratio', None) if realtime_quote else None
                        trend_result = self.trend_analyzer.analyze(
                            df, code, market_environment=market_env, pe_ratio=pe_for_score,
                        )
                        if trend_result:
                            initial_context["enhanced_context"] = {
                                "trend_analysis": {
                                    "dim_trend_score": trend_result.dim_trend_score,
                                    "dim_bias_score": trend_result.dim_bias_score,
                                    "dim_volume_score": trend_result.dim_volume_score,
                                    "dim_support_score": trend_result.dim_support_score,
                                    "dim_macd_score": trend_result.dim_macd_score,
                                    "dim_rsi_score": trend_result.dim_rsi_score,
                                    "dim_capital_flow_score": trend_result.dim_capital_flow_score,
                                    "total_score": trend_result.signal_score,
                                    "buy_signal": (
                                        trend_result.buy_signal.value
                                        if trend_result.buy_signal else None
                                    ),
                                    "market_environment": trend_result.market_environment,
                                }
                            }
                            logger.info(
                                f"[{code}] Agent mode: dimension scores computed "
                                f"(total={trend_result.signal_score})"
                            )
                except Exception as e:
                    logger.warning(f"[{code}] Failed to compute dimension scores for backtest: {e}")

            # 保存分析历史记录
            if result:
                try:
                    initial_context["stock_name"] = resolved_stock_name
                    self.db.save_analysis_history(
                        result=result,
                        query_id=query_id,
                        report_type=report_type.value,
                        news_content=None,
                        context_snapshot=initial_context,
                        save_snapshot=self.save_context_snapshot
                    )
                except Exception as e:
                    logger.warning(f"[{code}] 保存 Agent 分析历史失败: {e}")

            return result

        except Exception as e:
            logger.error(f"[{code}] Agent 分析失败: {e}")
            logger.exception(f"[{code}] Agent 详细错误信息:")
            return None

    def _agent_result_to_analysis_result(
        self, agent_result, code: str, stock_name: str, report_type: ReportType, query_id: str
    ) -> AnalysisResult:
        """
        将 AgentResult 转换为 AnalysisResult。
        """
        result = AnalysisResult(
            code=code,
            name=stock_name,
            sentiment_score=50,
            trend_prediction="未知",
            operation_advice="观望",
            success=agent_result.success,
            error_message=agent_result.error if not agent_result.success else None,
            data_sources=f"agent:{agent_result.provider}",
            model_used=agent_result.model or None,
        )

        if agent_result.success and agent_result.dashboard:
            dash = agent_result.dashboard
            ai_stock_name = str(dash.get("stock_name", "")).strip()
            if ai_stock_name and self._is_placeholder_stock_name(stock_name, code):
                result.name = ai_stock_name
            result.sentiment_score = self._safe_int(dash.get("sentiment_score"), 50)
            result.trend_prediction = dash.get("trend_prediction", "未知")
            result.operation_advice = dash.get("operation_advice", "观望")
            result.decision_type = dash.get("decision_type", "hold")
            result.analysis_summary = dash.get("analysis_summary", "")
            # The AI returns a top-level dict that contains a nested 'dashboard' sub-key
            # with core_conclusion / battle_plan / intelligence.  AnalysisResult's helper
            # methods (get_sniper_points, get_core_conclusion, etc.) expect that inner
            # structure, so we unwrap it here.
            result.dashboard = dash.get("dashboard") or dash
        else:
            result.sentiment_score = 50
            result.operation_advice = "观望"
            if not result.error_message:
                result.error_message = "Agent 未能生成有效的决策仪表盘"

        return result

    @staticmethod
    def _is_placeholder_stock_name(name: str, code: str) -> bool:
        """Return True when the stock name is missing or placeholder-like."""
        if not name:
            return True
        normalized = str(name).strip()
        if not normalized:
            return True
        if normalized == code:
            return True
        if normalized.startswith("股票"):
            return True
        if "Unknown" in normalized:
            return True
        return False

    @staticmethod
    def _safe_int(value: Any, default: int = 50) -> int:
        """安全地将值转换为整数。"""
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            import re
            match = re.search(r'-?\d+', value)
            if match:
                return int(match.group())
        return default
    
    def _describe_volume_ratio(self, volume_ratio: float) -> str:
        """
        量比描述
        
        量比 = 当前成交量 / 过去5日平均成交量
        """
        if volume_ratio < 0.5:
            return "极度萎缩"
        elif volume_ratio < 0.8:
            return "明显萎缩"
        elif volume_ratio < 1.2:
            return "正常"
        elif volume_ratio < 2.0:
            return "温和放量"
        elif volume_ratio < 3.0:
            return "明显放量"
        else:
            return "巨量"

    @staticmethod
    def _compute_ma_status(close: float, ma5: float, ma10: float, ma20: float) -> str:
        """
        Compute MA alignment status from price and MA values.
        Logic mirrors storage._analyze_ma_status (Issue #234).
        """
        close = close or 0
        ma5 = ma5 or 0
        ma10 = ma10 or 0
        ma20 = ma20 or 0
        if close > ma5 > ma10 > ma20 > 0:
            return "多头排列 📈"
        elif close < ma5 < ma10 < ma20 and ma20 > 0:
            return "空头排列 📉"
        elif close > ma5 and ma5 > ma10:
            return "短期向好 🔼"
        elif close < ma5 and ma5 < ma10:
            return "短期走弱 🔽"
        else:
            return "震荡整理 ↔️"

    @staticmethod
    def _reevaluate_buy_signal(result: TrendAnalysisResult) -> None:
        """Re-evaluate buy_signal after capital_flow_score injection updates signal_score."""
        result.buy_signal = StockTrendAnalyzer.classify_buy_signal(result.signal_score, result.trend_status)

