# -*- coding: utf-8 -*-
"""Historical and reference data: daily K-line, names, list, chip distribution."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..base import DataFetchError, RateLimitError, STANDARD_COLUMNS
from ..realtime_types import ChipDistribution, safe_float
from .utils import _is_etf_code, _is_us_code

logger = logging.getLogger(__name__)


class _HistoricalMixin:
    """Mixin: ``daily``/``fund_daily``, stock names, chip distribution."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch raw OHLCV data from Tushare.

        Selects ``fund_daily`` for ETFs and ``daily`` for regular stocks.
        Raises ``RateLimitError`` when the API reports quota exhaustion.
        """
        if self._api is None:
            raise DataFetchError("Tushare API 未初始化，请检查 Token 配置")

        if _is_us_code(stock_code):
            raise DataFetchError(
                f"TushareFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher"
            )

        self._check_rate_limit()

        ts_code = self._convert_stock_code(stock_code)

        # Tushare requires YYYYMMDD.
        ts_start = start_date.replace('-', '')
        ts_end = end_date.replace('-', '')

        is_etf = _is_etf_code(stock_code)
        api_name = "fund_daily" if is_etf else "daily"
        logger.debug(f"调用 Tushare {api_name}({ts_code}, {ts_start}, {ts_end})")

        try:
            if is_etf:
                df = self._api.fund_daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
            else:
                df = self._api.daily(
                    ts_code=ts_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )

            return df

        except Exception as e:
            error_msg = str(e).lower()

            if any(keyword in error_msg for keyword in ['quota', '配额', 'limit', '权限']):
                logger.warning(f"Tushare 配额可能超限: {e}")
                raise RateLimitError(f"Tushare 配额超限: {e}") from e

            raise DataFetchError(f"Tushare 获取数据失败: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Map Tushare ``daily`` columns to the project-wide standard schema.

        Tushare returns: ts_code, trade_date, open, high, low, close,
        pre_close, change, pct_chg, vol, amount.
        """
        df = df.copy()

        column_mapping = {
            'trade_date': 'date',
            'vol': 'volume',
            # open/high/low/close/amount/pct_chg already match.
        }

        df = df.rename(columns=column_mapping)

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        # Tushare ``vol`` is in 手 (lots) - convert to 股 (shares).
        if 'volume' in df.columns:
            df['volume'] = df['volume'] * 100

        # Tushare ``amount`` is in 千元 - convert to 元.
        if 'amount' in df.columns:
            df['amount'] = df['amount'] * 1000

        df['code'] = stock_code

        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]

        return df

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """Return the display name for ``stock_code`` via ``stock_basic``/``fund_basic``.

        Returns ``None`` when the API is unavailable or the lookup fails.
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，无法获取股票名称")
            return None

        if hasattr(self, '_stock_name_cache') and stock_code in self._stock_name_cache:
            return self._stock_name_cache[stock_code]

        if not hasattr(self, '_stock_name_cache'):
            self._stock_name_cache = {}

        try:
            self._check_rate_limit()

            ts_code = self._convert_stock_code(stock_code)

            if _is_etf_code(stock_code):
                df = self._api.fund_basic(
                    ts_code=ts_code,
                    fields='ts_code,name',
                )
            else:
                df = self._api.stock_basic(
                    ts_code=ts_code,
                    fields='ts_code,name',
                )

            if df is not None and not df.empty:
                name = df.iloc[0]['name']
                self._stock_name_cache[stock_code] = name
                logger.debug(f"Tushare 获取股票名称成功: {stock_code} -> {name}")
                return name

        except Exception as e:
            logger.warning(f"Tushare 获取股票名称失败 {stock_code}: {e}")

        return None

    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """Return the full list of listed stocks (``code``, ``name`` and meta).

        Side effect: warms the per-instance ``_stock_name_cache``.
        """
        if self._api is None:
            logger.warning("Tushare API 未初始化，无法获取股票列表")
            return None

        try:
            self._check_rate_limit()

            df = self._api.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,name,industry,area,market',
            )

            if df is not None and not df.empty:
                df['code'] = df['ts_code'].apply(lambda x: x.split('.')[0])

                if not hasattr(self, '_stock_name_cache'):
                    self._stock_name_cache = {}
                for _, row in df.iterrows():
                    self._stock_name_cache[row['code']] = row['name']

                logger.info(f"Tushare 获取股票列表成功: {len(df)} 条")
                return df[['code', 'name', 'industry', 'area', 'market']]

        except Exception as e:
            logger.warning(f"Tushare 获取股票列表失败: {e}")

        return None

    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """Return chip distribution via ``cyq_chips`` (5000-credit endpoint).

        Updates 18:00-19:00 daily; used as fallback when Akshare/Eastmoney fails.
        """
        if self._api is None:
            return None
        if _is_us_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 是美股，无筹码分布数据")
            return None
        if _is_etf_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 是 ETF，无筹码分布数据")
            return None

        try:
            self._check_rate_limit()
            ts_code = self._convert_stock_code(stock_code)
            china_now = datetime.now(ZoneInfo("Asia/Shanghai"))
            end_date = china_now.strftime("%Y%m%d")
            start_date = (china_now - pd.Timedelta(days=10)).strftime("%Y%m%d")

            df_cal = self._api.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date)
            if df_cal is None or df_cal.empty:
                return None
            df_cal.columns = [c.lower() for c in df_cal.columns]
            open_dates = df_cal[df_cal["is_open"] == 1]["cal_date"].tolist()
            if not open_dates:
                return None
            trade_date = open_dates[-1]

            self._check_rate_limit()
            df = self._api.cyq_chips(ts_code=ts_code, trade_date=trade_date)
            if df is None or df.empty:
                logger.debug(f"[筹码分布] Tushare cyq_chips 返回空 {stock_code} {trade_date}")
                return None

            df.columns = [c.lower() for c in df.columns]
            if df.empty:
                return None

            price = pd.to_numeric(df["price"], errors="coerce")
            pct = pd.to_numeric(df["percent"], errors="coerce").fillna(0)
            valid = price.notna() & (pct > 0)
            price = price[valid].values
            pct = pct[valid].values
            if len(price) == 0:
                return None

            avg_cost = float(np.sum(price * pct) / 100)
            if avg_cost <= 0:
                return None

            self._check_rate_limit()
            df_daily = self._api.daily(ts_code=ts_code, trade_date=trade_date)
            close_price = None
            if df_daily is not None and not df_daily.empty:
                df_daily.columns = [c.lower() for c in df_daily.columns]
                close_price = safe_float(df_daily.iloc[0].get("close"))

            idx = np.argsort(price)
            price_s = price[idx]
            pct_s = pct[idx]
            cum = np.cumsum(pct_s)

            def _percentile_price(pct_target: float) -> float:
                i = np.searchsorted(cum, pct_target)
                return float(price_s[min(i, len(price_s) - 1)])

            cost_90_low = _percentile_price(5)
            cost_90_high = _percentile_price(95)
            cost_70_low = _percentile_price(15)
            cost_70_high = _percentile_price(85)
            concentration_90 = (cost_90_high - cost_90_low) / avg_cost if avg_cost > 0 else 0
            concentration_70 = (cost_70_high - cost_70_low) / avg_cost if avg_cost > 0 else 0

            profit_ratio = 0.0
            if close_price and close_price > 0:
                below = pct_s[price_s < close_price]
                profit_ratio = float(np.sum(below) / 100) if len(below) > 0 else 0

            date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
            chip = ChipDistribution(
                code=stock_code,
                date=date_str,
                source="tushare",
                profit_ratio=profit_ratio,
                avg_cost=avg_cost,
                cost_90_low=cost_90_low,
                cost_90_high=cost_90_high,
                concentration_90=concentration_90,
                cost_70_low=cost_70_low,
                cost_70_high=cost_70_high,
                concentration_70=concentration_70,
            )
            logger.info(
                f"[筹码分布] {stock_code} Tushare 日期={date_str}: 获利比例={chip.profit_ratio:.1%}, "
                f"平均成本={chip.avg_cost:.2f}, 90%集中度={chip.concentration_90:.2%}"
            )
            return chip
        except Exception as e:
            logger.warning(f"[筹码分布] Tushare 获取 {stock_code} 失败: {e}")
            return None
