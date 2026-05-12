# -*- coding: utf-8 -*-
"""Tushare-specific helper functions and constants."""
from __future__ import annotations

import re
from datetime import datetime


# ETF code prefixes by exchange
# Shanghai: 51xxxx, 52xxxx, 56xxxx, 58xxxx
# Shenzhen: 15xxxx, 16xxxx, 18xxxx
_ETF_SH_PREFIXES = ('51', '52', '56', '58')
_ETF_SZ_PREFIXES = ('15', '16', '18')
_ETF_ALL_PREFIXES = _ETF_SH_PREFIXES + _ETF_SZ_PREFIXES


def _get_dynamic_cache_ttl() -> float:
    """Return dynamic cache TTL based on A-share trading session.

    During active trading hours the cache is refreshed more aggressively
    (10 s) so that screening always works with near-real-time data.
    Outside trading hours a conservative TTL (120 s) avoids unnecessary
    API calls.
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
    except ImportError:
        import pytz
        now = datetime.now(pytz.timezone("Asia/Shanghai"))

    t = now.hour * 100 + now.minute
    # Trading sessions: 9:15-11:30, 13:00-15:00
    if (915 <= t <= 1130) or (1300 <= t <= 1500):
        return 10.0  # aggressive refresh during trading
    return 120.0  # conservative during off-hours


def _is_etf_code(stock_code: str) -> bool:
    """Check if the code is an ETF fund code.

    ETF code ranges:
    - Shanghai ETF: 51xxxx, 52xxxx, 56xxxx, 58xxxx
    - Shenzhen ETF: 15xxxx, 16xxxx, 18xxxx
    """
    code = stock_code.strip().split('.')[0]
    return code.startswith(_ETF_ALL_PREFIXES) and len(code) == 6


def _is_us_code(stock_code: str) -> bool:
    """Determine whether ``stock_code`` looks like a US ticker.

    US codes consist of 1-5 uppercase letters, optionally followed by
    a single ``.X`` suffix (e.g. ``BRK.B``).
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))
