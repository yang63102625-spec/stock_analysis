# -*- coding: utf-8 -*-
"""``_EfinanceCore``: ``__init__`` / rate-limit / dispatch helpers.

The full ``EfinanceFetcher`` lives in :mod:`.fetcher` and composes this
core with the historical / realtime / market mixins.
"""
from __future__ import annotations

import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import get_config
from src.exceptions import DataFetchError, RateLimitError

from ..base import BaseFetcher, is_st_stock, normalize_stock_code
from ..rate_limit_mixin import RateLimitMixin, USER_AGENTS
from .utils import (
    EASTMONEY_HISTORY_ENDPOINT,
    _classify_eastmoney_error,
    _is_etf_code,
    _is_us_code,
)

logger = logging.getLogger(__name__)


class _EfinanceCore(RateLimitMixin, BaseFetcher):
    """
    Efinance 数据源实现
    
    优先级：0（最高，优先于 AkshareFetcher）
    数据来源：东方财富网（通过 efinance 库封装）
    仓库：https://github.com/Micro-sheep/efinance
    
    主要 API：
    - ef.stock.get_quote_history(): 获取历史 K 线数据
    - ef.stock.get_base_info(): 获取股票基本信息
    - ef.stock.get_realtime_quotes(): 获取实时行情
    
    关键策略：
    - 每次请求前随机休眠 1.5-3.0 秒
    - 随机 User-Agent 轮换
    - 失败后指数退避重试（最多3次）
    """
    
    name = "EfinanceFetcher"
    priority = int(os.getenv("EFINANCE_PRIORITY", "0"))  # 最高优先级，排在 AkshareFetcher 之前
    
    # Wall-clock timeout for blocking efinance network calls (seconds).
    # Reduced from 10s to 5s: in overseas environments Eastmoney APIs
    # (push2.eastmoney.com) almost always time out; 5s lets us fail fast
    # and fall through to the Tushare/AkShare degradation chain sooner.
    _EFINANCE_CALL_TIMEOUT = 5

    def __init__(self, sleep_min: float = 1.5, sleep_max: float = 3.0):
        """
        初始化 EfinanceFetcher
        
        Args:
            sleep_min: 最小休眠时间（秒）
            sleep_max: 最大休眠时间（秒）
        """
        self._rate_limit_min = sleep_min
        self._rate_limit_max = sleep_max
        # _last_request_time is lazy-initialised by RateLimitMixin._enforce_rate_limit.
        # 东财补丁开启才执行打补丁操作
        if get_config().enable_eastmoney_patch:
            eastmoney_patch()

    @staticmethod
    def _build_history_failure_message(
        stock_code: str,
        beg_date: str,
        end_date: str,
        exc: Exception,
        elapsed: float,
        is_etf: bool = False,
    ) -> Tuple[str, str]:
        category, detail = _classify_eastmoney_error(exc)
        instrument_type = "ETF" if is_etf else "stock"
        message = (
            "Eastmoney 历史K线接口失败: "
            f"endpoint={EASTMONEY_HISTORY_ENDPOINT}, stock_code={stock_code}, "
            f"market_type={instrument_type}, range={beg_date}~{end_date}, "
            f"category={category}, error_type={type(exc).__name__}, elapsed={elapsed:.2f}s, detail={detail}"
        )
        return category, message

    # _set_random_user_agent and _enforce_rate_limit are provided by RateLimitMixin
    
    def _run_with_timeout(self, fn, label: str, timeout: float = None):
        """Execute *fn* in a thread with a wall-clock timeout.

        Returns the result of *fn* on success, or raises DataFetchError /
        original exception on timeout / failure so the caller can handle it.
        """
        timeout = timeout or self._EFINANCE_CALL_TIMEOUT
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ef_timeout")
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            fut.cancel()
            logger.warning(
                f"[efinance] {label} timed out after {timeout}s"
            )
            raise DataFetchError(
                f"efinance {label} timed out after {timeout}s"
            )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    
    @retry(
        stop=stop_after_attempt(1),  # 减少到1次，避免触发限流
        wait=wait_exponential(multiplier=1, min=4, max=60),  # 保持等待时间设置
        retry=retry_if_exception_type((
            ConnectionError,
            TimeoutError,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 efinance 获取原始数据
        
        根据代码类型自动选择 API：
        - 美股：不支持，抛出异常让 DataFetcherManager 切换到其他数据源
        - 普通股票：使用 ef.stock.get_quote_history()
        - ETF 基金：使用 ef.stock.get_quote_history()（ETF 是交易所证券，使用股票 K 线接口）
        
        流程：
        1. 判断代码类型（美股/股票/ETF）
        2. 设置随机 User-Agent
        3. 执行速率限制（随机休眠）
        4. 调用对应的 efinance API
        5. 处理返回数据
        """
        # 美股不支持，抛出异常让 DataFetcherManager 切换到 AkshareFetcher/YfinanceFetcher
        if _is_us_code(stock_code):
            raise DataFetchError(f"EfinanceFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher")
        
        # 根据代码类型选择不同的获取方法
        if _is_etf_code(stock_code):
            return self._fetch_etf_data(stock_code, start_date, end_date)
        else:
            return self._fetch_stock_data(stock_code, start_date, end_date)
    
