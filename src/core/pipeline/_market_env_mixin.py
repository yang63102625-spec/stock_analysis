# -*- coding: utf-8 -*-
"""``_MarketEnvMixin``: market environment cache + context augmentation."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from threading import Lock
from typing import Any, Dict, Optional

import pandas as pd

from data_provider.realtime_types import ChipDistribution
from src.core.trading_calendar import get_market_for_stock, is_market_open

logger = logging.getLogger(__name__)


class _MarketEnvMixin:
    """Market-environment + context-snapshot helpers."""

    # --- Market environment cache (shared across concurrent analyze_stock calls) ---
    _market_env_cache: Optional[Dict[str, Any]] = None
    _market_env_cache_lock = Lock()
    _MARKET_ENV_TTL_SECONDS: int = 900  # 15 minutes

    def _get_market_environment(self) -> str:
        """Get broad market environment based on SSE index MA20.

        Returns one of: 'strong_bull', 'bull', 'neutral', 'bear', 'strong_bear'.
        Uses a 15-min TTL cache to avoid redundant API calls.
        Falls back to 'neutral' on any error (no impact on scoring).
        """
        now = time.time()

        # Check cache (thread-safe)
        with self._market_env_cache_lock:
            if (self._market_env_cache is not None
                    and now - self._market_env_cache.get('ts', 0) < self._MARKET_ENV_TTL_SECONDS):
                return self._market_env_cache['regime']

        # Fetch SSE composite index (000001.SH) daily data
        try:
            df, source = self.fetcher_manager.get_index_daily_data(
                index_code="000001.SH", days=30
            )
            if df is None or df.empty or len(df) < 20:
                logger.debug("[MarketEnv] SSE index data insufficient, defaulting to neutral")
                regime = "neutral"
                self._update_market_env_cache(regime, now)
                return regime

            # Find close column
            close_col = None
            for col in ('close', '收盘'):
                if col in df.columns:
                    close_col = col
                    break
            if close_col is None:
                self._update_market_env_cache("neutral", now)
                return "neutral"

            close_series = pd.to_numeric(df[close_col], errors='coerce').dropna()
            if len(close_series) < 20:
                self._update_market_env_cache("neutral", now)
                return "neutral"

            # Use last 25 bars for MA20 + slope calculation
            close_series = close_series.tail(25).reset_index(drop=True)
            ma20_series = close_series.rolling(window=20).mean()

            current_price = float(close_series.iloc[-1])
            current_ma20 = float(ma20_series.iloc[-1])

            if current_ma20 <= 0:
                self._update_market_env_cache("neutral", now)
                return "neutral"

            diff_pct = (current_price - current_ma20) / current_ma20 * 100

            # MA20 slope: compare current MA20 vs MA20 of 5 bars ago
            ma20_slope_positive = False
            ma20_slope_negative = False
            if len(ma20_series.dropna()) >= 6:
                ma20_5_ago = float(ma20_series.dropna().iloc[-6])
                if ma20_5_ago > 0:
                    ma20_slope_positive = current_ma20 > ma20_5_ago
                    ma20_slope_negative = current_ma20 < ma20_5_ago

            # Determine regime
            if current_price > current_ma20 and ma20_slope_positive:
                regime = "strong_bull"
            elif current_price > current_ma20:
                regime = "bull"
            elif abs(diff_pct) <= 1.0:
                regime = "neutral"
            elif current_price < current_ma20 and ma20_slope_negative:
                regime = "strong_bear"
            else:
                regime = "bear"

            logger.info(
                "[MarketEnv] SSE %.2f %s MA20 %.2f (diff %+.2f%%, slope %s) -> %s",
                current_price,
                ">" if current_price > current_ma20 else "<",
                current_ma20,
                diff_pct,
                "up" if ma20_slope_positive else ("down" if ma20_slope_negative else "flat"),
                regime.upper(),
            )
            self._update_market_env_cache(regime, now)
            return regime

        except Exception as e:
            logger.warning("[MarketEnv] Failed to determine market environment: %s", e)
            self._update_market_env_cache("neutral", now)
            return "neutral"

    def _update_market_env_cache(self, regime: str, ts: float) -> None:
        """Update the market environment cache (thread-safe)."""
        with self._market_env_cache_lock:
            self._market_env_cache = {'regime': regime, 'ts': ts}

    def _augment_historical_with_realtime(
        self, df: pd.DataFrame, realtime_quote: Any, code: str
    ) -> pd.DataFrame:
        """
        Augment historical OHLCV with today's realtime quote for intraday MA calculation.
        Issue #234: Use realtime price instead of yesterday's close for technical indicators.
        """
        if df is None or df.empty or 'close' not in df.columns:
            return df
        if realtime_quote is None:
            return df
        price = getattr(realtime_quote, 'price', None)
        if price is None or not (isinstance(price, (int, float)) and price > 0):
            return df

        # Optional: skip augmentation on non-trading days (fail-open)
        enable_realtime_tech = getattr(
            self.config, 'enable_realtime_technical_indicators', True
        )
        if not enable_realtime_tech:
            return df
        market = get_market_for_stock(code)
        if market and not is_market_open(market, date.today()):
            return df

        last_val = df['date'].max()
        last_date = (
            last_val.date() if hasattr(last_val, 'date') else
            (last_val if isinstance(last_val, date) else pd.Timestamp(last_val).date())
        )
        yesterday_close = float(df.iloc[-1]['close']) if len(df) > 0 else price
        open_p = getattr(realtime_quote, 'open_price', None) or getattr(
            realtime_quote, 'pre_close', None
        ) or yesterday_close
        high_p = getattr(realtime_quote, 'high', None) or price
        low_p = getattr(realtime_quote, 'low', None) or price
        vol = getattr(realtime_quote, 'volume', None) or 0
        amt = getattr(realtime_quote, 'amount', None)
        pct = getattr(realtime_quote, 'change_pct', None)

        if last_date >= date.today():
            # Update last row with realtime close (copy to avoid mutating caller's df)
            df = df.copy()
            idx = df.index[-1]
            df.loc[idx, 'close'] = price
            if open_p is not None:
                df.loc[idx, 'open'] = open_p
            if high_p is not None:
                df.loc[idx, 'high'] = high_p
            if low_p is not None:
                df.loc[idx, 'low'] = low_p
            if vol:
                df.loc[idx, 'volume'] = vol
            if amt is not None:
                df.loc[idx, 'amount'] = amt
            if pct is not None:
                df.loc[idx, 'pct_chg'] = pct
        else:
            # Append virtual today row
            new_row = {
                'code': code,
                'date': date.today(),
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': price,
                'volume': vol,
                'amount': amt if amt is not None else 0,
                'pct_chg': pct if pct is not None else 0,
            }
            new_df = pd.DataFrame([new_row])
            df = pd.concat([df, new_df], ignore_index=True)
        return df

    def _build_context_snapshot(
        self,
        enhanced_context: Dict[str, Any],
        news_content: Optional[str],
        realtime_quote: Any,
        chip_data: Optional[ChipDistribution]
    ) -> Dict[str, Any]:
        """
        构建分析上下文快照
        """
        return {
            "enhanced_context": enhanced_context,
            "news_content": news_content,
            "realtime_quote_raw": self._safe_to_dict(realtime_quote),
            "chip_distribution_raw": self._safe_to_dict(chip_data),
        }

    @staticmethod
    def _safe_to_dict(value: Any) -> Optional[Dict[str, Any]]:
        """
        安全转换为字典
        """
        if value is None:
            return None
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                return None
        if hasattr(value, "__dict__"):
            try:
                return dict(value.__dict__)
            except Exception:
                return None
        return None

    def _resolve_query_source(self, query_source: Optional[str]) -> str:
        """
        解析请求来源。

        优先级（从高到低）：
        1. 显式传入的 query_source：调用方明确指定时优先使用，便于覆盖推断结果或兼容未来 source_message 来自非 bot 的场景
        2. 存在 source_message 时推断为 "bot"：当前约定为机器人会话上下文
        3. 存在 query_id 时推断为 "web"：Web 触发的请求会带上 query_id
        4. 默认 "system"：定时任务或 CLI 等无上述上下文时

        Args:
            query_source: 调用方显式指定的来源，如 "bot" / "web" / "cli" / "system"

        Returns:
            归一化后的来源标识字符串，如 "bot" / "web" / "cli" / "system"
        """
        if query_source:
            return query_source
        if self.source_message:
            return "bot"
        if self.query_id:
            return "web"
        return "system"

    def _build_query_context(self, query_id: Optional[str] = None) -> Dict[str, str]:
        """
        生成用户查询关联信息
        """
        effective_query_id = query_id or self.query_id or ""

        context: Dict[str, str] = {
            "query_id": effective_query_id,
            "query_source": self.query_source or "",
        }

        if self.source_message:
            context.update({
                "requester_platform": self.source_message.platform or "",
                "requester_user_id": self.source_message.user_id or "",
                "requester_user_name": self.source_message.user_name or "",
                "requester_chat_id": self.source_message.chat_id or "",
                "requester_message_id": self.source_message.message_id or "",
                "requester_query": self.source_message.content or "",
            })

        return context
    
