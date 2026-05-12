# -*- coding: utf-8 -*-
"""
Core ``TushareFetcher`` setup: API initialisation, rate limiting and code
conversion. Other concerns (historical, realtime, market) live in mixin
modules and are composed by ``data_provider.tushare.fetcher.TushareFetcher``.
"""
from __future__ import annotations

import json as _json
import logging
import os
import time
import types
from typing import Optional

import pandas as pd
import requests

from ..base import BaseFetcher, is_bse_code
from ..rate_limit_mixin import RateLimitMixin
from .utils import _ETF_SH_PREFIXES, _ETF_SZ_PREFIXES

logger = logging.getLogger(__name__)


class _TushareCore(RateLimitMixin, BaseFetcher):
    """Connection management, rate limiting and code conversion.

    Mixins must inherit from this class so they can rely on ``self._api``,
    ``self._check_rate_limit()`` and ``self._convert_stock_code()``.
    """

    name = "TushareFetcher"
    priority = int(os.getenv("TUSHARE_PRIORITY", "2"))  # default priority; adjusted in __init__ based on token

    def __init__(self, rate_limit_per_minute: int = 80):
        """Initialise TushareFetcher.

        Args:
            rate_limit_per_minute: Max calls per minute (default 80, the
                Tushare free-tier quota).
        """
        self.rate_limit_per_minute = rate_limit_per_minute
        self._call_count = 0  # calls within current minute window
        self._minute_start: Optional[float] = None  # window start timestamp
        self._api: Optional[object] = None  # Tushare API handle

        self._init_api()

        # Bump priority once we know API initialised successfully.
        self.priority = self._determine_priority()

    def _init_api(self) -> None:
        """Initialise the Tushare API handle. Disabled if token missing."""
        from src.config import get_config

        config = get_config()

        if not config.tushare_token:
            logger.warning("Tushare Token 未配置，此数据源不可用")
            return

        try:
            import tushare as ts

            # Pass token directly to pro_api() to avoid writing ~/tk.csv
            # (fixes Operation not permitted in sandbox/restricted envs).
            self._api = ts.pro_api(token=config.tushare_token)

            # Fix: tushare SDK 1.4.x hardcodes api.waditu.com/dataapi which may
            # be unavailable (503). Monkey-patch the query method to use the
            # official api.tushare.pro endpoint which posts to root URL.
            self._patch_api_endpoint(config.tushare_token)

            logger.info("Tushare API 初始化成功")

        except Exception as e:
            logger.error(f"Tushare API 初始化失败: {e}")
            self._api = None

    def _patch_api_endpoint(self, token: str) -> None:
        """Patch the SDK to POST to the official api.tushare.pro root URL.

        The bundled SDK (v1.4.x) hardcodes ``http://api.waditu.com/dataapi``
        which sometimes returns 503, manifesting as silent empty DataFrames.
        Replacing the ``query`` method side-steps the broken endpoint.
        """
        TUSHARE_API_URL = "http://api.tushare.pro"
        _token = token
        _timeout = getattr(self._api, '_DataApi__timeout', 30)

        def patched_query(self_api, api_name, fields='', **kwargs):
            req_params = {
                'api_name': api_name,
                'token': _token,
                'params': kwargs,
                'fields': fields,
            }
            res = requests.post(TUSHARE_API_URL, json=req_params, timeout=_timeout)
            if res.status_code != 200:
                raise Exception(f"Tushare API HTTP {res.status_code}")
            result = _json.loads(res.text)
            if result['code'] != 0:
                raise Exception(result['msg'])
            data = result['data']
            columns = data['fields']
            items = data['items']
            return pd.DataFrame(items, columns=columns)

        self._api.query = types.MethodType(patched_query, self._api)
        logger.debug(f"Tushare API endpoint patched to {TUSHARE_API_URL}")

    def _determine_priority(self) -> int:
        """Pick priority based on token configuration and API state.

        - Token configured + API initialised -> priority -1 (highest, beats efinance).
        - Otherwise -> priority 2 (default fallback).
        """
        from src.config import get_config

        config = get_config()

        if config.tushare_token and self._api is not None:
            logger.info(
                "✅ 检测到 TUSHARE_TOKEN 且 API 初始化成功，"
                "Tushare 数据源优先级提升为最高 (Priority -1)"
            )
            return -1

        return 2

    def is_available(self) -> bool:
        """Return ``True`` when the API handle is ready."""
        return self._api is not None

    def _check_rate_limit(self) -> None:
        """Enforce the per-minute call budget.

        Sleeps until the next minute window when the quota is exhausted,
        then resets the counter.
        """
        current_time = time.time()

        if self._minute_start is None:
            self._minute_start = current_time
            self._call_count = 0
        elif current_time - self._minute_start >= 60:
            # Crossed into a new minute - reset.
            self._minute_start = current_time
            self._call_count = 0
            logger.debug("速率限制计数器已重置")

        if self._call_count >= self.rate_limit_per_minute:
            elapsed = current_time - self._minute_start
            sleep_time = max(0, 60 - elapsed) + 1  # +1 second buffer

            logger.warning(
                f"Tushare 达到速率限制 ({self._call_count}/{self.rate_limit_per_minute} 次/分钟)，"
                f"等待 {sleep_time:.1f} 秒..."
            )

            time.sleep(sleep_time)

            self._minute_start = time.time()
            self._call_count = 0

        self._call_count += 1
        logger.debug(f"Tushare 当前分钟调用次数: {self._call_count}/{self.rate_limit_per_minute}")

    def _convert_stock_code(self, stock_code: str) -> str:
        """Convert a 6-digit code to Tushare's ``XXXXXX.SUFFIX`` format.

        Examples:
            ``600519`` -> ``600519.SH``; ``000001`` -> ``000001.SZ``;
            ``563230`` -> ``563230.SH`` (ETF); ``430xxx`` -> ``430xxx.BJ``.
        """
        code = stock_code.strip()

        if '.' in code:
            return code.upper()

        # ETF: pick exchange by prefix.
        if code.startswith(_ETF_SH_PREFIXES) and len(code) == 6:
            return f"{code}.SH"
        if code.startswith(_ETF_SZ_PREFIXES) and len(code) == 6:
            return f"{code}.SZ"

        # BSE (Beijing Stock Exchange): 8xxxxx, 4xxxxx, 920xxx
        if is_bse_code(code):
            return f"{code}.BJ"

        # Regular stocks
        # Shanghai: 60xxxx (main board), 688xxx (STAR Market)
        # Shenzhen: 000/001/002/003/004 (main+SME), 300/301xxx (ChiNext)
        if code.startswith("60") or code.startswith("688"):
            return f"{code}.SH"
        elif code.startswith(('000', '001', '002', '003', '004', '300', '301')):
            return f"{code}.SZ"
        else:
            logger.warning(f"无法确定股票 {code} 的市场，默认使用深市")
            return f"{code}.SZ"
