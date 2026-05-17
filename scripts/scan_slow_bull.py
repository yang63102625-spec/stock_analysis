"""Slow-bull scanner — one-off research script.

Scans the full A-share market (LocalDB) and flags stocks matching the
"30-degree slow-bull" pattern:

  1. Higher lows over 250d (last-90d low > prior-90d low > pre-prior-90d low)
  2. MA60 / MA120 / MA250 in bullish stack, MA60 slope ∈ [10%, 60%] annualised
  3. 60d volatility (ATR/Price) ≤ 3.5%
  4. 250d max drawdown ≤ 25%
  5. Distance to 250d high ≤ 8% (near new high) and to 250d low ≥ 30%
  6. PE ∈ [10, 50], market cap ≥ 10B CNY
  7. Exclude ST / new listings (<300 trading days history)

Outputs a markdown report listing all qualifying tickers + scores.
"""
from __future__ import annotations

import sys
import logging
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import setup_env  # noqa: E402

setup_env()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.services.local_db import LocalStockDB  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("slow_bull")
logger.setLevel(logging.INFO)


# -------- thresholds (loose first pass; tighten later) --------
MIN_HISTORY_DAYS = 300
MA60_SLOPE_MIN_ANN = 0.10   # +10%/year
MA60_SLOPE_MAX_ANN = 0.60   # +60%/year (avoid parabolic)
VOL_60D_MAX = 0.035         # ATR%/price ≤ 3.5%
DD_250D_MAX = 0.25
DIST_HIGH_MAX = 0.08
DIST_LOW_MIN = 0.30
PE_MIN, PE_MAX = 5, 80
MCAP_MIN_YI = 100           # 100亿
TOP_N_OUT = 50


def _exclude_code(code: str, name: str) -> bool:
    if not code:
        return True
    c = code.split(".")[0]
    if c.startswith(("8", "4", "92")):  # BSE
        return True
    if name and ("ST" in name.upper() or "退" in name):
        return True
    return False


