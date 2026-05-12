# -*- coding: utf-8 -*-
"""Akshare-specific helpers and small reusable constants."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Tuple

import requests

from ..base import is_bse_code
from ..us_index_mapping import is_us_stock_code

SINA_REALTIME_ENDPOINT = "hq.sinajs.cn/list"
TENCENT_REALTIME_ENDPOINT = "qt.gtimg.cn/q"

# ---------------------------------------------------------------------------
# Realtime cache with dynamic TTL: 60s during trading hours, 1200s after-hours.
# ---------------------------------------------------------------------------
_INTRADAY_TTL = 60     # 1 min - keep data fresh during trading
_AFTERHOURS_TTL = 1200  # 20 min - relax after market close


def _get_realtime_ttl() -> int:
    """Return cache TTL based on current A-share trading session.

    Trading window: weekdays 09:15 - 15:05 (CST). Outside this window
    the data is static so a longer TTL is safe.
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.weekday() >= 5:
        return _AFTERHOURS_TTL
    t = now.hour * 100 + now.minute
    if 915 <= t <= 1505:
        return _INTRADAY_TTL
    return _AFTERHOURS_TTL


# Cache dicts - ttl is computed dynamically via _get_realtime_ttl().
_realtime_cache: Dict[str, Any] = {
    'data': None,
    'timestamp': 0,
}

_etf_realtime_cache: Dict[str, Any] = {
    'data': None,
    'timestamp': 0,
}


def _is_etf_code(stock_code: str) -> bool:
    """Return ``True`` for ETF fund codes (51/52/56/58 SH, 15/16/18 SZ)."""
    etf_prefixes = ('51', '52', '56', '58', '15', '16', '18')
    code = stock_code.strip().split('.')[0]
    return code.startswith(etf_prefixes) and len(code) == 6


def _is_hk_code(stock_code: str) -> bool:
    """Return ``True`` for Hong Kong tickers (5-digit, optional ``hk`` prefix)."""
    code = stock_code.lower()
    if code.startswith('hk'):
        # An ``hk`` prefix is unambiguous; remainder must be 1-5 digits.
        numeric_part = code[2:]
        return numeric_part.isdigit() and 1 <= len(numeric_part) <= 5
    # Without prefix only pure 5-digit codes are HK (avoid clashing with A-share).
    return code.isdigit() and len(code) == 5


def is_hk_stock_code(stock_code: str) -> bool:
    """Public wrapper around :func:`_is_hk_code` for cross-module use."""
    return _is_hk_code(stock_code)


def _is_us_code(stock_code: str) -> bool:
    """Return ``True`` for US stock tickers (delegates to ``us_index_mapping``)."""
    return is_us_stock_code(stock_code)


def _to_sina_tx_symbol(stock_code: str) -> str:
    """Convert a 6-digit A-share code to the sh/sz/bj symbol used by Sina/Tencent."""
    base = (stock_code.strip().split(".")[0] if "." in stock_code else stock_code).strip()
    if is_bse_code(base):
        return f"bj{base}"
    # Shanghai: 60xxxx (main), 5xxxx (ETF), 90xxxx (B-share)
    if base.startswith(("6", "5", "90")):
        return f"sh{base}"
    return f"sz{base}"


def _classify_realtime_http_error(exc: Exception) -> Tuple[str, str]:
    """Classify Sina/Tencent realtime quote failures into stable categories."""
    detail = str(exc).strip() or type(exc).__name__
    lowered = detail.lower()

    remote_disconnect_keywords = (
        "remotedisconnected",
        "remote end closed connection without response",
        "connection aborted",
        "connection broken",
        "protocolerror",
        "chunkedencodingerror",
    )
    timeout_keywords = (
        "timeout",
        "timed out",
        "readtimeout",
        "connecttimeout",
    )
    rate_limit_keywords = (
        "banned",
        "blocked",
        "频率",
        "rate limit",
        "too many requests",
        "429",
        "限制",
        "forbidden",
        "403",
    )

    if any(keyword in lowered for keyword in remote_disconnect_keywords):
        return "remote_disconnect", detail
    if isinstance(exc, (TimeoutError, requests.exceptions.Timeout)) or any(
        keyword in lowered for keyword in timeout_keywords
    ):
        return "timeout", detail
    if any(keyword in lowered for keyword in rate_limit_keywords):
        return "rate_limit_or_anti_bot", detail
    if isinstance(exc, requests.exceptions.RequestException):
        return "request_error", detail
    return "unknown_request_error", detail


def _build_realtime_failure_message(
    source_name: str,
    endpoint: str,
    stock_code: str,
    symbol: str,
    category: str,
    detail: str,
    elapsed: float,
    error_type: str,
) -> str:
    return (
        f"{source_name} 实时行情接口失败: endpoint={endpoint}, stock_code={stock_code}, "
        f"symbol={symbol}, category={category}, error_type={error_type}, "
        f"elapsed={elapsed:.2f}s, detail={detail}"
    )
