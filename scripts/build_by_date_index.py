"""Rebuild by-date sharded index from existing per-stock parquet files.

Per-stock layout (slow for full-market single-day reads):
    daily/<ts_code>.parquet

By-date layout (fast for full-market single-day reads):
    daily_by_date/<YYYYMMDD>.parquet

Run after preload to make backtests 50-100x faster on full-market reads.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from src.services.local_db import default_db


TABLES = ("daily", "daily_basic", "moneyflow")


def rebuild(table: str, db) -> None:
    src_dir = db.root / table
    dst_dir = db.root / f"{table}_by_date"
    if not src_dir.exists():
        print(f"[skip] {table}: src dir missing")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    files = sorted(src_dir.glob("*.parquet"))
    print(f"[{table}] reading {len(files)} per-stock files...")
    chunks = []
    for i, f in enumerate(files):
        try:
            chunks.append(pd.read_parquet(f))
        except Exception as e:
            print(f"  WARN: {f.name}: {e}")
        if (i + 1) % 1000 == 0:
            print(f"  ...{i+1}/{len(files)}")
    if not chunks:
        print(f"[{table}] no data, skipping")
        return
    df = pd.concat(chunks, ignore_index=True)
    print(f"[{table}] concat done: {len(df)} rows, {time.time()-t0:.1f}s — writing by-date shards")

    if "trade_date" not in df.columns:
        print(f"[{table}] missing trade_date column, skip")
        return

    n_dates = 0
    for td, sub in df.groupby("trade_date"):
        out = dst_dir / f"{td}.parquet"
        tmp = out.with_suffix(".parquet.tmp")
        sub.reset_index(drop=True).to_parquet(tmp, index=False)
        tmp.replace(out)
        n_dates += 1
    print(f"[{table}] wrote {n_dates} by-date shards in {time.time()-t0:.1f}s total")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", nargs="+", default=list(TABLES))
    args = ap.parse_args()

    db = default_db()
    for t in args.tables:
        rebuild(t, db)


if __name__ == "__main__":
    main()