def _slope_pct_per_year(series: pd.Series) -> float:
    """Linear regression slope of log(series) -> annualised growth rate."""
    y = np.log(series.values.astype(float))
    n = len(y)
    if n < 2 or np.any(~np.isfinite(y)):
        return float("nan")
    x = np.arange(n, dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return slope * 250.0  # daily -> annual


def evaluate(df_daily: pd.DataFrame) -> dict | None:
    if df_daily is None or len(df_daily) < MIN_HISTORY_DAYS:
        return None
    df = df_daily.sort_values("trade_date").tail(260).copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    if len(close) < 250:
        return None

    last = float(close.iloc[-1])
    high250 = float(high.max())
    low250 = float(low.min())
    if last <= 0 or high250 <= 0 or low250 <= 0:
        return None

    # MAs
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    ma120 = close.rolling(120).mean().iloc[-1]
    ma250 = close.rolling(250).mean().iloc[-1]
    if not (np.isfinite(ma20) and np.isfinite(ma60)
            and np.isfinite(ma120) and np.isfinite(ma250)):
        return None
    bullish_stack = (ma20 > ma60 > ma120 > ma250) and (last > ma60)

    # MA60 slope last 60d
    ma60_series = close.rolling(60).mean().dropna().tail(60)
    slope_ann = _slope_pct_per_year(ma60_series) if len(ma60_series) >= 30 else float("nan")

    # higher lows (90-day windows)
    seg3 = low.iloc[-90:].min()
    seg2 = low.iloc[-180:-90].min()
    seg1 = low.iloc[-260:-180].min() if len(low) >= 260 else low.iloc[:max(1, len(low) - 180)].min()
    higher_lows = (seg3 > seg2 > seg1)

    # vol (ATR/price, 60d)
    tr = pd.concat([
        (high - low).abs(),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr60 = tr.rolling(60).mean().iloc[-1]
    vol_pct = atr60 / last if last else float("nan")

    # 250d MaxDD on close
    roll_max = close.rolling(250, min_periods=50).max()
    dd_series = (close / roll_max) - 1.0
    dd250 = float(-dd_series.tail(250).min()) if dd_series.notna().any() else float("nan")

    # distance from extremes
    dist_high = (high250 - last) / high250
    dist_low = (last - low250) / low250

    checks = {
        "bullish_stack": bool(bullish_stack),
        "slope_ok": bool(MA60_SLOPE_MIN_ANN <= slope_ann <= MA60_SLOPE_MAX_ANN),
        "higher_lows": bool(higher_lows),
        "vol_ok": bool(np.isfinite(vol_pct) and vol_pct <= VOL_60D_MAX),
        "dd_ok": bool(np.isfinite(dd250) and dd250 <= DD_250D_MAX),
        "dist_high_ok": bool(dist_high <= DIST_HIGH_MAX),
        "dist_low_ok": bool(dist_low >= DIST_LOW_MIN),
    }
    passes = sum(checks.values())

    return {
        "last": last,
        "ma60": float(ma60),
        "slope_ann_pct": round(slope_ann * 100, 1) if np.isfinite(slope_ann) else None,
        "higher_lows": checks["higher_lows"],
        "vol_pct": round(float(vol_pct) * 100, 2) if np.isfinite(vol_pct) else None,
        "dd250_pct": round(dd250 * 100, 1) if np.isfinite(dd250) else None,
        "dist_high_pct": round(float(dist_high) * 100, 2),
        "dist_low_pct": round(float(dist_low) * 100, 1),
        "checks_passed": passes,
        "all_pass": passes == len(checks),
    }


def main() -> None:
    db = LocalStockDB()
    sb = db.get_stock_basic()
    if sb is None or sb.empty:
        logger.error("stock_basic empty; run sync first")
        sys.exit(1)
    sb = sb[~sb.apply(lambda r: _exclude_code(str(r.get("ts_code", "")), str(r.get("name", ""))), axis=1)]
    logger.info("universe: %d codes after exclusions", len(sb))

    # latest market daily_basic for PE / mcap
    # find most recent trade_date with daily_basic data
    today = pd.Timestamp.now().strftime("%Y%m%d")
    db_basic = None
    for delta in range(0, 14):
        td = (pd.Timestamp(today) - pd.Timedelta(days=delta)).strftime("%Y%m%d")
        try:
            db_basic = db.get_market_daily_basic(td)
            if db_basic is not None and not db_basic.empty:
                logger.info("daily_basic snapshot date: %s (%d rows)", td, len(db_basic))
                break
        except Exception:
            continue
    if db_basic is None or db_basic.empty:
        logger.warning("no recent daily_basic; PE/mcap filter skipped")
        db_basic = pd.DataFrame()

    if not db_basic.empty:
        db_basic = db_basic[["ts_code", "pe_ttm", "total_mv"]].copy()
        db_basic["total_mv_yi"] = db_basic["total_mv"] / 1e4  # 万元 -> 亿元

    results = []
    t0 = time.time()
    for i, row in enumerate(sb.itertuples(index=False), 1):
        ts_code = getattr(row, "ts_code", None)
        name = getattr(row, "name", "")
        if not ts_code:
            continue
        try:
            df_d = db.get_daily(ts_code)
        except Exception:
            continue
        ev = evaluate(df_d)
        if ev is None or not ev["all_pass"]:
            continue
        rec = {
            "ts_code": ts_code,
            "name": name,
            "industry": getattr(row, "industry", ""),
            **ev,
        }
        results.append(rec)
        if i % 500 == 0:
            logger.info("scanned %d / %d  | hits=%d  | elapsed=%.1fs", i, len(sb), len(results), time.time() - t0)

    logger.info("scan done in %.1fs, raw hits=%d", time.time() - t0, len(results))

    df_out = pd.DataFrame(results)
    if df_out.empty:
        logger.warning("no slow-bull candidates found")
        return

    if not db_basic.empty:
        df_out = df_out.merge(db_basic, on="ts_code", how="left")
        # apply pe & mcap filter
        df_out = df_out[
            (df_out["pe_ttm"].between(PE_MIN, PE_MAX, inclusive="both"))
            & (df_out["total_mv_yi"] >= MCAP_MIN_YI)
        ]
        logger.info("after PE & mcap filter: %d", len(df_out))

    # composite score: slope (moderate is best), low vol, low dd
    if not df_out.empty:
        # reward slope near 25%/year, penalize extremes
        def slope_score(s):
            if s is None or not np.isfinite(s):
                return 0.0
            return max(0.0, 10.0 - abs(s - 25.0) / 3.5)
        df_out["score"] = (
            df_out["slope_ann_pct"].apply(slope_score)
            + (3.5 - df_out["vol_pct"].astype(float)) * 5
            + (25 - df_out["dd250_pct"].astype(float)) * 0.4
        )
        df_out = df_out.sort_values("score", ascending=False).head(TOP_N_OUT)

    out_dir = ROOT / "reports" / "slow_bull"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "slow_bull_scan.md"
    cols = ["ts_code", "name", "industry", "last", "slope_ann_pct",
            "vol_pct", "dd250_pct", "dist_high_pct", "dist_low_pct",
            "pe_ttm", "total_mv_yi", "score"]
    cols = [c for c in cols if c in df_out.columns]
    with md.open("w") as f:
        f.write("# 30°慢牛形态扫描结果\n\n")
        f.write(f"扫描时间: {pd.Timestamp.now():%Y-%m-%d %H:%M}\n\n")
        f.write(f"全市场候选数: {len(sb)}, 通过几何过滤: {len(results)}, "
                f"通过PE&市值过滤后取 Top {len(df_out)}\n\n")
        f.write("## 过滤参数\n")
        f.write(f"- MA60 年化斜率 ∈ [{MA60_SLOPE_MIN_ANN*100:.0f}%, {MA60_SLOPE_MAX_ANN*100:.0f}%]\n")
        f.write(f"- 60日波动率(ATR/Price) ≤ {VOL_60D_MAX*100:.1f}%\n")
        f.write(f"- 250日最大回撤 ≤ {DD_250D_MAX*100:.0f}%\n")
        f.write(f"- 距250日高点 ≤ {DIST_HIGH_MAX*100:.0f}%, 距250日低点 ≥ {DIST_LOW_MIN*100:.0f}%\n")
        f.write(f"- PE ∈ [{PE_MIN}, {PE_MAX}], 总市值 ≥ {MCAP_MIN_YI}亿\n")
        f.write("- MA20 > MA60 > MA120 > MA250 (多头排列), 三段 90 日 higher lows\n\n")
        f.write("## 候选列表\n\n")
        f.write(df_out[cols].to_markdown(index=False, floatfmt=".2f"))
    logger.info("wrote %s", md)
    print(f"\n报告: {md}")


if __name__ == "__main__":
    main()
