# -*- coding: utf-8 -*-
"""Small-cap factor screener.

Returns the top-N smallest-market-cap eligible A-shares.

Two execution paths, mirroring the rest of the picker:

* **Live mode** (no ``as_of_date``) — uses ``_fetch_spot_data`` to pull the
  current full-market quote (Tushare daily → akshare spot → efinance
  fallback chain that all other strategies rely on). This guarantees the
  picker reflects today's tradable universe.
* **Historical / backtest mode** (``as_of_date`` set) — reads market
  breadth from LocalStockDB by-date parquet shards (Tushare-backed).

Universe filters (ST / 退市 / *ST / new listings within 365 days) and the
optional liquidity floor are applied identically in both modes.

Reference research and parameter justification: see
docs/research/SMALL_CAP_FINAL_REPORT.md.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

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
    """Mixin: ``_screen_small_cap``."""

    def _screen_small_cap(
        self,
        trade_date_yyyymmdd: Optional[str] = None,
        top_n: int = SMALL_CAP_TOP_N_DEFAULT,
        min_amount_yuan: float = SMALL_CAP_MIN_AMOUNT_YUAN_DEFAULT,
    ) -> List[ScreenedStock]:
        """Return top-N smallest-market-cap eligible A-shares.

        - ``trade_date_yyyymmdd`` set (backtest) → read from LocalStockDB.
        - ``trade_date_yyyymmdd`` is None (live) → use _fetch_spot_data,
          the same realtime path the other strategies take.
        """
        is_historical = bool(trade_date_yyyymmdd)

        if is_historical:
            picks = self._select_small_cap_from_localdb(
                trade_date_yyyymmdd, top_n, min_amount_yuan,
            )
        else:
            picks = self._select_small_cap_live(top_n, min_amount_yuan)

        if not picks:
            logger.info(
                "[SmallCap] no candidates (mode=%s, top_n=%d, min_amount=%g)",
                "historical" if is_historical else "live", top_n, min_amount_yuan,
            )
        return picks

    # ------------------------------------------------------------------
    # Live path — share the realtime spot fetch with other strategies.
    # ------------------------------------------------------------------

    def _select_small_cap_live(
        self, top_n: int, min_amount_yuan: float,
    ) -> List[ScreenedStock]:
        df = self._fetch_spot_data(trade_date=None)
        if df is None or df.empty:
            logger.warning("[SmallCap] live spot fetch returned nothing")
            return []

        # Spot DataFrame uses akshare-convention Chinese column names with
        # 总市值 in yuan (see data_fetch._try_tushare normalisation block).
        mc_col = "总市值" if "总市值" in df.columns else None
        if mc_col is None:
            logger.warning("[SmallCap] spot data missing 总市值 column; cannot rank")
            return []

        panel = df.copy()
        panel["_mv_yuan"] = pd.to_numeric(panel[mc_col], errors="coerce")
        panel = panel.dropna(subset=["_mv_yuan"])
        panel = panel[panel["_mv_yuan"] > 0]

        # Exclusions: ST in name, KC/CY/BSE (60-300 yi is the sweet spot for
        # the factor and these boards have different tick rules / risk).
        if "名称" in panel.columns:
            panel = panel[~panel["名称"].astype(str).str.contains("ST|退|\\*", regex=True, na=False)]
        if "代码" in panel.columns:
            code_str = panel["代码"].astype(str)
            # Drop BSE (8/4 legacy + 92 new code range 920xxx-924xxx) — their
            # liquidity profile and trading rules diverge from the main
            # sample the small_cap factor was validated on.
            panel = panel[~code_str.str.startswith(("8", "4", "92"))]

        if panel.empty:
            return []

        # Optional liquidity floor (today's 成交额, since live mode doesn't
        # have a cheap 5-day average without extra calls).
        if min_amount_yuan > 0 and "成交额" in panel.columns:
            amt = pd.to_numeric(panel["成交额"], errors="coerce").fillna(0)
            panel = panel[amt >= min_amount_yuan]
            if panel.empty:
                return []

        panel = panel.sort_values("_mv_yuan").head(top_n)

        return [self._spot_row_to_screened_stock(row) for _, row in panel.iterrows()]

    @staticmethod
    def _spot_row_to_screened_stock(row) -> ScreenedStock:
        code = str(row.get("代码", "") or "")
        name = str(row.get("名称", "") or "")
        price = float(pd.to_numeric(row.get("最新价", 0), errors="coerce") or 0)
        change_pct = float(pd.to_numeric(row.get("涨跌幅", 0), errors="coerce") or 0)
        vol_ratio = float(pd.to_numeric(row.get("量比", 0), errors="coerce") or 0)
        turnover = float(pd.to_numeric(row.get("换手率", 0), errors="coerce") or 0)
        pe = float(pd.to_numeric(row.get("市盈率-动态", 0), errors="coerce") or 0)
        pb = float(pd.to_numeric(row.get("市净率", 0), errors="coerce") or 0)
        mv_yuan = float(pd.to_numeric(row.get("总市值", 0), errors="coerce") or 0)
        amount_yuan = float(pd.to_numeric(row.get("成交额", 0), errors="coerce") or 0)
        industry = str(row.get("industry") or row.get("行业") or "")

        market_cap_yi = mv_yuan / 1e8
        amount_yi = amount_yuan / 1e8
        # Smaller cap → higher score (same as historical path).
        score = 1500.0 / max(market_cap_yi, 1.0) if market_cap_yi > 0 else 0.0

        return ScreenedStock(
            code=code,
            name=name,
            price=price,
            change_pct=change_pct,
            volume_ratio=vol_ratio,
            turnover_rate=turnover,
            pe=pe,
            pb=pb,
            market_cap=market_cap_yi,
            amount=amount_yi,
            change_pct_60d=float(pd.to_numeric(row.get("60日涨跌幅", 0), errors="coerce") or 0),
            score=score,
            strategies=["small_cap"],
            industry=industry,
        )

    # ------------------------------------------------------------------
    # Historical path — LocalDB only. Used by backtest harness.
    # ------------------------------------------------------------------

    def _select_small_cap_from_localdb(
        self, trade_date_yyyymmdd: str, top_n: int, min_amount_yuan: float,
    ) -> List[ScreenedStock]:
        try:
            from src.services.local_db import default_db
        except Exception as e:
            logger.warning("[SmallCap] LocalStockDB unavailable: %s", e)
            return []

        db = default_db()
        td = trade_date_yyyymmdd

        try:
            daily = db.get_market_daily(td)
            basic = db.get_market_daily_basic(td)
        except Exception as e:
            logger.warning("[SmallCap] LocalDB fetch failed for %s: %s", td, e)
            return []

        if daily is None or daily.empty or basic is None or basic.empty:
            logger.info("[SmallCap] no LocalDB market data for %s", td)
            return []

        panel = daily.merge(basic[["ts_code", "total_mv"]], on="ts_code", how="inner")
        panel = panel.dropna(subset=["total_mv"])
        panel = panel[panel["total_mv"] > 0]
        if panel.empty:
            return []

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

        if min_amount_yuan > 0:
            panel = self._small_cap_apply_liquidity_floor(
                db, panel, td, min_amount_yuan, SMALL_CAP_LIQUIDITY_LOOKBACK_DAYS,
            )
            if panel.empty:
                return []

        panel = panel.sort_values("total_mv").head(top_n)
        return [self._localdb_row_to_screened_stock(row) for _, row in panel.iterrows()]

    @staticmethod
    def _small_cap_static_filters(db) -> Tuple[set, dict]:
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
    def _localdb_row_to_screened_stock(row) -> ScreenedStock:
        ts_code = str(row.get("ts_code", ""))
        code = ts_code.split(".")[0] if "." in ts_code else ts_code
        close = float(row.get("close", 0) or 0)
        amount_thousand_yuan = float(row.get("amount", 0) or 0)
        total_mv_wan = float(row.get("total_mv", 0) or 0)
        market_cap_yi = total_mv_wan / 1e4
        amount_yi = amount_thousand_yuan / 1e5
        pct_chg = float(row.get("pct_chg", 0) or 0)
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
