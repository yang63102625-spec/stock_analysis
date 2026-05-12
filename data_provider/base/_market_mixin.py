# -*- coding: utf-8 -*-
"""``_MarketMixin``: market-wide aggregates (indices / stats / sectors)."""
from __future__ import annotations

import logging
from datetime import datetime, time as dt_time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)


class _MarketMixin:
    """Market-wide aggregate helpers for :class:`DataFetcherManager`."""

    @staticmethod
    def _is_trading_hours() -> bool:
        """Check if current time is within A-share trading hours (weekday 09:15-15:30 CST)."""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if now.weekday() >= 5:  # Saturday / Sunday
            return False
        t = now.time()
        return dt_time(9, 15) <= t <= dt_time(15, 30)

    def get_main_indices(self, region: str = "cn") -> List[Dict[str, Any]]:
        """Fetch main index realtime quotes with stale-data awareness.

        During trading hours on weekdays, if a fetcher returns data whose
        ``data_date`` is not today, it is considered stale and the next
        fetcher in the fallback chain is tried.  Outside trading hours the
        previous trading day's data is acceptable.

        When all fetchers return stale data, the last result is returned
        with an extra ``_stale`` flag on each index dict.
        """
        today_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        require_today = self._is_trading_hours()
        last_stale_data: Optional[List[Dict[str, Any]]] = None

        for fetcher in self._fetchers:
            try:
                data = fetcher.get_main_indices(region=region)
                if not data:
                    continue

                # Check freshness via data_date field
                idx_dates = [idx.get("data_date") for idx in data if idx.get("data_date")]
                is_stale = bool(idx_dates) and all(d != today_str for d in idx_dates)

                if is_stale and require_today:
                    logger.warning(
                        f"[{fetcher.name}] Index data_date={idx_dates[0]} (not today={today_str}), "
                        "trying next fetcher"
                    )
                    last_stale_data = data
                    continue

                logger.info(f"[{fetcher.name}] 获取指数行情成功")
                return data
            except Exception as e:
                logger.warning(f"[{fetcher.name}] 获取指数行情失败: {e}")
                continue

        # All fetchers returned stale data — mark and return the last one
        if last_stale_data is not None:
            logger.warning(
                "[DataFetcherManager] All fetchers returned stale index data, "
                "marking indices as _stale"
            )
            for idx in last_stale_data:
                idx["_stale"] = True
            return last_stale_data

        return []

    def get_market_stats(self) -> Dict[str, Any]:
        """Fetch market up/down statistics with stale-data awareness.

        During trading hours, if a fetcher returns data whose ``data_date``
        is not today (Shanghai timezone), it is considered stale and the next
        fetcher is tried.  When all fetchers return stale data, the last
        result is returned with an extra ``_stale`` flag.
        """
        today_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        require_today = self._is_trading_hours()
        last_stale_data: Optional[Dict[str, Any]] = None

        for fetcher in self._fetchers:
            try:
                data = fetcher.get_market_stats()
                if not data:
                    continue

                # Check freshness via data_date field
                data_date = data.get("data_date")
                is_stale = bool(data_date) and data_date != today_str

                if is_stale and require_today:
                    logger.warning(
                        f"[{fetcher.name}] Market stats data_date={data_date} "
                        f"(not today={today_str}), trying next fetcher"
                    )
                    last_stale_data = data
                    continue

                logger.info(f"[{fetcher.name}] 获取市场统计成功")
                return data
            except Exception as e:
                logger.warning(f"[{fetcher.name}] 获取市场统计失败: {e}")
                continue

        # All fetchers returned stale data — mark and return the last one
        if last_stale_data is not None:
            logger.warning(
                "[DataFetcherManager] All fetchers returned stale market stats, "
                "marking as _stale"
            )
            last_stale_data["_stale"] = True
            return last_stale_data

        return {}

    def get_sector_rankings(self, n: int = 5) -> Tuple[List[Dict], List[Dict]]:
        """Fetch sector rankings with stale-data awareness.

        During trading hours, if a fetcher returns sector dicts whose
        ``data_date`` is not today (Shanghai timezone), it is considered
        stale and the next fetcher is tried.  When all fetchers return
        stale data, the last result is returned with ``_stale=True``
        on each sector dict.
        """
        today_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        require_today = self._is_trading_hours()
        last_stale_data: Optional[Tuple[List[Dict], List[Dict]]] = None

        for fetcher in self._fetchers:
            try:
                data = fetcher.get_sector_rankings(n)
                if not data:
                    continue

                top_sectors, bottom_sectors = data
                if not top_sectors and not bottom_sectors:
                    continue

                # Check freshness via data_date on sector dicts
                all_sectors = top_sectors + bottom_sectors
                sec_dates = [s.get("data_date") for s in all_sectors if s.get("data_date")]
                is_stale = bool(sec_dates) and all(d != today_str for d in sec_dates)

                if is_stale and require_today:
                    logger.warning(
                        f"[{fetcher.name}] Sector data_date={sec_dates[0]} "
                        f"(not today={today_str}), trying next fetcher"
                    )
                    last_stale_data = data
                    continue

                logger.info(f"[{fetcher.name}] 获取板块排行成功")
                return data
            except Exception as e:
                logger.warning(f"[{fetcher.name}] 获取板块排行失败: {e}")
                continue

        # All fetchers returned stale data — mark and return the last one
        if last_stale_data is not None:
            logger.warning(
                "[DataFetcherManager] All fetchers returned stale sector data, "
                "marking as _stale"
            )
            top_sectors, bottom_sectors = last_stale_data
            for sec in top_sectors + bottom_sectors:
                sec["_stale"] = True
            return top_sectors, bottom_sectors

        return [], []

    def get_index_daily_data(
        self,
        index_code: str = "000001.SH",
        days: int = 25,
        end_date: Optional[str] = None,
    ) -> Tuple[Optional[pd.DataFrame], str]:
        """Get index daily OHLCV data (e.g. SSE index 000001.SH).

        Uses Tushare index_daily API. Returns (DataFrame, source_name) or
        (None, "") when data is unavailable.
        """
        from datetime import timedelta

        if end_date is None:
            end_date_dt = datetime.now()
        else:
            end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")

        start_date_dt = end_date_dt - timedelta(days=days * 2)
        ts_end = end_date_dt.strftime("%Y%m%d")
        ts_start = start_date_dt.strftime("%Y%m%d")

        # --- Attempt 1: Tushare index_daily ---
        for fetcher in self._fetchers:
            if fetcher.name != "TushareFetcher":
                continue
            if not fetcher.is_available():
                logger.debug("[get_index_daily_data] TushareFetcher not available, skipping")
                break
            try:
                fetcher._check_rate_limit()
                df = fetcher._api.index_daily(
                    ts_code=index_code,
                    start_date=ts_start,
                    end_date=ts_end,
                )
                if df is not None and not df.empty:
                    df = df.rename(columns={"trade_date": "date", "vol": "volume"})
                    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
                    if "volume" in df.columns:
                        df["volume"] = df["volume"] * 100
                    if "amount" in df.columns:
                        df["amount"] = df["amount"] * 1000
                    df = df.sort_values("date", ascending=True).reset_index(drop=True)
                    logger.info(
                        "[get_index_daily_data] Tushare index_daily OK: %s, rows=%d",
                        index_code, len(df),
                    )
                    return df, "TushareFetcher"
            except Exception as e:
                logger.warning("[get_index_daily_data] Tushare index_daily failed: %s", e)
            break

        # --- Attempt 2: AkShare index data ---
        for fetcher in self._fetchers:
            if fetcher.name != "AkshareFetcher":
                continue
            try:
                import akshare as ak

                # akshare uses pure numeric code "000001" for SSE index
                ak_code = index_code.split(".")[0]
                ak_start = start_date_dt.strftime("%Y%m%d")
                ak_end = end_date_dt.strftime("%Y%m%d")
                df = ak.stock_zh_index_daily(symbol=f"sh{ak_code}")
                if df is not None and not df.empty:
                    df = df.rename(columns={"date": "date"})
                    df["date"] = pd.to_datetime(df["date"])
                    df = df[(df["date"] >= pd.Timestamp(start_date_dt)) & (df["date"] <= pd.Timestamp(end_date_dt))]
                    df = df.sort_values("date", ascending=True).reset_index(drop=True)
                    if not df.empty:
                        logger.info(
                            "[get_index_daily_data] AkShare OK: %s, rows=%d",
                            index_code, len(df),
                        )
                        return df, "AkshareFetcher"
            except Exception as e:
                logger.warning("[get_index_daily_data] AkShare index failed: %s", e)
            break

        logger.warning("[get_index_daily_data] All sources failed for %s", index_code)
        return None, ""

