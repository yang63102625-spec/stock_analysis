"""Sector rotation + intra-sector leader scan (one-off research script).

Strategy idea:
  1. Pick strong sectors: sector 20d return rank in top K%, sector MA20 rising.
  2. Within each strong sector, pick stocks that outperform their sector
     on 60d return, are above MA20, and have sufficient liquidity.

Score = relative strength vs sector + volume confirmation + trend angle.

Usage:
  python scripts/scan_sector_leader.py --as-of 20260515 --top-sectors 20 --top-per-sector 3
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import setup_env  # noqa: E402
setup_env()

from src.services.local_db import default_db  # noqa: E402

import os as _os
logging.basicConfig(
    level=logging.DEBUG if _os.environ.get("SCAN_DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SECTOR_LOOKBACK_DAYS = 20      # window for sector momentum ranking
STOCK_LOOKBACK_DAYS = 60       # window for individual stock relative strength
TOP_SECTOR_PCT = 0.20          # keep top 20% strongest sectors
MIN_STOCKS_PER_SECTOR = 5      # ignore tiny sectors (noise)
MIN_AMOUNT_YI = 1.0            # min daily turnover (亿) to ensure liquidity
MIN_MARKET_CAP_YI = 30.0       # avoid micro caps (manipulation risk)


def _load_universe(db) -> pd.DataFrame:
    """Return stock_basic with mainboard flag and industry."""
    sb = db.get_stock_basic()
    sb = sb[sb["industry"].notna() & (sb["industry"] != "")].copy()
    return sb[["ts_code", "name", "industry"]]


def _trading_days_before(db, as_of: str, n: int) -> str:
    """Return the YYYYMMDD that is `n` trading days before `as_of` (inclusive end)."""
    cal = db.get_trade_cal()
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    open_days = cal["cal_date"].tolist()
    if as_of not in open_days:
        # snap to the most recent open day
        prior = [d for d in open_days if d <= as_of]
        if not prior:
            raise ValueError(f"no trading day <= {as_of}")
        as_of = prior[-1]
    idx = open_days.index(as_of)
    start_idx = max(0, idx - n + 1)
    return open_days[start_idx]


def _load_daily_window(db, ts_codes: List[str], start: str, end: str) -> pd.DataFrame:
    """Vectorized load: stack daily for many codes in window. Returns long-form DF."""
    frames = []
    for ts in ts_codes:
        df = db.get_daily(ts, start_date=start, end_date=end)
        if df is None or df.empty:
            continue
        df = df[["trade_date", "close", "open", "high", "low", "vol", "amount"]].copy()
        df["ts_code"] = ts
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["trade_date"] = out["trade_date"].astype(str)
    return out


def _compute_returns(daily: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Per-stock return from start->end. Returns DF[ts_code, ret_pct, last_close, last_amount]."""
    if daily.empty:
        return pd.DataFrame(columns=["ts_code", "ret_pct", "last_close", "last_amount"])
    g = daily.sort_values(["ts_code", "trade_date"]).groupby("ts_code")
    rows = []
    for ts, sub in g:
        if len(sub) < 2:
            continue
        first = sub.iloc[0]
        last = sub.iloc[-1]
        if first["close"] <= 0:
            continue
        rows.append({
            "ts_code": ts,
            "ret_pct": (last["close"] / first["close"] - 1.0) * 100.0,
            "last_close": float(last["close"]),
            "last_amount": float(last["amount"]),
            "last_date": last["trade_date"],
        })
    return pd.DataFrame(rows)


def _compute_ma_slope(daily: pd.DataFrame, ts: str, end: str, window: int = 20) -> float:
    """Annualized linear slope of last `window` closes (pct/year). NaN if insufficient.

    Formula: slope_per_day = polyfit(x, close, 1) in price/day units.
    Annualized return ≈ slope_per_day * 250 / mean_close * 100 (pct).
    Avoids the exp(log_slope*250) blow-up of geometric annualization on noisy data.
    """
    sub = daily[(daily["ts_code"] == ts) & (daily["trade_date"] <= end)].sort_values("trade_date")
    if len(sub) < window:
        return float("nan")
    closes = sub["close"].tail(window).to_numpy()
    if (closes <= 0).any():
        return float("nan")
    x = np.arange(len(closes), dtype=float)
    slope, _ = np.polyfit(x, closes, 1)  # price units per day
    mean_close = float(np.mean(closes))
    if mean_close <= 0:
        return float("nan")
    return float(slope * 250 / mean_close * 100.0)


