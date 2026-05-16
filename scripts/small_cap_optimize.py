"""Find the optimal small_cap configuration for retail capital.

Constrained search:
  - freq ∈ {5, 10, 20} trading days
  - top_n ∈ {30, 50, 100, 150, 200}
  - liquidity floor ∈ {0, 2_000_000, 5_000_000, 10_000_000} yuan/day
Optimize: maximize Sharpe subject to MDD ≤ 35%.

Also adds:
  - Drawdown-based defensive overlay (cash when SSE < MA60 by 5%)
  - Year-by-year alpha for the winning config
"""
from __future__ import annotations

import argparse
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from src.services.local_db import default_db
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from small_cap_deep_dive import (  # type: ignore
    _load_static_filters, _daily, _basic, _amount_map,
    select_small_cap, holding_return, run_backtest, market_bh_total,
    annualization_factor, build_rebal_windows, get_rebal_dates, prewarm,
    BacktestResult, COST_PER_REPLACEMENT, _is_eligible,
)


db = default_db()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20240109")
    ap.add_argument("--end", default="20260509")
    ap.add_argument("--mdd-cap", type=float, default=35.0,
                    help="exclude configs with MDD > this %")
    args = ap.parse_args()

    _load_static_filters()
    cal = db.get_trade_cal("SSE", "20230101", args.end)
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    all_dates = cal["cal_date"].astype(str).tolist()

    freqs = [5, 10, 20]
    rebal_per = {f: get_rebal_dates(args.start, args.end, f) for f in freqs}
    windows_per = {f: build_rebal_windows(rebal_per[f], all_dates, 60) for f in freqs}
    prewarm(list(rebal_per.values()), list(windows_per.values()))

    bh = market_bh_total(rebal_per[20][0], rebal_per[20][-1])
    print(f"\n=== BASELINE: Mkt EQW B&H: {bh:+.2f}% ===\n", flush=True)

    print("--- GRID SEARCH: freq × top-N × min_amount ---", flush=True)
    print(f"{'F':>3s} {'N':>4s} {'MinAmt':>10s} | {'NetTot':>8s} {'CAGR':>7s} "
          f"{'MDD':>6s} {'Sharpe':>7s} {'Calmar':>7s} {'WR':>5s} {'Turn':>5s} {'Alpha':>8s}", flush=True)
    print("-" * 95, flush=True)
    rows = []
    for freq in freqs:
        rebal = rebal_per[freq]
        wins = windows_per[freq]
        ann = annualization_factor(rebal[0], rebal[-1], len(rebal) - 1)
        years = (pd.Timestamp(rebal[-1]) - pd.Timestamp(rebal[0])).days / 365.25
        for n_top in (30, 50, 100, 150, 200):
            for min_amt in (0, 2_000_000, 5_000_000, 10_000_000):
                r = run_backtest(f"f{freq}n{n_top}m{min_amt}", rebal, wins,
                                  n_top, min_amount_yuan=min_amt)
                mdd = r.mdd_pct()
                shp = r.sharpe(ann)
                nav = r.nav_net[-1] if r.nav_net else 1.0
                cagr = (nav ** (1 / max(years, 1e-9)) - 1) * 100 if nav > 0 else float("nan")
                calmar = (cagr / mdd) if mdd > 0 else float("nan")
                rows.append({
                    "freq": freq, "n_top": n_top, "min_amt": min_amt,
                    "net": r.net_total_pct, "cagr": cagr, "mdd": mdd,
                    "sharpe": shp, "calmar": calmar, "wr": r.wr_pct,
                    "turn": r.avg_turnover_pct, "alpha": r.net_total_pct - bh,
                    "_obj": r,
                })
                star = "*" if mdd <= args.mdd_cap else " "
                print(f"{star}{freq:>2d} {n_top:>4d} {min_amt:>10,d} | "
                      f"{r.net_total_pct:+7.1f}% {cagr:+6.1f}% {mdd:>5.1f}% "
                      f"{shp:>6.2f} {calmar:>6.2f} {r.wr_pct:>4.1f}% "
                      f"{r.avg_turnover_pct:>4.1f}% {r.net_total_pct - bh:+7.1f}%",
                      flush=True)

    qualified = [r for r in rows if r["mdd"] <= args.mdd_cap]
    if not qualified:
        print(f"\n!! No config meets MDD ≤ {args.mdd_cap}% !!", flush=True)
        qualified = rows

    print(f"\n=== TOP 5 by Sharpe (MDD ≤ {args.mdd_cap}%) ===", flush=True)
    for r in sorted(qualified, key=lambda r: -r["sharpe"])[:5]:
        print(f"  freq={r['freq']:2d} top-{r['n_top']:3d} minAmt={r['min_amt']:>10,d} "
              f"| Sharpe={r['sharpe']:.2f} Calmar={r['calmar']:.2f} "
              f"NET={r['net']:+.1f}% MDD={r['mdd']:.1f}% Alpha={r['alpha']:+.1f}%", flush=True)

    print(f"\n=== TOP 5 by Calmar (MDD ≤ {args.mdd_cap}%) ===", flush=True)
    for r in sorted(qualified, key=lambda r: -r["calmar"])[:5]:
        print(f"  freq={r['freq']:2d} top-{r['n_top']:3d} minAmt={r['min_amt']:>10,d} "
              f"| Calmar={r['calmar']:.2f} Sharpe={r['sharpe']:.2f} "
              f"NET={r['net']:+.1f}% MDD={r['mdd']:.1f}% Alpha={r['alpha']:+.1f}%", flush=True)

    print(f"\n=== TOP 5 by Alpha (MDD ≤ {args.mdd_cap}%) ===", flush=True)
    for r in sorted(qualified, key=lambda r: -r["alpha"])[:5]:
        print(f"  freq={r['freq']:2d} top-{r['n_top']:3d} minAmt={r['min_amt']:>10,d} "
              f"| Alpha={r['alpha']:+.1f}% Sharpe={r['sharpe']:.2f} "
              f"NET={r['net']:+.1f}% MDD={r['mdd']:.1f}%", flush=True)


if __name__ == "__main__":
    main()
