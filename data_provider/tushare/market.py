# -*- coding: utf-8 -*-
"""
Market-wide views: index quotes, market up/down statistics and
SW industry sector rankings.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ..base import is_bse_code, is_kc_cy_stock, is_st_stock, normalize_stock_code
from ..realtime_types import safe_float
from .realtime import _SHARED_EXECUTOR

logger = logging.getLogger(__name__)


class _MarketMixin:
    """Mixin: ``get_main_indices``, ``get_market_stats``, ``get_sector_rankings``."""

    # Index mapping: ts_code -> (display_name, efinance-style code)
    _INDICES_MAP = {
        '000001.SH': ('上证指数', 'sh000001'),
        '399001.SZ': ('深证成指', 'sz399001'),
        '399006.SZ': ('创业板指', 'sz399006'),
        '000016.SH': ('上证50', 'sh000016'),
        '000905.SH': ('中证500', 'sh000905'),
        '000688.SH': ('科创50', 'sh000688'),
        '000300.SH': ('沪深300', 'sh000300'),
    }

    def get_main_indices(self, region: str = "cn") -> Optional[List[dict]]:
        """Fetch main index quotes with realtime-first, index_daily fallback.

        Priority:
        1. api.rt_idx_k() — dedicated realtime index K-line endpoint.
        2. api.index_daily() — returns previous trading-day close data.

        Return format is aligned with efinance/akshare get_main_indices().
        """
        if region != "cn":
            return None
        if self._api is None:
            return None

        # --- Strategy 1: rt_idx_k (realtime index K-line, dedicated endpoint) ---
        realtime_results = self._get_indices_via_rt_idx_k()
        if realtime_results:
            return realtime_results

        # --- Strategy 2: index_daily fallback (may return previous trading day) ---
        return self._get_indices_via_daily()

    def _get_indices_via_rt_idx_k(self) -> Optional[List[dict]]:
        """Fetch index quotes via pro_api.rt_idx_k (dedicated realtime index K-line).

        rt_idx_k returns: ts_code, name, trade_time, close, pre_close, high, open, low, vol, amount.
        pct_chg is computed as (close - pre_close) / pre_close * 100.
        data_date is extracted from trade_time.

        Returns list of index dicts, or None on failure (falls back to index_daily).
        """
        from ..realtime_types import safe_float
        try:
            tushare_codes = list(self._INDICES_MAP.keys())
            codes_str = ','.join(tushare_codes)

            # Wall-clock timeout to avoid hanging on network issues
            future = _SHARED_EXECUTOR.submit(self._api.rt_idx_k, ts_code=codes_str)
            try:
                df = future.result(timeout=8)
            except Exception:
                df = None

            if df is None or df.empty:
                logger.debug("[Tushare] rt_idx_k returned empty")
                return None

            # Normalize column names to lowercase
            df.columns = [c.lower() for c in df.columns]

            results = []
            for ts_code, (name, efinance_code) in self._INDICES_MAP.items():
                row = df[df['ts_code'] == ts_code]
                if row.empty:
                    continue
                row = row.iloc[0]

                close = safe_float(row.get('close'))
                pre_close = safe_float(row.get('pre_close'))
                high = safe_float(row.get('high'))
                low = safe_float(row.get('low'))
                open_price = safe_float(row.get('open'))
                vol = safe_float(row.get('vol'))
                amount = safe_float(row.get('amount'))
                trade_time = str(row.get('trade_time', ''))

                if close is None or close <= 0:
                    continue

                # Compute pct_chg and change from close / pre_close
                pct_chg = None
                change = None
                if pre_close and pre_close > 0:
                    change = round(close - pre_close, 4)
                    pct_chg = round((close - pre_close) / pre_close * 100, 4)

                # Extract date from trade_time (e.g. "2026-04-17 14:30:00" -> "2026-04-17")
                data_date = trade_time[:10] if len(trade_time) >= 10 else ''
                if not data_date or len(data_date) != 10:
                    # Fallback: use today's date in China timezone
                    data_date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")

                amplitude = 0.0
                if pre_close and pre_close > 0 and high and low:
                    amplitude = (high - low) / pre_close * 100

                results.append({
                    'code': efinance_code,
                    'name': name,
                    'current': close,
                    'change': change,
                    'change_pct': pct_chg,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'prev_close': pre_close,
                    'volume': vol,
                    'amount': amount * 1000 if amount else 0,
                    'amplitude': amplitude,
                    'data_date': data_date,
                })

            if results:
                logger.info(
                    f"[Tushare] Fetched {len(results)}/{len(self._INDICES_MAP)} index quotes "
                    "via rt_idx_k (realtime)"
                )
                return results

            logger.debug("[Tushare] rt_idx_k matched no index codes")
            return None

        except Exception as e:
            logger.debug(f"[Tushare] rt_idx_k index fetch failed: {e}")
            return None

    def _get_indices_via_daily(self) -> Optional[List[dict]]:
        """Fallback: fetch index data via api.index_daily (returns previous trading day)."""
        from ..realtime_types import safe_float

        china_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        end_date = china_now.strftime('%Y%m%d')
        start_date = (china_now - pd.Timedelta(days=7)).strftime('%Y%m%d')

        results = []
        for ts_code, (name, efinance_code) in self._INDICES_MAP.items():
            try:
                self._check_rate_limit()
                df = self._api.index_daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )
                if df is None or df.empty:
                    logger.debug(f"[Tushare] index_daily empty for {ts_code}")
                    continue

                # index_daily returns newest first; take the first row
                row = df.iloc[0]
                trade_date = str(row.get('trade_date', ''))

                current = safe_float(row['close'])
                prev_close = safe_float(row['pre_close'])
                high = safe_float(row['high'])
                low = safe_float(row['low'])

                # Format data_date as YYYY-MM-DD for freshness tracking
                data_date = (
                    f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
                    if len(trade_date) == 8 else trade_date
                )

                # Compute amplitude (%) consistent with efinance/akshare
                amplitude = 0.0
                if prev_close and prev_close > 0 and high and low:
                    amplitude = (high - low) / prev_close * 100

                results.append({
                    'code': efinance_code,
                    'name': name,
                    'current': current,
                    'change': safe_float(row['change']),
                    'change_pct': safe_float(row['pct_chg']),
                    'open': safe_float(row['open']),
                    'high': high,
                    'low': low,
                    'prev_close': prev_close,
                    'volume': safe_float(row['vol']),
                    'amount': safe_float(row['amount']) * 1000 if safe_float(row['amount']) else 0,
                    'amplitude': amplitude,
                    'data_date': data_date,
                })
            except Exception as e:
                logger.debug(f"[Tushare] index_daily failed for {name}({ts_code}): {e}")
                continue

        if results:
            logger.info(f"[Tushare] Fetched {len(results)}/{len(self._INDICES_MAP)} index quotes via index_daily")
            return results

        logger.warning("[Tushare] No index data retrieved from index_daily")
        return None

    def get_market_stats(self) -> Optional[dict]:
        """
        Get market up/down statistics.

        Strategy (priority order):
        1. During trading hours: use realtime_list (0-credit crawler) for live
           statistics. This is much more timely than daily() which only has
           post-market data.
        2. Fallback to daily() Pro API (works both intraday and post-market).
        """
        if self._api is None:
            return None

        try:
            self._check_rate_limit()
            logger.info("[API] Tushare get_market_stats...")

            china_now = datetime.now(ZoneInfo("Asia/Shanghai"))
            china_now_str = china_now.strftime("%H:%M")
            current_date = china_now.strftime("%Y%m%d")

            start_date = (datetime.now() - pd.Timedelta(days=20)).strftime('%Y%m%d')
            df_cal = self._api.trade_cal(exchange='SSE', start_date=start_date, end_date=current_date)
            date_list = df_cal[df_cal['is_open'] == 1]['cal_date'].tolist()

            is_trading_day = current_date in date_list
            use_realtime = is_trading_day and '09:25' <= china_now_str <= '16:30'

            # === Strategy 1: realtime_list during trading hours ===
            if use_realtime:
                rl_stats = self._market_stats_from_realtime_list()
                if rl_stats is not None:
                    rl_stats["data_date"] = china_now.strftime("%Y-%m-%d")
                    logger.info("[Tushare] market_stats from realtime_list (live)")
                    return rl_stats
                logger.debug("[Tushare] realtime_list unavailable, falling back to daily()")

            # === Strategy 2: daily() Pro API ===
            if use_realtime:
                target_date = current_date
                fallback_date = date_list[1] if len(date_list) > 1 else None
                logger.info("[Tushare] Trading hours, attempting daily() for market stats")
            else:
                fallback_date = None
                if current_date not in date_list:
                    target_date = date_list[0]
                elif china_now_str < '09:30':
                    target_date = date_list[1] if len(date_list) > 1 else date_list[0]
                else:
                    target_date = date_list[0]

            try:
                df = self._api.daily(
                    TS_CODE='3*.SZ,6*.SH,0*.SZ,92*.BJ',
                    start_date=target_date, end_date=target_date,
                )

                if (df is None or df.empty) and fallback_date:
                    logger.info(
                        f"[Tushare] daily() empty for {target_date}, "
                        f"falling back to {fallback_date}"
                    )
                    target_date = fallback_date
                    df = self._api.daily(
                        TS_CODE='3*.SZ,6*.SH,0*.SZ,92*.BJ',
                        start_date=fallback_date, end_date=fallback_date,
                    )

                if df is not None and not df.empty:
                    df.columns = [col.lower() for col in df.columns]
                    df_basic = self._api.stock_basic(fields='ts_code,name')
                    df = pd.merge(df, df_basic, on='ts_code', how='left')
                    if 'amount' in df.columns:
                        df['amount'] = df['amount'] * 1000

                    logger.info(
                        f"[Tushare] market_stats from daily() date={target_date}, rows={len(df)}"
                    )
                    stats = self._calc_market_stats(df)
                    if stats is not None:
                        stats["data_date"] = (
                            f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
                        )
                    return stats
                else:
                    logger.warning(
                        f"[Tushare] daily() returned empty for {target_date}, "
                        "no market stats available"
                    )
            except Exception as e:
                logger.error(f"[Tushare] ts.pro_api().daily failed: {e}")

        except Exception as e:
            logger.error(f"[Tushare] get_market_stats failed: {e}")

        return None

    def _market_stats_from_realtime_list(self) -> Optional[Dict[str, Any]]:
        """
        Compute market statistics directly from realtime_list snapshot.

        This avoids consuming Pro API credits and provides truly live data
        during trading hours.

        Returns:
            dict with up_count, down_count, flat_count, limit_up_count,
            limit_down_count, total_amount; or None on failure.
        """
        df = self._fetch_realtime_list()
        if df is None or df.empty:
            return None

        try:
            # realtime_list columns: ts_code, name, price, pct_change, change,
            # volume, amount, open, high, low, pre_close, ...
            required = {'ts_code', 'price', 'pre_close'}
            if not required.issubset(set(df.columns)):
                logger.warning(f"[realtime_list] missing required columns: {required - set(df.columns)}")
                return None

            # Filter to A-share stocks only (SH/SZ/BJ main boards)
            df = df[df['ts_code'].str.match(r'^(0|3|6|9)\d{5}\.(SZ|SH|BJ)$', na=False)].copy()
            if df.empty:
                return None

            df['price'] = pd.to_numeric(df['price'], errors='coerce')
            df['pre_close'] = pd.to_numeric(df['pre_close'], errors='coerce')

            # Drop rows with missing / zero prices or suspended stocks
            amount_col = 'amount' if 'amount' in df.columns else None
            if amount_col:
                df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
                df = df[(df['price'] > 0) & (df['pre_close'] > 0) & (df[amount_col] > 0)]
            else:
                df = df[(df['price'] > 0) & (df['pre_close'] > 0)]

            up_count = 0
            down_count = 0
            flat_count = 0
            limit_up_count = 0
            limit_down_count = 0

            name_col = 'name' if 'name' in df.columns else None

            for _, row in df.iterrows():
                ts_code = str(row['ts_code'])
                pure_code = ts_code.split('.')[0]
                stock_name = str(row.get('name', '')) if name_col else ''
                cur = float(row['price'])
                pre = float(row['pre_close'])

                if is_bse_code(pure_code):
                    ratio = 0.30
                elif is_kc_cy_stock(pure_code):
                    ratio = 0.20
                elif is_st_stock(stock_name):
                    ratio = 0.05
                else:
                    ratio = 0.10

                limit_up_price = np.floor(pre * (1 + ratio) * 100 + 0.5) / 100.0
                limit_down_price = np.floor(pre * (1 - ratio) * 100 + 0.5) / 100.0
                lu_tol = round(abs(pre * (1 + ratio) - limit_up_price), 10)
                ld_tol = round(abs(pre * (1 - ratio) - limit_down_price), 10)

                if abs(cur - limit_up_price) <= lu_tol:
                    limit_up_count += 1
                if abs(cur - limit_down_price) <= ld_tol:
                    limit_down_count += 1

                if cur > pre:
                    up_count += 1
                elif cur < pre:
                    down_count += 1
                else:
                    flat_count += 1

            total_amount = 0.0
            if amount_col and amount_col in df.columns:
                # realtime_list amount is in yuan; convert to 亿
                total_amount = df[amount_col].sum() / 1e8

            return {
                'up_count': up_count,
                'down_count': down_count,
                'flat_count': flat_count,
                'limit_up_count': limit_up_count,
                'limit_down_count': limit_down_count,
                'total_amount': total_amount,
            }

        except Exception as e:
            logger.warning(f"[realtime_list] market stats computation failed: {e}")
            return None
    
    def _calc_market_stats(
            self,
            df: pd.DataFrame,
            ) -> Optional[Dict[str, Any]]:
            """从行情 DataFrame 计算涨跌统计。"""
            import numpy as np

            df = df.copy()
            
            # 1. 提取基础比对数据：最新价、昨收
            # 兼容不同接口返回的列名 sina/em efinance tushare xtdata
            code_col = next((c for c in ['代码', '股票代码', 'ts_code','stock_code'] if c in df.columns), None)
            name_col = next((c for c in ['名称', '股票名称','name','name'] if c in df.columns), None)
            close_col = next((c for c in ['最新价', '最新价', 'close','lastPrice'] if c in df.columns), None)
            pre_close_col = next((c for c in ['昨收', '昨日收盘', 'pre_close','lastClose'] if c in df.columns), None)
            amount_col = next((c for c in ['成交额', '成交额', 'amount','amount'] if c in df.columns), None) 
            
            limit_up_count = 0
            limit_down_count = 0
            up_count = 0
            down_count = 0
            flat_count = 0

            for code, name, current_price, pre_close, amount in zip(
                df[code_col], df[name_col], df[close_col], df[pre_close_col], df[amount_col]
            ):
                
                # 停牌过滤 efinance 的停牌数据有时候会缺失价格显示为 '-'，em 显示为none
                if pd.isna(current_price) or pd.isna(pre_close) or current_price in ['-'] or pre_close in ['-'] or amount == 0:
                    continue
                
                # em、efinance 为str 需要转换为float
                current_price = float(current_price)
                pre_close = float(pre_close)
                
                # 获取去除前缀的纯数字代码
                pure_code = normalize_stock_code(str(code)) 

                # A. 确定每只股票的涨跌幅比例 (使用纯数字代码判断)
                if is_bse_code(pure_code): 
                    ratio = 0.30
                elif is_kc_cy_stock(pure_code): #pure_code.startswith(('688', '30')):
                    ratio = 0.20
                elif is_st_stock(name): #'ST' in str_name:
                    ratio = 0.05
                else:
                    ratio = 0.10

                # B. 严格按照 A 股规则计算涨跌停价：昨收 * (1 ± 比例) -> 四舍五入保留2位小数
                limit_up_price = np.floor(pre_close * (1 + ratio) * 100 + 0.5) / 100.0
                limit_down_price = np.floor(pre_close * (1 - ratio) * 100 + 0.5) / 100.0

                limit_up_price_Tolerance = round(abs(pre_close * (1 + ratio) - limit_up_price), 10)
                limit_down_price_Tolerance = round(abs(pre_close * (1 - ratio) - limit_down_price), 10)

                # C. 精确比对
                if current_price > 0 :
                    is_limit_up = (current_price > 0) and (abs(current_price - limit_up_price) <= limit_up_price_Tolerance)
                    is_limit_down = (current_price > 0) and (abs(current_price - limit_down_price) <= limit_down_price_Tolerance)

                    if is_limit_up:
                        limit_up_count += 1
                    if is_limit_down:
                        limit_down_count += 1

                    if current_price > pre_close:
                        up_count += 1
                    elif current_price < pre_close:
                        down_count += 1
                    else:
                        flat_count += 1
                    
            # 统计数量
            stats = {
                'up_count': up_count,
                'down_count': down_count,
                'flat_count': flat_count,
                'limit_up_count': limit_up_count,
                'limit_down_count': limit_down_count,
                'total_amount': 0.0,
            }
            
            # 成交额统计
            if amount_col and amount_col in df.columns:
                df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
                stats['total_amount'] = (df[amount_col].sum() / 1e8)
                
            return stats

    def get_sector_rankings(self, n: int = 5) -> Optional[Tuple[List[Dict], List[Dict]]]:
        """
        获取板块涨跌榜 (Tushare Pro).
        Priority: rt_sw_k (realtime) > sw_daily (daily fallback).
        申万一级行业，按涨跌幅排序。优先于东财接口（易限流）。
        """
        if self._api is None:
            return None

        # --- Strategy 1: rt_sw_k (realtime, highest priority) ---
        rt_result = self._get_sector_rankings_via_rt_sw_k(n)
        if rt_result is not None:
            return rt_result

        # --- Strategy 2: sw_daily (daily, fallback) ---
        return self._get_sector_rankings_via_sw_daily(n)

    def _get_sector_rankings_via_rt_sw_k(self, n: int) -> Optional[Tuple[List[Dict], List[Dict]]]:
        """Fetch sector rankings via rt_sw_k (realtime SW industry K-line).

        Returns (top_sectors, bottom_sectors) tuple, or None on failure.
        """
        try:
            self._check_rate_limit()
            logger.debug("[板块排行] Trying Tushare rt_sw_k (realtime)...")

            # Wall-clock timeout to avoid hanging on network issues
            future = _SHARED_EXECUTOR.submit(self._api.rt_sw_k)
            try:
                df_rt = future.result(timeout=8)
            except Exception:
                df_rt = None

            if df_rt is None or df_rt.empty:
                logger.debug("[板块排行] rt_sw_k returned empty")
                return None

            # Normalize column names to lowercase
            df_rt.columns = [c.lower() for c in df_rt.columns]

            # Filter to L1 industry indices only (801010~801880)
            df_rt = df_rt[df_rt["ts_code"].str.match(r"^801\d{3}\.SI$")]
            composite_codes = {"801001.SI", "801002.SI", "801003.SI", "801005.SI"}
            df_rt = df_rt[~df_rt["ts_code"].isin(composite_codes)]

            if df_rt.empty:
                logger.debug("[板块排行] rt_sw_k no L1 sectors after filter")
                return None

            df_rt["pct_change"] = pd.to_numeric(df_rt["pct_change"], errors="coerce")
            df_rt = df_rt.dropna(subset=["pct_change"])

            # Extract data_date from trade_time (e.g. "2026-04-22 14:30:00" -> "2026-04-22")
            trade_time_str = str(df_rt["trade_time"].iloc[0]) if "trade_time" in df_rt.columns else ""
            data_date = trade_time_str[:10] if len(trade_time_str) >= 10 else (
                datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            )

            name_col = "name" if "name" in df_rt.columns else df_rt.columns[1]
            top_df = df_rt.nlargest(n, "pct_change")
            bottom_df = df_rt.nsmallest(n, "pct_change")

            top_sectors = [
                {"name": str(row[name_col]), "change_pct": float(row["pct_change"]), "data_date": data_date}
                for _, row in top_df.iterrows()
            ]
            bottom_sectors = [
                {"name": str(row[name_col]), "change_pct": float(row["pct_change"]), "data_date": data_date}
                for _, row in bottom_df.iterrows()
            ]

            logger.info(
                "[板块排行] Tushare rt_sw_k realtime: 领涨/领跌各%d个板块, data_date=%s", n, data_date
            )
            return top_sectors, bottom_sectors
        except Exception as e:
            logger.debug("[板块排行] rt_sw_k failed, falling back to sw_daily: %s", e)
            return None

    def _get_sector_rankings_via_sw_daily(self, n: int) -> Optional[Tuple[List[Dict], List[Dict]]]:
        """Fallback: fetch sector rankings via sw_daily (daily data)."""
        try:
            self._check_rate_limit()
            china_now = datetime.now(ZoneInfo("Asia/Shanghai"))
            today_str = china_now.strftime("%Y%m%d")
            end_date = today_str
            start_date = (china_now - pd.Timedelta(days=10)).strftime("%Y%m%d")

            df_cal = self._api.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date)
            if df_cal is None or df_cal.empty:
                return None
            df_cal.columns = [c.lower() for c in df_cal.columns]
            open_dates = df_cal[df_cal["is_open"] == 1]["cal_date"].tolist()
            # Tushare trade_cal usually returns descending order (latest first), but let's sort to be safe
            open_dates = sorted(open_dates, reverse=True)
            if not open_dates:
                return None
            
            # Try recent trade dates (latest first, fallback to earlier if data not ready)
            latest_trade_date = open_dates[0]
            df_sw = None
            for attempt, try_date in enumerate(open_dates[:5]):
                self._check_rate_limit()
                df_sw = self._api.sw_daily(trade_date=try_date, fields="ts_code,name,pct_change")
                if df_sw is not None and not df_sw.empty:
                    latest_trade_date = try_date
                    if attempt > 0:
                        logger.info(
                            "[板块排行] Tushare sw_daily: using %s (latest %s not ready)",
                            try_date, open_dates[0],
                        )
                    break
            else:
                logger.warning("[板块排行] Tushare sw_daily empty for all recent 5 trade dates")
                return None

            df_sw.columns = [c.lower() for c in df_sw.columns]
            if "pct_change" not in df_sw.columns:
                return None
            df_sw["pct_change"] = pd.to_numeric(df_sw["pct_change"], errors="coerce")
            df_sw = df_sw.dropna(subset=["pct_change"])
            name_col = "name" if "name" in df_sw.columns else df_sw.columns[1]

            # Convert latest_trade_date (YYYYMMDD) to YYYY-MM-DD for freshness tracking
            data_date = f"{latest_trade_date[:4]}-{latest_trade_date[4:6]}-{latest_trade_date[6:8]}"

            top = df_sw.nlargest(n, "pct_change")
            bottom = df_sw.nsmallest(n, "pct_change")
            top_sectors = [
                {"name": str(row[name_col]), "change_pct": float(row["pct_change"]), "data_date": data_date}
                for _, row in top.iterrows()
            ]
            bottom_sectors = [
                {"name": str(row[name_col]), "change_pct": float(row["pct_change"]), "data_date": data_date}
                for _, row in bottom.iterrows()
            ]
            logger.info(f"[板块排行] Tushare sw_daily 成功: 领涨/领跌各{n}个板块, data_date={data_date}")
            return top_sectors, bottom_sectors
        except Exception as e:
            logger.warning(f"[板块排行] Tushare 获取失败: {e}")
            return None
