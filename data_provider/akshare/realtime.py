# -*- coding: utf-8 -*-
"""
Realtime quote helpers (Eastmoney / Sina / Tencent / ETF / HK) plus the
chip-distribution and enhanced-data endpoints.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..base import is_bse_code
from ..rate_limit_mixin import USER_AGENTS
from ..realtime_types import (
    ChipDistribution,
    RealtimeSource,
    UnifiedRealtimeQuote,
    get_chip_circuit_breaker,
    get_realtime_circuit_breaker,
    safe_float,
    safe_int,
)
from ..us_index_mapping import is_us_index_code
from .utils import (
    SINA_REALTIME_ENDPOINT,
    TENCENT_REALTIME_ENDPOINT,
    _build_realtime_failure_message,
    _classify_realtime_http_error,
    _etf_realtime_cache,
    _get_realtime_ttl,
    _is_etf_code,
    _is_hk_code,
    _is_us_code,
    _realtime_cache,
    _to_sina_tx_symbol,
)

logger = logging.getLogger(__name__)


class _RealtimeMixin:
    """Mixin: realtime quotes (multiple sources), chip distribution, enhanced data."""

    def get_realtime_quote(
        self, stock_code: str, source: str = "em", force_refresh: bool = False
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        Get realtime quote data (supports multiple data sources).

        Data source priority (configurable):
        1. em: Eastmoney (akshare ak.stock_zh_a_spot_em) - richest fields
        2. sina: Sina Finance - lightweight, basic quote
        3. tencent: Tencent direct API - single stock query, low load

        Args:
            stock_code: Stock / ETF code
            source: Data source type, one of "em", "sina", "tencent"
            force_refresh: If True, bypass cache and fetch fresh data from API

        Returns:
            UnifiedRealtimeQuote object, or None on failure
        """
        # 检查熔断器状态
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = f"akshare_{source}"
        
        if not circuit_breaker.is_available(source_key):
            logger.warning(f"[熔断] 数据源 {source_key} 处于熔断状态，跳过")
            return None
        
        # 根据代码类型选择不同的获取方法
        if _is_us_code(stock_code):
            # 美股不使用 Akshare，由 YfinanceFetcher 处理
            logger.debug(f"[API跳过] {stock_code} 是美股，Akshare 不支持美股实时行情")
            return None
        elif _is_hk_code(stock_code):
            return self._get_hk_realtime_quote(stock_code)
        elif _is_etf_code(stock_code):
            return self._get_etf_realtime_quote(stock_code, force_refresh=force_refresh)
        else:
            # A-shares: route by source
            if source == "sina":
                return self._get_stock_realtime_quote_sina(stock_code)
            elif source == "tencent":
                return self._get_stock_realtime_quote_tencent(stock_code)
            else:
                return self._get_stock_realtime_quote_em(stock_code, force_refresh=force_refresh)
    
    def _get_stock_realtime_quote_em(
        self, stock_code: str, force_refresh: bool = False
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        获取普通 A 股实时行情数据（东方财富数据源）
        
        数据来源：ak.stock_zh_a_spot_em()
        优点：数据最全，含量比、换手率、市盈率、市净率、总市值、流通市值等
        缺点：全量拉取，数据量大，容易超时/限流
        """
        import akshare as ak
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_em"
        
        try:
            # Check cache (skip when force_refresh is requested)
            current_time = time.time()
            ttl = _get_realtime_ttl()
            if (not force_refresh and _realtime_cache['data'] is not None and
                current_time - _realtime_cache['timestamp'] < ttl):
                df = _realtime_cache['data']
                cache_age = int(current_time - _realtime_cache['timestamp'])
                logger.debug(f"[缓存命中] A股实时行情(东财) - 缓存年龄 {cache_age}s/{ttl}s")
            else:
                # 触发全量刷新
                logger.info(f"[缓存未命中] 触发全量刷新 A股实时行情(东财)")
                last_error: Optional[Exception] = None
                df = None
                for attempt in range(1, 3):
                    try:
                        # 防封禁策略
                        self._set_random_user_agent()
                        self._enforce_rate_limit()

                        logger.info(f"[API调用] ak.stock_zh_a_spot_em() 获取A股实时行情... (attempt {attempt}/2)")
                        import time as _time
                        api_start = _time.time()

                        df = ak.stock_zh_a_spot_em()

                        api_elapsed = _time.time() - api_start
                        logger.info(f"[API返回] ak.stock_zh_a_spot_em 成功: 返回 {len(df)} 只股票, 耗时 {api_elapsed:.2f}s")
                        circuit_breaker.record_success(source_key)
                        break
                    except Exception as e:
                        last_error = e
                        logger.warning(f"[API错误] ak.stock_zh_a_spot_em 获取失败 (attempt {attempt}/2): {e}")
                        time.sleep(min(2 ** attempt, 5))

                # 更新缓存：成功缓存数据；失败也缓存空数据，避免同一轮任务对同一接口反复请求
                if df is None:
                    logger.error(f"[API错误] ak.stock_zh_a_spot_em 最终失败: {last_error}")
                    circuit_breaker.record_failure(source_key, str(last_error))
                    df = pd.DataFrame()
                _realtime_cache['data'] = df
                _realtime_cache['timestamp'] = current_time
                logger.info(f"[缓存更新] A股实时行情(东财) 缓存已刷新，TTL={ttl}s")

            if df is None or df.empty:
                logger.warning(f"[实时行情] A股实时行情数据为空，跳过 {stock_code}")
                return None
            
            # 查找指定股票
            row = df[df['代码'] == stock_code]
            if row.empty:
                logger.warning(f"[API返回] 未找到股票 {stock_code} 的实时行情")
                return None
            
            row = row.iloc[0]
            
            # 使用 realtime_types.py 中的统一转换函数
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=str(row.get('名称', '')),
                source=RealtimeSource.AKSHARE_EM,
                price=safe_float(row.get('最新价')),
                change_pct=safe_float(row.get('涨跌幅')),
                change_amount=safe_float(row.get('涨跌额')),
                volume=safe_int(row.get('成交量')),
                amount=safe_float(row.get('成交额')),
                volume_ratio=safe_float(row.get('量比')),
                turnover_rate=safe_float(row.get('换手率')),
                amplitude=safe_float(row.get('振幅')),
                open_price=safe_float(row.get('今开')),
                high=safe_float(row.get('最高')),
                low=safe_float(row.get('最低')),
                pe_ratio=safe_float(row.get('市盈率-动态')),
                pb_ratio=safe_float(row.get('市净率')),
                total_mv=safe_float(row.get('总市值')),
                circ_mv=safe_float(row.get('流通市值')),
                change_60d=safe_float(row.get('60日涨跌幅')),
                high_52w=safe_float(row.get('52周最高')),
                low_52w=safe_float(row.get('52周最低')),
            )
            
            logger.info(f"[实时行情-东财] {stock_code} {quote.name}: 价格={quote.price}, 涨跌={quote.change_pct}%, "
                       f"量比={quote.volume_ratio}, 换手率={quote.turnover_rate}%")
            return quote
            
        except Exception as e:
            logger.error(f"[API错误] 获取 {stock_code} 实时行情(东财)失败: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None
    
    def _get_stock_realtime_quote_sina(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取普通 A 股实时行情数据（新浪财经数据源）
        
        数据来源：新浪财经接口（直连，单股票查询）
        优点：单股票查询，负载小，速度快
        缺点：数据字段较少，无量比/PE/PB等
        
        接口格式：http://hq.sinajs.cn/list=sh600519,sz000001
        """
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_sina"
        symbol = _to_sina_tx_symbol(stock_code)
        url = f"http://{SINA_REALTIME_ENDPOINT}={symbol}"
        api_start = time.time()
        
        try:
            headers = {
                'Referer': 'http://finance.sina.com.cn',
                'User-Agent': random.choice(USER_AGENTS)
            }
            
            logger.info(
                f"[API调用] 新浪财经接口获取 {stock_code} 实时行情: endpoint={SINA_REALTIME_ENDPOINT}, symbol={symbol}"
            )
            
            self._enforce_rate_limit()
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'gbk'
            api_elapsed = time.time() - api_start
            
            if response.status_code != 200:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="http_status",
                    detail=f"HTTP {response.status_code}",
                    elapsed=api_elapsed,
                    error_type="HTTPStatus",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            # 解析数据：var hq_str_sh600519="贵州茅台,1866.000,1870.000,..."
            content = response.text.strip()
            if '=""' in content or not content:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="empty_response",
                    detail="empty quote payload",
                    elapsed=api_elapsed,
                    error_type="EmptyResponse",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            # 提取引号内的数据
            data_start = content.find('"')
            data_end = content.rfind('"')
            if data_start == -1 or data_end == -1:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="malformed_payload",
                    detail="quote payload missing quotes",
                    elapsed=api_elapsed,
                    error_type="MalformedPayload",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            data_str = content[data_start+1:data_end]
            fields = data_str.split(',')
            
            if len(fields) < 32:
                failure_message = _build_realtime_failure_message(
                    source_name="新浪",
                    endpoint=SINA_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="insufficient_fields",
                    detail=f"field_count={len(fields)}",
                    elapsed=api_elapsed,
                    error_type="InsufficientFields",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            circuit_breaker.record_success(source_key)
            
            # 新浪数据字段顺序：
            # 0:名称 1:今开 2:昨收 3:最新价 4:最高 5:最低 6:买一价 7:卖一价
            # 8:成交量(股) 9:成交额(元) ... 30:日期 31:时间
            # 使用 realtime_types.py 中的统一转换函数
            price = safe_float(fields[3])
            pre_close = safe_float(fields[2])
            change_pct = None
            change_amount = None
            if price and pre_close and pre_close > 0:
                change_amount = price - pre_close
                change_pct = (change_amount / pre_close) * 100
            
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=fields[0],
                source=RealtimeSource.AKSHARE_SINA,
                price=price,
                change_pct=change_pct,
                change_amount=change_amount,
                volume=safe_int(fields[8]),  # 成交量（股）
                amount=safe_float(fields[9]),  # 成交额（元）
                open_price=safe_float(fields[1]),
                high=safe_float(fields[4]),
                low=safe_float(fields[5]),
                pre_close=pre_close,
            )
            
            logger.info(
                f"[实时行情-新浪] {stock_code} {quote.name}: endpoint={SINA_REALTIME_ENDPOINT}, "
                f"价格={quote.price}, 涨跌={quote.change_pct}, 成交量={quote.volume}, elapsed={api_elapsed:.2f}s"
            )
            return quote
            
        except Exception as e:
            api_elapsed = time.time() - api_start
            category, detail = _classify_realtime_http_error(e)
            failure_message = _build_realtime_failure_message(
                source_name="新浪",
                endpoint=SINA_REALTIME_ENDPOINT,
                stock_code=stock_code,
                symbol=symbol,
                category=category,
                detail=detail,
                elapsed=api_elapsed,
                error_type=type(e).__name__,
            )
            logger.error(failure_message)
            circuit_breaker.record_failure(source_key, failure_message)
            return None
    
    def _get_stock_realtime_quote_tencent(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取普通 A 股实时行情数据（腾讯财经数据源）
        
        数据来源：腾讯财经接口（直连，单股票查询）
        优点：单股票查询，负载小，包含换手率
        缺点：无量比/PE/PB等估值数据
        
        接口格式：http://qt.gtimg.cn/q=sh600519,sz000001
        """
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_tencent"
        symbol = _to_sina_tx_symbol(stock_code)
        url = f"http://{TENCENT_REALTIME_ENDPOINT}={symbol}"
        api_start = time.time()
        
        try:
            headers = {
                'Referer': 'http://finance.qq.com',
                'User-Agent': random.choice(USER_AGENTS)
            }
            
            logger.info(
                f"[API调用] 腾讯财经接口获取 {stock_code} 实时行情: endpoint={TENCENT_REALTIME_ENDPOINT}, symbol={symbol}"
            )
            
            self._enforce_rate_limit()
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'gbk'
            api_elapsed = time.time() - api_start
            
            if response.status_code != 200:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="http_status",
                    detail=f"HTTP {response.status_code}",
                    elapsed=api_elapsed,
                    error_type="HTTPStatus",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            content = response.text.strip()
            if '=""' in content or not content:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="empty_response",
                    detail="empty quote payload",
                    elapsed=api_elapsed,
                    error_type="EmptyResponse",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            # 提取数据
            data_start = content.find('"')
            data_end = content.rfind('"')
            if data_start == -1 or data_end == -1:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="malformed_payload",
                    detail="quote payload missing quotes",
                    elapsed=api_elapsed,
                    error_type="MalformedPayload",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            data_str = content[data_start+1:data_end]
            fields = data_str.split('~')

            if len(fields) < 45:
                failure_message = _build_realtime_failure_message(
                    source_name="腾讯",
                    endpoint=TENCENT_REALTIME_ENDPOINT,
                    stock_code=stock_code,
                    symbol=symbol,
                    category="insufficient_fields",
                    detail=f"field_count={len(fields)}",
                    elapsed=api_elapsed,
                    error_type="InsufficientFields",
                )
                logger.warning(failure_message)
                circuit_breaker.record_failure(source_key, failure_message)
                return None
            
            circuit_breaker.record_success(source_key)
            
            # 腾讯数据字段顺序（完整）：
            # 1:名称 2:代码 3:最新价 4:昨收 5:今开 6:成交量(手) 7:外盘 8:内盘
            # 9-28:买卖五档 30:时间戳 31:涨跌额 32:涨跌幅(%) 33:最高 34:最低 35:收盘/成交量/成交额
            # 36:成交量(手) 37:成交额(万) 38:换手率(%) 39:市盈率 43:振幅(%)
            # 44:流通市值(亿) 45:总市值(亿) 46:市净率 47:涨停价 48:跌停价 49:量比
            # 使用 realtime_types.py 中的统一转换函数
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=fields[1] if len(fields) > 1 else "",
                source=RealtimeSource.TENCENT,
                price=safe_float(fields[3]),
                change_pct=safe_float(fields[32]),
                change_amount=safe_float(fields[31]) if len(fields) > 31 else None,
                volume=safe_int(fields[6]) * 100 if fields[6] else None,  # 腾讯返回的是手，转为股
                open_price=safe_float(fields[5]),
                high=safe_float(fields[33]) if len(fields) > 33 else None,  # 修正：字段 33 是最高价
                low=safe_float(fields[34]) if len(fields) > 34 else None,  # 修正：字段 34 是最低价
                pre_close=safe_float(fields[4]),
                turnover_rate=safe_float(fields[38]) if len(fields) > 38 else None,
                amplitude=safe_float(fields[43]) if len(fields) > 43 else None,
                volume_ratio=safe_float(fields[49]) if len(fields) > 49 else None,  # 量比
                pe_ratio=safe_float(fields[39]) if len(fields) > 39 else None,  # 市盈率
                pb_ratio=safe_float(fields[46]) if len(fields) > 46 else None,  # 市净率
                circ_mv=safe_float(fields[44]) * 100000000 if len(fields) > 44 and fields[44] else None,  # 流通市值(亿->元)
                total_mv=safe_float(fields[45]) * 100000000 if len(fields) > 45 and fields[45] else None,  # 总市值(亿->元)
            )
            
            logger.info(
                f"[实时行情-腾讯] {stock_code} {quote.name}: endpoint={TENCENT_REALTIME_ENDPOINT}, "
                f"价格={quote.price}, 涨跌={quote.change_pct}%, 量比={quote.volume_ratio}, "
                f"换手率={quote.turnover_rate}%, elapsed={api_elapsed:.2f}s"
            )
            return quote
            
        except Exception as e:
            api_elapsed = time.time() - api_start
            category, detail = _classify_realtime_http_error(e)
            failure_message = _build_realtime_failure_message(
                source_name="腾讯",
                endpoint=TENCENT_REALTIME_ENDPOINT,
                stock_code=stock_code,
                symbol=symbol,
                category=category,
                detail=detail,
                elapsed=api_elapsed,
                error_type=type(e).__name__,
            )
            logger.error(failure_message)
            circuit_breaker.record_failure(source_key, failure_message)
            return None
    
    def _get_etf_realtime_quote(self, stock_code: str, force_refresh: bool = False) -> Optional[UnifiedRealtimeQuote]:
        """
        获取 ETF 基金实时行情数据
        
        数据来源：ak.fund_etf_spot_em()
        包含：最新价、涨跌幅、成交量、成交额、换手率等
        
        Args:
            stock_code: ETF 代码
            
        Returns:
            UnifiedRealtimeQuote 对象，获取失败返回 None
        """
        import akshare as ak
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_etf"
        
        try:
            # Check cache (skip when force_refresh is requested)
            current_time = time.time()
            if (not force_refresh and _etf_realtime_cache['data'] is not None and
                current_time - _etf_realtime_cache['timestamp'] < _get_realtime_ttl()):
                df = _etf_realtime_cache['data']
                logger.debug(f"[缓存命中] 使用缓存的ETF实时行情数据")
            else:
                last_error: Optional[Exception] = None
                df = None
                for attempt in range(1, 3):
                    try:
                        # 防封禁策略
                        self._set_random_user_agent()
                        self._enforce_rate_limit()

                        logger.info(f"[API调用] ak.fund_etf_spot_em() 获取ETF实时行情... (attempt {attempt}/2)")
                        import time as _time
                        api_start = _time.time()

                        df = ak.fund_etf_spot_em()

                        api_elapsed = _time.time() - api_start
                        logger.info(f"[API返回] ak.fund_etf_spot_em 成功: 返回 {len(df)} 只ETF, 耗时 {api_elapsed:.2f}s")
                        circuit_breaker.record_success(source_key)
                        break
                    except Exception as e:
                        last_error = e
                        logger.warning(f"[API错误] ak.fund_etf_spot_em 获取失败 (attempt {attempt}/2): {e}")
                        time.sleep(min(2 ** attempt, 5))

                if df is None:
                    logger.error(f"[API错误] ak.fund_etf_spot_em 最终失败: {last_error}")
                    circuit_breaker.record_failure(source_key, str(last_error))
                    df = pd.DataFrame()
                _etf_realtime_cache['data'] = df
                _etf_realtime_cache['timestamp'] = current_time

            if df is None or df.empty:
                logger.warning(f"[实时行情] ETF实时行情数据为空，跳过 {stock_code}")
                return None
            
            # 查找指定 ETF
            row = df[df['代码'] == stock_code]
            if row.empty:
                logger.warning(f"[API返回] 未找到 ETF {stock_code} 的实时行情")
                return None
            
            row = row.iloc[0]
            
            # 使用 realtime_types.py 中的统一转换函数
            # ETF 行情数据构建
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=str(row.get('名称', '')),
                source=RealtimeSource.AKSHARE_EM,
                price=safe_float(row.get('最新价')),
                change_pct=safe_float(row.get('涨跌幅')),
                change_amount=safe_float(row.get('涨跌额')),
                volume=safe_int(row.get('成交量')),
                amount=safe_float(row.get('成交额')),
                volume_ratio=safe_float(row.get('量比')),
                turnover_rate=safe_float(row.get('换手率')),
                amplitude=safe_float(row.get('振幅')),
                open_price=safe_float(row.get('开盘价')),
                high=safe_float(row.get('最高价')),
                low=safe_float(row.get('最低价')),
                total_mv=safe_float(row.get('总市值')),
                circ_mv=safe_float(row.get('流通市值')),
                high_52w=safe_float(row.get('52周最高')),
                low_52w=safe_float(row.get('52周最低')),
            )
            
            logger.info(f"[ETF实时行情] {stock_code} {quote.name}: 价格={quote.price}, 涨跌={quote.change_pct}%, "
                       f"换手率={quote.turnover_rate}%")
            return quote
            
        except Exception as e:
            logger.error(f"[API错误] 获取 ETF {stock_code} 实时行情失败: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None
    
    def _get_hk_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取港股实时行情数据
        
        数据来源：ak.stock_hk_spot_em()
        包含：最新价、涨跌幅、成交量、成交额等
        
        Args:
            stock_code: 港股代码
            
        Returns:
            UnifiedRealtimeQuote 对象，获取失败返回 None
        """
        import akshare as ak
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "akshare_hk"
        
        try:
            # 防封禁策略
            self._set_random_user_agent()
            self._enforce_rate_limit()
            
            # 确保代码格式正确（5位数字）
            code = stock_code.lower().replace('hk', '').zfill(5)
            
            logger.info(f"[API调用] ak.stock_hk_spot_em() 获取港股实时行情...")
            import time as _time
            api_start = _time.time()
            
            df = ak.stock_hk_spot_em()
            
            api_elapsed = _time.time() - api_start
            logger.info(f"[API返回] ak.stock_hk_spot_em 成功: 返回 {len(df)} 只港股, 耗时 {api_elapsed:.2f}s")
            circuit_breaker.record_success(source_key)
            
            # 查找指定港股
            row = df[df['代码'] == code]
            if row.empty:
                logger.warning(f"[API返回] 未找到港股 {code} 的实时行情")
                return None
            
            row = row.iloc[0]
            
            # 使用 realtime_types.py 中的统一转换函数
            # 港股行情数据构建
            quote = UnifiedRealtimeQuote(
                code=stock_code,
                name=str(row.get('名称', '')),
                source=RealtimeSource.AKSHARE_EM,
                price=safe_float(row.get('最新价')),
                change_pct=safe_float(row.get('涨跌幅')),
                change_amount=safe_float(row.get('涨跌额')),
                volume=safe_int(row.get('成交量')),
                amount=safe_float(row.get('成交额')),
                volume_ratio=safe_float(row.get('量比')),
                turnover_rate=safe_float(row.get('换手率')),
                amplitude=safe_float(row.get('振幅')),
                pe_ratio=safe_float(row.get('市盈率')),
                pb_ratio=safe_float(row.get('市净率')),
                total_mv=safe_float(row.get('总市值')),
                circ_mv=safe_float(row.get('流通市值')),
                high_52w=safe_float(row.get('52周最高')),
                low_52w=safe_float(row.get('52周最低')),
            )
            
            logger.info(f"[港股实时行情] {stock_code} {quote.name}: 价格={quote.price}, 涨跌={quote.change_pct}%, "
                       f"换手率={quote.turnover_rate}%")
            return quote
            
        except Exception as e:
            logger.error(f"[API错误] 获取港股 {stock_code} 实时行情失败: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None
    
    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        获取筹码分布数据
        
        数据来源：ak.stock_cyq_em()
        包含：获利比例、平均成本、筹码集中度
        
        注意：ETF/指数没有筹码分布数据，会直接返回 None
        
        Args:
            stock_code: 股票代码
            
        Returns:
            ChipDistribution 对象（最新一天的数据），获取失败返回 None
        """
        import akshare as ak

        # 美股没有筹码分布数据（Akshare 不支持）
        if _is_us_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 是美股，无筹码分布数据")
            return None

        # ETF/指数没有筹码分布数据
        if _is_etf_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 是 ETF/指数，无筹码分布数据")
            return None
        
        def _do_fetch() -> Optional[ChipDistribution]:
            self._set_random_user_agent()
            self._enforce_rate_limit()
            # Extra delay for chip API (Eastmoney closes connections on frequent requests)
            time.sleep(random.uniform(1.5, 3.0))

            logger.info(f"[API调用] ak.stock_cyq_em(symbol={stock_code}) 获取筹码分布...")
            api_start = time.time()
            df = ak.stock_cyq_em(symbol=stock_code)
            api_elapsed = time.time() - api_start

            if df.empty:
                logger.warning(f"[API返回] ak.stock_cyq_em 返回空数据, 耗时 {api_elapsed:.2f}s")
                return None

            logger.info(f"[API返回] ak.stock_cyq_em 成功: 返回 {len(df)} 天数据, 耗时 {api_elapsed:.2f}s")
            logger.debug(f"[API返回] 筹码数据列名: {list(df.columns)}")

            latest = df.iloc[-1]
            chip = ChipDistribution(
                code=stock_code,
                date=str(latest.get('日期', '')),
                profit_ratio=safe_float(latest.get('获利比例')),
                avg_cost=safe_float(latest.get('平均成本')),
                cost_90_low=safe_float(latest.get('90成本-低')),
                cost_90_high=safe_float(latest.get('90成本-高')),
                concentration_90=safe_float(latest.get('90集中度')),
                cost_70_low=safe_float(latest.get('70成本-低')),
                cost_70_high=safe_float(latest.get('70成本-高')),
                concentration_70=safe_float(latest.get('70集中度')),
            )
            logger.info(
                f"[筹码分布] {stock_code} 日期={chip.date}: 获利比例={chip.profit_ratio:.1%}, "
                f"平均成本={chip.avg_cost}, 90%集中度={chip.concentration_90:.2%}, "
                f"70%集中度={chip.concentration_70:.2%}"
            )
            return chip

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                chip = _do_fetch()
                if chip is not None:
                    return chip
                break  # empty data, no retry
            except Exception as e:
                err_msg = str(e).lower()
                is_retryable = any(
                    k in err_msg for k in ("remote", "connection", "disconnected", "aborted", "timeout")
                )
                if attempt < max_retries and is_retryable:
                    backoff = min(2 ** attempt, 10)
                    logger.warning(f"[API错误] 获取 {stock_code} 筹码失败 (attempt {attempt}/{max_retries}), {backoff}s 后重试: {e}")
                    time.sleep(backoff)
                else:
                    logger.error(f"[API错误] 获取 {stock_code} 筹码分布失败: {e}")
                    return None
        return None
    
    def get_enhanced_data(self, stock_code: str, days: int = 60) -> Dict[str, Any]:
        """
        获取增强数据（历史K线 + 实时行情 + 筹码分布）
        
        Args:
            stock_code: 股票代码
            days: 历史数据天数
            
        Returns:
            包含所有数据的字典
        """
        result = {
            'code': stock_code,
            'daily_data': None,
            'realtime_quote': None,
            'chip_distribution': None,
        }
        
        # 获取日线数据
        try:
            df = self.get_daily_data(stock_code, days=days)
            result['daily_data'] = df
        except Exception as e:
            logger.error(f"获取 {stock_code} 日线数据失败: {e}")
        
        # 获取实时行情
        result['realtime_quote'] = self.get_realtime_quote(stock_code)
        
        # 获取筹码分布
        result['chip_distribution'] = self.get_chip_distribution(stock_code)
        
        return result

