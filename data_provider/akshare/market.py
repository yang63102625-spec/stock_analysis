# -*- coding: utf-8 -*-
"""Market-wide views: indices, market stats, sector rankings."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from ..base import is_bse_code, is_kc_cy_stock, is_st_stock, normalize_stock_code
from ..realtime_types import safe_float
from ..us_index_mapping import is_us_index_code

logger = logging.getLogger(__name__)


class _MarketMixin:
    """Mixin: ``get_main_indices``, ``get_market_stats``, ``get_sector_rankings``."""

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """
        获取主要指数实时行情 (新浪接口)，仅支持 A 股
        """
        if region != "cn":
            return None
        import akshare as ak

        # 主要指数代码映射
        indices_map = {
            'sh000001': '上证指数',
            'sz399001': '深证成指',
            'sz399006': '创业板指',
            'sh000688': '科创50',
            'sh000016': '上证50',
            'sh000300': '沪深300',
        }

        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            # 使用 akshare 获取指数行情（新浪财经接口）
            df = ak.stock_zh_index_spot_sina()

            results = []
            if df is not None and not df.empty:
                for code, name in indices_map.items():
                    # 查找对应指数
                    row = df[df['代码'] == code]
                    if row.empty:
                        # 尝试带前缀查找
                        row = df[df['代码'].str.contains(code)]

                    if not row.empty:
                        row = row.iloc[0]
                        current = safe_float(row.get('最新价', 0))
                        prev_close = safe_float(row.get('昨收', 0))
                        high = safe_float(row.get('最高', 0))
                        low = safe_float(row.get('最低', 0))

                        # 计算振幅
                        amplitude = 0.0
                        if prev_close > 0:
                            amplitude = (high - low) / prev_close * 100

                        results.append({
                            'code': code,
                            'name': name,
                            'current': current,
                            'change': safe_float(row.get('涨跌额', 0)),
                            'change_pct': safe_float(row.get('涨跌幅', 0)),
                            'open': safe_float(row.get('今开', 0)),
                            'high': high,
                            'low': low,
                            'prev_close': prev_close,
                            'volume': safe_float(row.get('成交量', 0)),
                            'amount': safe_float(row.get('成交额', 0)),
                            'amplitude': amplitude,
                        })
            return results

        except Exception as e:
            logger.error(f"[Akshare] 获取指数行情失败: {e}")
            return None

    def get_market_stats(self) -> Optional[Dict[str, Any]]:
        """
        获取市场涨跌统计

        数据源优先级：
        1. 东财接口 (ak.stock_zh_a_spot_em)
        2. 新浪接口 (ak.stock_zh_a_spot)
        """
        import akshare as ak

        # Priority 1: Eastmoney
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_zh_a_spot_em() 获取市场统计...")
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                stats = self._calc_market_stats(df)
                if stats is not None:
                    # Realtime data -> today's date
                    from zoneinfo import ZoneInfo
                    stats["data_date"] = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
                return stats
        except Exception as e:
            logger.warning(f"[Akshare] 东财接口获取市场统计失败: {e}，尝试新浪接口")

        # 东财失败后，尝试新浪接口 (with 10s wall-clock cap to avoid
        # cascading timeouts when called inside _gather_market_intel)
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_zh_a_spot() 获取市场统计(新浪)...")

            def _sina_fetch():
                return ak.stock_zh_a_spot()

            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="sina_stats") as pool:
                fut = pool.submit(_sina_fetch)
                df = fut.result(timeout=10)

            if df is not None and not df.empty:
                stats = self._calc_market_stats(df)
                if stats is not None:
                    from zoneinfo import ZoneInfo
                    stats["data_date"] = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
                return stats
        except _FutTimeout:
            logger.warning("[Akshare] 新浪接口获取市场统计超时(10s)")
        except Exception as e:
            logger.error(f"[Akshare] 新浪接口获取市场统计也失败: {e}")

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
        获取板块涨跌榜

        数据源优先级：
        1. 东财接口 (ak.stock_board_industry_name_em)
        2. 新浪接口 (ak.stock_sector_spot)
        """
        import akshare as ak

        # 优先东财接口
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_board_industry_name_em() 获取板块排行...")
            df = ak.stock_board_industry_name_em()
            if df is not None and not df.empty:
                change_col = '涨跌幅'
                if change_col in df.columns:
                    df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
                    df = df.dropna(subset=[change_col])

                    # 涨幅前n
                    top = df.nlargest(n, change_col)
                    top_sectors = [
                        {'name': row['板块名称'], 'change_pct': row[change_col]}
                        for _, row in top.iterrows()
                    ]

                    bottom = df.nsmallest(n, change_col)
                    bottom_sectors = [
                        {'name': row['板块名称'], 'change_pct': row[change_col]}
                        for _, row in bottom.iterrows()
                    ]

                    return top_sectors, bottom_sectors
        except Exception as e:
            logger.warning(f"[Akshare] 东财接口获取板块排行失败: {e}，尝试新浪接口")

        # 东财失败后，尝试新浪接口
        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API调用] ak.stock_sector_spot() 获取板块排行(新浪)...")
            df = ak.stock_sector_spot(indicator='新浪行业')
            if df is None or df.empty:
                return None

            change_col = None
            for col in ['涨跌幅', 'change_pct', '涨幅']:
                if col in df.columns:
                    change_col = col
                    break

            name_col = None
            for col in ['板块', '板块名称', 'label', 'name']:
                if col in df.columns:
                    name_col = col
                    break

            if not change_col or not name_col:
                return None

            df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
            df = df.dropna(subset=[change_col])
            top = df.nlargest(n, change_col)
            bottom = df.nsmallest(n, change_col)
            top_sectors = [
                {'name': str(row[name_col]), 'change_pct': float(row[change_col])}
                for _, row in top.iterrows()
            ]
            bottom_sectors = [
                {'name': str(row[name_col]), 'change_pct': float(row[change_col])}
                for _, row in bottom.iterrows()
            ]
            return top_sectors, bottom_sectors
        except Exception as e:
            logger.error(f"[Akshare] 新浪接口获取板块排行也失败: {e}")
            return None

