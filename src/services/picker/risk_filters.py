# -*- coding: utf-8 -*-
"""Risk filtering functions for the stock picker pipeline.

Contains: bias filter, limit-up streak, consecutive up days, healthy pullback,
B-wave risk detection, and leader candidate check.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from data_provider.base import is_kc_cy_stock
from src.services.picker.constants import (
    B_WAVE_LOOKBACK_DAYS,
    B_WAVE_LOW_DAYS_AGO_MAX,
    B_WAVE_LOW_DAYS_AGO_MIN,
    B_WAVE_MIN_DROOP_PCT,
    B_WAVE_RETRACE_HI,
    B_WAVE_RETRACE_LO,
    LEADER_CHANGE_60D_MIN,
    LEADER_CHANGE_PCT_HI,
    LEADER_CHANGE_PCT_LO,
    LEADER_TURNOVER_HI,
    LEADER_TURNOVER_LO,
    LEADER_VOLUME_RATIO_MIN,
    LIMIT_UP_DAYS_THRESHOLD,
    LIMIT_UP_PCT_KC_CY,
    LIMIT_UP_PCT_MAIN,
    PICKER_MAX_BIAS_PCT,
    PickerModeParams,
    ScreenedStock,
)

logger = logging.getLogger(__name__)


def is_leader_candidate(s: ScreenedStock) -> bool:
    """Check if stock qualifies for leader bias exemption."""
    return (
        s.change_pct_60d > LEADER_CHANGE_60D_MIN
        and LEADER_CHANGE_PCT_LO <= s.change_pct <= LEADER_CHANGE_PCT_HI
        and s.volume_ratio > LEADER_VOLUME_RATIO_MIN
        and LEADER_TURNOVER_LO <= s.turnover_rate <= LEADER_TURNOVER_HI
    )


def filter_by_bias(
    candidates: List[ScreenedStock],
    data_manager,
    as_of_date: Optional[str],
    fetch_daily_batch_fn,
    max_bias_pct: float = PICKER_MAX_BIAS_PCT,
    leader_bias_exempt_pct: float = 0.0,
) -> List[ScreenedStock]:
    """Filter out stocks with MA5 bias > max_bias_pct (strict entry strategy).
    When leader_bias_exempt_pct > 0, allow bias up to that value for leader candidates."""
    if not data_manager or not candidates:
        return candidates
    end_date = as_of_date
    requests = [(s.code, None, end_date, 10) for s in candidates]
    batch = fetch_daily_batch_fn(requests)
    filtered = []
    for s in candidates:
        df_daily, _ = batch.get((s.code, "", end_date or "", 10), (None, ""))
        if df_daily is None or len(df_daily) < 5:
            filtered.append(s)
            continue
        close_col = _first_col(df_daily, "close", "收盘")
        if close_col is None:
            filtered.append(s)
            continue
        date_col = _first_col(df_daily, "date", "日期") or df_daily.columns[0]
        df_daily = df_daily.sort_values(date_col).tail(5)
        ma5 = float(df_daily[close_col].mean())
        if ma5 <= 0:
            filtered.append(s)
            continue
        bias_pct = (s.price - ma5) / ma5 * 100
        if bias_pct <= max_bias_pct:
            filtered.append(s)
        elif (
            leader_bias_exempt_pct > 0
            and bias_pct <= leader_bias_exempt_pct
            and is_leader_candidate(s)
        ):
            filtered.append(s)
            logger.debug(f"[Screener] Leader exempt {s.code} bias={bias_pct:.1f}%")
        else:
            logger.debug(f"[Screener] Exclude {s.code} bias={bias_pct:.1f}% > {max_bias_pct}%")
    return filtered


def filter_limit_up_streak(
    candidates: List[ScreenedStock],
    data_manager,
    as_of_date: Optional[str],
    fetch_daily_batch_fn,
    days: int = 5,
    min_limit_up_days: int = LIMIT_UP_DAYS_THRESHOLD,
) -> List[ScreenedStock]:
    """Exclude stocks with 2+ limit-up days in last 5 days (streak/speculative risk).
    Uses board-specific threshold: main 10%, ChiNext/STAR 20%.
    """
    if not data_manager or not candidates:
        return candidates
    end_date = as_of_date
    requests = [(s.code, None, end_date, days + 5) for s in candidates]
    batch = fetch_daily_batch_fn(requests)
    filtered = []
    for s in candidates:
        df_daily, _ = batch.get((s.code, "", end_date or "", days + 5), (None, ""))
        if df_daily is None or len(df_daily) < days:
            filtered.append(s)
            continue
        pct_col = _first_col(df_daily, "pct_chg", "涨跌幅")
        if pct_col is None:
            filtered.append(s)
            continue
        pct_threshold = LIMIT_UP_PCT_KC_CY if is_kc_cy_stock(s.code) else LIMIT_UP_PCT_MAIN
        date_col = _first_col(df_daily, "date", "日期") or df_daily.columns[0]
        df_daily = df_daily.sort_values(date_col).tail(days)
        pct = pd.to_numeric(df_daily[pct_col], errors="coerce").fillna(0)
        limit_up_count = int((pct >= pct_threshold).sum())
        if limit_up_count >= min_limit_up_days:
            logger.debug(
                f"[Screener] Exclude {s.code} limit-up streak: {limit_up_count} days in last {days}"
            )
        else:
            filtered.append(s)
    return filtered


def filter_consecutive_up_days(
    candidates: List[ScreenedStock],
    data_manager,
    as_of_date: Optional[str],
    fetch_daily_batch_fn,
    picker_mode: str = "balanced",
    days: int = 5,
    max_up_days: Optional[int] = None,
) -> List[ScreenedStock]:
    """Exclude stocks with too many consecutive up days (avoid buying at streak end)."""
    if not data_manager or not candidates:
        return candidates

    if max_up_days is None:
        max_up_days = PickerModeParams.for_mode(picker_mode).max_consecutive_up_days
    end_date = as_of_date
    requests = [(s.code, None, end_date, days + 5) for s in candidates]
    batch = fetch_daily_batch_fn(requests)
    filtered = []
    for s in candidates:
        df_daily, _ = batch.get((s.code, "", end_date or "", days + 5), (None, ""))
        if df_daily is None or len(df_daily) < days:
            filtered.append(s)
            continue
        pct_col = _first_col(df_daily, "pct_chg", "涨跌幅")
        if pct_col is None:
            filtered.append(s)
            continue
        date_col = _first_col(df_daily, "date", "日期") or df_daily.columns[0]
        df_daily = df_daily.sort_values(date_col).tail(days)
        pct_series = pd.to_numeric(df_daily[pct_col], errors="coerce").fillna(0).values

        consecutive_up = 0
        for pct in reversed(pct_series):
            if pct > 0:
                consecutive_up += 1
            else:
                break

        if consecutive_up > max_up_days:
            logger.debug(
                f"[Screener] Exclude {s.code}: {consecutive_up} consecutive up days > max {max_up_days}"
            )
        else:
            filtered.append(s)
    return filtered


def filter_healthy_pullback(
    candidates: List[ScreenedStock],
    data_manager,
    as_of_date: Optional[str],
    fetch_daily_batch_fn,
    picker_mode: str = "balanced",
    lookback_days: int = 20,
    params: Optional[Any] = None,
    strategy_id: Optional[str] = None,
) -> List[ScreenedStock]:
    """Filter for healthy pullback confirmation to distinguish from trend reversal.

    Checks (strategy-specific when params provided):
    1. Volume shrink: volume_ratio < 1.0 on pullback day
    2. MA bullish alignment: MA5 > MA10 > MA20
    3. Retracement limit: pullback < X% of prior 10d rally
    4. Min distance from 20d high: must be >=X% below high
    5. Price above MA20: reject if below MA20
    6. Near MA10 support: price within X% above MA10
    """
    if not data_manager or not candidates:
        return candidates

    mode_params = params if params is not None else PickerModeParams.for_mode(picker_mode)
    end_date = as_of_date

    # Batch fetch daily data for all candidates
    requests = [(s.code, None, end_date, lookback_days + 5) for s in candidates]
    batch = fetch_daily_batch_fn(requests)

    filtered = []
    for s in candidates:
        df_daily, _ = batch.get((s.code, "", end_date or "", lookback_days + 5), (None, ""))
        if df_daily is None or len(df_daily) < 10:
            filtered.append(s)  # Keep if no data
            continue

        close_col = _first_col(df_daily, "close", "收盘", "最新价")
        high_col = _first_col(df_daily, "high", "最高")
        date_col = _first_col(df_daily, "date", "日期") or df_daily.columns[0]
        if close_col is None:
            filtered.append(s)
            continue

        df_daily = df_daily.sort_values(date_col).tail(lookback_days).reset_index(drop=True)
        close_series = pd.to_numeric(df_daily[close_col], errors="coerce").fillna(0)

        # Check 1: Volume shrink or mild expansion (1.0-1.3 acceptable for healthy pullback)
        VOLUME_SHRINK_LIMIT = 1.3  # Allow mild expansion as valid pullback signal
        if mode_params.require_volume_shrink and s.change_pct <= 0 and s.volume_ratio >= VOLUME_SHRINK_LIMIT:
            logger.debug(
                "[Screener] Exclude %s %s: volume_ratio %.2f >= %.1f on pullback day",
                s.code, s.name, s.volume_ratio, VOLUME_SHRINK_LIMIT,
            )
            continue

        # Check 2: MA bullish alignment with tolerance for convergence
        MA_TOLERANCE = 0.005  # 0.5% tolerance for MA convergence (accumulation signal)
        if mode_params.require_ma_bullish and len(close_series) >= 20:
            ma5 = float(close_series.tail(5).mean())
            ma10 = float(close_series.tail(10).mean())
            ma20 = float(close_series.tail(20).mean())
            if not (ma5 >= ma10 * (1 - MA_TOLERANCE) and ma10 >= ma20 * (1 - MA_TOLERANCE)):
                logger.debug(
                    "[Screener] Exclude %s %s: MA not bullish "
                    "(MA5=%.2f, MA10=%.2f, MA20=%.2f, gap=%.2f%%)",
                    s.code, s.name, ma5, ma10, ma20,
                    (ma5 - ma10) / ma10 * 100 if ma10 > 0 else 0,
                )
                continue

        # Check 3: Retracement limit
        if len(close_series) >= 10 and high_col:
            high_series = pd.to_numeric(df_daily[high_col], errors="coerce").fillna(0)
            low_col = _first_col(df_daily, "low", "最低")
            if low_col:
                low_series = pd.to_numeric(df_daily[low_col], errors="coerce").fillna(0)
            else:
                low_series = close_series  # Fallback to close if no low column
            # Prior 10d high and low
            recent_high = float(high_series.tail(10).max())
            recent_low = float(low_series.tail(10).min())
            rally = recent_high - recent_low
            if rally > 0.01 and recent_high > 0:  # Avoid near-zero division
                current_pullback = recent_high - s.price
                # Only check if actually pulled back (current_pullback > 0)
                if current_pullback > 0:
                    retracement = current_pullback / rally
                    if retracement > mode_params.max_retracement_pct:
                        logger.debug(
                            f"[Screener] Exclude {s.code}: retracement {retracement:.1%} "
                            f"> max {mode_params.max_retracement_pct:.1%}"
                        )
                        continue

        # Check 4: minimum distance from 20-day high
        min_pb = getattr(mode_params, 'min_pullback_from_high_pct', 0.0)
        if min_pb > 0 and high_col and len(close_series) >= 20:
            high_series_4 = pd.to_numeric(df_daily[high_col], errors="coerce").fillna(0)
            if len(high_series_4) >= 20:
                high_20d = float(high_series_4.tail(20).max())
                if high_20d > 0:
                    distance_from_high_pct = (high_20d - s.price) / high_20d * 100
                    if distance_from_high_pct < min_pb:
                        logger.debug(
                            "[Screener] Exclude %s %s: only %.1f%% below 20d high (%.2f), "
                            "need >= %.1f%% pullback",
                            s.code, s.name, distance_from_high_pct, high_20d, min_pb,
                        )
                        continue

        # Check 5: price must be above MA20 (below MA20 = entering downtrend)
        req_above_ma20 = getattr(mode_params, 'require_price_above_ma20', False)
        if req_above_ma20 and len(close_series) >= 20:
            ma20 = float(close_series.tail(20).mean())
            if ma20 > 0 and s.price < ma20:
                logger.debug(
                    "[Screener] Exclude %s %s: price %.2f below MA20 %.2f, "
                    "potential downtrend",
                    s.code, s.name, s.price, ma20,
                )
                continue

        # Check 6: price must be near MA10 support (not floating above)
        max_above_ma10 = getattr(mode_params, 'max_distance_above_ma10_pct', 0.0)
        if max_above_ma10 > 0 and len(close_series) >= 10:
            ma10 = float(close_series.tail(10).mean())
            if ma10 > 0:
                dist_above_ma10 = (s.price - ma10) / ma10 * 100
                if dist_above_ma10 > max_above_ma10:
                    logger.debug(
                        "[Screener] Exclude %s %s: %.1f%% above MA10 (%.2f), "
                        "not near support yet (max %.1f%%)",
                        s.code, s.name, dist_above_ma10, ma10, max_above_ma10,
                    )
                    continue

        filtered.append(s)

    return filtered


def filter_b_wave_risk(
    candidates: List[ScreenedStock],
    data_manager,
    as_of_date: Optional[str],
    fetch_daily_batch_fn,
    lookback_days: int = B_WAVE_LOOKBACK_DAYS,
) -> List[ScreenedStock]:
    """Exclude stocks likely in B-wave bounce (fake recovery before C-wave down).
    Pattern: A-wave drop >= 5%, then bounce 35-65% of the drop, low 2-14 days ago.
    """
    if not data_manager or not candidates:
        return candidates
    end_date = as_of_date
    requests = [(s.code, None, end_date, lookback_days + 5) for s in candidates]
    batch = fetch_daily_batch_fn(requests)
    filtered = []
    for s in candidates:
        df_daily, _ = batch.get((s.code, "", end_date or "", lookback_days + 5), (None, ""))
        if df_daily is None or len(df_daily) < lookback_days:
            filtered.append(s)
            continue
        close_col = _first_col(df_daily, "close", "收盘", "最新价")
        if close_col is None:
            filtered.append(s)
            continue
        date_col = _first_col(df_daily, "date", "日期") or df_daily.columns[0]
        df_daily = df_daily.sort_values(date_col).tail(lookback_days).reset_index(drop=True)
        ser = pd.to_numeric(df_daily[close_col], errors="coerce").fillna(0)
        if len(ser) < lookback_days:
            filtered.append(s)
            continue
        idx_max = int(ser.idxmax())
        idx_min = int(ser.idxmin())
        high_val = float(ser.iloc[idx_max])
        low_val = float(ser.iloc[idx_min])
        if high_val <= 0 or low_val <= 0:
            filtered.append(s)
            continue

        if idx_min <= idx_max:
            filtered.append(s)
            continue
        drop_pct = (high_val - low_val) / high_val * 100
        if drop_pct < B_WAVE_MIN_DROOP_PCT:
            filtered.append(s)
            continue

        current = s.price
        rebound_pct = (current - low_val) / low_val * 100 if low_val > 0 else 0
        retracement = rebound_pct / drop_pct if drop_pct > 0 else 0
        days_since_low = (len(ser) - 1) - idx_min

        if (
            B_WAVE_RETRACE_LO <= retracement <= B_WAVE_RETRACE_HI
            and B_WAVE_LOW_DAYS_AGO_MIN <= days_since_low <= B_WAVE_LOW_DAYS_AGO_MAX
        ):
            logger.debug(
                f"[Screener] Exclude {s.code} B-wave risk: drop={drop_pct:.1f}%, "
                f"retrace={retracement:.0%}, low {days_since_low}d ago"
            )
        else:
            filtered.append(s)
    return filtered


def _first_col(df: pd.DataFrame, *names: str):
    """Return first column name that exists in df, or None."""
    for n in names:
        if n in df.columns:
            return n
    return None
