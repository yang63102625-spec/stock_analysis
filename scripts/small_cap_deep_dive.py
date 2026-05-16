"""Deep-dive on the small_cap factor — the only A-share factor that survived
2yr OOS in factor_alpha_test.

Purpose
-------
Lock down the optimal investable small_cap configuration along five axes:

  1. Year-by-year breakdown (regime stability)
  2. Rebalance frequency sweep (5/10/20/40/60 trading days)
  3. Top-N retail-executable size sweep (10..200)
  4. Liquidity floor (require avg-daily-amount > X yuan)
  5. Risk metrics (NAV path, MDD, Sharpe, Calmar, monthly win-rate)

All passes share one in-process cache built from LocalDB by-date shards,
so runtime is dominated by the first pre-warm; subsequent passes are
seconds. Universe: full A-share, ST/退市/* excluded, listed > 365 days.

Costs: commission 0.025% x2 + stamp 0.05% + slippage 0.1% x2 = 0.275%
per fully rotated stock per rebalance.

Usage::

    python scripts/small_cap_deep_dive.py --start 20240109 --end 20260509
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.services.local_db import default_db


db = default_db()

COST_PER_REPLACEMENT = 0.00025 * 2 + 0.0005 + 0.001 * 2  # 0.275%

_DAILY_CACHE: Dict[str, pd.DataFrame] = {}
_BASIC_CACHE: Dict[str, pd.DataFrame] = {}
_AMOUNT_CACHE: Dict[str, Dict[str, float]] = {}  # date -> ts_code -> amount (yuan)
_EXCLUDE_TS: set = set()
_LIST_DATE: Dict[str, str] = {}


def _daily(d: str) -> pd.DataFrame:
    if d not in _DAILY_CACHE:
        _DAILY_CACHE[d] = db.get_market_daily(d)
    return _DAILY_CACHE[d]


def _basic(d: str) -> pd.DataFrame:
    if d not in _BASIC_CACHE:
        _BASIC_CACHE[d] = db.get_market_daily_basic(d)
    return _BASIC_CACHE[d]


def _amount_map(d: str) -> Dict[str, float]:
    """Return ts_code -> daily traded amount (yuan).

    Tushare 'daily' has 'amount' in 千元 (thousand yuan); convert to yuan.
    """
    if d in _AMOUNT_CACHE:
        return _AMOUNT_CACHE[d]
    df = _daily(d)
    if df.empty or "amount" not in df.columns:
        _AMOUNT_CACHE[d] = {}
        return _AMOUNT_CACHE[d]
    m = dict(zip(df["ts_code"], df["amount"].astype(float) * 1000.0))
    _AMOUNT_CACHE[d] = m
    return m


def _load_static_filters() -> None:
    global _EXCLUDE_TS, _LIST_DATE
    sb = db.get_stock_basic()
    if sb.empty:
        return
    _LIST_DATE = dict(zip(sb["ts_code"], sb["list_date"].astype(str)))
    name_mask = sb["name"].str.contains(r"ST|退|\*", regex=True, na=False)
    _EXCLUDE_TS = set(sb.loc[name_mask, "ts_code"].tolist())


def _is_eligible(ts_code: str, trade_date: str, min_list_days: int = 365) -> bool:
    if ts_code in _EXCLUDE_TS:
        return False
    ld = _LIST_DATE.get(ts_code)
    if ld:
        if (pd.Timestamp(trade_date) - pd.Timestamp(ld)).days < min_list_days:
            return False
    return True


def get_rebal_dates(start: str, end: str, freq_days: int) -> List[str]:
    cal = db.get_trade_cal("SSE", start, end)
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    return cal["cal_date"].astype(str).tolist()[::freq_days]


def select_small_cap(
    entry_date: str,
    n_top: int,
    min_amount_yuan: float = 0.0,
    avg_amount_lookback: int = 5,
    lookback_dates: Optional[List[str]] = None,
) -> List[str]:
    """Select top-N smallest market-cap stocks at entry_date, with optional
    liquidity floor based on average daily turnover over last N days.
    """
    basic = _basic(entry_date)
    daily = _daily(entry_date)
    if basic.empty or daily.empty:
        return []
    panel = daily.merge(basic[["ts_code", "total_mv"]], on="ts_code", how="inner")
    panel = panel.dropna(subset=["total_mv"])
    panel = panel[panel["total_mv"] > 0]
    panel = panel[panel["ts_code"].apply(lambda c: _is_eligible(c, entry_date))]
    if panel.empty:
        return []

    if min_amount_yuan > 0 and lookback_dates:
        # Compute avg daily amount over last `avg_amount_lookback` trading days
        recent = lookback_dates[-avg_amount_lookback:]
        amount_sum: Dict[str, float] = {}
        amount_cnt: Dict[str, int] = {}
        for d in recent:
            for ts, a in _amount_map(d).items():
                amount_sum[ts] = amount_sum.get(ts, 0.0) + a
                amount_cnt[ts] = amount_cnt.get(ts, 0) + 1
        avg_amt = {
            ts: amount_sum[ts] / amount_cnt[ts]
            for ts in amount_sum
            if amount_cnt[ts] >= max(2, avg_amount_lookback // 2)
        }
        panel = panel[panel["ts_code"].apply(
            lambda c: avg_amt.get(c, 0.0) >= min_amount_yuan)]
        if panel.empty:
            return []

    panel = panel.sort_values("total_mv").head(n_top)
    return panel["ts_code"].tolist()


def holding_return(picks: List[str], entry: str, exit: str) -> float:
    if not picks:
        return 0.0
    df_e = _daily(entry)
    df_x = _daily(exit)
    if df_e.empty or df_x.empty or "ts_code" not in df_e.columns or "ts_code" not in df_x.columns:
        return 0.0
    e = dict(zip(df_e["ts_code"], df_e["close"].astype(float)))
    x = dict(zip(df_x["ts_code"], df_x["close"].astype(float)))
    rets = []
    for ts in picks:
        p0, p1 = e.get(ts), x.get(ts)
        if p0 and p1 and p0 > 0:
            rets.append(p1 / p0 - 1)
    return float(np.mean(rets)) if rets else 0.0


@dataclass
class BacktestResult:
    label: str
    nav_gross: List[float]   # NAV path including pre-cost
    nav_net: List[float]     # NAV path net of costs
    rebal_dates: List[str]   # date at each NAV[i+1]
    rets: List[float]
    npicks: List[int]
    turnovers: List[float]

    @property
    def gross_total_pct(self) -> float:
        return (self.nav_gross[-1] - 1) * 100 if self.nav_gross else 0

    @property
    def net_total_pct(self) -> float:
        return (self.nav_net[-1] - 1) * 100 if self.nav_net else 0

    @property
    def n(self) -> int:
        return len(self.rets)

    @property
    def avg_per_rebal_pct(self) -> float:
        return float(np.mean(self.rets) * 100) if self.rets else 0

    @property
    def wr_pct(self) -> float:
        return float(np.mean([r > 0 for r in self.rets]) * 100) if self.rets else 0

    @property
    def avg_picks(self) -> float:
        return float(np.mean(self.npicks)) if self.npicks else 0

    @property
    def avg_turnover_pct(self) -> float:
        return float(np.mean(self.turnovers) * 100) if self.turnovers else 0

    def mdd_pct(self) -> float:
        if not self.nav_net:
            return 0.0
        nav = np.asarray(self.nav_net)
        peak = np.maximum.accumulate(nav)
        dd = (peak - nav) / peak
        return float(np.max(dd) * 100)

    def sharpe(self, periods_per_year: float) -> float:
        if not self.rets:
            return 0.0
        arr = np.asarray(self.rets)
        if arr.std() == 0:
            return 0.0
        return float((arr.mean() / arr.std()) * np.sqrt(periods_per_year))

    def calmar(self) -> float:
        years = self.n / max(1, self.n)  # placeholder; actual annualization below
        return 0.0  # computed externally with explicit years


def run_backtest(
    label: str,
    rebal: List[str],
    rebal_windows: List[List[str]],
    n_top: int,
    min_amount_yuan: float = 0.0,
    avg_amount_lookback: int = 5,
) -> BacktestResult:
    nav_g, nav_n = [1.0], [1.0]
    rets, npicks, turns = [], [], []
    prev_set: set = set()
    for i in range(len(rebal) - 1):
        d_entry, d_exit = rebal[i], rebal[i + 1]
        picks = select_small_cap(
            d_entry, n_top, min_amount_yuan, avg_amount_lookback,
            rebal_windows[i] if rebal_windows else None,
        )
        if not picks:
            continue
        curr_set = set(picks)
        if i == 0 or not prev_set:
            turnover = 1.0
        else:
            n_replaced = len(curr_set - prev_set)
            turnover = n_replaced / max(1, len(curr_set))
        cost = turnover * COST_PER_REPLACEMENT
        ret = holding_return(picks, d_entry, d_exit)
        nav_g.append(nav_g[-1] * (1 + ret))
        nav_n.append(nav_n[-1] * (1 + ret) * (1 - cost))
        rets.append(ret)
        npicks.append(len(picks))
        turns.append(turnover)
        prev_set = curr_set
    return BacktestResult(label, nav_g, nav_n, rebal[1: 1 + len(rets)],
                           rets, npicks, turns)


def annualization_factor(start: str, end: str, n_periods: int) -> float:
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    years = days / 365.25
    return n_periods / max(years, 1e-9)


def market_bh_total(start: str, end: str) -> float:
    df_s, df_e = _daily(start), _daily(end)
    if df_s.empty or df_e.empty:
        return 0.0
    s = dict(zip(df_s["ts_code"], df_s["close"].astype(float)))
    e = dict(zip(df_e["ts_code"], df_e["close"].astype(float)))
    rets = [e[t] / s[t] - 1 for t in s
            if t in e and s[t] > 0 and e[t] > 0 and _is_eligible(t, start)]
    return float(np.mean(rets) * 100) if rets else 0.0


def prewarm(rebal_all_passes: List[List[str]], rebal_windows_all: List[List[str]]) -> None:
    needed: set = set()
    for r in rebal_all_passes:
        needed.update(r)
    for ws in rebal_windows_all:
        for w in ws:
            needed.update(w)
    needed = sorted(needed)
    print(f"[prewarm] {len(needed)} unique trade dates", flush=True)
    t0 = time.time()
    for i, d in enumerate(needed):
        _daily(d)
        if (i + 1) % 200 == 0:
            print(f"  ...{i+1}/{len(needed)} ({time.time()-t0:.0f}s)", flush=True)
    # daily_basic only needed at rebal entry dates
    rebal_entry_dates = sorted({d for r in rebal_all_passes for d in r[:-1]})
    for d in rebal_entry_dates:
        _basic(d)
    print(f"[prewarm] done in {time.time()-t0:.1f}s\n", flush=True)


def build_rebal_windows(rebal: List[str], all_dates: List[str], lookback: int = 60) -> List[List[str]]:
    idx_map = {d: i for i, d in enumerate(all_dates)}
    windows = []
    for d in rebal[:-1]:
        idx = idx_map.get(d)
        if idx is None:
            windows.append([])
            continue
        start = max(0, idx - lookback)
        windows.append(all_dates[start:idx + 1])
    return windows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20240109")
    ap.add_argument("--end", default="20260509")
    args = ap.parse_args()

    _load_static_filters()
    print(f"[filter] ST/退/* excluded: {len(_EXCLUDE_TS)} codes\n", flush=True)

    cal = db.get_trade_cal("SSE", "20230101", args.end)
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    all_dates = cal["cal_date"].astype(str).tolist()

    # Define passes
    rebal_freqs = [5, 10, 20, 40, 60]
    rebal_per_freq = {f: get_rebal_dates(args.start, args.end, f) for f in rebal_freqs}
    windows_per_freq = {f: build_rebal_windows(rebal_per_freq[f], all_dates, 60)
                        for f in rebal_freqs}

    prewarm(list(rebal_per_freq.values()), list(windows_per_freq.values()))

    bh = market_bh_total(rebal_per_freq[20][0], rebal_per_freq[20][-1])
    print(f"=== BASELINE: Mkt EQW B&H ({rebal_per_freq[20][0]}->{rebal_per_freq[20][-1]}): {bh:+.2f}%  ===\n", flush=True)

    # ── Pass 1: rebalance frequency × top-N grid (no liquidity floor) ──
    print("--- PASS 1: Rebalance frequency × top-N (no liquidity filter) ---", flush=True)
    print(f"{'Freq':>5s} {'Top-N':>5s} | {'NAV NET':>9s} {'AvgRebal':>9s} {'WR':>5s} {'Turn':>6s} {'MDD':>6s} {'Sharpe':>7s} {'NetAlpha':>9s}", flush=True)
    print("-" * 95, flush=True)
    rows = []
    for freq in rebal_freqs:
        rebal = rebal_per_freq[freq]
        wins = windows_per_freq[freq]
        ann = annualization_factor(rebal[0], rebal[-1], len(rebal) - 1)
        for n_top in (20, 30, 50, 100, 200):
            r = run_backtest(f"f={freq}_n={n_top}", rebal, wins, n_top)
            mdd = r.mdd_pct()
            shp = r.sharpe(ann)
            print(f"{freq:>5d} {n_top:>5d} | {r.net_total_pct:+8.2f}% {r.avg_per_rebal_pct:+8.2f}% "
                  f"{r.wr_pct:>4.1f}% {r.avg_turnover_pct:>5.1f}% {mdd:>5.2f}% "
                  f"{shp:>6.2f} {r.net_total_pct - bh:+8.2f}%", flush=True)
            rows.append({"freq": freq, "n_top": n_top, "net": r.net_total_pct,
                         "alpha": r.net_total_pct - bh, "mdd": mdd, "sharpe": shp,
                         "wr": r.wr_pct, "turn": r.avg_turnover_pct,
                         "navs": r.nav_net, "dates": r.rebal_dates})

    best = max(rows, key=lambda r: r["alpha"])
    print(f"\n>>> Best by NET alpha: freq={best['freq']}, top-{best['n_top']}, "
          f"alpha={best['alpha']:+.2f}%, MDD={best['mdd']:.2f}%, Sharpe={best['sharpe']:.2f}", flush=True)
    best_sharpe = max(rows, key=lambda r: r["sharpe"])
    print(f">>> Best by Sharpe: freq={best_sharpe['freq']}, top-{best_sharpe['n_top']}, "
          f"alpha={best_sharpe['alpha']:+.2f}%, MDD={best_sharpe['mdd']:.2f}%, Sharpe={best_sharpe['sharpe']:.2f}\n", flush=True)

    # ── Pass 2: liquidity floor on best config ──
    print("--- PASS 2: liquidity floor on best by-Sharpe config ---", flush=True)
    bf = best_sharpe["freq"]
    bn = best_sharpe["n_top"]
    print(f"{'MinAmt(yuan)':>14s} | {'NAV NET':>9s} {'AvgPicks':>8s} {'MDD':>6s} {'Sharpe':>7s} {'Alpha':>9s}", flush=True)
    print("-" * 70, flush=True)
    for min_amt in (0, 5_000_000, 10_000_000, 20_000_000, 50_000_000, 100_000_000):
        rebal = rebal_per_freq[bf]
        wins = windows_per_freq[bf]
        ann = annualization_factor(rebal[0], rebal[-1], len(rebal) - 1)
        r = run_backtest(f"liq_{min_amt}", rebal, wins, bn, min_amount_yuan=min_amt)
        print(f"{min_amt:>14,d} | {r.net_total_pct:+8.2f}% {r.avg_picks:>7.1f} "
              f"{r.mdd_pct():>5.2f}% {r.sharpe(ann):>6.2f} {r.net_total_pct - bh:+8.2f}%", flush=True)

    # ── Pass 3: year-by-year breakdown of best config ──
    print(f"\n--- PASS 3: Year-by-year decomposition of freq={bf}, top-{bn} ---", flush=True)
    # Run once full window, then slice NAV
    rebal = rebal_per_freq[bf]
    wins = windows_per_freq[bf]
    r_full = run_backtest("full", rebal, wins, bn)
    # Pair (date, nav)
    series = pd.Series(r_full.nav_net[1:], index=pd.to_datetime(r_full.rebal_dates))
    print(f"{'Year':>6s} {'StartNAV':>9s} {'EndNAV':>9s} {'YearRet':>9s} {'BH(EW)':>9s} {'Alpha':>8s} {'Periods':>8s}", flush=True)
    print("-" * 75, flush=True)
    for year in sorted({d.year for d in series.index}):
        sub = series[series.index.year == year]
        if sub.empty:
            continue
        # Start NAV: previous year's last NAV (or 1.0 for first year)
        prior = series[series.index.year < year]
        start_nav = prior.iloc[-1] if not prior.empty else 1.0
        end_nav = sub.iloc[-1]
        year_ret = (end_nav / start_nav - 1) * 100
        # Year B&H benchmark
        # Anchor on last trade day of prev year & last trade day of this year
        year_trade_dates = [d for d in all_dates if d.startswith(str(year))]
        if not year_trade_dates:
            continue
        bh_year = market_bh_total(year_trade_dates[0], year_trade_dates[-1])
        print(f"{year:>6d} {start_nav:>8.4f} {end_nav:>8.4f} {year_ret:+8.2f}% "
              f"{bh_year:+8.2f}% {year_ret - bh_year:+7.2f}% {len(sub):>7d}", flush=True)

    # ── Pass 4: Full risk metrics on best config ──
    print(f"\n--- PASS 4: Risk metrics — freq={bf}, top-{bn} ---", flush=True)
    nav_arr = np.asarray(r_full.nav_net)
    rets_arr = np.diff(nav_arr) / nav_arr[:-1]
    days = (pd.Timestamp(r_full.rebal_dates[-1]) - pd.Timestamp(rebal[0])).days
    years = days / 365.25
    cagr = (nav_arr[-1] ** (1 / years) - 1) * 100 if nav_arr[-1] > 0 else float("nan")
    mdd = r_full.mdd_pct()
    sharpe = r_full.sharpe(annualization_factor(rebal[0], rebal[-1], len(rebal) - 1))
    calmar = (cagr / mdd) if mdd > 0 else float("nan")
    print(f"  NET total return   : {r_full.net_total_pct:+.2f}%", flush=True)
    print(f"  Period             : {years:.2f} years", flush=True)
    print(f"  CAGR               : {cagr:+.2f}%/yr", flush=True)
    print(f"  Max drawdown       : {mdd:.2f}%", flush=True)
    print(f"  Sharpe (annualised): {sharpe:.2f}", flush=True)
    print(f"  Calmar (CAGR/MDD)  : {calmar:.2f}", flush=True)
    print(f"  Rebal win-rate     : {r_full.wr_pct:.1f}%", flush=True)
    print(f"  Avg turnover/rebal : {r_full.avg_turnover_pct:.1f}%", flush=True)


if __name__ == "__main__":
    main()
