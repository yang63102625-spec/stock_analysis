# -*- coding: utf-8 -*-
"""Real-time market condition filtering (Stage 1.5) for the stock picker pipeline."""

import logging
from typing import Dict, List, Optional

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed

from data_provider.base import is_kc_cy_stock
from src.services.picker.constants import (
    LIMIT_UP_PCT_KC_CY,
    LIMIT_UP_PCT_MAIN,
    ScreenedStock,
)
from src.services.picker.screener import StockScreener

logger = logging.getLogger(__name__)

_REALTIME_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="realtime")


def filter_by_realtime(
    candidates: List[ScreenedStock],
    data_manager,
    config,
) -> List[ScreenedStock]:
    """Filter candidates by real-time market conditions (limit-up, volume spike, price range, etc).

    Uses strategy-specific params to enforce daily_change_max and volume_ratio_min limits.
    Queries realtime data in PARALLEL to avoid timeouts on large candidate pools.
    """
    if not candidates:
        return candidates

    from src.services.picker_strategies import get_strategy_params

    is_kccy = is_kc_cy_stock

    # Pre-warm realtime caches
    try:
        from data_provider.tushare_fetcher import TushareFetcher
        if data_manager:
            for fetcher in getattr(data_manager, '_fetchers', []):
                if isinstance(fetcher, TushareFetcher) and fetcher.is_available():
                    fetcher._fetch_realtime_rt_k()
                    fetcher._fetch_realtime_list()
                    logger.info(
                        "[Screener] realtime caches (rt_k + realtime_list) warmed up "
                        "before parallel fetch (%d candidates)", len(candidates),
                    )
                    break
    except Exception:
        pass  # Non-critical

    # Parallel fetch of realtime quotes
    def _fetch_one_quote(code: str) -> tuple:
        """Fetch realtime quote for one stock. Returns (code, quote)."""
        try:
            if not data_manager:
                return (code, None)
            try:
                quote = data_manager.get_realtime_quote(code, force_refresh=True)
            except TypeError:
                quote = data_manager.get_realtime_quote(code)
            return (code, quote)
        except Exception as e:
            logger.debug(f"[RealTime] Failed to fetch {code}: {e}")
            return (code, None)

    realtime_quotes: Dict[str, Optional] = {}
    futures = {_REALTIME_EXECUTOR.submit(_fetch_one_quote, stock.code): stock.code for stock in candidates}
    try:
        for future in as_completed(futures, timeout=60):
            try:
                code, quote = future.result(timeout=10)
                realtime_quotes[code] = quote
            except FuturesTimeout:
                code = futures[future]
                logger.debug(f"[RealTime] Timeout fetching {code}")
                realtime_quotes[code] = None
            except Exception as e:
                code = futures[future]
                logger.debug(f"[RealTime] Error fetching {code}: {e}")
                realtime_quotes[code] = None
    except FuturesTimeout:
        timed_out = [c for f, c in futures.items() if not f.done()]
        for c in timed_out:
            realtime_quotes.setdefault(c, None)
        logger.warning(
            f"[RealTime] Global timeout (60s): {len(timed_out)} futures unfinished: {timed_out}"
        )
    finally:
        for fut in futures:
            if not fut.done():
                fut.cancel()

    # Helper: safe float conversion
    def _safe_float(val) -> Optional[float]:
        """Convert to float safely. Returns None for None/NaN/non-numeric."""
        if val is None:
            return None
        try:
            f = float(val)
            if f != f:  # NaN check
                return None
            return f
        except (TypeError, ValueError):
            return None

    # Now filter using fetched data
    filtered = []
    excluded_reasons: Dict[str, List[str]] = {}

    for stock in candidates:
        code = stock.code
        try:
            reasons = []

            # Use realtime data if available, otherwise fall back to daily data
            realtime_quote = realtime_quotes.get(code)
            change_pct = _safe_float(
                realtime_quote.change_pct
                if (realtime_quote and realtime_quote.change_pct is not None)
                else stock.change_pct
            )
            vol_ratio = _safe_float(stock.volume_ratio)  # default to daily data
            if realtime_quote and realtime_quote.volume_ratio is not None and realtime_quote.volume_ratio > 0:
                vol_ratio = _safe_float(realtime_quote.volume_ratio)
            elif realtime_quote and (realtime_quote.volume_ratio is None or realtime_quote.volume_ratio == 0):
                # rt_k does not provide volume_ratio; try computing from 5-day avg
                rt_vol = _safe_float(getattr(realtime_quote, 'volume', None))
                if rt_vol and rt_vol > 0 and data_manager:
                    try:
                        df_hist, _src = data_manager.get_daily_data(code, days=6)
                        if df_hist is not None and len(df_hist) >= 2:
                            hvc = StockScreener._first_col(df_hist, 'vol', 'volume', '成交量')
                            if hvc:
                                hist_vol = pd.to_numeric(
                                    df_hist[hvc], errors='coerce'
                                ).iloc[:-1]
                                avg_5d = hist_vol.mean()
                                if not pd.isna(avg_5d) and avg_5d > 0:
                                    vr = StockScreener._calc_volume_ratio(rt_vol, float(avg_5d))
                                    if vr > 0:
                                        vol_ratio = vr
                    except Exception:
                        pass  # keep stock.volume_ratio as fallback
                if vol_ratio is None or vol_ratio == 0:
                    logger.debug(
                        "[Picker] %s: realtime volume_ratio missing/zero, "
                        "using daily value %s", code, stock.volume_ratio,
                    )

            # Log when critical fields are None for debugging
            if change_pct is None or vol_ratio is None:
                logger.debug(
                    f"[RealTime] {code}: change_pct={change_pct}, vol_ratio={vol_ratio} "
                    f"(realtime={'yes' if realtime_quote else 'no'})"
                )

            # Rule 1: Exclude limit-up stocks
            if getattr(config, "picker_realtime_exclude_limit_up", True):
                limit_up_pct = LIMIT_UP_PCT_KC_CY if is_kccy(code) else LIMIT_UP_PCT_MAIN
                if change_pct is not None and change_pct >= limit_up_pct - 0.1:
                    reasons.append(f"涨停({change_pct:.1f}%)")

            # Rule 2: Exclude limit-down stocks
            if getattr(config, "picker_realtime_exclude_limit_down", True):
                limit_down_pct = -LIMIT_UP_PCT_KC_CY if is_kccy(code) else -LIMIT_UP_PCT_MAIN
                if change_pct is not None and change_pct <= limit_down_pct + 0.1:
                    reasons.append(f"跌停({change_pct:.1f}%)")

            # Rule 3: Apply STRATEGY-SPECIFIC limits
            turnover = _safe_float(stock.turnover_rate)
            market_cap = _safe_float(stock.market_cap)
            if realtime_quote:
                rt_turnover = _safe_float(getattr(realtime_quote, "turnover_rate", None))
                if rt_turnover is not None and rt_turnover > 0:
                    turnover = rt_turnover
                elif rt_turnover is not None and rt_turnover == 0:
                    logger.debug(
                        f"[Picker] {code}: realtime turnover_rate is 0, "
                        f"using daily value {stock.turnover_rate}"
                    )
                rt_mv = _safe_float(getattr(realtime_quote, "total_mv", None))
                if rt_mv is not None and rt_mv > 0:
                    market_cap = rt_mv / 1e8
                elif rt_mv is not None and rt_mv == 0:
                    logger.debug(
                        f"[Picker] {code}: realtime total_mv is 0, "
                        f"using daily value {stock.market_cap}"
                    )

            # Apply strategy-specific params
            if stock.strategies:
                strategy_failures = []
                for strategy_id in stock.strategies:
                    params = get_strategy_params(strategy_id)

                    if (
                        params.daily_change_min is not None
                        and change_pct is not None
                        and change_pct < params.daily_change_min
                    ):
                        strategy_failures.append(
                            f"涨幅不足({change_pct:.1f}%<{params.daily_change_min}%)"
                        )

                    if (
                        params.daily_change_max is not None
                        and change_pct is not None
                        and change_pct > params.daily_change_max
                    ):
                        strategy_failures.append(
                            f"涨幅超({change_pct:.1f}%>{params.daily_change_max}%)"
                        )

                    if (
                        params.volume_ratio_min is not None
                        and vol_ratio is not None
                        and vol_ratio < params.volume_ratio_min
                    ):
                        strategy_failures.append(
                            f"量比不足({vol_ratio:.1f}x<{params.volume_ratio_min}x)"
                        )

                if strategy_failures:
                    reasons.extend(strategy_failures)

            # Rule 4: Filter by today's change % range (environment override)
            daily_chg_min = getattr(config, "picker_realtime_daily_chg_min", None)
            daily_chg_max = getattr(config, "picker_realtime_daily_chg_max", None)
            if daily_chg_min is not None and change_pct is not None and change_pct < daily_chg_min:
                reasons.append(f"涨幅不足(要求>{daily_chg_min}%,当前{change_pct:.1f}%)")
            if daily_chg_max is not None and change_pct is not None and change_pct > daily_chg_max:
                reasons.append(f"涨幅过大(要求<{daily_chg_max}%,当前{change_pct:.1f}%)")

            # Rule 5: Exclude abnormal volume spike
            max_vol_ratio = getattr(config, "picker_realtime_max_volume_ratio", 0.0)
            if max_vol_ratio > 0 and vol_ratio is not None and vol_ratio > max_vol_ratio:
                reasons.append(f"异常放量(量比{vol_ratio:.1f}>{max_vol_ratio})")

            if reasons:
                excluded_reasons[code] = reasons
            else:
                # Update ScreenedStock fields with realtime values
                if realtime_quote:
                    if change_pct is not None:
                        stock.change_pct = change_pct
                    if vol_ratio is not None and vol_ratio > 0:
                        stock.volume_ratio = vol_ratio
                    if turnover is not None and turnover > 0:
                        stock.turnover_rate = turnover
                    if market_cap is not None and market_cap > 0:
                        stock.market_cap = market_cap
                    rt_price = _safe_float(getattr(realtime_quote, 'price', None))
                    if rt_price is not None and rt_price > 0:
                        stock.price = rt_price
                    rt_pe = _safe_float(getattr(realtime_quote, 'pe_ratio', None))
                    if rt_pe is not None:
                        stock.pe = rt_pe
                    rt_pb = _safe_float(getattr(realtime_quote, 'pb_ratio', None))
                    if rt_pb is not None:
                        stock.pb = rt_pb
                filtered.append(stock)

        except Exception as e:
            # Graceful degradation: keep the candidate on unexpected errors
            logger.warning(f"[RealTime] Realtime check failed for {code}: {e}")
            filtered.append(stock)

    if excluded_reasons:
        logger.info(f"[StockPicker] Real-time filtering excluded {len(excluded_reasons)} stocks:")
        for code, reasons in sorted(excluded_reasons.items())[:10]:
            logger.info(f"  {code}: {', '.join(reasons)}")
        if len(excluded_reasons) > 10:
            logger.info(f"  ... and {len(excluded_reasons) - 10} more")

    return filtered
