"""Single-factor alpha test on A-share, 2024-2026 OOS.

Tests classical factors by sorting stocks at each rebalance date, taking
top decile, holding equal-weight until next rebalance, then comparing
total return to equal-weight market B&H.

Factors:
  - small_cap: lowest total_mv (smallest 10%)
  - low_pe: lowest positive PE
  - low_vol: lowest 20-day return std
  - st_rev: worst 20-day return (short-term reversal)
  - momentum: best 60-day return
  - high_turnover: highest turnover_rate (sell signal in CN)
  - low_turnover: lowest turnover_rate

Universe: all A-share stocks with both daily + daily_basic at rebalance date.
Excludes ST (handled by name filter requires lookup; we approximate by
requiring positive close).

Output: total return, monthly avg, win rate vs market.
"""
from __future__ import annotations

import argparse
import time
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.services.local_db import default_db


db = default_db()


_PANEL_CACHE: Dict[str, pd.DataFrame] = {}
_BASIC_CACHE: Dict[str, pd.DataFrame] = {}
_EXCLUDE_FILTER_ENABLED = False
_EXCLUDE_TS_CODES: set = set()
_LIST_DATE_MAP: Dict[str, str] = {}
_NEW_STOCK_DAYS = 365  # exclude stocks listed within last N days


def _load_static_filters() -> None:
    """Pre-load name + list_date for ST/new-stock exclusion."""
    global _EXCLUDE_TS_CODES, _LIST_DATE_MAP
    sb = db.get_stock_basic()
    if sb.empty:
        return
    _LIST_DATE_MAP = dict(zip(sb["ts_code"], sb["list_date"].astype(str)))
    # Static ST exclusion (current snapshot — historical name changes ignored)
    name_mask = sb["name"].str.contains(r"ST|退|\*", regex=True, na=False)
    _EXCLUDE_TS_CODES = set(sb.loc[name_mask, "ts_code"].tolist())


def _is_eligible(ts_code: str, trade_date: str) -> bool:
    """Return False if ST or listed within last N days at trade_date."""
    if not _EXCLUDE_FILTER_ENABLED:
        return True
    if ts_code in _EXCLUDE_TS_CODES:
        return False
    list_date = _LIST_DATE_MAP.get(ts_code)
    if list_date:
        td_dt = pd.Timestamp(trade_date)
        ld_dt = pd.Timestamp(list_date)
        if (td_dt - ld_dt).days < _NEW_STOCK_DAYS:
            return False
    return True


def _cached_daily(d: str) -> pd.DataFrame:
    if d not in _PANEL_CACHE:
        _PANEL_CACHE[d] = db.get_market_daily(d)
    return _PANEL_CACHE[d]


def _cached_basic(d: str) -> pd.DataFrame:
    if d not in _BASIC_CACHE:
        _BASIC_CACHE[d] = db.get_market_daily_basic(d)
    return _BASIC_CACHE[d]


def get_rebal_dates(start: str, end: str, freq_days: int) -> List[str]:
    """Get rebalance dates from trade calendar, every freq_days trading days."""
    cal = db.get_trade_cal("SSE", start, end)
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    dates = cal["cal_date"].astype(str).tolist()
    return dates[::freq_days]


def load_market_panel(date: str) -> pd.DataFrame:
    """Merge daily + daily_basic for one trade_date (cached)."""
    daily = _cached_daily(date)
    basic = _cached_basic(date)
    if daily.empty or basic.empty:
        return pd.DataFrame()
    cols_b = [c for c in ["ts_code", "turnover_rate", "pe_ttm", "pb", "total_mv", "circ_mv"] if c in basic.columns]
    return daily.merge(basic[cols_b], on="ts_code", how="inner")


