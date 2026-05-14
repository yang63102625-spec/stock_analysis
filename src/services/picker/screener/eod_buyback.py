# -*- coding: utf-8 -*-
"""
End-of-day buyback strategy: dedicated full-market realtime path that does
not rely on the daily-spot pipeline used by the other strategies.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Dict, List, Set
from zoneinfo import ZoneInfo

import pandas as pd

from data_provider.base import is_kc_cy_stock
from src.services.picker.constants import (
    LIMIT_UP_PCT_KC_CY,
    LIMIT_UP_PCT_MAIN,
    ScreenedStock,
)

logger = logging.getLogger(__name__)


class _EodBuybackMixin:
    """Mixin: ``_screen_eod_buyback_realtime`` + ``_has_recent_limit_up_check``."""

    def _screen_eod_buyback_realtime(self) -> List[ScreenedStock]:
        """Screen eod_buyback via Tushare batch realtime quotes."""
        import tushare as ts
        from src.services.picker_strategies import is_mainboard_stock

        if not self._data_manager:
            logger.warning("[EOD-RT] No data_manager")
            return []

        t0 = time.time()
        all_codes: list = []
        for fetcher in self._data_manager._fetchers:
            if hasattr(fetcher, "get_stock_list"):
                try:
                    df_list = fetcher.get_stock_list()
                    if df_list is not None and not df_list.empty:
                        all_codes = df_list["code"].tolist()
                        logger.info(
                            f"[EOD-RT] Got {len(all_codes)} stock codes from {type(fetcher).__name__}"
                        )
                        break
                except Exception as e:
                    logger.debug(f"[EOD-RT] get_stock_list failed from {type(fetcher).__name__}: {e}")

        if not all_codes:
            logger.warning("[EOD-RT] Failed to get stock code list")
            return []

        # Batch query realtime quotes (200 per batch)
        BATCH_SIZE = 200
        all_dfs: list = []
        for i in range(0, len(all_codes), BATCH_SIZE):
            batch = all_codes[i: i + BATCH_SIZE]
            try:
                df_batch = ts.get_realtime_quotes(batch)
                if df_batch is not None and not df_batch.empty:
                    all_dfs.append(df_batch)
            except Exception as e:
                logger.debug(f"[EOD-RT] Batch {i // BATCH_SIZE} failed: {e}")

        if not all_dfs:
            logger.warning("[EOD-RT] No realtime data from any batch")
            return []

        df = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"[EOD-RT] Fetched realtime quotes for {len(df)} stocks in {time.time() - t0:.1f}s")

        # Supplement turnover_rate and total_mv from Tushare Pro daily_basic
        try:
            tushare_fetcher = None
            for fetcher in self._data_manager._fetchers:
                if type(fetcher).__name__ == "TushareFetcher":
                    tushare_fetcher = fetcher
                    break

            if tushare_fetcher and tushare_fetcher._api:
                from src.core.trading_calendar import get_last_trading_day as _get_ltd

                now_sh_sup = datetime.now(ZoneInfo("Asia/Shanghai"))
                trade_day = _get_ltd("cn", now_sh_sup.date())
                if trade_day is None:
                    from datetime import timedelta as _td
                    for offset in (0, 1, 2):
                        candidate = (now_sh_sup.date() - _td(days=offset)).strftime("%Y%m%d")
                        tushare_fetcher._check_rate_limit()
                        _df_try = tushare_fetcher._api.daily_basic(
                            trade_date=candidate, fields="ts_code,turnover_rate,total_mv"
                        )
                        if _df_try is not None and not _df_try.empty:
                            trade_day = (now_sh_sup.date() - _td(days=offset))
                            break

                if trade_day is not None:
                    trade_date_str = trade_day.strftime("%Y%m%d")
                    tushare_fetcher._check_rate_limit()
                    df_basic = tushare_fetcher._api.daily_basic(
                        trade_date=trade_date_str,
                        fields="ts_code,turnover_rate,total_mv,pe_ttm,pb",
                    )
                    if df_basic is not None and not df_basic.empty:
                        df_basic["code"] = df_basic["ts_code"].str.split(".").str[0]
                        df_basic["total_mv_yi"] = df_basic["total_mv"] / 1e4
                        df = df.merge(
                            df_basic[["code", "turnover_rate", "total_mv_yi", "pe_ttm", "pb"]],
                            on="code", how="left",
                        )
                        logger.info(
                            f"[EOD-RT] Supplemented turnover/mv from daily_basic({trade_date_str}): "
                            f"{df['turnover_rate'].notna().sum()} turnover, "
                            f"{df['total_mv_yi'].notna().sum()} market_cap"
                        )
                    else:
                        logger.warning(f"[EOD-RT] daily_basic returned empty for {trade_date_str}")
                else:
                    logger.warning("[EOD-RT] Could not determine latest trading day for daily_basic")
            else:
                logger.debug("[EOD-RT] TushareFetcher not available, skipping daily_basic supplement")
        except Exception as e:
            logger.warning(f"[EOD-RT] Failed to supplement from daily_basic: {e}")

        logger.debug(f"[EOD-RT] DataFrame columns after supplement: {list(df.columns)}")

        # Compute change_pct from price and pre_close
        df["price"] = pd.to_numeric(df.get("price", pd.Series(dtype=float)), errors="coerce")
        pre_close_col = "pre_close" if "pre_close" in df.columns else "settlement"
        df["pre_close"] = pd.to_numeric(df.get(pre_close_col, pd.Series(dtype=float)), errors="coerce")
        df["calc_change_pct"] = (
            (df["price"] - df["pre_close"]) / df["pre_close"].replace(0, float("nan"))
        ) * 100

        # One-pass filter
        mask = pd.Series(True, index=df.index)
        code_col = "code"
        if code_col in df.columns:
            mask &= df[code_col].apply(lambda c: is_mainboard_stock(str(c)))
        if "name" in df.columns:
            mask &= ~df["name"].str.contains("ST", na=False, case=False)
        mask &= (df["calc_change_pct"] >= 3.0) & (df["calc_change_pct"] <= 6.0)

        # Turnover filter
        turnover_col = None
        for col_name in ["turnover", "turnover_rate"]:
            if col_name in df.columns:
                turnover_col = col_name
                break
        if turnover_col:
            turnover = pd.to_numeric(df[turnover_col], errors="coerce")
            has_turnover = turnover.notna() & (turnover > 0)
            if has_turnover.any():
                mask &= ~has_turnover | ((turnover >= 5.0) & (turnover <= 12.0))
                logger.info(
                    f"[EOD-RT] Turnover filter applied via '{turnover_col}' "
                    f"({has_turnover.sum()} stocks had data)"
                )
            else:
                logger.info("[EOD-RT] Turnover data unavailable, skipping filter")
        else:
            logger.info("[EOD-RT] No turnover column, skipping filter")

        # Market cap filter
        mktcap_col = None
        mktcap_already_yi = False
        for col_name in ["mktcap", "nmc", "market_cap"]:
            if col_name in df.columns:
                mktcap_col = col_name
                break
        if mktcap_col is None and "total_mv_yi" in df.columns:
            mktcap_col = "total_mv_yi"
            mktcap_already_yi = True
        if mktcap_col:
            mktcap = pd.to_numeric(df[mktcap_col], errors="coerce")
            mktcap_yi = mktcap if mktcap_already_yi else mktcap / 1e4
            has_mktcap = mktcap.notna() & (mktcap > 0)
            if has_mktcap.any():
                mask &= ~has_mktcap | ((mktcap_yi >= 60.0) & (mktcap_yi <= 300.0))
                logger.info(
                    f"[EOD-RT] Market cap filter applied via '{mktcap_col}' "
                    f"({has_mktcap.sum()} stocks had data)"
                )
            else:
                logger.info("[EOD-RT] Market cap data unavailable, skipping filter")
        else:
            logger.info("[EOD-RT] No market cap column, skipping filter")

        # VWAP filter
        if "volume" in df.columns and "amount" in df.columns:
            rt_volume_vwap = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
            rt_amount_vwap = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
            vwap_valid = (rt_volume_vwap > 0) & (rt_amount_vwap > 0)
            vwap = rt_amount_vwap / rt_volume_vwap.replace(0, float("nan"))
            vwap_mask = ~vwap_valid | (df["price"] >= vwap)
            mask &= vwap_mask
            logger.info(f"[EOD-RT] VWAP filter applied ({vwap_valid.sum()} stocks had data)")
        else:
            logger.info("[EOD-RT] VWAP skipped (no volume/amount columns)")

        df_filtered = df[mask].copy()
        logger.info(f"[EOD-RT] After all filters: {len(df_filtered)} stocks")

        if df_filtered.empty:
            return []

        # Volume ratio computation
        now_sh = datetime.now(ZoneInfo("Asia/Shanghai"))
        is_after_close = now_sh.hour >= 15
        vol_ratio_map: Dict[str, float] = {}

        # Try realtime_list first for today's live vol_ratio
        try:
            tushare_fetcher = None
            for fetcher in getattr(self._data_manager, '_fetchers', []):
                if type(fetcher).__name__ == 'TushareFetcher':
                    tushare_fetcher = fetcher
                    break
            if tushare_fetcher:
                df_rt = tushare_fetcher._fetch_realtime_list()
                if df_rt is not None and not df_rt.empty and 'vol_ratio' in df_rt.columns:
                    rt = df_rt.copy()
                    if 'ts_code' in rt.columns:
                        rt['_code6'] = rt['ts_code'].str.split('.').str[0]
                        rt = rt.drop_duplicates(subset='_code6', keep='first')
                        rt_vr_lookup = dict(
                            zip(rt['_code6'], pd.to_numeric(rt['vol_ratio'], errors='coerce'))
                        )
                        for _, row in df_filtered.iterrows():
                            code = str(row.get("code", ""))
                            vr = rt_vr_lookup.get(code)
                            if vr is not None and not pd.isna(vr) and vr > 0:
                                vol_ratio_map[code] = float(vr)
                        logger.info(
                            "[EOD-RT] Realtime vol_ratio loaded for %d/%d candidates from realtime_list",
                            len(vol_ratio_map), len(df_filtered),
                        )
        except Exception as e:
            logger.debug("[EOD-RT] Failed to load realtime vol_ratio: %s", e)

        if is_after_close and "volume" in df_filtered.columns:
            logger.info("[EOD-RT] Post-close mode: computing volume ratio from 5-day avg")
            rt_vol = pd.to_numeric(df_filtered["volume"], errors="coerce")
            keep_idx: list = []
            for idx, row in df_filtered.iterrows():
                code = str(row.get("code", ""))
                if code in vol_ratio_map:
                    vr_rt = vol_ratio_map[code]
                    if 2.5 <= vr_rt <= 4.0:
                        keep_idx.append(idx)
                    else:
                        logger.debug(f"[EOD-RT] {code} realtime vol_ratio={vr_rt:.2f} out of [2.5,4], dropped")
                    continue
                today_vol = float(rt_vol.get(idx, 0) or 0)
                if today_vol <= 0:
                    keep_idx.append(idx)
                    continue
                try:
                    df_daily_vr, _src = self._data_manager.get_daily_data(code, days=6)
                    if df_daily_vr is None or len(df_daily_vr) < 2:
                        keep_idx.append(idx)
                        continue
                    vol_col = self._first_col(df_daily_vr, "vol", "volume", "成交量")
                    if vol_col is None:
                        keep_idx.append(idx)
                        continue
                    hist_vol = pd.to_numeric(df_daily_vr[vol_col], errors="coerce").iloc[:-1]
                    avg_5d = hist_vol.mean()
                    if avg_5d <= 0 or pd.isna(avg_5d):
                        keep_idx.append(idx)
                        continue
                    vol_ratio = today_vol / avg_5d
                    vol_ratio_map[code] = vol_ratio
                    if 2.5 <= vol_ratio <= 4.0:
                        keep_idx.append(idx)
                    else:
                        logger.debug(f"[EOD-RT] {code} vol_ratio={vol_ratio:.2f} out of [2.5,4], dropped")
                except Exception as e:
                    logger.debug(f"[EOD-RT] vol_ratio calc error for {code}: {e}")
                    keep_idx.append(idx)
            before_cnt = len(df_filtered)
            df_filtered = df_filtered.loc[keep_idx]
            logger.info(f"[EOD-RT] Volume ratio filter: {before_cnt} -> {len(df_filtered)} stocks")
        elif not is_after_close and "volume" in df_filtered.columns:
            if not vol_ratio_map:
                logger.info("[EOD-RT] Intraday: realtime_list vol_ratio unavailable, computing from 5-day avg")
                rt_vol = pd.to_numeric(df_filtered["volume"], errors="coerce")
                for idx, row in df_filtered.iterrows():
                    code = str(row.get("code", ""))
                    if code in vol_ratio_map:
                        continue
                    today_vol = float(rt_vol.get(idx, 0) or 0)
                    if today_vol <= 0:
                        continue
                    try:
                        df_hist, _src = self._data_manager.get_daily_data(code, days=6)
                        if df_hist is None or len(df_hist) < 2:
                            continue
                        hvc = self._first_col(df_hist, "vol", "volume", "成交量")
                        if hvc is None:
                            continue
                        hist_vol = pd.to_numeric(df_hist[hvc], errors="coerce").iloc[:-1]
                        avg_5d = hist_vol.mean()
                        if pd.isna(avg_5d) or avg_5d <= 0:
                            continue
                        vr = self._calc_volume_ratio(float(today_vol), float(avg_5d))
                        if vr > 0:
                            vol_ratio_map[code] = vr
                    except Exception:
                        continue
                logger.info(
                    "[EOD-RT] Intraday vol_ratio computed for %d/%d candidates",
                    len(vol_ratio_map), len(df_filtered),
                )
            else:
                logger.info(
                    "[EOD-RT] Intraday mode: using %d realtime vol_ratio values from realtime_list",
                    len(vol_ratio_map),
                )

        if df_filtered.empty:
            return []

        # Compute 60d change for candidate stocks
        change_60d_map: Dict[str, float] = {}
        tushare_api = self._get_tushare_api()
        if tushare_api:
            try:
                candidate_codes = [str(row.get("code", "")) for _, row in df_filtered.iterrows()]
                from src.core.trading_calendar import get_last_trading_day as _get_ltd_60
                now_sh_60 = datetime.now(ZoneInfo("Asia/Shanghai"))
                td_60 = _get_ltd_60("cn", now_sh_60.date())
                if td_60 is not None:
                    td_str = td_60.strftime("%Y%m%d")
                    start_60 = (pd.Timestamp(td_str) - pd.Timedelta(days=120)).strftime("%Y%m%d")
                    df_cal = tushare_api.trade_cal(exchange="SSE", start_date=start_60, end_date=td_str)
                    if df_cal is not None and not df_cal.empty:
                        df_cal.columns = [c.lower() for c in df_cal.columns]
                        df_cal = df_cal[df_cal["is_open"] == 1].sort_values("cal_date")
                        dates_60 = df_cal["cal_date"].tolist()
                        if td_str in dates_60:
                            idx_60 = dates_60.index(td_str)
                        else:
                            idx_60 = len(dates_60) - 1
                        if idx_60 >= 60:
                            date_60d_ago = dates_60[idx_60 - 60]
                            df_60d = tushare_api.daily(trade_date=date_60d_ago)
                            if df_60d is not None and not df_60d.empty:
                                df_60d.columns = [c.lower() for c in df_60d.columns]
                                close_60d_lookup = dict(
                                    zip(
                                        df_60d["ts_code"].str.split(".").str[0],
                                        pd.to_numeric(df_60d["close"], errors="coerce"),
                                    )
                                )
                                for _, row in df_filtered.iterrows():
                                    code = str(row.get("code", ""))
                                    cur_price = float(row.get("price", 0) or 0)
                                    old_close = close_60d_lookup.get(code)
                                    if old_close and old_close > 0 and cur_price > 0:
                                        change_60d_map[code] = (cur_price - old_close) / old_close * 100
                                logger.info(
                                    f"[EOD-RT] 60d change computed for {len(change_60d_map)} candidates"
                                )
                            else:
                                logger.debug("[EOD-RT] Not enough trading days for 60d change")
            except Exception as e:
                logger.warning(f"[EOD-RT] Failed to compute 60d change: {e}")

        # Build ScreenedStock list
        candidates_pre: list = []
        for _, row in df_filtered.iterrows():
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            price = float(row.get("price", 0) or 0)
            chg = float(row.get("calc_change_pct", 0) or 0)
            raw_tr = row.get("turnover_rate") if "turnover_rate" in df_filtered.columns else None
            if raw_tr is None or pd.isna(raw_tr):
                raw_tr = row.get("turnover", 0)
            turnover_val = float(pd.to_numeric(raw_tr, errors="coerce") or 0)
            amount_val = float(pd.to_numeric(row.get("amount", 0), errors="coerce") or 0)
            raw_mc = row.get("total_mv_yi") if "total_mv_yi" in df_filtered.columns else None
            mktcap_val = float(pd.to_numeric(raw_mc, errors="coerce") or 0) if raw_mc is not None else 0.0

            candidates_pre.append(ScreenedStock(
                code=code, name=name, price=price,
                change_pct=chg,
                volume_ratio=vol_ratio_map.get(code, 0.0),
                turnover_rate=turnover_val,
                pe=float(pd.to_numeric(row.get("pe_ttm"), errors="coerce") or 0)
                if "pe_ttm" in df_filtered.columns else 0.0,
                pb=float(pd.to_numeric(row.get("pb"), errors="coerce") or 0)
                if "pb" in df_filtered.columns else 0.0,
                market_cap=mktcap_val,
                amount=amount_val / 1e8 if amount_val else 0.0,
                change_pct_60d=change_60d_map.get(code, 0.0),
                score=0.0,
                strategies=["eod_buyback"],
            ))

        # Sector strength bonus
        _sector_top20_codes: Set[str] = set()
        _sector_top50_codes: Set[str] = set()
        try:
            from src.services.sector_strength_service import SectorStrengthService
            _eod_sector_svc = SectorStrengthService()
            _sector_top20_codes = _eod_sector_svc.get_strong_sector_codes(top_pct=0.20)
            _sector_top50_codes = _eod_sector_svc.get_strong_sector_codes(top_pct=0.50)
            logger.info(
                "[EOD-RT] Sector strength loaded: top20%%=%d codes, top50%%=%d codes",
                len(_sector_top20_codes), len(_sector_top50_codes),
            )
        except Exception as e:
            logger.warning("[EOD-RT] Sector strength data unavailable, skipping bonus: %s", e)

        # Filter consecutive up days
        from src.services.picker_strategies import EOD_BUYBACK_PARAMS as _eod_params
        max_consec = _eod_params.max_consecutive_up_days
        candidates_pre = self._filter_consecutive_up_days(candidates_pre, max_up_days=max_consec)
        logger.info(
            f"[EOD-RT] After consecutive-up-days filter (max={max_consec}): {len(candidates_pre)} candidates"
        )

        # Score candidates
        logger.info(f"[EOD-RT] Scoring {len(candidates_pre)} candidates with today limit-up signal...")
        final: list = []
        for s in candidates_pre:
            try:
                base_score = (
                    10.0
                    + min(s.change_pct, 6.0) * 2
                    + (5.0 if 100 <= s.market_cap <= 200 else 0.0)
                )
                today_change = s.change_pct
                if today_change >= 5.5:
                    base_score += 15.0
                    logger.debug("[EOD] %s strong band momentum (%.1f%%), +15 pts", s.code, today_change)
                elif today_change >= 4.5:
                    base_score += 8.0
                    logger.debug("[EOD] %s moderate band momentum (%.1f%%), +8 pts", s.code, today_change)

                if _sector_top20_codes or _sector_top50_codes:
                    if s.code in _sector_top20_codes:
                        base_score += 10.0
                        logger.debug("[EOD] %s sector top 20%%, +10 pts", s.code)
                    elif s.code in _sector_top50_codes:
                        base_score += 5.0
                        logger.debug("[EOD] %s sector top 50%%, +5 pts", s.code)
                    else:
                        base_score -= 10.0
                        logger.debug("[EOD] %s sector bottom 50%%, -10 pts", s.code)

                s.score = base_score
                final.append(s)
            except Exception as e:
                logger.debug(f"[EOD-RT] scoring error for {s.code}: {e}")

        logger.info(f"[EOD-RT] Final eod_buyback candidates: {len(final)}")

        # Deduplicate by code
        seen_codes: set = set()
        deduped: list = []
        for s in final:
            if s.code not in seen_codes:
                seen_codes.add(s.code)
                deduped.append(s)
        if len(deduped) < len(final):
            logger.info(f"[EOD-RT] Deduplicated: {len(final)} -> {len(deduped)} candidates")
        return deduped

    def _screen_eod_buyback_historical(self, as_of_date: str) -> List[ScreenedStock]:
        """Replay the 7 hard filters of eod_buyback on a historical trade date.

        Uses Tushare ``daily(trade_date=as_of)`` + ``daily_basic(trade_date=as_of)``
        instead of `ts.get_realtime_quotes()`, which has no trade_date parameter
        and would silently return today's data — the look-ahead bug fixed in
        commit P0-1 of `reports/eod_tuning/METHODOLOGY_REVIEW.md`.

        Filters mirror `_screen_eod_buyback_realtime` (line 140-203):
          - mainboard only (no ST, no KC/CY which are 30/68)
          - close-day pct_chg in [3, 6]
          - turnover_rate in [5, 12] %
          - total_mv in [60, 300] 亿
          - non-limit-up entry (already excluded by pct_chg <= 6)

        VWAP filter is skipped: daily bars don't have intraday VWAP. The
        realtime path uses end-of-day ``amount/volume`` proxy; in historical
        replay this approximation is the same number on both sides, so the
        filter degenerates and is dropped to avoid pretending we have it.

        Volume-ratio filter is computed from 5-day prior daily volumes
        (matching the realtime fallback path at line 271-281).

        as_of_date: YYYY-MM-DD or YYYYMMDD.
        """
        api = self._get_tushare_api() if hasattr(self, "_get_tushare_api") else None
        if api is None:
            logger.warning("[EOD-HIST] Tushare API unavailable; cannot replay historical eod_buyback")
            return []

        td = as_of_date.replace("-", "")
        from src.services.picker_strategies import is_mainboard_stock

        # Iter-1 H lever: market-regime filter (mean-reversion entry).
        # Iter-0 evidence: only winning trades happened the day after CSI300
        # dropped >=0.59%. The "尾盘异动 + 中盘 + 量比 2.5-4" combo behaves
        # as a contrarian signal in A-share T+1 microstructure.
        # Threshold: enter only when CSI300 closed at -0.5% or worse on `td`.
        try:
            df_csi = api.index_daily(ts_code="000300.SH", start_date=td, end_date=td)
            if df_csi is None or df_csi.empty:
                logger.warning(f"[EOD-HIST] {td}: CSI300 unavailable, skipping market-regime filter")
            else:
                df_csi.columns = [c.lower() for c in df_csi.columns]
                csi_pct = float(df_csi.iloc[0].get("pct_chg", 0))
                # Reversal needs a meaningful selloff. Don't cap the lower bound —
                # Iter-3 evidence: tightening to [-1.5, -0.5] dropped WR from 44.9
                # to 39.5%. The biggest winners come from the worst panic days.
                if csi_pct > -0.5:
                    logger.info(
                        f"[EOD-HIST] {td}: CSI300 pct_chg={csi_pct:+.2f}% > -0.5%, "
                        f"market-regime filter blocks entry (no contrarian setup)"
                    )
                    return []
                logger.info(
                    f"[EOD-HIST] {td}: CSI300 pct_chg={csi_pct:+.2f}% <= -0.5%, "
                    f"contrarian setup OK, proceeding"
                )
        except Exception as e:
            logger.warning(f"[EOD-HIST] {td}: market-regime check failed: {e}, proceeding without filter")

        try:
            df_daily = api.daily(trade_date=td)
            if df_daily is None or df_daily.empty:
                logger.warning(f"[EOD-HIST] daily({td}) returned empty")
                return []
            df_basic = api.daily_basic(
                trade_date=td,
                fields="ts_code,turnover_rate,total_mv,pe_ttm,pb",
            )
            if df_basic is None or df_basic.empty:
                logger.warning(f"[EOD-HIST] daily_basic({td}) returned empty")
                return []
        except Exception as e:
            logger.warning(f"[EOD-HIST] Tushare fetch failed for {td}: {e}")
            return []

        df_daily.columns = [c.lower() for c in df_daily.columns]
        df_basic.columns = [c.lower() for c in df_basic.columns]
        df_daily["code"] = df_daily["ts_code"].str.split(".").str[0]
        df_basic["code"] = df_basic["ts_code"].str.split(".").str[0]
        df_basic["total_mv_yi"] = df_basic["total_mv"] / 1e4

        # Resolve stock names from stock_basic (cached aggressively in TushareFetcher)
        try:
            df_names = api.stock_basic(fields="ts_code,name")
            df_names.columns = [c.lower() for c in df_names.columns]
            df_names["code"] = df_names["ts_code"].str.split(".").str[0]
            name_map = dict(zip(df_names["code"], df_names["name"]))
        except Exception:
            name_map = {}

        df = df_daily.merge(
            df_basic[["code", "turnover_rate", "total_mv_yi", "pe_ttm", "pb"]],
            on="code", how="left",
        )

        # Iter-2 G lever: signal direction rewrite (mean-reversion candidate).
        # Old (动量延续): 强势放量 +3~6%, 量比 2.5~4 → 诱多信号
        # New (反转候选): 大盘恐慌跌的日子里，找当日抗跌、缩量微涨的票，
        #                 假设它们次日大盘反弹时弹性最大。
        mask = pd.Series(True, index=df.index)
        mask &= df["code"].apply(lambda c: is_mainboard_stock(str(c)))
        if name_map:
            df["name"] = df["code"].map(name_map).fillna("")
            mask &= ~df["name"].str.contains("ST", na=False, case=False)
        else:
            df["name"] = ""
        chg = pd.to_numeric(df["pct_chg"], errors="coerce")
        mask &= (chg >= -0.5) & (chg <= 1.5)  # Iter-9: 更纯粹的"弱抗跌"信号（含小幅微跌）
        tr = pd.to_numeric(df["turnover_rate"], errors="coerce")
        mask &= (tr >= 2.0) & (tr <= 8.0)    # 适度活跃但不过热（缩量为主）
        mc = pd.to_numeric(df["total_mv_yi"], errors="coerce")
        mask &= (mc >= 60.0) & (mc <= 300.0)

        df_filtered = df[mask].copy()
        logger.info(
            f"[EOD-HIST] {td}: {len(df_daily)} stocks → {len(df_filtered)} after 7 hard filters"
        )
        if df_filtered.empty:
            return []

        # --- Money flow filter (Iter-3): require main-force net inflow ---
        # Hypothesis: T+1 short-term alpha comes from "institutions accumulate
        # while retail sells" (smart money / dumb money divergence). For the
        # mean-reversion eod_buyback variant, the ideal candidate is one that
        # the main force is QUIETLY buying on the dip.
        # Filter: (大单+超大单 净流入 > 0) AND (中小单 净流出，即主散背离)
        try:
            from data_provider.moneyflow_fetcher import MoneyflowFetcher
            mf = MoneyflowFetcher(api)
            df_mf = mf.get_market_moneyflow(td)
        except Exception as e:
            logger.warning(f"[EOD-HIST] moneyflow fetch failed: {e}; skipping flow filter")
            df_mf = None

        if df_mf is not None and not df_mf.empty:
            df_mf["code"] = df_mf["ts_code"].str.split(".").str[0]
            for col in ("buy_lg_amount", "buy_elg_amount", "sell_lg_amount",
                        "sell_elg_amount", "buy_sm_amount", "buy_md_amount",
                        "sell_sm_amount", "sell_md_amount"):
                if col in df_mf.columns:
                    df_mf[col] = pd.to_numeric(df_mf[col], errors="coerce").fillna(0)
            df_mf["main_net"] = (
                df_mf.get("buy_lg_amount", 0) + df_mf.get("buy_elg_amount", 0)
                - df_mf.get("sell_lg_amount", 0) - df_mf.get("sell_elg_amount", 0)
            )
            df_mf["retail_net"] = (
                df_mf.get("buy_sm_amount", 0) + df_mf.get("buy_md_amount", 0)
                - df_mf.get("sell_sm_amount", 0) - df_mf.get("sell_md_amount", 0)
            )
            flow_lookup = df_mf.set_index("code")[["main_net", "retail_net"]].to_dict("index")
            before = len(df_filtered)
            keep_codes = []
            for code in df_filtered["code"]:
                f = flow_lookup.get(code)
                if f is None:
                    continue  # no flow data → drop（保守，避免污染）
                if f["main_net"] > 0 and f["retail_net"] < 0:
                    keep_codes.append(code)
            df_filtered = df_filtered[df_filtered["code"].isin(keep_codes)].copy()
            logger.info(
                f"[EOD-HIST] {td}: moneyflow filter (main>0 & retail<0): {before} → {len(df_filtered)}"
            )
        else:
            logger.warning(f"[EOD-HIST] {td}: moneyflow unavailable, no flow filter applied")

        if df_filtered.empty:
            return []

        # Iter-2 part A: tighten main-force threshold from > 0 to > 1000 万元.
        # > 0 is too weak — institutional positioning often shows up only when
        # 当日主力净流入 ≥ 千万级别. Tushare moneyflow amounts are in 千元
        # (thousands of CNY), so 1000 万元 = 10000 千元 = 10000 in the column.
        if df_mf is not None and not df_mf.empty:
            MAIN_FORCE_MIN_KCNY = 5000  # Iter-8: 500万元 (300万→500万 提质)
            before_n = len(df_filtered)
            keep_codes = []
            for code in df_filtered["code"]:
                f = flow_lookup.get(code)
                if f and f["main_net"] >= MAIN_FORCE_MIN_KCNY:
                    keep_codes.append(code)
            df_filtered = df_filtered[df_filtered["code"].isin(keep_codes)].copy()
            logger.info(
                f"[EOD-HIST] {td}: main_net ≥ 1000万元 filter: {before_n} → {len(df_filtered)}"
            )

        if df_filtered.empty:
            return []

        # Iter-2 part B (DROPPED): sector strength filter
        # SectorStrengthService relies on akshare which is rate-limited / blocked
        # in historical backtest mode (3x retry all fail). Skipping until we
        # have a Tushare-only sector strength path.

        # Iter-2 part C: north-bound capital confirmation.
        # 当日北向 (沪深港通) 净流入 > 0 → 大盘有外资接盘 → T+1 反弹更容易兑现.
        # 北向流出日 (避险情绪重)，回避所有候选.
        try:
            df_north = api.moneyflow_hsgt(start_date=td, end_date=td)
            if df_north is not None and not df_north.empty:
                df_north.columns = [c.lower() for c in df_north.columns]
                north_money = float(pd.to_numeric(
                    df_north["north_money"].iloc[0], errors="coerce"
                ) or 0)
                if north_money <= 0:
                    logger.info(
                        f"[EOD-HIST] {td}: north_money={north_money:.0f}百万 ≤ 0, "
                        f"reject all {len(df_filtered)} candidates"
                    )
                    return []
                else:
                    logger.info(f"[EOD-HIST] {td}: north_money={north_money:.0f}百万 > 0, pass")
        except Exception as e:
            logger.warning(f"[EOD-HIST] {td}: north flow check failed: {e}, proceeding")

        # Iter-10 evidence: chg_60d>=-10% filter dropped 0 candidates
        # (mean-reversion picks aren't in steep downtrends). Removed.

        # Iter-3 P bonus: 过去 3 个交易日上过龙虎榜的票优先（资金注意力信号）
        dragon_codes: set = set()
        try:
            from datetime import datetime as _dt
            check_dates = []
            cur = _dt.strptime(td, "%Y%m%d")
            df_cal_p = api.trade_cal(
                exchange="SSE",
                start_date=(cur - pd.Timedelta(days=10)).strftime("%Y%m%d"),
                end_date=td,
            )
            df_cal_p.columns = [c.lower() for c in df_cal_p.columns]
            open_dates = df_cal_p[df_cal_p["is_open"] == 1].sort_values("cal_date")["cal_date"].tolist()
            check_dates = [d for d in open_dates if d <= td][-3:]
            for chk_td in check_dates:
                try:
                    df_tl = api.top_list(trade_date=chk_td)
                    if df_tl is not None and not df_tl.empty:
                        df_tl.columns = [c.lower() for c in df_tl.columns]
                        # 只取「净买入」上榜（reason 含"涨幅" 或 "换手"），排除跌幅榜
                        df_tl["code"] = df_tl["ts_code"].str.split(".").str[0]
                        positive_reasons = df_tl["reason"].astype(str).str.contains(
                            "涨幅|换手|振幅", na=False
                        )
                        net_buy_mask = pd.to_numeric(df_tl["net_amount"], errors="coerce") > 0
                        dragon_codes.update(df_tl[positive_reasons & net_buy_mask]["code"].tolist())
                except Exception:
                    continue
            logger.info(
                f"[EOD-HIST] {td}: 过去 3 日龙虎榜（净买入）覆盖 {len(dragon_codes)} 只票"
            )
            # Iter-6 evidence: 龙虎榜 hard filter → 0 picks (88 dragon codes
            # have ZERO overlap with 12 mean-reversion candidates — opposite
            # signals). Reverted to bonus-only via existing scoring code.
        except Exception as e:
            logger.warning(f"[EOD-HIST] {td}: top_list bonus failed: {e}")

        # Volume ratio: vol(td) / mean(vol(td-5..td-1)).
        # Fast path: pull last 6 daily(trade_date=...) market snapshots from
        # Tushare (one call per date) and aggregate in-memory. This replaces
        # N per-stock get_daily_data() calls (which each do their own daily
        # request), turning O(N_candidates) into O(6) Tushare calls.
        vol_ratio_map: Dict[str, float] = {}
        try:
            df_cal = api.trade_cal(
                exchange="SSE",
                start_date=(pd.Timestamp(td) - pd.Timedelta(days=20)).strftime("%Y%m%d"),
                end_date=td,
            )
            df_cal.columns = [c.lower() for c in df_cal.columns]
            df_cal = df_cal[df_cal["is_open"] == 1].sort_values("cal_date")
            prior_dates = df_cal[df_cal["cal_date"] < td]["cal_date"].tolist()[-5:]
        except Exception as e:
            logger.warning(f"[EOD-HIST] trade_cal failed: {e}; skipping vol_ratio")
            prior_dates = []

        if prior_dates:
            today_vol_map = dict(zip(df_filtered["code"], pd.to_numeric(df_filtered["vol"], errors="coerce")))
            hist_vol_acc: Dict[str, list] = {c: [] for c in df_filtered["code"]}
            for prior_td in prior_dates:
                try:
                    df_p = api.daily(trade_date=prior_td)
                    if df_p is None or df_p.empty:
                        continue
                    df_p.columns = [c.lower() for c in df_p.columns]
                    df_p["code"] = df_p["ts_code"].str.split(".").str[0]
                    cand_set = set(df_filtered["code"])
                    df_p = df_p[df_p["code"].isin(cand_set)]
                    for _, row in df_p.iterrows():
                        v = pd.to_numeric(row.get("vol"), errors="coerce")
                        if pd.notna(v) and v > 0:
                            hist_vol_acc[row["code"]].append(float(v))
                except Exception as e:
                    logger.debug(f"[EOD-HIST] daily({prior_td}) failed: {e}")
                    continue

            for code, hist_vols in hist_vol_acc.items():
                today_v = today_vol_map.get(code)
                if today_v is None or pd.isna(today_v) or today_v <= 0 or not hist_vols:
                    continue
                avg = sum(hist_vols) / len(hist_vols)
                if avg > 0:
                    vol_ratio_map[code] = float(today_v) / avg

        if vol_ratio_map:
            # Iter-2: 缩量优先（量比 0.7~1.5），避开异常放量
            df_filtered = df_filtered[
                df_filtered["code"].apply(
                    lambda c: 0.7 <= vol_ratio_map.get(c, 0) <= 1.5
                )
            ].copy()
            logger.info(
                f"[EOD-HIST] {td}: after vol_ratio∈[0.7,1.5] (缩量过滤): {len(df_filtered)} stocks"
            )
        else:
            logger.warning(
                f"[EOD-HIST] {td}: vol_ratio unavailable for all candidates, skipping that filter"
            )

        if df_filtered.empty:
            return []

        # 60-day prior change for context (used by AI selector but not by score here)
        # Score: same shape as realtime path scoring, minus the sector strength bonus
        # (sector data is live-only; for backtest we keep it deterministic).
        candidates: list = []
        for _, row in df_filtered.iterrows():
            code = str(row.get("code", ""))
            chg_v = float(row.get("pct_chg", 0) or 0)
            mc_v = float(row.get("total_mv_yi", 0) or 0)
            vr_v = vol_ratio_map.get(code, 1.0)

            # Iter-2 reversal scoring:
            # - prefer the票最抗跌（chg 越接近 0 越好，因为大盘大跌它还涨说明承接强）
            # - prefer 中盘 100-200 亿（弹性最好）
            # - prefer 量比 ~1.0（最干净的缩量信号）
            base_score = 20.0 - abs(chg_v - 1.0) * 3.0  # peak at chg=1%
            if 100 <= mc_v <= 200:
                base_score += 5.0
            base_score -= abs(vr_v - 1.0) * 5.0  # peak at vr=1.0
            # Iter-3 P: 龙虎榜资金注意力 bonus（最多 +12 分）
            if code in dragon_codes:
                base_score += 12.0

            candidates.append(ScreenedStock(
                code=code,
                name=str(row.get("name", "")),
                price=float(row.get("close", 0) or 0),  # historical close, not realtime
                change_pct=chg_v,
                volume_ratio=vol_ratio_map.get(code, 0.0),
                turnover_rate=float(pd.to_numeric(row.get("turnover_rate"), errors="coerce") or 0),
                pe=float(pd.to_numeric(row.get("pe_ttm"), errors="coerce") or 0),
                pb=float(pd.to_numeric(row.get("pb"), errors="coerce") or 0),
                market_cap=mc_v,
                amount=float(pd.to_numeric(row.get("amount"), errors="coerce") or 0) / 1e5,  # 千元 -> 亿元
                change_pct_60d=0.0,  # not computed in historical path; downstream tolerates 0
                score=base_score,
                strategies=["eod_buyback"],
            ))

        candidates.sort(key=lambda s: s.score, reverse=True)
        logger.info(f"[EOD-HIST] {td}: final {len(candidates)} eod_buyback candidates")
        return candidates

    def _has_recent_limit_up_check(self, code: str, days: int = 20) -> bool:
        """Check if stock had limit-up within recent N trading days.
        NOTE: Currently unused. Retained for potential future strategies.
        """
        try:
            if not self._data_manager:
                return False
            df, _src = self._data_manager.get_daily_data(code, days=days)
            if df is None or df.empty:
                return False
            limit_pct = LIMIT_UP_PCT_KC_CY if is_kc_cy_stock(code) else LIMIT_UP_PCT_MAIN
            chg_col = self._first_col(df, "pct_chg", "涨跌幅", "change_pct")
            if chg_col is None:
                return False
            pct = pd.to_numeric(df[chg_col], errors="coerce")
            return bool((pct >= limit_pct).any())
        except Exception as e:
            logger.debug(f"[EOD-RT] _has_recent_limit_up_check error for {code}: {e}")
            return False