def _rank_sectors(
    universe: pd.DataFrame, daily: pd.DataFrame, end: str,
) -> pd.DataFrame:
    """Returns sector rank DF with ret_pct, n_stocks, ma20_slope_pct_per_y."""
    rets = _compute_returns(daily, daily["trade_date"].min(), end)
    if rets.empty:
        return pd.DataFrame()
    merged = rets.merge(universe[["ts_code", "industry"]], on="ts_code", how="inner")
    # Sector return = median of constituents (robust to extremes)
    sec = merged.groupby("industry").agg(
        ret_pct=("ret_pct", "median"),
        n_stocks=("ts_code", "count"),
    ).reset_index()
    sec = sec[sec["n_stocks"] >= MIN_STOCKS_PER_SECTOR]

    # Sector MA20 slope: take cap-weighted-ish median of slopes of large constituents
    sec_slope = []
    for ind, sub in merged.groupby("industry"):
        top_codes = sub.nlargest(min(10, len(sub)), "last_amount")["ts_code"].tolist()
        slopes = [
            _compute_ma_slope(daily, ts, end, window=SECTOR_LOOKBACK_DAYS)
            for ts in top_codes
        ]
        slopes = [s for s in slopes if not np.isnan(s)]
        sec_slope.append({
            "industry": ind,
            "ma20_slope_pct_per_y": float(np.median(slopes)) if slopes else float("nan"),
        })
    sec = sec.merge(pd.DataFrame(sec_slope), on="industry", how="left")
    sec = sec.sort_values("ret_pct", ascending=False).reset_index(drop=True)
    sec["rank_pct"] = (sec.index + 1) / len(sec)
    return sec


def _score_leaders_in_sector(
    universe_sub: pd.DataFrame, daily: pd.DataFrame, sector_ret: float, end: str,
    daily_basic_last: pd.DataFrame,
) -> pd.DataFrame:
    """Score each stock in a sector. Returns DF with score, return_60d, etc."""
    ts_codes = universe_sub["ts_code"].tolist()
    rets = _compute_returns(daily, daily["trade_date"].min(), end)
    if rets.empty:
        return pd.DataFrame()
    rets = rets[rets["ts_code"].isin(ts_codes)]
    rets = rets.merge(universe_sub[["ts_code", "name", "industry"]], on="ts_code")

    # Liquidity + valuation gate from daily_basic (only pull non-colliding cols)
    if not daily_basic_last.empty:
        db_cols = ["ts_code", "pe_ttm", "total_mv", "circ_mv"]
        avail = [c for c in db_cols if c in daily_basic_last.columns]
        # daily_basic may have its own `close` etc. -- keep only what we need
        rets = rets.merge(daily_basic_last[avail], on="ts_code", how="left")

    n0 = len(rets)

    # Filter: liquidity, market cap, valid PE
    # Tushare daily.amount unit = 千元; ÷1e5 -> 亿元
    rets["last_amount_yi"] = rets["last_amount"] / 1e5
    rets = rets[rets["last_amount_yi"] >= MIN_AMOUNT_YI]
    n_after_liq = len(rets)
    if "total_mv" in rets.columns:
        rets["total_mv_yi"] = rets["total_mv"] / 1e4  # tushare total_mv 单位是万元
        rets = rets[rets["total_mv_yi"] >= MIN_MARKET_CAP_YI]
    n_after_cap = len(rets)
    if "pe_ttm" in rets.columns:
        rets = rets[(rets["pe_ttm"] > 0) & (rets["pe_ttm"] < 200)]
    n_after_pe = len(rets)

    if rets.empty:
        logger.debug("  pipeline drop %d->%d (liq)->%d (cap)->%d (pe)->0",
                     n0, n_after_liq, n_after_cap, n_after_pe)
        return pd.DataFrame()

    # Relative strength vs sector
    rets["excess_vs_sector"] = rets["ret_pct"] - sector_ret

    # Trend angle (MA20 slope)
    rets["ma20_slope"] = rets["ts_code"].apply(
        lambda ts: _compute_ma_slope(daily, ts, end, window=20)
    )
    n_before_trend = len(rets)
    rets = rets[rets["ma20_slope"].notna() & (rets["ma20_slope"] > 0)]
    n_after_trend = len(rets)
    if rets.empty:
        logger.debug("  pipeline drop %d->%d (liq)->%d (cap)->%d (pe)->%d (trend slope)->0",
                     n0, n_after_liq, n_after_cap, n_after_pe, n_before_trend)
        return pd.DataFrame()

    # Score: excess return (0-40) + trend angle (0-30) + liquidity (0-20) + cap sweet-spot (0-10)
    rets["score_excess"] = rets["excess_vs_sector"].clip(0, 40)
    rets["score_trend"] = rets["ma20_slope"].clip(0, 150) / 5.0  # 150%/y -> 30
    rets["score_liq"] = np.minimum(rets["last_amount_yi"] / 2.0, 20.0)  # 40亿 -> 20
    if "total_mv_yi" in rets.columns:
        rets["score_cap"] = rets["total_mv_yi"].apply(
            lambda c: 10.0 if 50 <= c <= 800 else (5.0 if c < 50 else 3.0)
        )
    else:
        rets["score_cap"] = 5.0

    rets["score"] = rets["score_excess"] + rets["score_trend"] + rets["score_liq"] + rets["score_cap"]
    return rets.sort_values("score", ascending=False)