def compute_factor(date: str, lookback_dates: List[str]) -> pd.DataFrame:
    """Build factor panel at date using a pre-sliced lookback window.

    lookback_dates: chronological list of trading dates, last entry == date.
    """
    panel = load_market_panel(date)
    if panel.empty or len(lookback_dates) < 21:
        return pd.DataFrame()

    # Build wide close matrix from cached daily snapshots
    closes_by_date: Dict[str, Dict[str, float]] = {}
    for d in lookback_dates:
        df = _cached_daily(d)
        if not df.empty:
            closes_by_date[d] = dict(zip(df["ts_code"], df["close"].astype(float)))
    sorted_dates = sorted(closes_by_date.keys())
    if len(sorted_dates) < 21:
        return pd.DataFrame()
    today = sorted_dates[-1]
    d20 = sorted_dates[-21]
    d60 = sorted_dates[max(0, len(sorted_dates) - 61)]
    last21 = sorted_dates[-21:]

    rows = []
    for ts_code in panel["ts_code"]:
        c_today = closes_by_date[today].get(ts_code)
        c_20 = closes_by_date[d20].get(ts_code)
        c_60 = closes_by_date[d60].get(ts_code)
        if c_today is None or c_20 is None or c_today <= 0 or c_20 <= 0:
            continue
        ret_20 = c_today / c_20 - 1
        ret_60 = (c_today / c_60 - 1) if (c_60 and c_60 > 0) else np.nan

        prices = [closes_by_date[d].get(ts_code) for d in last21]
        prices = [p for p in prices if p and p > 0]
        if len(prices) < 5:
            continue
        arr = np.asarray(prices, dtype=float)
        rets = np.diff(arr) / arr[:-1]
        vol_20 = float(np.std(rets)) if rets.size > 1 else np.nan

        rows.append({"ts_code": ts_code, "close": c_today,
                     "ret_20": ret_20, "ret_60": ret_60, "vol_20": vol_20})

    fac = pd.DataFrame(rows)
    if fac.empty:
        return fac
    fac = fac.merge(panel[["ts_code", "turnover_rate", "pe_ttm", "total_mv"]], on="ts_code")
    if _EXCLUDE_FILTER_ENABLED:
        fac = fac[fac["ts_code"].apply(lambda c: _is_eligible(c, date))]
    return fac.reset_index(drop=True)


def select_top(fac: pd.DataFrame, factor: str, ascending: bool, decile: float = 0.1) -> List[str]:
    """Return top decile (or bottom if ascending=True) ts_codes by factor value."""
    df = fac.dropna(subset=[factor])
    if factor in ("pe_ttm",):
        df = df[df[factor] > 0]
    if df.empty:
        return []
    df = df.sort_values(factor, ascending=ascending)
    n = max(1, int(len(df) * decile))
    return df["ts_code"].head(n).tolist()


def compute_holding_return(picks: List[str], entry_date: str, exit_date: str) -> float:
    """Equal-weight return of `picks` from entry_date to exit_date close."""
    if not picks:
        return 0.0
    df_e = _cached_daily(entry_date)
    df_x = _cached_daily(exit_date)
    if df_e.empty or df_x.empty:
        return 0.0
    e_map = dict(zip(df_e["ts_code"], df_e["close"].astype(float)))
    x_map = dict(zip(df_x["ts_code"], df_x["close"].astype(float)))
    rets = []
    for ts in picks:
        p0 = e_map.get(ts)
        p1 = x_map.get(ts)
        if p0 and p1 and p0 > 0:
            rets.append(p1 / p0 - 1)
    return float(np.mean(rets)) if rets else 0.0


FACTORS: Dict[str, Tuple[str, bool]] = {
    "small_cap":     ("total_mv", True),
    "low_pe":        ("pe_ttm", True),
    "low_vol":       ("vol_20", True),
    "st_rev":        ("ret_20", True),
    "momentum_60d":  ("ret_60", False),
    "high_turnover": ("turnover_rate", False),
    "low_turnover":  ("turnover_rate", True),
}


def _rank_pct(s: pd.Series, ascending: bool) -> pd.Series:
    """Percentile rank in [0,1]; smaller value = better when ascending=True."""
    return s.rank(ascending=ascending, pct=True, method="average")


def select_intersection(fac: pd.DataFrame, specs: List[Tuple[str, bool]],
                        decile: float = 0.1) -> List[str]:
    """Pick stocks in the top decile of EVERY factor."""
    s = fac.copy()
    for col, asc in specs:
        s = s.dropna(subset=[col])
        if col in ("pe_ttm",):
            s = s[s[col] > 0]
    if s.empty:
        return []
    n_per = max(20, int(len(s) * (decile ** (1 / max(1, len(specs))))))
    chosen: set = set(s["ts_code"])
    for col, asc in specs:
        ranked = s.sort_values(col, ascending=asc).head(n_per)
        chosen &= set(ranked["ts_code"])
    return list(chosen)


