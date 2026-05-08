# -*- coding: utf-8 -*-
"""
Strategy Attribution Service
=============================

Rolling per-strategy performance analytics over historical picker runs:

  - Pulls picker_history records from storage
  - For each pick, simulates forward N+5 / N+10 / N+20 day return using the
    unified trade_levels engine (same exit rules as production)
  - Aggregates per strategy: win rate, avg P/L, profit factor, max drawdown
  - Exposes get_strategy_weights() that picker can call to auto-reweight
    consistently underperforming strategies

Used by:
  - Picker merge stage (auto-reweight via get_strategy_weights())
  - Notification weekly report (format_weekly_report())

Caches results in-memory with a TTL (configurable, default 6 hours) so the
picker doesn't trigger a heavy backtest pass on every run.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Auto-reweight thresholds.
REWEIGHT_LOOKBACK_DAYS = 42              # ~2 months: covers at least one style-rotation
                                          # cycle (was 28: too easily polluted by single regime).
REWEIGHT_MIN_PICKS = 10                   # Need at least N picks for confidence
REWEIGHT_BAD_WIN_RATE = 42.0              # %: below this = "bad" (was 40: breakout
                                          # baseline win rate is ~40-45%; 40 was too lenient).
REWEIGHT_BAD_PROFIT_FACTOR = 1.0          # below this (= average loss > avg win) = "bad"
REWEIGHT_FACTOR_BAD = 0.6                 # Multiplier when both bad conditions hit
                                          # (was 0.7: too gentle — bad strategies still kept 70%).
ATTRIBUTION_TTL_SECONDS = 6 * 3600

# Default holding-day windows for per-pick evaluation.
HOLD_WINDOWS = (5, 10, 20)


@dataclass
class StrategyMetrics:
    """Aggregated metrics for a single strategy over the lookback window."""

    strategy_id: str
    sample_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate_pct: Optional[float] = None
    avg_return_pct: Optional[float] = None
    profit_factor: Optional[float] = None  # sum(gains) / abs(sum(losses))
    max_drawdown_pct: Optional[float] = None  # worst single-pick return
    avg_hold_days: Optional[float] = None

    def is_underperforming(self) -> bool:
        """True if metric pair is bad enough to trigger auto-reweight."""
        if self.sample_count < REWEIGHT_MIN_PICKS:
            return False
        if self.win_rate_pct is None or self.profit_factor is None:
            return False
        return (
            self.win_rate_pct < REWEIGHT_BAD_WIN_RATE
            and self.profit_factor < REWEIGHT_BAD_PROFIT_FACTOR
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "sample_count": self.sample_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate_pct": round(self.win_rate_pct, 2) if self.win_rate_pct is not None else None,
            "avg_return_pct": round(self.avg_return_pct, 2) if self.avg_return_pct is not None else None,
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor is not None else None,
            "max_drawdown_pct": round(self.max_drawdown_pct, 2) if self.max_drawdown_pct is not None else None,
            "avg_hold_days": round(self.avg_hold_days, 1) if self.avg_hold_days is not None else None,
            "is_underperforming": self.is_underperforming(),
        }


@dataclass
class _AttributionCache:
    metrics: Dict[str, StrategyMetrics] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)
    computed_at: float = 0.0
    lookback_days: int = REWEIGHT_LOOKBACK_DAYS
    lock: threading.Lock = field(default_factory=threading.Lock)


_cache = _AttributionCache()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_recent_picks(db: Any, lookback_days: int) -> List[Tuple[datetime, Dict[str, Any]]]:
    """Return [(created_at, pick_dict), ...] for picker runs in the last N days.

    Each pick_dict carries the fields written by StockPick.to_dict(), including
    `strategies` (multi-strategy union) and `ideal_buy/stop_loss/...`.
    """
    out: List[Tuple[datetime, Dict[str, Any]]] = []
    if db is None:
        return out
    try:
        # Use limit large enough to cover the window; picker_history grows slowly.
        records, _total = db.get_picker_history_list(limit=200, offset=0)
        cutoff = datetime.now() - timedelta(days=lookback_days)
        for rec in records or []:
            created = rec.get("created_at")
            if not created:
                continue
            try:
                ts = datetime.fromisoformat(created) if isinstance(created, str) else created
            except Exception:
                continue
            if ts < cutoff:
                continue
            # Pull full detail to access picks_json.
            detail = db.get_picker_history_detail(rec["id"])
            if not detail:
                continue
            picks = detail.get("picks") or []
            for p in picks:
                if isinstance(p, dict):
                    out.append((ts, p))
        logger.debug("[Attribution] Loaded %d picks within %d days", len(out), lookback_days)
    except Exception as exc:
        logger.warning("[Attribution] load_recent_picks failed: %s", exc)
    return out


def _evaluate_pick_return(
    *, data_manager: Any, pick: Dict[str, Any], pick_date: datetime,
    hold_days: int = 10,
) -> Optional[Dict[str, Any]]:
    """Simulate forward return for one pick using unified trade_levels rules.

    Returns dict with `return_pct`, `hold_days`, `exit_reason`, or None when
    insufficient data.
    """
    code = pick.get("code")
    entry_price = pick.get("ideal_buy") or pick.get("price")
    if not code or not entry_price:
        return None

    strategies = pick.get("strategies") or []
    strategy_id = strategies[0] if strategies else "buy_pullback"

    try:
        from src.services.trade_levels import simulate_forward_trade

        # Fetch forward bars from the entry date.
        start_iso = pick_date.strftime("%Y-%m-%d")
        end_iso = (pick_date + timedelta(days=hold_days * 2)).strftime("%Y-%m-%d")
        df, _ = data_manager.get_daily_data(code, start_date=start_iso, end_date=end_iso, days=hold_days * 3)
        if df is None or df.empty:
            return None

        # Normalise column names.
        col_close = next((c for c in ("close", "收盘") if c in df.columns), None)
        if col_close is None:
            return None
        col_high = next((c for c in ("high", "最高") if c in df.columns), col_close)
        col_low = next((c for c in ("low", "最低") if c in df.columns), col_close)
        col_pct = next((c for c in ("pct_chg", "涨跌幅") if c in df.columns), None)
        date_col = next((c for c in ("date", "日期") if c in df.columns), df.columns[0])

        df = df.sort_values(date_col).reset_index(drop=True)
        # Filter to >= pick_date and limit to hold_days bars.
        try:
            df_dt = df.copy()
            df_dt[date_col] = df_dt[date_col].astype(str).str[:10]
            df_dt = df_dt[df_dt[date_col] >= pick_date.strftime("%Y-%m-%d")].head(hold_days)
        except Exception:
            df_dt = df.head(hold_days)

        if df_dt.empty:
            return None

        # Compute MA10/MA20/ATR if absent (best-effort).
        if "ma10" not in df_dt.columns:
            df_dt = df_dt.copy()
            df_dt["ma10"] = df_dt[col_close].rolling(10, min_periods=1).mean()
        if "ma20" not in df_dt.columns:
            df_dt["ma20"] = df_dt[col_close].rolling(20, min_periods=1).mean()
        if "atr" not in df_dt.columns:
            try:
                tr = (df_dt[col_high] - df_dt[col_low]).abs()
                df_dt["atr"] = tr.rolling(14, min_periods=1).mean()
            except Exception:
                df_dt["atr"] = 0.0

        bars = []
        for _, r in df_dt.iterrows():
            bars.append({
                "close": float(r[col_close]),
                "high": float(r[col_high]) if col_high else float(r[col_close]),
                "low": float(r[col_low]) if col_low else float(r[col_close]),
                "ma10": float(r.get("ma10") or 0.0),
                "ma20": float(r.get("ma20") or 0.0),
                "atr": float(r.get("atr") or 0.0),
                "pct_chg": float(r[col_pct]) if col_pct and r.get(col_pct) is not None else None,
            })
        if not bars:
            return None

        is_kc_cy = str(code).startswith("688") or str(code).startswith("30")
        sim = simulate_forward_trade(
            strategy_id=strategy_id,
            entry_price=float(entry_price),
            market_cap_yi=0.0,
            bars=bars,
            apply_slippage=True,
            apply_limit_up_filter=False,  # Re-evaluating historical pick, not a new entry
            is_kc_cy=is_kc_cy,
        )
        if sim.get("skipped"):
            return None
        return {
            "return_pct": sim["return_pct"],
            "hold_days": sim["hold_days"],
            "exit_reason": sim["exit_reason"],
            "strategies": strategies,
            "primary_strategy": strategy_id,
        }
    except Exception as exc:
        logger.debug("[Attribution] evaluate_pick_return failed for %s: %s", code, exc)
        return None


def _aggregate(per_strategy_returns: Dict[str, List[Dict[str, Any]]]) -> Dict[str, StrategyMetrics]:
    """Aggregate per-strategy return arrays into StrategyMetrics."""
    out: Dict[str, StrategyMetrics] = {}
    for sid, items in per_strategy_returns.items():
        if not items:
            out[sid] = StrategyMetrics(strategy_id=sid)
            continue
        rets = [float(it["return_pct"]) for it in items if it.get("return_pct") is not None]
        holds = [float(it["hold_days"]) for it in items if it.get("hold_days") is not None]
        if not rets:
            out[sid] = StrategyMetrics(strategy_id=sid, sample_count=len(items))
            continue
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]
        sum_wins = sum(wins)
        sum_losses_abs = sum(abs(r) for r in losses)
        pf = (sum_wins / sum_losses_abs) if sum_losses_abs > 0 else (float("inf") if sum_wins > 0 else 0.0)
        out[sid] = StrategyMetrics(
            strategy_id=sid,
            sample_count=len(rets),
            win_count=len(wins),
            loss_count=len(losses),
            win_rate_pct=(len(wins) / len(rets) * 100.0),
            avg_return_pct=(sum(rets) / len(rets)),
            profit_factor=pf if pf != float("inf") else 99.0,
            max_drawdown_pct=min(rets),
            avg_hold_days=(sum(holds) / len(holds)) if holds else None,
        )
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_strategy_metrics(
    *, db: Any, data_manager: Any, lookback_days: int = REWEIGHT_LOOKBACK_DAYS,
    hold_days: int = 10, force_refresh: bool = False,
) -> Dict[str, StrategyMetrics]:
    """Compute metrics per strategy using cached or fresh forward simulations.

    Returns: {strategy_id: StrategyMetrics}.
    """
    now = time.time()
    if (
        not force_refresh
        and _cache.metrics
        and (now - _cache.computed_at) < ATTRIBUTION_TTL_SECONDS
        and _cache.lookback_days == lookback_days
    ):
        return dict(_cache.metrics)

    with _cache.lock:
        if (
            not force_refresh
            and _cache.metrics
            and (time.time() - _cache.computed_at) < ATTRIBUTION_TTL_SECONDS
            and _cache.lookback_days == lookback_days
        ):
            return dict(_cache.metrics)

        picks = _load_recent_picks(db, lookback_days)
        per_strategy: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for pick_date, pick in picks:
            ev = _evaluate_pick_return(
                data_manager=data_manager, pick=pick, pick_date=pick_date,
                hold_days=hold_days,
            )
            if ev is None:
                continue
            # Attribute to ALL strategies that flagged this pick (resonance fairness).
            strategies = ev.get("strategies") or [ev["primary_strategy"]]
            for sid in strategies:
                per_strategy[sid].append(ev)

        metrics = _aggregate(per_strategy)
        _cache.metrics = metrics
        _cache.lookback_days = lookback_days
        _cache.computed_at = time.time()

        # Pre-compute reweight weights.
        _cache.weights = {
            sid: (REWEIGHT_FACTOR_BAD if m.is_underperforming() else 1.0)
            for sid, m in metrics.items()
        }
        logger.info(
            "[Attribution] Computed metrics over %d days (%d strategies). Reweighted: %s",
            lookback_days, len(metrics),
            [s for s, w in _cache.weights.items() if w < 1.0] or "none",
        )
        return dict(metrics)


def get_strategy_weights(
    *, db: Any = None, data_manager: Any = None,
) -> Dict[str, float]:
    """Return current reweight multipliers per strategy.

    Used by picker merge stage when STRATEGY_AUTO_REWEIGHT=true. Returns empty
    dict if attribution data is unavailable (caller treats as 1.0 weights).
    """
    now = time.time()
    if _cache.weights and (now - _cache.computed_at) < ATTRIBUTION_TTL_SECONDS:
        return dict(_cache.weights)
    if db is None or data_manager is None:
        return {}
    try:
        compute_strategy_metrics(db=db, data_manager=data_manager)
    except Exception as exc:
        logger.warning("[Attribution] get_strategy_weights failed: %s", exc)
        return {}
    return dict(_cache.weights)


def format_weekly_report(metrics: Dict[str, StrategyMetrics]) -> str:
    """Format a Chinese weekly performance report for notifications."""
    if not metrics:
        return "📊 策略表现周报：暂无足够样本数据"

    lines = ["# 📊 策略表现周报（近 4 周）", ""]
    lines.append("| 策略 | 样本 | 胜率 | 平均收益 | 盈亏比 | 最差单笔 | 状态 |")
    lines.append("|------|------|------|---------|--------|---------|------|")

    sorted_items = sorted(
        metrics.items(),
        key=lambda kv: (kv[1].win_rate_pct or 0, kv[1].profit_factor or 0),
        reverse=True,
    )
    for sid, m in sorted_items:
        if m.sample_count == 0:
            lines.append(f"| {sid} | 0 | - | - | - | - | 无样本 |")
            continue
        status = "🔴 失效" if m.is_underperforming() else "🟢 正常"
        wr = f"{m.win_rate_pct:.1f}%" if m.win_rate_pct is not None else "-"
        avg = f"{m.avg_return_pct:+.2f}%" if m.avg_return_pct is not None else "-"
        pf = f"{m.profit_factor:.2f}" if m.profit_factor is not None else "-"
        dd = f"{m.max_drawdown_pct:+.2f}%" if m.max_drawdown_pct is not None else "-"
        lines.append(f"| {sid} | {m.sample_count} | {wr} | {avg} | {pf} | {dd} | {status} |")

    underperformers = [sid for sid, m in metrics.items() if m.is_underperforming()]
    if underperformers:
        lines.append("")
        lines.append(
            f"⚠️ **失效告警**：以下策略将自动降权 ×{REWEIGHT_FACTOR_BAD:.1f}："
        )
        for sid in underperformers:
            lines.append(f"- {sid}")

    return "\n".join(lines)


def reset_cache() -> None:
    """Reset module-level attribution cache (for tests / forced refresh)."""
    _cache.metrics.clear()
    _cache.weights.clear()
    _cache.computed_at = 0.0
