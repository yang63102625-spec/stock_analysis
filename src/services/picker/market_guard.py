# -*- coding: utf-8 -*-
"""Market environment assessment / guard logic for the stock picker."""

import logging
from typing import Optional

import pandas as pd

from src.services.picker.constants import MarketEnvironment

logger = logging.getLogger(__name__)


def check_market_environment(data_manager, as_of_date: Optional[str] = None) -> Optional[MarketEnvironment]:
    """Check SSE index vs MA20 to determine market regime.

    Returns MarketEnvironment or None if data unavailable.
    """
    if not data_manager:
        return None
    try:
        # Use SSE composite index (000001.SH) via dedicated index API
        df, source = data_manager.get_index_daily_data(
            index_code="000001.SH", days=25, end_date=as_of_date,
        )
        if df is None or len(df) < 20:
            logger.warning("[MarketGuard] SSE index data insufficient (<20 bars)")
            return None

        close_col = _first_col(df, "close", "收盘")
        if close_col is None:
            return None

        close_series = pd.to_numeric(df[close_col], errors="coerce").dropna()
        if len(close_series) < 20:
            return None

        close_series = close_series.tail(20)
        ma20 = float(close_series.mean())
        current = float(close_series.iloc[-1])
        diff_pct = (current - ma20) / ma20 * 100 if ma20 > 0 else 0.0
        logger.debug("[MarketGuard] SSE index data: %d bars, latest close=%.1f", len(df), current)

        # Buffer zone: within 1% below MA20 is considered neutral (not weak)
        MARKET_GUARD_BUFFER_PCT = 1.0

        if current > ma20:
            regime = "strong"
        elif (ma20 - current) / ma20 * 100 <= MARKET_GUARD_BUFFER_PCT:
            regime = "neutral"  # Within buffer zone
        else:
            regime = "weak"

        env = MarketEnvironment(
            is_strong=regime != "weak",  # strong and neutral both pass
            index_price=current,
            index_ma20=ma20,
            diff_pct=diff_pct,
            regime=regime,
        )
        logger.info(
            "[MarketGuard] SSE %.1f %s MA20 %.1f (diff %+.2f%%) -> %s",
            current, ">" if current > ma20 else "<", ma20, diff_pct,
            regime.upper(),
        )
        return env
    except Exception as e:
        logger.warning("[MarketGuard] Market check failed: %s", e)
        return None


def _first_col(df: pd.DataFrame, *names: str):
    """Return first column name that exists in df, or None."""
    for n in names:
        if n in df.columns:
            return n
    return None
