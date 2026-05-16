"""Regime overlay on the best small_cap config.

Test whether macro regime filters can cut MDD without killing alpha.

Regime signals tested (each evaluated at rebalance date, decides whether
to hold the small_cap basket or go to cash for the next period):

  R1 SSE > MA20         (above 20d MA)
  R2 SSE > MA60         (above 60d MA — slower)
  R3 SSE > MA120        (very slow trend)
  R4 SSE 20d return > 0 (positive momentum)
  R5 SSE MA20 > MA60    (golden-cross style)
  R6 SSE drawdown from 60d high < 5%
  R7 NONE (baseline)

Base config: freq=5d, top-50, min_amount=2_000_000 (gold winner).
"""
from __future__ import annotations

import argparse
import sys, os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.services.local_db import default_db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from small_cap_deep_dive import (  # type: ignore
    _load_static_filters, _daily, _basic, select_small_cap, holding_return,
    market_bh_total, annualization_factor, build_rebal_windows,
    get_rebal_dates, prewarm, COST_PER_REPLACEMENT,
)


db = default_db()
SSE_CODE = "000001.SH"


def _sse_history(start: str, end: str) -> pd.DataFrame:
    """Get SSE daily history sorted by date."""
    df = db.get_index_daily(SSE_CODE, start, end)
    if df.empty:
        return df
    return df.sort_values("trade_date").reset_index(drop=True)


def _ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(window=n, min_periods=1).mean()


def make_regime_signal(sse: pd.DataFrame, name: str) -> Dict[str, bool]:
    """Return mapping trade_date -> True/False (in-market)."""
    sse = sse.copy()
    sse["ma20"] = _ma(sse["close"], 20)
    sse["ma60"] = _ma(sse["close"], 60)
    sse["ma120"] = _ma(sse["close"], 120)
    sse["max60"] = sse["close"].rolling(60, min_periods=1).max()
    sse["ret20"] = sse["close"].pct_change(20)
    if name == "R1_above_MA20":
        sig = sse["close"] > sse["ma20"]
    elif name == "R2_above_MA60":
        sig = sse["close"] > sse["ma60"]
    elif name == "R3_above_MA120":
        sig = sse["close"] > sse["ma120"]
    elif name == "R4_20d_ret_pos":
        sig = sse["ret20"] > 0
    elif name == "R5_MA20_above_MA60":
        sig = sse["ma20"] > sse["ma60"]
    elif name == "R6_drawdown_below_5pct":
        sig = (sse["max60"] - sse["close"]) / sse["max60"] < 0.05
    elif name == "R7_NONE":
        sig = pd.Series([True] * len(sse), index=sse.index)
    else:
        raise ValueError(name)
    return dict(zip(sse["trade_date"].astype(str), sig.fillna(False)))


def run_with_regime(rebal: List[str], windows: List[List[str]],
                     n_top: int, min_amt: int,
                     regime_map: Dict[str, bool]) -> Dict:
    nav_g, nav_n = [1.0], [1.0]
    rets, npicks, turns, in_mkt = [], [], [], []
    prev_set: set = set()
    for i in range(len(rebal) - 1):
        d_entry, d_exit = rebal[i], rebal[i + 1]
        on = regime_map.get(d_entry, False)
        in_mkt.append(1 if on else 0)
        if not on:
            # cash for this period — pay only the rotation-out cost
            # (sell prev holdings); next period entry may rebuy.
            if prev_set:
                # 100% sell — full turnover
                cost = COST_PER_REPLACEMENT
                nav_n.append(nav_n[-1] * (1 - cost))
            else:
                nav_n.append(nav_n[-1])
            nav_g.append(nav_g[-1])  # cash = no change gross
            rets.append(0.0)
            npicks.append(0)
            turns.append(1.0 if prev_set else 0.0)
            prev_set = set()
            continue
        picks = select_small_cap(d_entry, n_top, min_amt, 5, windows[i])
        if not picks:
            nav_g.append(nav_g[-1])
            nav_n.append(nav_n[-1])
            rets.append(0.0)
            npicks.append(0)
            turns.append(0.0)
            continue
        curr_set = set(picks)
        if not prev_set:
            turnover = 1.0
        else:
            n_repl = len(curr_set - prev_set) + len(prev_set - curr_set) / 2
            turnover = min(1.0, n_repl / max(1, len(curr_set)))
        cost = turnover * COST_PER_REPLACEMENT
        ret = holding_return(picks, d_entry, d_exit)
        nav_g.append(nav_g[-1] * (1 + ret))
        nav_n.append(nav_n[-1] * (1 + ret) * (1 - cost))
        rets.append(ret)
        npicks.append(len(picks))
        turns.append(turnover)
        prev_set = curr_set

    nav_arr = np.asarray(nav_n)
    peak = np.maximum.accumulate(nav_arr)
    dd = (peak - nav_arr) / peak
    mdd = float(dd.max() * 100)
    in_mkt_pct = float(np.mean(in_mkt) * 100) if in_mkt else 0
    arr = np.asarray(rets)
    sharpe = float(arr.mean() / arr.std() * np.sqrt(52)) if arr.std() > 0 else 0
    net_total = (nav_n[-1] - 1) * 100
    return {
        "net_total_pct": net_total,
        "mdd_pct": mdd,
        "sharpe": sharpe,
        "in_market_pct": in_mkt_pct,
        "wr_pct": float(np.mean([r > 0 for r in rets if r != 0]) * 100) if any(r != 0 for r in rets) else 0,
        "nav": nav_n,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20240109")
    ap.add_argument("--end", default="20260509")
    ap.add_argument("--freq", type=int, default=5)
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--min-amt", type=int, default=2_000_000)
    args = ap.parse_args()

    _load_static_filters()
    cal = db.get_trade_cal("SSE", "20230101", args.end)
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    all_dates = cal["cal_date"].astype(str).tolist()

    rebal = get_rebal_dates(args.start, args.end, args.freq)
    windows = build_rebal_windows(rebal, all_dates, 60)
    prewarm([rebal], [windows])

    sse = _sse_history("20230101", args.end)
    if sse.empty:
        print("SSE history empty!")
        return

    regimes = ["R7_NONE", "R1_above_MA20", "R2_above_MA60", "R3_above_MA120",
               "R4_20d_ret_pos", "R5_MA20_above_MA60", "R6_drawdown_below_5pct"]

    bh = market_bh_total(rebal[0], rebal[-1])
    print(f"\n=== BASELINE: Mkt EQW B&H: {bh:+.2f}% ===", flush=True)
    print(f"Config: freq={args.freq}d, top-{args.top_n}, min_amt={args.min_amt:,}", flush=True)
    print(f"\n{'Regime':>26s} | {'NET':>8s} {'MDD':>6s} {'Sharpe':>7s} {'InMkt%':>7s} {'WR':>5s} {'Alpha':>8s}", flush=True)
    print("-" * 80, flush=True)
    for name in regimes:
        sig_map = make_regime_signal(sse, name)
        r = run_with_regime(rebal, windows, args.top_n, args.min_amt, sig_map)
        print(f"{name:>26s} | {r['net_total_pct']:+7.1f}% {r['mdd_pct']:>5.1f}% "
              f"{r['sharpe']:>6.2f} {r['in_market_pct']:>6.1f}% {r['wr_pct']:>4.1f}% "
              f"{r['net_total_pct'] - bh:+7.1f}%", flush=True)


if __name__ == "__main__":
    main()
