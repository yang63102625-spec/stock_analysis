# -*- coding: utf-8 -*-
"""
Unified Trade Levels Engine
============================

Single source of truth for entry/stop/target levels across:
- Stock picker (quantitative screening output)
- AI analyzer (decision dashboard battle_plan)
- Backtest engines (forward return simulation)

Design principles:
1. Numerical layer is owned by code, not LLM. LLM only explains, never invents
   stop/take-profit numbers.
2. Strategy-aware: each strategy (buy_pullback / breakout / bottom_reversal /
   eod_buyback) has its own level computation logic.
3. ATR-based trailing stop replaces fixed-percentage take-profit ceilings to
   let winners run while protecting profits.
4. Risk/Reward (R/R) is always computed; callers can hard-filter R/R < 1.8.

Public API:
- compute_trade_levels(...)        -> TradeLevels
- evaluate_trailing_exit(...)      -> (should_exit: bool, reason: str)
- compute_atr(...)                 -> float (14-day ATR helper)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Strategy IDs (mirrored from picker_strategies for cross-import safety)
BUY_PULLBACK = "buy_pullback"
BREAKOUT = "breakout"
BOTTOM_REVERSAL = "bottom_reversal"
EOD_BUYBACK = "eod_buyback"

# Risk/Reward floor: candidates below this should be filtered by callers.
# Tuned to 2.0 (was 1.8): A-share round-trip cost (slippage + tax + commission)
# eats ~0.5% so net R/R floor is ~1.7; 2.0 net ≥ 1.7 keeps positive expectancy
# at win rates >= 45%.
RR_MIN = 2.0

# Slippage assumed by backtest (one-way, percent of price).
DEFAULT_SLIPPAGE_PCT = 0.3

# Limit-up percentage thresholds (used by backtest entry filter).
LIMIT_UP_MAIN = 9.8
LIMIT_UP_KCCY = 19.8


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class TradeLevels:
    """Computed trade levels for a single (stock, strategy, snapshot)."""

    ideal_buy: float = 0.0
    secondary_buy: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2_rule: str = ""
    expected_target: float = 0.0   # Expected average exit (used for R/R), accounts for trailing
    position_pct: float = 0.0      # 0.0 ~ 0.25 (0 = no position recommended)
    risk_reward: float = 0.0       # (expected_target - ideal_buy) / (ideal_buy - stop_loss)
    stage_rules: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def passes_rr_filter(self) -> bool:
        """True iff R/R >= RR_MIN (caller's hard filter)."""
        return self.risk_reward >= RR_MIN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ideal_buy": round(self.ideal_buy, 3),
            "secondary_buy": round(self.secondary_buy, 3),
            "stop_loss": round(self.stop_loss, 3),
            "take_profit_1": round(self.take_profit_1, 3),
            "take_profit_2_rule": self.take_profit_2_rule,
            "expected_target": round(self.expected_target, 3),
            "position_pct": round(self.position_pct, 3),
            "risk_reward": round(self.risk_reward, 2),
            "stage_rules": self.stage_rules,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------


def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Compute simple-mean ATR over the last `period` bars.

    Returns 0.0 when input is too short or contains invalid data.
    Prefer reusing the ATR_20 column from data_provider when available; this
    helper is a fallback for callers that only have raw OHLC arrays.
    """
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return 0.0
    trs: List[float] = []
    for i in range(n - period, n):
        if i == 0:
            tr = highs[i] - lows[i]
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        if not math.isnan(tr):
            trs.append(tr)
    if not trs:
        return 0.0
    return sum(trs) / len(trs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_pos(*values: Optional[float]) -> bool:
    """All inputs are positive finite numbers."""
    for v in values:
        if v is None or not isinstance(v, (int, float)):
            return False
        if math.isnan(v) or v <= 0:
            return False
    return True


def _market_cap_band(market_cap_yi: float) -> str:
    """Return 'small' (<50亿), 'mid' (50-300亿), 'large' (>300亿)."""
    if market_cap_yi <= 0:
        return "mid"
    if market_cap_yi < 50:
        return "small"
    if market_cap_yi <= 300:
        return "mid"
    return "large"


def _base_position_pct(market_cap_yi: float) -> float:
    """Base position by market cap; refined later by R/R.

    Tightened from (6/12/18) to (5/12/15) to cap single-name blow-up risk —
    A-share idiosyncratic events (业绩雷/立案/质押爆仓) make 18% large-cap
    bets too concentrated even before R/R boost.
    """
    band = _market_cap_band(market_cap_yi)
    if band == "small":
        return 0.05   # 5% baseline (was 6%): small caps are illiquid + ATR-heavy
    if band == "mid":
        return 0.12   # 12% baseline (sweet spot)
    return 0.15       # 15% baseline (was 18%): cap concentration risk


def _stop_loss_pct_for_band(market_cap_yi: float) -> float:
    """Differentiated absolute stop-loss percent by market cap (positive value)."""
    band = _market_cap_band(market_cap_yi)
    if band == "small":
        return 0.06   # -6% (was -5%): small caps need wider stops vs intraday noise
    if band == "mid":
        return 0.06   # -6%
    return 0.07       # -7%


def _adjust_position_by_rr(base_pct: float, rr: float) -> float:
    """Refine position by R/R: high R/R earns boost, but with tighter cap.

    Tuned: boost factor 1.30 (was 1.20), cap 22% (was 25%) — separates "great"
    signals more from "decent" ones, while keeping absolute single-name cap safer.
    """
    if rr <= 0:
        return base_pct
    if rr >= 3.0:
        return min(base_pct * 1.30, 0.22)
    if rr < RR_MIN:
        return 0.0   # Caller should hard-filter; safety net here.
    return base_pct


# ---------------------------------------------------------------------------
# Strategy config table (data, not code) — eliminates ~150 lines of duplication
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StrategyConfig:
    """Per-strategy configuration. All multipliers are applied to ideal_buy."""

    tp1_mult: float           # take_profit_1 = ideal * tp1_mult
    expected_mult: float       # expected_target = ideal * expected_mult (used for R/R)
    pos_mult: float = 1.0      # position multiplier on top of market-cap baseline
    stop_pct_extra: float = 0.0  # additional stop-loss percent on top of band default
    abs_stop_cap_pct: Optional[float] = None  # if set, hard cap stop loss at this drop
    tp2_rule: str = "赚到 +15% 后启用动态保护——股价跌破 10 日均线，或从最高点回撤 2.5 倍日波幅时清仓"
    stage_rules: Dict[str, str] = field(default_factory=dict, hash=False, compare=False)


# Empirical expected-target multipliers account for staged trim + trailing tail
# distribution conditional on success. Tuned from historical picker_backtest.
_STRATEGY_CONFIGS: Dict[str, _StrategyConfig] = {
    BUY_PULLBACK: _StrategyConfig(
        tp1_mult=1.05, expected_mult=1.12,
        stage_rules={
            "stage_6pct": "减仓 1/3，止损上移至成本",
            "stage_12pct": "再减 1/3，止损上移至 +6%",
            "stage_15pct": "剩余 1/3 启用动态保护：跌破 10 日均线或从最高点回撤 2.5 倍日波幅时清仓",
        },
    ),
    BREAKOUT: _StrategyConfig(
        # tp1 raised 1.06→1.08: breakout first leg averages +8-12%; trimming
        # at +6% truncates the fat-tail winners that justify the strategy.
        tp1_mult=1.08, expected_mult=1.13,
        stage_rules={
            "stage_6pct": "减仓 1/3，止损上移至成本",
            "stage_12pct": "再减 1/3，止损上移至 +6%",
            "stage_15pct": "剩余 1/3 启用动态保护：跌破 10 日均线或从最高点回撤 2.5 倍日波幅时清仓",
            "fail_breakout": "若 3 个交易日内回到突破位下方 → 全部止损",
        },
    ),
    BOTTOM_REVERSAL: _StrategyConfig(
        # Hard cap raised +15→+20: real reversals run +18-25% on main leg;
        # +15 single-shot exit caps fat-tail winners. New rule: +15 减半 / +20 全清.
        tp1_mult=1.08, expected_mult=1.14,
        pos_mult=0.6, stop_pct_extra=0.02,
        tp2_rule="浮盈 +15% 减半，+20% 全部止盈（让真反转走完主升段）",
        stage_rules={
            "stage_8pct": "减仓 1/3",
            "stage_15pct": "再减 1/2，止损上移至 +8%",
            "stage_20pct": "全部止盈（反转策略硬顶 +20%）",
            "no_progress_3d": "买入 3 日内未确认上涨 → 减半",
        },
    ),
    EOD_BUYBACK: _StrategyConfig(
        # expected_mult 1.025→1.018: aligns with realistic EOD buyback median
        # next-day return; previous value inflated R/R and over-sized position.
        tp1_mult=1.03, expected_mult=1.018,
        pos_mult=0.7, abs_stop_cap_pct=0.03,
        tp2_rule="次日尾盘前清仓（不持隔夜超过 1 日）",
        stage_rules={
            "next_day_open_+3pct": "次日早盘 +3% 减半",
            "next_day_close": "次日尾盘前必须清仓",
        },
    ),
}


def _resolve_entry_anchor(
    sid: str, current_price: float, ma5: float,
    prior_high: Optional[float], recent_low: Optional[float], day_low: Optional[float],
) -> Tuple[float, float, Optional[float]]:
    """Return (ideal_buy, secondary_buy, tech_stop_anchor).

    - ideal_buy:        primary entry price for R/R math.
    - secondary_buy:    pullback re-entry reference shown in UI.
    - tech_stop_anchor: technical stop reference (None = use abs_stop only).
    """
    if sid == BUY_PULLBACK:
        ideal = min(current_price, ma5 * 1.01) if _safe_pos(ma5) else current_price
        return ideal, current_price * 0.97, None  # MA20-based stop applied separately
    if sid == BREAKOUT:
        bk = prior_high if _safe_pos(prior_high) else current_price * 0.98
        return current_price, bk, bk * 0.97
    if sid == BOTTOM_REVERSAL:
        anchor = recent_low * 0.98 if _safe_pos(recent_low) else current_price * 0.94
        return current_price, current_price * 0.97, anchor
    if sid == EOD_BUYBACK:
        anchor = day_low * 0.98 if _safe_pos(day_low) else current_price * 0.97
        return current_price, current_price * 0.99, anchor
    # Fallback (unknown strategy → pullback semantics).
    ideal = min(current_price, ma5 * 1.01) if _safe_pos(ma5) else current_price
    return ideal, current_price * 0.97, None


# ---------------------------------------------------------------------------
# Public entry: compute_trade_levels
# ---------------------------------------------------------------------------


def compute_trade_levels(
    *,
    code: str = "",
    strategy_id: str,
    current_price: float,
    ma5: float = 0.0,
    ma10: float = 0.0,
    ma20: float = 0.0,
    atr: float = 0.0,
    market_cap_yi: float = 0.0,
    prior_high: Optional[float] = None,
    recent_low: Optional[float] = None,
    day_low: Optional[float] = None,
) -> TradeLevels:
    """Compute strategy-specific trade levels for a stock snapshot.

    Returns TradeLevels. Caller should check `passes_rr_filter` for hard filtering.
    Unknown strategy IDs fall back to buy_pullback semantics (safest default).
    """
    if not _safe_pos(current_price):
        logger.debug("[trade_levels] %s skipped: invalid current_price=%s", code, current_price)
        return TradeLevels(notes=["invalid_current_price"])

    sid = (strategy_id or "").strip().lower()
    cfg = _STRATEGY_CONFIGS.get(sid) or _STRATEGY_CONFIGS[BUY_PULLBACK]

    ideal, secondary, tech_stop_anchor = _resolve_entry_anchor(
        sid, current_price, ma5, prior_high, recent_low, day_low,
    )

    # Stop-loss: max(technical_anchor, absolute) so the higher floor wins.
    abs_stop_pct = _stop_loss_pct_for_band(market_cap_yi) + cfg.stop_pct_extra
    if cfg.abs_stop_cap_pct is not None:
        abs_stop_pct = min(abs_stop_pct, cfg.abs_stop_cap_pct)
    abs_stop = ideal * (1 - abs_stop_pct)

    if tech_stop_anchor is not None:
        stop = max(tech_stop_anchor, abs_stop)
    elif _safe_pos(ma20):
        # buy_pullback path: prefer MA20 - 0.5% as technical stop.
        stop = max(ma20 * 0.995, abs_stop)
    else:
        stop = abs_stop

    tp1 = ideal * cfg.tp1_mult
    expected = ideal * cfg.expected_mult

    risk = max(ideal - stop, 1e-6)
    rr = (expected - ideal) / risk

    base_pos = _base_position_pct(market_cap_yi) * cfg.pos_mult
    pos = _adjust_position_by_rr(base_pos, rr)

    return TradeLevels(
        ideal_buy=ideal, secondary_buy=secondary,
        stop_loss=stop, take_profit_1=tp1,
        take_profit_2_rule=cfg.tp2_rule, expected_target=expected,
        position_pct=pos, risk_reward=rr,
        stage_rules=cfg.stage_rules,
    )


# ---------------------------------------------------------------------------
# Trailing exit evaluation
# ---------------------------------------------------------------------------


def evaluate_trailing_exit(
    *,
    strategy_id: str,
    entry_price: float,
    current_price: float,
    current_high: float,
    ma10: float,
    ma20: float = 0.0,
    atr: float = 0.0,
    holding_days: int = 0,
    peak_price: Optional[float] = None,
) -> Tuple[bool, str]:
    """Evaluate whether a held position should exit now.

    Sequence of checks (early-return on first hit):
      1. Below initial absolute stop: hard exit.
      2. Bottom-reversal special rule: +15% hard take-profit.
      3. Stage-based stop tightening (浮盈 5% → 成本，10% → +5%).
      4. Trailing (浮盈 >20%): below MA10 OR retraced ATR×2.5 from peak.
      5. Time stop: 20 trading days no meaningful progress.

    Args:
        strategy_id:   Strategy that opened the position.
        entry_price:   Original entry price.
        current_price: Latest close.
        current_high:  Latest bar high (used for hit detection).
        ma10:          Current MA10 value.
        ma20:          Current MA20 value (optional).
        atr:           Current ATR (period determined by caller; 14 or 20 fine).
        holding_days:  Trading days held.
        peak_price:    Highest close since entry (caller tracks; defaults to current_price).

    Returns:
        (should_exit, reason). reason is a short Chinese tag for logging.
    """
    if not _safe_pos(entry_price, current_price):
        return False, "invalid_input"

    profit_pct = (current_price - entry_price) / entry_price * 100
    peak = peak_price if (peak_price and peak_price > entry_price) else current_price

    sid = (strategy_id or "").strip().lower()

    # Bottom reversal: hard +20% cap (was +15), no trailing past cap.
    if sid == BOTTOM_REVERSAL and profit_pct >= 20.0:
        return True, "bottom_reversal_hardcap_20pct"

    # EOD buyback: must close within next session.
    if sid == EOD_BUYBACK and holding_days >= 1:
        return True, "eod_buyback_next_day_close"

    # Trailing zone (>=15% profit, was 20%): A-share rallies often start ABC
    # consolidation around +18-22%; entering trailing at 15% locks in 3-5%
    # additional profit on average versus the 20% threshold.
    if profit_pct >= 15.0:
        if _safe_pos(ma10) and current_price < ma10:
            return True, "trailing_below_ma10"
        if _safe_pos(atr) and atr > 0:
            retrace = peak - current_price
            if retrace >= atr * 2.5:
                return True, "trailing_atr2.5_retrace"

    # Stage stop: profit 12-15% — break +6% floor (was 10-20% / +5%).
    # Wider stages reduce premature stop-outs from intraday noise.
    if 12.0 <= profit_pct < 15.0:
        floor = entry_price * 1.06
        if current_price < floor:
            return True, "stage12_break_+6pct_floor"

    # Stage stop: profit 6-12% — break cost (was 5-10%).
    if 6.0 <= profit_pct < 12.0:
        if current_price < entry_price:
            return True, "stage6_break_cost"

    # Time stop: 20 trading days without breaking +5%.
    if holding_days >= 20 and profit_pct < 5.0:
        return True, "time_stop_20d_no_progress"

    # MA20 break for non-reversal strategies (defensive trend-failure exit).
    if sid != BOTTOM_REVERSAL and _safe_pos(ma20) and current_price < ma20 * 0.97:
        return True, "broke_ma20"

    return False, ""


# ---------------------------------------------------------------------------
# Backtest helper: simulate forward trade with unified rules
# ---------------------------------------------------------------------------


def simulate_forward_trade(
    *,
    strategy_id: str,
    entry_price: float,
    market_cap_yi: float,
    bars: List[Dict[str, float]],
    apply_slippage: bool = True,
    apply_limit_up_filter: bool = True,
    is_kc_cy: bool = False,
) -> Dict[str, Any]:
    """Simulate a forward trade using unified trade_levels exit rules.

    Replaces hardcoded -8% / +15% in picker_backtest_service. Bars must be
    forward-only (after entry day), each having keys: close, high, low,
    optional ma10, ma20, atr, pct_chg.

    Returns dict with: exit_price, exit_reason, return_pct, hold_days,
    skipped (True if entry skipped due to limit-up filter).
    """
    if not _safe_pos(entry_price):
        return {"skipped": True, "skip_reason": "invalid_entry_price"}

    # Slippage on entry (assume buy at slightly higher price).
    effective_entry = entry_price * (1 + DEFAULT_SLIPPAGE_PCT / 100.0) if apply_slippage else entry_price

    # Limit-up filter: if entry day's pct_chg >= limit-up threshold, skip
    # (cannot realistically buy in at limit-up board). Caller is responsible
    # for placing entry-day bar at index 0 OR passing pct_chg via kwargs.
    if apply_limit_up_filter and bars:
        entry_pct = bars[0].get("pct_chg")
        if entry_pct is not None:
            limit_pct = LIMIT_UP_KCCY if is_kc_cy else LIMIT_UP_MAIN
            if entry_pct >= limit_pct:
                return {"skipped": True, "skip_reason": "limit_up_unfillable"}

    peak_price = effective_entry
    for i, bar in enumerate(bars):
        close = bar.get("close")
        high = bar.get("high", close)
        if close is None or close <= 0:
            continue
        if high and high > peak_price:
            peak_price = high

        should_exit, reason = evaluate_trailing_exit(
            strategy_id=strategy_id,
            entry_price=effective_entry,
            current_price=float(close),
            current_high=float(high) if high else float(close),
            ma10=float(bar.get("ma10") or 0.0),
            ma20=float(bar.get("ma20") or 0.0),
            atr=float(bar.get("atr") or 0.0),
            holding_days=i + 1,
            peak_price=peak_price,
        )
        if should_exit:
            exit_price = float(close) * (1 - DEFAULT_SLIPPAGE_PCT / 100.0) if apply_slippage else float(close)
            ret = (exit_price - effective_entry) / effective_entry * 100.0
            return {
                "skipped": False,
                "exit_price": exit_price,
                "exit_reason": reason,
                "return_pct": ret,
                "hold_days": i + 1,
            }

    # No exit triggered: settle at last bar close.
    if not bars:
        return {"skipped": True, "skip_reason": "no_bars"}
    last_close = bars[-1].get("close")
    if last_close is None or last_close <= 0:
        return {"skipped": True, "skip_reason": "invalid_exit_price"}
    exit_price = float(last_close) * (1 - DEFAULT_SLIPPAGE_PCT / 100.0) if apply_slippage else float(last_close)
    ret = (exit_price - effective_entry) / effective_entry * 100.0
    return {
        "skipped": False,
        "exit_price": exit_price,
        "exit_reason": "window_end",
        "return_pct": ret,
        "hold_days": len(bars),
    }
