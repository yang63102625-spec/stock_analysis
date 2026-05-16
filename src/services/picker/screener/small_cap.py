# -*- coding: utf-8 -*-
"""Small-cap factor screener.

Dedicated full-market screening path that does not rely on the daily-spot
pipeline used by buy_pullback / breakout / bottom_reversal. Reads market
breadth directly from LocalStockDB (Tushare-backed parquet warehouse) and
selects the N smallest-market-cap eligible stocks at the given trade date.

Why it's separate from the daily-spot pipeline:
    The other strategies are single-day momentum/pullback patterns scored
    from akshare spot fields (中文列名). small_cap is a cross-sectional
    monthly-rebalanced factor whose universe definition (ST exclusion,
    new-listing exclusion, optional liquidity floor) and ranking signal
    (total_mv ascending) come from Tushare daily_basic. Forcing it through
    the daily-spot path would lose the universe filters and rank by the
    wrong column.

Reference research and parameter justification: see
docs/research/SMALL_CAP_FINAL_REPORT.md.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

import pandas as pd

from src.services.picker.constants import ScreenedStock

logger = logging.getLogger(__name__)

# Defaults tuned in docs/research/SMALL_CAP_FINAL_REPORT.md (top-50, 20d
# rebalance, 2M yuan liquidity floor). Picker emits the top-N daily; the
# *rebalance cadence* is the operator's responsibility (e.g. monthly cron).
SMALL_CAP_TOP_N_DEFAULT = 50
SMALL_CAP_MIN_AMOUNT_YUAN_DEFAULT = 2_000_000.0
SMALL_CAP_LIQUIDITY_LOOKBACK_DAYS = 5
SMALL_CAP_MIN_LIST_DAYS = 365  # exclude first-year new listings


class _SmallCapMixin:
    """Mixin: ``_screen_small_cap_historical`` + ``_screen_small_cap_live``."""

    def _screen_small_cap(
        self,
        trade_date_yyyymmdd: Optional[str] = None,
        top_n: int = SMALL_CAP_TOP_N_DEFAULT,
        min_amount_yuan: float = SMALL_CAP_MIN_AMOUNT_YUAN_DEFAULT,
    ) -> List[ScreenedStock]:
        """Return top-N smallest-market-cap eligible A-shares at trade_date.

        ``trade_date_yyyymmdd`` may be ``None`` (live mode → latest cached
        date). Returns empty list when LocalDB has no coverage; caller is
        expected to tolerate it the same way buy_pullback tolerates a
        missing spot snapshot.
        """
        try:
            from src.services.local_db import default_db
        except Exception as e:
            logger.warning("[SmallCap] LocalStockDB unavailable: %s", e)
            return []

        db = default_db()

        # Resolve target trade date.
        td = self._resolve_small_cap_trade_date(db, trade_date_yyyymmdd)
        if not td:
            logger.warning("[SmallCap] cannot resolve trade date; returning []")
            return []

        try:
            daily = db.get_market_daily(td)
            basic = db.get_market_daily_basic(td)
        except Exception as e:
            logger.warning("[SmallCap] LocalDB fetch failed for %s: %s", td, e)
            return []

        if daily is None or daily.empty or basic is None or basic.empty:
            logger.info("[SmallCap] no market data for %s", td)
            return []

        panel = daily.merge(basic[["ts_code", "total_mv"]], on="ts_code", how="inner")
        panel = panel.dropna(subset=["total_mv"])
        panel = panel[panel["total_mv"] > 0]
        if panel.empty:
            return []

        # Universe exclusions (ST / 退市 / *ST / new listings within 1y).
        exclude_ts, list_dates = self._small_cap_static_filters(db)
        if exclude_ts:
            panel = panel[~panel["ts_code"].isin(exclude_ts)]
        if list_dates:
            td_ts = pd.Timestamp(td)
            min_days = SMALL_CAP_MIN_LIST_DAYS

            def _old_enough(ts: str) -> bool:
                ld = list_dates.get(ts)
                if not ld:
                    return True
                try:
                    return (td_ts - pd.Timestamp(ld)).days >= min_days
                except Exception:
                    return True

            panel = panel[panel["ts_code"].apply(_old_enough)]

        if panel.empty:
            return []

        # Optional liquidity floor: avg daily amount over previous N sessions.
        if min_amount_yuan > 0:
            panel = self._small_cap_apply_liquidity_floor(
                db, panel, td, min_amount_yuan, SMALL_CAP_LIQUIDITY_LOOKBACK_DAYS,
            )
            if panel.empty:
                return []

        panel = panel.sort_values("total_mv").head(top_n)

        return [self._small_cap_to_screened_stock(row) for _, row in panel.iterrows()]

    @staticmethod
    def _resolve_small_cap_trade_date(db, trade_date_yyyymmdd: Optional[str]) -> Optional[str]:
        if trade_date_yyyymmdd:
            return trade_date_yyyymmdd
        try:
            cal = db.get_trade_cal("SSE")
            cal = cal[cal["is_open"] == 1].sort_values("cal_date")
            if cal.empty:
                return None
            return str(cal["cal_date"].iloc[-1])
        except Exception as e:
            logger.warning("[SmallCap] trade_cal lookup failed: %s", e)
            return None

    @staticmethod
    def _small_cap_static_filters(db):
        try:
            sb = db.get_stock_basic()
        except Exception:
            return set(), {}
        if sb is None or sb.empty:
            return set(), {}
        name_mask = sb["name"].str.contains(r"ST|退|\*", regex=True, na=False)
        exclude_ts = set(sb.loc[name_mask, "ts_code"].tolist())
        list_dates = dict(zip(sb["ts_code"], sb["list_date"].astype(str)))
        return exclude_ts, list_dates

    @staticmethod
    def _small_cap_apply_liquidity_floor(
        db, panel: pd.DataFrame, trade_date: str,
        min_amount_yuan: float, lookback_days: int,
    ) -> pd.DataFrame:
        try:
            cal = db.get_trade_cal("SSE")
            cal = cal[cal["is_open"] == 1].sort_values("cal_date")
            sessions = cal["cal_date"].astype(str).tolist()
            if trade_date in sessions:
                idx = sessions.index(trade_date)
            else:
                idx = len(sessions) - 1
            prior = sessions[max(0, idx - lookback_days):idx]
        except Exception:
            prior = []

        if not prior:
            return panel

        amount_sum: dict = {}
        amount_cnt: dict = {}
        for d in prior:
            try:
                df_d = db.get_market_daily(d)
            except Exception:
                continue
            if df_d is None or df_d.empty or "amount" not in df_d.columns:
                continue
            for ts, a in zip(df_d["ts_code"], df_d["amount"].astype(float) * 1000.0):
                amount_sum[ts] = amount_sum.get(ts, 0.0) + a
                amount_cnt[ts] = amount_cnt.get(ts, 0) + 1

        min_obs = max(2, lookback_days // 2)
        avg_amt = {
            ts: amount_sum[ts] / amount_cnt[ts]
            for ts in amount_sum if amount_cnt[ts] >= min_obs
        }
        if not avg_amt:
            return panel

        return panel[panel["ts_code"].apply(lambda c: avg_amt.get(c, 0.0) >= min_amount_yuan)]

    @staticmethod
    def _small_cap_to_screened_stock(row) -> ScreenedStock:
        ts_code = str(row.get("ts_code", ""))
        code = ts_code.split(".")[0] if "." in ts_code else ts_code
        close = float(row.get("close", 0) or 0)
        amount_thousand_yuan = float(row.get("amount", 0) or 0)
        total_mv_wan = float(row.get("total_mv", 0) or 0)
        # daily_basic.total_mv 单位: 万元; 转为亿元 (/1e4)
        market_cap_yi = total_mv_wan / 1e4
        # daily.amount 单位: 千元; 转为亿元 (/1e5)
        amount_yi = amount_thousand_yuan / 1e5
        pct_chg = float(row.get("pct_chg", 0) or 0)

        # Score: smaller cap = higher score (linear inverse within universe).
        # 50 yi → ~30, 200 yi → ~7.5; passes downstream rank consumers without
        # collapsing all picks to the same value.
        score = 1500.0 / max(market_cap_yi, 1.0) if market_cap_yi > 0 else 0.0

        return ScreenedStock(
            code=code,
            name="",
            price=close,
            change_pct=pct_chg,
            volume_ratio=0.0,
            turnover_rate=0.0,
            pe=0.0,
            pb=0.0,
            market_cap=market_cap_yi,
            amount=amount_yi,
            change_pct_60d=0.0,
            score=score,
            strategies=["small_cap"],
        )


def small_cap_top_n() -> int:
    """Env override for SMALL_CAP_TOP_N (default 50)."""
    try:
        return max(1, int(os.environ.get("SMALL_CAP_TOP_N", SMALL_CAP_TOP_N_DEFAULT)))
    except ValueError:
        return SMALL_CAP_TOP_N_DEFAULT


def small_cap_min_amount_yuan() -> float:
    """Env override for SMALL_CAP_MIN_AMOUNT_YUAN (default 2_000_000)."""
    try:
        return max(0.0, float(os.environ.get(
            "SMALL_CAP_MIN_AMOUNT_YUAN", SMALL_CAP_MIN_AMOUNT_YUAN_DEFAULT,
        )))
    except ValueError:
        return SMALL_CAP_MIN_AMOUNT_YUAN_DEFAULT
