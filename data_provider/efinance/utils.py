# -*- coding: utf-8 -*-
"""Module-level helpers + constants used across the Efinance mixins.

The TTLCache instances and the small ``_is_etf_code`` /
``_get_realtime_ttl`` / ``_classify_eastmoney_error`` helpers live here so
they can be imported from each mixin without circular dependencies.
"""
from __future__ import annotations


import logging
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import requests  # 引入 requests 以捕获异常
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from patch.eastmoney_patch import eastmoney_patch
from src.config import get_config
from src.exceptions import DataFetchError, RateLimitError

from ..base import BaseFetcher, STANDARD_COLUMNS, is_bse_code, is_st_stock, is_kc_cy_stock, normalize_stock_code
from ..rate_limit_mixin import RateLimitMixin, USER_AGENTS
from ..realtime_types import (
    UnifiedRealtimeQuote, RealtimeSource,
    get_realtime_circuit_breaker,
    safe_float, safe_int  # 使用统一的类型转换函数
)


logger = logging.getLogger(__name__)

EASTMONEY_HISTORY_ENDPOINT = "push2his.eastmoney.com/api/qt/stock/kline/get"


# User-Agent pool is now imported from rate_limit_mixin.USER_AGENTS


# ---------------------------------------------------------------------------
# Realtime cache with dynamic TTL: 60s during trading hours, 600s after-hours.
# ---------------------------------------------------------------------------
_INTRADAY_TTL = 60    # 1 min — keep data fresh during trading
_AFTERHOURS_TTL = 600  # 10 min — relax after market close


def _get_realtime_ttl() -> int:
    """Return cache TTL based on current A-share trading session.

    Trading window: weekdays 09:15 – 15:05 (CST).  Outside this window
    the data is static so a longer TTL is safe.
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    # Weekends
    if now.weekday() >= 5:
        return _AFTERHOURS_TTL
    t = now.hour * 100 + now.minute  # e.g. 0930, 1505
    if 915 <= t <= 1505:
        return _INTRADAY_TTL
    return _AFTERHOURS_TTL


# Realtime caches use the unified ``TTLCache``; dynamic TTL comes from
# ``_get_realtime_ttl()`` and is passed at ``set`` time.
from ..caching_manager import TTLCache  # noqa: E402  (import-after-definition)

_realtime_cache = TTLCache(name="efinance_realtime_a")
_etf_realtime_cache = TTLCache(name="efinance_realtime_etf")
_REALTIME_KEY = "spot"


def _is_etf_code(stock_code: str) -> bool:
    """
    判断代码是否为 ETF 基金
    
    ETF 代码规则：
    - 上交所 ETF: 51xxxx, 52xxxx, 56xxxx, 58xxxx
    - 深交所 ETF: 15xxxx, 16xxxx, 18xxxx
    
    Args:
        stock_code: 股票/基金代码
        
    Returns:
        True 表示是 ETF 代码，False 表示是普通股票代码
    """
    etf_prefixes = ('51', '52', '56', '58', '15', '16', '18')
    return stock_code.startswith(etf_prefixes) and len(stock_code) == 6


def _is_us_code(stock_code: str) -> bool:
    """
    判断代码是否为美股
    
    美股代码规则：
    - 1-5个大写字母，如 'AAPL', 'TSLA'
    - 可能包含 '.'，如 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


def _classify_eastmoney_error(exc: Exception) -> Tuple[str, str]:
    """
    Classify Eastmoney request failures into stable log categories.
    """
    message = str(exc).strip()
    lowered = message.lower()

    remote_disconnect_keywords = (
        'remotedisconnected',
        'remote end closed connection without response',
        'connection aborted',
        'connection broken',
        'protocolerror',
    )
    timeout_keywords = (
        'timeout',
        'timed out',
        'readtimeout',
        'connecttimeout',
    )
    rate_limit_keywords = (
        'banned',
        'blocked',
        '频率',
        'rate limit',
        'too many requests',
        '429',
        '限制',
        'forbidden',
        '403',
    )

    if any(keyword in lowered for keyword in remote_disconnect_keywords):
        return "remote_disconnect", message
    if isinstance(exc, (TimeoutError, requests.exceptions.Timeout)) or any(
        keyword in lowered for keyword in timeout_keywords
    ):
        return "timeout", message
    if any(keyword in lowered for keyword in rate_limit_keywords):
        return "rate_limit_or_anti_bot", message
    if isinstance(exc, requests.exceptions.RequestException):
        return "request_error", message
    return "unknown_request_error", message