def scan(as_of: str, top_sectors_pct: float, top_per_sector: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Main scan entry. Returns (sector_rank_df, leader_picks_df)."""
    db = default_db()
    universe = _load_universe(db)
    logger.info("Universe: %d stocks across %d industries",
                len(universe), universe["industry"].nunique())

    start_60d = _trading_days_before(db, as_of, STOCK_LOOKBACK_DAYS)
    logger.info("Loading daily window %s..%s for %d stocks (may take ~30s)",
                start_60d, as_of, len(universe))
    daily = _load_daily_window(db, universe["ts_code"].tolist(), start_60d, as_of)
    if daily.empty:
        logger.error("No daily data loaded")
        return pd.DataFrame(), pd.DataFrame()
    logger.info("Loaded %d daily bars", len(daily))

    # Sector ranking uses 20d window
    start_20d = _trading_days_before(db, as_of, SECTOR_LOOKBACK_DAYS)
    daily_20d = daily[daily["trade_date"] >= start_20d]
    sec_rank = _rank_sectors(universe, daily_20d, as_of)
    if sec_rank.empty:
        logger.error("Sector ranking failed")
        return pd.DataFrame(), pd.DataFrame()

    # Pick strong sectors: top K% by ret AND positive MA20 slope
    sec_rank["strong"] = (
        (sec_rank["rank_pct"] <= top_sectors_pct)
        & (sec_rank["ma20_slope_pct_per_y"] > 0)
    )
    strong_sectors = sec_rank[sec_rank["strong"]].copy()
    logger.info("Strong sectors: %d / %d (top %d%% by 20d return + positive MA20 slope)",
                len(strong_sectors), len(sec_rank), int(top_sectors_pct * 100))

    # daily_basic for liquidity/valuation
    try:
        daily_basic = db.get_market_daily_basic(as_of)
    except Exception as e:
        logger.warning("daily_basic %s failed: %s", as_of, e)
        daily_basic = pd.DataFrame()

    all_picks = []
    for _, sec_row in strong_sectors.iterrows():
        ind = sec_row["industry"]
        sub_universe = universe[universe["industry"] == ind]
        leaders = _score_leaders_in_sector(
            sub_universe, daily, sec_row["ret_pct"], as_of, daily_basic,
        )
        if leaders.empty:
            continue
        picks = leaders.head(top_per_sector).copy()
        picks["sector_ret_20d"] = sec_row["ret_pct"]
        picks["sector_rank_pct"] = sec_row["rank_pct"]
        all_picks.append(picks)

    picks_df = pd.concat(all_picks, ignore_index=True) if all_picks else pd.DataFrame()
    if not picks_df.empty:
        picks_df = picks_df.sort_values("score", ascending=False).reset_index(drop=True)
    return sec_rank, picks_df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="20260515", help="YYYYMMDD")
    ap.add_argument("--top-sectors-pct", type=float, default=TOP_SECTOR_PCT)
    ap.add_argument("--top-per-sector", type=int, default=3)
    args = ap.parse_args()

    sec_rank, picks = scan(args.as_of, args.top_sectors_pct, args.top_per_sector)
    if sec_rank.empty:
        return 1

    print("\n=== Top 15 Sectors (by 20d median return) ===")
    cols = ["industry", "ret_pct", "n_stocks", "ma20_slope_pct_per_y", "strong"]
    print(sec_rank[cols].head(15).to_string(index=False, float_format="%.2f"))

    if picks.empty:
        print("\nNo leader picks (no stock passed the in-sector filters).")
        return 0

    print(f"\n=== Top 30 Leader Picks (as of {args.as_of}) ===")
    show_cols = [
        "ts_code", "name", "industry", "ret_pct", "excess_vs_sector",
        "ma20_slope", "last_amount_yi", "score",
    ]
    show_cols = [c for c in show_cols if c in picks.columns]
    print(picks[show_cols].head(30).to_string(index=False, float_format="%.2f"))

    print(f"\nTotal picks: {len(picks)} across {picks['industry'].nunique()} sectors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
