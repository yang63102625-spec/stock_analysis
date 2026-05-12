# -*- coding: utf-8 -*-
"""``_RealtimeMixin``: prefetch and per-stock realtime quotes for the manager.

This mixin implements ``prefetch_realtime_quotes`` and ``get_realtime_quote``
along with the small helpers used to merge / supplement quotes across
multiple data sources.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .codes import normalize_stock_code

logger = logging.getLogger(__name__)


class _RealtimeMixin:
    """Realtime-quote orchestration for :class:`DataFetcherManager`."""

    def prefetch_realtime_quotes(self, stock_codes: List[str]) -> int:
        """
        批量预取实时行情数据（在分析开始前调用）
        
        策略：
        1. 检查优先级中是否包含全量拉取数据源（efinance/akshare_em）
        2. 如果不包含，跳过预取（新浪/腾讯是单股票查询，无需预取）
        3. 如果自选股数量 >= 5 且使用全量数据源，则预取填充缓存
        
        这样做的好处：
        - 使用新浪/腾讯时：每只股票独立查询，无全量拉取问题
        - 使用 efinance/东财时：预取一次，后续缓存命中
        
        Args:
            stock_codes: 待分析的股票代码列表
            
        Returns:
            预取的股票数量（0 表示跳过预取）
        """
        # Normalize all codes
        stock_codes = [normalize_stock_code(c) for c in stock_codes]

        from src.config import get_config

        config = get_config()

        # Issue #455: PREFETCH_REALTIME_QUOTES=false 可禁用预取，避免全市场拉取
        if not getattr(config, "prefetch_realtime_quotes", True):
            logger.debug("[预取] PREFETCH_REALTIME_QUOTES=false，跳过批量预取")
            return 0

        # 检查优先级中是否包含全量拉取数据源
        # 注意：新增全量接口（如 tushare_realtime）时需同步更新此列表
        # 全量接口特征：一次 API 调用拉取全市场 5000+ 股票数据
        priority = config.realtime_source_priority.lower()
        bulk_sources = ['efinance', 'akshare_em', 'tushare']  # 全量接口列表
        
        # 如果优先级中前两个都不是全量数据源，跳过预取
        # 因为新浪/腾讯是单股票查询，不需要预取
        priority_list = [s.strip() for s in priority.split(',')]
        first_bulk_source_index = None
        for i, source in enumerate(priority_list):
            if source in bulk_sources:
                first_bulk_source_index = i
                break
        
        # 如果没有全量数据源，或者全量数据源排在第 3 位之后，跳过预取
        if first_bulk_source_index is None or first_bulk_source_index >= 2:
            logger.info(f"[预取] 当前优先级使用轻量级数据源(sina/tencent)，无需预取")
            return 0
        
        # 如果股票数量少于 5 个，不进行批量预取（逐个查询更高效）
        if len(stock_codes) < 5:
            logger.info(f"[预取] 股票数量 {len(stock_codes)} < 5，跳过批量预取")
            return 0
        
        logger.info(f"[预取] 开始批量预取实时行情，共 {len(stock_codes)} 只股票...")
        
        # 尝试通过 efinance 或 akshare 预取
        # 只需要调用一次 get_realtime_quote，缓存机制会自动拉取全市场数据
        try:
            # 用第一只股票触发全量拉取
            first_code = stock_codes[0]
            quote = self.get_realtime_quote(first_code)
            
            if quote:
                logger.info(f"[预取] 批量预取完成，缓存已填充")
                return len(stock_codes)
            else:
                logger.warning(f"[预取] 批量预取失败，将使用逐个查询模式")
                return 0
                
        except Exception as e:
            logger.error(f"[预取] 批量预取异常: {e}")
            return 0
    
    def get_realtime_quote(self, stock_code: str, force_refresh: bool = False):
        """
        Get realtime quote data (with automatic failover).

        Failover strategy (by configured priority):
        1. US stocks: use YfinanceFetcher.get_realtime_quote()
        2. EfinanceFetcher.get_realtime_quote()
        3. AkshareFetcher.get_realtime_quote(source="em")  - Eastmoney
        4. AkshareFetcher.get_realtime_quote(source="sina") - Sina
        5. AkshareFetcher.get_realtime_quote(source="tencent") - Tencent
        6. Return None (graceful degradation)

        Args:
            stock_code: Stock code
            force_refresh: If True, bypass cache in underlying fetchers

        Returns:
            UnifiedRealtimeQuote object, or None if all sources fail
        """
        # Normalize code (strip SH/SZ prefix etc.)
        stock_code = normalize_stock_code(stock_code)

        from ..realtime_types import get_realtime_circuit_breaker
        from ..akshare.utils import _is_us_code
        from ..us_index_mapping import is_us_index_code
        from src.config import get_config

        config = get_config()

        # 美股指数由 YfinanceFetcher 处理（在美股股票检查之前）
        if is_us_index_code(stock_code):
            for fetcher in self._fetchers:
                if fetcher.name == "YfinanceFetcher":
                    if hasattr(fetcher, 'get_realtime_quote'):
                        try:
                            quote = fetcher.get_realtime_quote(stock_code)
                            if quote is not None:
                                logger.info(f"[实时行情] 美股指数 {stock_code} 成功获取 (来源: yfinance)")
                                return quote
                        except Exception as e:
                            logger.warning(f"[实时行情] 美股指数 {stock_code} 获取失败: {e}")
                    break
            logger.warning(f"[实时行情] 美股指数 {stock_code} 无可用数据源")
            return None

        # 美股单独处理，使用 YfinanceFetcher
        if _is_us_code(stock_code):
            for fetcher in self._fetchers:
                if fetcher.name == "YfinanceFetcher":
                    if hasattr(fetcher, 'get_realtime_quote'):
                        try:
                            quote = fetcher.get_realtime_quote(stock_code)
                            if quote is not None:
                                logger.info(f"[实时行情] 美股 {stock_code} 成功获取 (来源: yfinance)")
                                return quote
                        except Exception as e:
                            logger.warning(f"[实时行情] 美股 {stock_code} 获取失败: {e}")
                    break
            logger.warning(f"[实时行情] 美股 {stock_code} 无可用数据源")
            return None
        
        # 获取配置的数据源优先级
        source_priority = config.realtime_source_priority.split(',')
        
        errors = []
        # primary_quote holds the first successful result; we may supplement
        # missing fields (volume_ratio, turnover_rate, etc.) from later sources.
        primary_quote = None
        
        for source in source_priority:
            source = source.strip().lower()
            
            try:
                quote = None
                
                if source == "efinance":
                    # Try EfinanceFetcher
                    for fetcher in self._fetchers:
                        if fetcher.name == "EfinanceFetcher":
                            if hasattr(fetcher, 'get_realtime_quote'):
                                quote = fetcher.get_realtime_quote(
                                    stock_code, force_refresh=force_refresh
                                )
                            break
                
                elif source == "akshare_em":
                    # Try AkshareFetcher Eastmoney source
                    for fetcher in self._fetchers:
                        if fetcher.name == "AkshareFetcher":
                            if hasattr(fetcher, 'get_realtime_quote'):
                                quote = fetcher.get_realtime_quote(
                                    stock_code, source="em", force_refresh=force_refresh
                                )
                            break
                
                elif source == "akshare_sina":
                    # Try AkshareFetcher Sina source
                    for fetcher in self._fetchers:
                        if fetcher.name == "AkshareFetcher":
                            if hasattr(fetcher, 'get_realtime_quote'):
                                quote = fetcher.get_realtime_quote(
                                    stock_code, source="sina", force_refresh=force_refresh
                                )
                            break
                
                elif source in ("tencent", "akshare_qq"):
                    # Try AkshareFetcher Tencent source
                    for fetcher in self._fetchers:
                        if fetcher.name == "AkshareFetcher":
                            if hasattr(fetcher, 'get_realtime_quote'):
                                quote = fetcher.get_realtime_quote(
                                    stock_code, source="tencent", force_refresh=force_refresh
                                )
                            break
                
                elif source == "tushare":
                    # 尝试 TushareFetcher（需要 Tushare Pro 积分）
                    for fetcher in self._fetchers:
                        if fetcher.name == "TushareFetcher":
                            if hasattr(fetcher, 'get_realtime_quote'):
                                quote = fetcher.get_realtime_quote(stock_code)
                            break
                
                if quote is not None and quote.has_basic_data():
                    if primary_quote is None:
                        # First successful source becomes primary
                        primary_quote = quote
                        logger.info(f"[实时行情] {stock_code} 成功获取 (来源: {source})")
                        # If all key supplementary fields are present, return early
                        if not self._quote_needs_supplement(primary_quote):
                            return primary_quote
                        # Otherwise, continue to try later sources for missing fields
                        missing = self._get_missing_supplement_fields(primary_quote)
                        logger.debug(
                            f"[实时行情] {stock_code} 部分字段缺失 {missing}，尝试从后续数据源补充"
                        )
                    else:
                        # Supplement missing fields from this source
                        merged = self._merge_quote_fields(primary_quote, quote)
                        if merged:
                            logger.info(f"[实时行情] {stock_code} 从 {source} 补充了缺失字段: {merged}")
                        else:
                            logger.debug(f"[实时行情] {stock_code} 从 {source} 未能补充任何字段")
                        # Stop supplementing once all key fields are filled
                        if not self._quote_needs_supplement(primary_quote):
                            break
                elif quote is not None and primary_quote is not None:
                    # quote has no basic price data but may still carry supplement
                    # fields (e.g. turnover_rate from akshare_em)
                    merged = self._merge_quote_fields(primary_quote, quote)
                    if merged:
                        logger.info(
                            f"[实时行情] {stock_code} 从 {source} (无基础价格) 补充了字段: {merged}"
                        )
                    if not self._quote_needs_supplement(primary_quote):
                        break
                    
            except Exception as e:
                error_msg = f"[{source}] 失败: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)
                continue
        
        # Return primary even if some fields are still missing
        if primary_quote is not None:
            return primary_quote

        # 所有数据源都失败，返回 None（降级兜底）
        if errors:
            logger.warning(f"[实时行情] {stock_code} 所有数据源均失败，降级处理: {'; '.join(errors)}")
        else:
            logger.warning(f"[实时行情] {stock_code} 无可用数据源")
        
        return None

    # Fields worth supplementing from secondary sources when the primary
    # source returns None for them. Ordered by importance.
    _SUPPLEMENT_FIELDS = [
        'volume_ratio', 'turnover_rate',
        'pe_ratio', 'pb_ratio', 'total_mv', 'circ_mv',
        'amplitude',
    ]

    @classmethod
    def _quote_needs_supplement(cls, quote) -> bool:
        """Check if any key supplementary field is still None."""
        for f in cls._SUPPLEMENT_FIELDS:
            if getattr(quote, f, None) is None:
                return True
        return False

    @classmethod
    def _get_missing_supplement_fields(cls, quote) -> list:
        """Return list of supplement field names that are still None."""
        return [f for f in cls._SUPPLEMENT_FIELDS if getattr(quote, f, None) is None]

    @classmethod
    def _merge_quote_fields(cls, primary, secondary) -> list:
        """
        Copy non-None fields from *secondary* into *primary* where
        *primary* has None. Returns list of field names that were filled.
        """
        filled = []
        for f in cls._SUPPLEMENT_FIELDS:
            if getattr(primary, f, None) is None:
                val = getattr(secondary, f, None)
                if val is not None:
                    setattr(primary, f, val)
                    filled.append(f)
        return filled

