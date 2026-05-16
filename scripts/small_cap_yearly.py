"""Year-by-year decomposition for the gold + silver small_cap configs.

Runs each calendar year independently with NAV starting at 1.0,
showing both gold (freq=20, top-50, min_amt=2M) and Sharpe-best
(freq=5, top-200) configurations.
"""
from __future__ import annotations

import sys, os
import time
import numpy as np
import pandas as pd

from src.services.local_db import default_db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from small_cap_deep_dive import (  # type: ignore
    _load_static_filters, _daily, _basic, run_backtest, market_bh_total,
    annualization_factor, build_rebal_windows, get_rebal_dates, prewarm,
)


db = default_db()


def main():
    _load_static_filters()
    cal = db.get_trade_cal("SSE", "20190101", "20261231")
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    all_dates = cal["cal_date"].astype(str).tolist()

    configs = [
        ("Gold (freq=20 top-50 min_amt=2M)", 20, 50, 2_000_000),
        ("Sharpe (freq=5 top-200)", 5, 200, 0),
        ("Aggressive (freq=5 top-50 min_amt=2M)", 5, 50, 2_000_000),
    ]

    # Pre-warm full data once
    rebals = []
    windows_list = []
    for label, freq, n_top, min_amt in configs:
        for year in range(2020, 2027):
            ystart = f"{year}0101"
            yend = f"{year}1231"
            rb = get_rebal_dates(ystart, yend, freq)
            if len(rb) >= 2:
                rebals.append(rb)
                windows_list.append(build_rebal_windows(rb, all_dates, 60))
    prewarm(rebals, windows_list)

    print(f"\n{'Config':40s} {'Year':>6s} {'NetRet':>9s} {'BH(EW)':>9s} {'Alpha':>8s} "
          f"{'MDD':>6s} {'WR':>5s} {'AvgPicks':>9s}", flush=True)
    print("-" * 105, flush=True)
    for label, freq, n_top, min_amt in configs:
        for year in range(2020, 2027):
            ystart = f"{year}0101"
            yend = f"{year}1231"
            rb = get_rebal_dates(ystart, yend, freq)
            if len(rb) < 2:
                continue
            wins = build_rebal_windows(rb, all_dates, 60)
            r = run_backtest(f"{label}_{year}", rb, wins, n_top, min_amount_yuan=min_amt)
            bh = market_bh_total(rb[0], rb[-1])
            mdd = r.mdd_pct()
            print(f"{label:40s} {year:>6d} {r.net_total_pct:+8.2f}% {bh:+8.2f}% "
                  f"{r.net_total_pct - bh:+7.2f}% {mdd:>5.2f}% {r.wr_pct:>4.1f}% {r.avg_picks:>8.1f}",
                  flush=True)
        print(flush=True)


if __name__ == "__main__":
    main()