def select_composite(fac: pd.DataFrame, specs: List[Tuple[str, bool, float]],
                     decile: float = 0.1) -> List[str]:
    """Composite score: sum of weighted percentile ranks; pick top decile.

    spec items: (col_name, ascending, weight). 'ascending=True' means smaller
    value is better (e.g. small_cap → True).
    """
    s = fac.copy()
    for col, _, _ in specs:
        s = s.dropna(subset=[col])
        if col in ("pe_ttm",):
            s = s[s[col] > 0]
    if s.empty:
        return []
    s = s.copy()
    s["_score"] = 0.0
    for col, asc, w in specs:
        s["_score"] += w * _rank_pct(s[col], ascending=asc)
    s = s.sort_values("_score")  # smaller _score = better
    n = max(1, int(len(s) * decile))
    return s["ts_code"].head(n).tolist()


def backtest_factor(name: str, factor_col: str, ascending: bool,
                     rebal_dates: List[str], rebal_windows: List[List[str]],
                     decile: float = 0.1) -> Dict:
    nav = 1.0
    rets_per_period: List[float] = []
    n_picks_per: List[int] = []
    for i in range(len(rebal_dates) - 1):
        d_entry = rebal_dates[i]
        d_exit = rebal_dates[i + 1]
        fac = compute_factor(d_entry, rebal_windows[i])
        if fac.empty:
            continue
        picks = select_top(fac, factor_col, ascending, decile)
        if not picks:
            continue
        ret = compute_holding_return(picks, d_entry, d_exit)
        nav *= 1 + ret
        rets_per_period.append(ret)
        n_picks_per.append(len(picks))
    total_ret = (nav - 1) * 100
    avg_ret = float(np.mean(rets_per_period) * 100) if rets_per_period else 0
    win_rate = float(np.mean([r > 0 for r in rets_per_period]) * 100) if rets_per_period else 0
    return {
        "factor": name,
        "total_return_pct": round(total_ret, 2),
        "avg_per_rebal_pct": round(avg_ret, 2),
        "win_rate_pct": round(win_rate, 2),
        "n_periods": len(rets_per_period),
        "avg_picks": round(float(np.mean(n_picks_per)), 0) if n_picks_per else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20240109")
    ap.add_argument("--end", default="20260109")
    ap.add_argument("--rebal-days", type=int, default=20, help="rebalance every N trading days")
    ap.add_argument("--decile", type=float, default=0.1)
    ap.add_argument("--exclude-st-new", action="store_true",
                    help="Exclude ST stocks and stocks listed within last 365 days")
    args = ap.parse_args()

    global _EXCLUDE_FILTER_ENABLED
    _EXCLUDE_FILTER_ENABLED = args.exclude_st_new
    if _EXCLUDE_FILTER_ENABLED:
        _load_static_filters()
        print(f"[Filter] ST/退/* + new-stock(<365d) exclusion ON: "
              f"{len(_EXCLUDE_TS_CODES)} ST/退 codes loaded", flush=True)

    rebal = get_rebal_dates(args.start, args.end, args.rebal_days)
    print(f"Rebal dates ({args.rebal_days}d freq): {len(rebal)} from {rebal[0]} to {rebal[-1]}", flush=True)

    # Pre-slice 60-day lookback windows for each rebal entry date
    cal = db.get_trade_cal("SSE", "20230101", args.end)
    cal = cal[cal["is_open"] == 1].sort_values("cal_date")
    all_trade_dates = cal["cal_date"].astype(str).tolist()
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    rebal_windows: List[List[str]] = []
    for d in rebal[:-1]:
        idx = date_to_idx.get(d)
        if idx is None:
            rebal_windows.append([])
            continue
        start = max(0, idx - 60)
        rebal_windows.append(all_trade_dates[start : idx + 1])

    # Pre-warm cache: union of all dates we'll touch
    needed: set = set()
    for w in rebal_windows:
        needed.update(w)
    needed.update(rebal)
    needed = sorted(needed)
    print(f"Pre-warming cache for {len(needed)} trade dates...", flush=True)
    t_pre = time.time()
    for i, d in enumerate(needed):
        _cached_daily(d)
        if (i + 1) % 50 == 0:
            print(f"  ...{i+1}/{len(needed)} ({time.time()-t_pre:.0f}s)", flush=True)
    # Also pre-warm daily_basic for rebal entry dates only
    for d in rebal[:-1]:
        _cached_basic(d)
    print(f"Pre-warm done in {time.time()-t_pre:.1f}s\n", flush=True)

    # Market B&H baseline
    df_s = _cached_daily(rebal[0])
    df_e = _cached_daily(rebal[-1])
    s_map = dict(zip(df_s["ts_code"], df_s["close"].astype(float)))
    e_map = dict(zip(df_e["ts_code"], df_e["close"].astype(float)))
    bh_rets = [
        e_map[ts] / s_map[ts] - 1
        for ts in s_map
        if ts in e_map and s_map[ts] > 0 and e_map[ts] > 0
        and _is_eligible(ts, rebal[0])
    ]
    bh_total = float(np.mean(bh_rets) * 100) if bh_rets else 0
    print(f"=== BASELINE: Market EQW B&H ({rebal[0]}→{rebal[-1]}): {bh_total:+.2f}% ===\n", flush=True)

    print(f"{'Factor':16s} | {'Total':>8s} | {'AvgPer':>8s} | {'WR':>6s} | {'N':>3s} | {'AvgPicks':>8s} | {'vs B&H':>8s}", flush=True)
    print("-" * 80, flush=True)

    rows = []
    for name, (col, asc) in FACTORS.items():
        t0 = time.time()
        r = backtest_factor(name, col, asc, rebal, rebal_windows, args.decile)
        r["alpha_vs_bh"] = round(r["total_return_pct"] - bh_total, 2)
        r["elapsed_s"] = round(time.time() - t0, 1)
        rows.append(r)
        print(f"{r['factor']:16s} | {r['total_return_pct']:+7.2f}% | {r['avg_per_rebal_pct']:+7.2f}% | "
              f"{r['win_rate_pct']:5.1f}% | {r['n_periods']:3d} | {r['avg_picks']:7.0f} | {r['alpha_vs_bh']:+7.2f}%   ({r['elapsed_s']}s)", flush=True)

    # ── Multi-factor combinations ────────────────────────────────────
    print("\n--- Multi-factor combinations ---", flush=True)
    combos = [
        ("intersect: small ∩ st_rev",
         lambda fac: select_intersection(fac, [("total_mv", True), ("ret_20", True)], args.decile)),
        ("intersect: small ∩ low_turn",
         lambda fac: select_intersection(fac, [("total_mv", True), ("turnover_rate", True)], args.decile)),
        ("intersect: small ∩ st_rev ∩ low_turn",
         lambda fac: select_intersection(fac,
             [("total_mv", True), ("ret_20", True), ("turnover_rate", True)], args.decile)),
        ("composite: small + st_rev (1:1)",
         lambda fac: select_composite(fac,
             [("total_mv", True, 1.0), ("ret_20", True, 1.0)], args.decile)),
        ("composite: small + st_rev + low_turn (1:1:1)",
         lambda fac: select_composite(fac,
             [("total_mv", True, 1.0), ("ret_20", True, 1.0), ("turnover_rate", True, 1.0)], args.decile)),
        ("composite: small(2) + st_rev(1) + low_turn(1)",
         lambda fac: select_composite(fac,
             [("total_mv", True, 2.0), ("ret_20", True, 1.0), ("turnover_rate", True, 1.0)], args.decile)),
    ]
    for name, picker in combos:
        t0 = time.time()
        nav = 1.0
        rets, npicks = [], []
        for i in range(len(rebal) - 1):
            d_entry, d_exit = rebal[i], rebal[i+1]
            fac = compute_factor(d_entry, rebal_windows[i])
            if fac.empty:
                continue
            picks = picker(fac)
            if not picks:
                continue
            ret = compute_holding_return(picks, d_entry, d_exit)
            nav *= 1 + ret
            rets.append(ret)
            npicks.append(len(picks))
        total = (nav - 1) * 100
        avg = float(np.mean(rets) * 100) if rets else 0
        wr = float(np.mean([r > 0 for r in rets]) * 100) if rets else 0
        ap_ = round(float(np.mean(npicks)), 0) if npicks else 0
        print(f"{name:48s} | {total:+7.2f}% | {avg:+6.2f}% | {wr:5.1f}% | picks~{ap_:.0f} | "
              f"alpha {total - bh_total:+7.2f}%   ({time.time()-t0:.1f}s)", flush=True)
        rows.append({
            "factor": name, "total_return_pct": round(total, 2),
            "alpha_vs_bh": round(total - bh_total, 2),
        })

    # ── Top-N retail-executable sizes (with full transaction costs) ──
    print("\n--- Top-N retail-executable (with TX costs: commission 0.025%×2 + stamp 0.05% + slippage 0.1%×2) ---", flush=True)
    # Per-share-rotated cost: every share replaced incurs sell+buy frictions.
    COST_PER_REPLACEMENT = 0.00025*2 + 0.0005 + 0.001*2  # 0.275% per fully rotated stock
    def _run_picker(picker_fn, label):
        nav_gross = 1.0
        nav_net = 1.0
        rets, npicks = [], []
        prev_set: set = set()
        total_turnover = 0.0
        for i in range(len(rebal) - 1):
            d_entry, d_exit = rebal[i], rebal[i+1]
            fac = compute_factor(d_entry, rebal_windows[i])
            if fac.empty:
                continue
            picks = picker_fn(fac)
            if not picks:
                continue
            curr_set = set(picks)
            if i == 0:
                turnover = 1.0  # initial buy
            else:
                if not prev_set:
                    turnover = 1.0
                else:
                    n_replaced = len(curr_set - prev_set)
                    turnover = n_replaced / max(1, len(curr_set))
            total_turnover += turnover
            cost_drag = turnover * COST_PER_REPLACEMENT
            ret = compute_holding_return(picks, d_entry, d_exit)
            nav_gross *= 1 + ret
            nav_net *= (1 + ret) * (1 - cost_drag)
            rets.append(ret)
            npicks.append(len(picks))
            prev_set = curr_set
        gross = (nav_gross - 1) * 100
        net = (nav_net - 1) * 100
        avg = float(np.mean(rets) * 100) if rets else 0
        wr = float(np.mean([r > 0 for r in rets]) * 100) if rets else 0
        ap_ = round(float(np.mean(npicks)), 0) if npicks else 0
        avg_turnover_pct = (total_turnover / max(1, len(rets)) * 100)
        print(f"{label:50s} | gross {gross:+7.2f}% | NET {net:+7.2f}% | "
              f"WR {wr:5.1f}% | picks~{ap_:3.0f} | turn~{avg_turnover_pct:4.0f}%/mo | "
              f"NET alpha {net - bh_total:+7.2f}%", flush=True)
        return {"factor": label, "total_return_pct": round(net, 2),
                "alpha_vs_bh": round(net - bh_total, 2)}

    for n_top in (10, 20, 30, 50, 100):
        rows.append(_run_picker(
            lambda fac, n=n_top: fac.dropna(subset=["total_mv"]).sort_values("total_mv").head(n)["ts_code"].tolist(),
            f"pure small_cap top-{n_top}"))
    for n_top in (10, 20, 30, 50, 100):
        def _comp(fac, n=n_top):
            f = fac.dropna(subset=["total_mv","turnover_rate"]).copy()
            f["_score"] = _rank_pct(f["total_mv"], True) + _rank_pct(f["turnover_rate"], True)
            return f.sort_values("_score").head(n)["ts_code"].tolist()
        rows.append(_run_picker(_comp, f"composite small+low_turn top-{n_top}"))

    # Best factor
    best = max(rows, key=lambda r: r["alpha_vs_bh"])
    print(f"\n>>> Best: {best['factor']} (alpha vs B&H: {best['alpha_vs_bh']:+.2f}%)", flush=True)


if __name__ == "__main__":
    main()
