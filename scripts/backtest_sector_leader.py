"""Walk-forward backtest for sector-leader strategy.

Methodology:
  - Rebalance every N trading days (default 21d = ~monthly).
  - On each rebalance date, run scan_sector_leader.scan().
  - Take top K picks (by score) -> equal-weight portfolio.
  - Hold for `hold_days` trading days, then exit at close.
  - Track per-trade return + portfolio equity curve.
  - Benchmarks: HS300 buy-and-hold + equal-weight all-stocks buy-and-hold.

Usage:
  python scripts/backtest_sector_leader.py --start 20240501 --end 20260515 \
    --rebalance-days 21 --hold-days 21 --top-k 10
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import setup_env  # noqa: E402
setup_env()

from src.services.local_db import default_db  # noqa: E402
from scripts.scan_sector_leader import scan, _trading_days_before  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def _list_rebalance_dates(db, start: str, end: str, step: int) -> List[str]:
    cal = db.get_trade_cal()
    open_days = cal[(cal["is_open"] == 1) & (cal["cal_date"] >= start) & (cal["cal_date"] <= end)]
    open_days = open_days.sort_values("cal_date")["cal_date"].tolist()
    if not open_days:
        return []
    return open_days[::step]


def _fwd_return(db, ts: str, entry_date: str, hold_days: int) -> Optional[Tuple[float, str]]:
    """Return (pct_return, exit_date) after `hold_days` from entry_date close."""
    cal = db.get_trade_cal()
    open_days = cal[(cal["is_open"] == 1) & (cal["cal_date"] >= entry_date)]
    open_days = open_days.sort_values("cal_date")["cal_date"].tolist()
    if len(open_days) < hold_days + 1:
        return None
    exit_date = open_days[hold_days]
    df = db.get_daily(ts, start_date=entry_date, end_date=exit_date)
    if df is None or df.empty:
        return None
    df = df.sort_values("trade_date")
    if str(df.iloc[0]["trade_date"]) != entry_date:
        return None
    if str(df.iloc[-1]["trade_date"]) != exit_date:
        return None
    entry = float(df.iloc[0]["close"])
    exit_ = float(df.iloc[-1]["close"])
    if entry <= 0:
        return None
    return (exit_ / entry - 1.0) * 100.0, exit_date


def _benchmark_return(db, index_code: str, start: str, end: str) -> Optional[float]:
    df = db.get_index_daily(index_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return None
    df = df.sort_values("trade_date")
    return (float(df.iloc[-1]["close"]) / float(df.iloc[0]["close"]) - 1.0) * 100.0


def _equal_weight_market_return(db, start: str, end: str) -> Optional[float]:
    """Cross-sectional equal-weight return of all stocks: mean of per-stock returns."""
    sb = db.get_stock_basic()
    rets = []
    for ts in sb["ts_code"].head(500):  # sample 500 for speed
        df = db.get_daily(ts, start_date=start, end_date=end)
        if df is None or df.empty:
            continue
        df = df.sort_values("trade_date")
        if len(df) < 2 or float(df.iloc[0]["close"]) <= 0:
            continue
        rets.append((float(df.iloc[-1]["close"]) / float(df.iloc[0]["close"]) - 1.0) * 100.0)
    if not rets:
        return None
    return float(np.mean(rets))


def run_backtest(
    start: str, end: str, rebalance_days: int, hold_days: int,
    top_k: int, top_sectors_pct: float, top_per_sector: int,
) -> Dict:
    db = default_db()
    rebal_dates = _list_rebalance_dates(db, start, end, rebalance_days)
    logger.info("Rebalance dates: %d (every %dd from %s to %s)",
                len(rebal_dates), rebalance_days, start, end)

    all_trades: List[Dict] = []
    equity = 1.0
    equity_curve = [{"date": start, "equity": 1.0}]

    for i, rebal_date in enumerate(rebal_dates):
        logger.info("[%d/%d] %s - scanning...", i + 1, len(rebal_dates), rebal_date)
        try:
            _, picks = scan(rebal_date, top_sectors_pct, top_per_sector)
        except Exception as e:
            logger.warning("  scan failed: %s", e)
            continue
        if picks.empty:
            logger.info("  no picks")
            equity_curve.append({"date": rebal_date, "equity": equity})
            continue
        picks = picks.head(top_k)

        # Evaluate forward return for each pick
        period_returns = []
        for _, p in picks.iterrows():
            fr = _fwd_return(db, p["ts_code"], rebal_date, hold_days)
            if fr is None:
                continue
            ret_pct, exit_date = fr
            all_trades.append({
                "entry_date": rebal_date,
                "exit_date": exit_date,
                "ts_code": p["ts_code"],
                "name": p["name"],
                "industry": p["industry"],
                "score": p["score"],
                "ret_pct": ret_pct,
            })
            period_returns.append(ret_pct)

        if period_returns:
            period_avg = float(np.mean(period_returns))
            equity *= (1.0 + period_avg / 100.0)
            logger.info("  picks=%d traded=%d avg_ret=%.2f%% equity=%.4f",
                        len(picks), len(period_returns), period_avg, equity)
        equity_curve.append({"date": rebal_date, "equity": equity})

    trades_df = pd.DataFrame(all_trades)
    equity_df = pd.DataFrame(equity_curve)

    if trades_df.empty:
        return {"trades": trades_df, "equity": equity_df, "summary": {}}

    # Benchmarks
    hs300 = _benchmark_return(db, "000300.SH", start, end)
    csi500 = _benchmark_return(db, "000905.SH", start, end)
    eqw_mkt = _equal_weight_market_return(db, start, end)

    n = len(trades_df)
    wins = int((trades_df["ret_pct"] > 0).sum())
    avg = float(trades_df["ret_pct"].mean())
    win_avg = float(trades_df[trades_df["ret_pct"] > 0]["ret_pct"].mean()) if wins else 0.0
    loss_avg = float(trades_df[trades_df["ret_pct"] <= 0]["ret_pct"].mean()) if n - wins else 0.0
    pf = (win_avg * wins) / abs(loss_avg * (n - wins)) if (n - wins) and loss_avg < 0 else float("inf")

    # Max drawdown of equity curve
    eq_vals = equity_df["equity"].to_numpy()
    peaks = np.maximum.accumulate(eq_vals)
    drawdowns = (eq_vals - peaks) / peaks
    mdd = float(drawdowns.min() * 100)

    total_ret = float((equity - 1.0) * 100.0)

    summary = {
        "n_trades": n,
        "win_rate_pct": round(100.0 * wins / n, 2),
        "avg_return_pct": round(avg, 3),
        "win_avg_pct": round(win_avg, 3),
        "loss_avg_pct": round(loss_avg, 3),
        "profit_factor": round(pf, 3),
        "total_return_pct": round(total_ret, 2),
        "max_drawdown_pct": round(mdd, 2),
        "benchmark_hs300_pct": round(hs300, 2) if hs300 is not None else None,
        "benchmark_csi500_pct": round(csi500, 2) if csi500 is not None else None,
        "benchmark_eqw_market_pct": round(eqw_mkt, 2) if eqw_mkt is not None else None,
        "alpha_vs_hs300_pct": round(total_ret - hs300, 2) if hs300 is not None else None,
        "alpha_vs_eqw_pct": round(total_ret - eqw_mkt, 2) if eqw_mkt is not None else None,
    }
    return {"trades": trades_df, "equity": equity_df, "summary": summary}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20240501")
    ap.add_argument("--end", default="20260515")
    ap.add_argument("--rebalance-days", type=int, default=21)
    ap.add_argument("--hold-days", type=int, default=21)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--top-sectors-pct", type=float, default=0.20)
    ap.add_argument("--top-per-sector", type=int, default=3)
    args = ap.parse_args()

    res = run_backtest(
        args.start, args.end, args.rebalance_days, args.hold_days,
        args.top_k, args.top_sectors_pct, args.top_per_sector,
    )

    print("\n=== SUMMARY ===")
    for k, v in res["summary"].items():
        print(f"  {k}: {v}")

    if not res["trades"].empty:
        print(f"\n=== Top 10 trades by return ===")
        print(res["trades"].nlargest(10, "ret_pct")[
            ["entry_date", "ts_code", "name", "industry", "ret_pct"]
        ].to_string(index=False, float_format="%.2f"))
        print(f"\n=== Bottom 10 trades by return ===")
        print(res["trades"].nsmallest(10, "ret_pct")[
            ["entry_date", "ts_code", "name", "industry", "ret_pct"]
        ].to_string(index=False, float_format="%.2f"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
