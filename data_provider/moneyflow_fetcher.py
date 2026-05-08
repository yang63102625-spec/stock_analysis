# -*- coding: utf-8 -*-
"""Capital flow data fetcher using Tushare API."""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)


class MoneyflowFetcher:
    """Fetch north-bound capital and individual stock money flow data from Tushare."""

    def __init__(self, pro_api):
        """Initialize with Tushare pro API instance."""
        self._pro = pro_api

    def get_north_flow(self, days: int = 5) -> Optional[pd.DataFrame]:
        """
        Get north-bound capital flow (HSGT) for recent N days.

        Uses Tushare moneyflow_hsgt interface.
        Returns DataFrame with columns: trade_date, hgt, sgt, north_money, south_money
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")

            df = self._pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                logger.warning("No north-bound flow data returned from Tushare")
                return None

            # Sort by date ascending and take last N trading days
            df = df.sort_values('trade_date', ascending=True).tail(days).reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch north-bound flow: {e}")
            return None

    def get_stock_moneyflow(self, ts_code: str, days: int = 5) -> Optional[pd.DataFrame]:
        """
        Get individual stock money flow (large/small orders) for recent N days.

        Uses Tushare moneyflow interface.
        Returns DataFrame with buy/sell amounts by order size.
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")

            df = self._pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                logger.warning(f"No moneyflow data for {ts_code}")
                return None

            # Sort by date ascending and take last N trading days
            df = df.sort_values('trade_date', ascending=True).tail(days).reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch moneyflow for {ts_code}: {e}")
            return None

    def analyze_capital_flow(self, ts_code: str, days: int = 5) -> Dict[str, Any]:
        """
        Analyze capital flow for scoring integration.

        Returns:
            dict with keys:
                - main_force_score (int): 0-6, based on large+xlarge order net inflow trend
                - north_score (int): 0-4, based on north-bound capital trend
                - total_capital_score (int): 0-10, sum of above
                - main_force_signal (str): description of main force activity
                - north_signal (str): description of north-bound capital activity
        """
        result = {
            "main_force_score": 0,
            "north_score": 0,
            "total_capital_score": 0,
            "main_force_signal": "",
            "north_signal": "",
        }

        # --- Main force analysis (large + extra-large orders) ---
        # Minimum flow threshold: daily net inflow must >= 1M (100万) to count
        MIN_FLOW_THRESHOLD = 1_000_000  # 100万元
        stock_flow = self.get_stock_moneyflow(ts_code, days=days)
        if stock_flow is not None and not stock_flow.empty:
            # Calculate daily net inflow for large + extra-large orders (unit: 10k CNY)
            stock_flow['main_net'] = (
                stock_flow['buy_lg_amount'] + stock_flow['buy_elg_amount']
                - stock_flow['sell_lg_amount'] - stock_flow['sell_elg_amount']
            )

            net_values = stock_flow['main_net'].tolist()
            # Only count days where abs(net) >= threshold as significant inflow
            significant_inflow_days = sum(1 for v in net_values[-3:] if v >= MIN_FLOW_THRESHOLD)
            total_net = sum(net_values)
            latest_net = net_values[-1] if net_values else 0

            if significant_inflow_days >= 3:
                # 3+ consecutive days net inflow with positive cumulative
                result["main_force_score"] = 6
                result["main_force_signal"] = (
                    f"主力连续{significant_inflow_days}日显著净流入(>{MIN_FLOW_THRESHOLD/1e4:.0f}万)，累计{total_net:.0f}万"
                )
            elif significant_inflow_days >= 2:
                # 2 consecutive days inflow
                result["main_force_score"] = 3
                result["main_force_signal"] = f"主力连续2日显著净流入，今日{latest_net:.0f}万"
            elif latest_net > 0:
                # Only today inflow
                result["main_force_score"] = 1
                result["main_force_signal"] = f"主力今日净流入{latest_net:.0f}万，但趋势不稳"
            else:
                result["main_force_score"] = 0
                result["main_force_signal"] = f"主力净流出，今日{latest_net:.0f}万"
        else:
            result["main_force_signal"] = "资金流向数据暂不可用"

        # --- North-bound capital analysis ---
        north_flow = self.get_north_flow(days=days)
        if north_flow is not None and not north_flow.empty:
            north_values = north_flow['north_money'].tolist()  # Unit: million CNY
            consecutive_inflow = sum(1 for v in north_values[-3:] if v > 0)
            total_north = sum(north_values)
            latest_north = north_values[-1] if north_values else 0

            if consecutive_inflow >= 3:
                result["north_score"] = 4
                result["north_signal"] = (
                    f"北向连续{consecutive_inflow}日净流入，累计{total_north:.0f}百万"
                )
            elif consecutive_inflow >= 2:
                result["north_score"] = 2
                result["north_signal"] = f"北向连续2日净流入，今日{latest_north:.0f}百万"
            elif latest_north > 0:
                # Only today inflow
                result["north_score"] = 1
                result["north_signal"] = f"北向今日净流入{latest_north:.0f}百万，趋势待确认"
            else:
                result["north_score"] = 0
                result["north_signal"] = f"北向资金净流出，今日{latest_north:.0f}百万"
        else:
            result["north_signal"] = "北向资金数据暂不可用"

        result["total_capital_score"] = result["main_force_score"] + result["north_score"]

        # Anomaly detection: large single-day outflow warning
        if stock_flow is not None and not stock_flow.empty:
            net_values_check = stock_flow['main_net'].tolist()
            if net_values_check and min(net_values_check[-3:]) < -5_000_000:  # Single day outflow > 500万
                result["main_force_score"] = max(0, result["main_force_score"] - 3)
                result["main_force_signal"] = "⚠️ 近期存在单日大幅主力流出(>500万)，需警惕"
                result["total_capital_score"] = result["main_force_score"] + result["north_score"]

        return result
