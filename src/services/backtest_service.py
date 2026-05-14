# -*- coding: utf-8 -*-
"""Backtest orchestration service."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select

from src.config import get_config
from src.core.backtest_engine import (
    OVERALL_SENTINEL_CODE,
    AnalysisSnapshot,
    BacktestEngine,
    EvaluationConfig,
)
from src.repositories.backtest_repo import BacktestRepository
from src.repositories.stock_repo import StockRepository
from src.storage import AnalysisHistory, BacktestResult, BacktestSummary, DatabaseManager

from src.services._backtest_score_mixin import _ScoreEffectivenessMixin

logger = logging.getLogger(__name__)


class BacktestService(_ScoreEffectivenessMixin):
    """Service layer to run and query backtests."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()
        self.repo = BacktestRepository(self.db)
        self.stock_repo = StockRepository(self.db)

    def run_backtest(
        self,
        *,
        code: Optional[str] = None,
        force: bool = False,
        eval_window_days: Optional[int] = None,
        min_age_days: Optional[int] = None,
        limit: int = 200,
        strategies: Optional[List[str]] = None,  # deprecated, ignored
    ) -> Dict[str, Any]:
        """Run backtest over candidate analyses; return aggregate counters."""
        del strategies  # v3: strategy override removed; replay each AI plan as-is.
        eval_window_days, min_age_days, eval_config = self._resolve_run_config(
            eval_window_days, min_age_days,
        )

        candidates = self.repo.get_candidates(
            code=code, min_age_days=min_age_days, limit=int(limit),
            eval_window_days=eval_window_days, force=force,
        )
        self._log_run_start(candidates, code, force, eval_window_days, min_age_days, int(limit))

        processed = completed = insufficient = errors = 0
        touched_codes: set[str] = set()
        results_to_save: List[BacktestResult] = []

        for analysis in candidates:
            processed += 1
            touched_codes.add(analysis.code)
            self._log_progress(processed, len(candidates), analysis)

            row, kind = self._evaluate_one_candidate(analysis, eval_window_days, eval_config)
            results_to_save.append(row)
            if kind == "completed":
                completed += 1
            elif kind == "insufficient":
                insufficient += 1
            elif kind == "error":
                errors += 1
            # kind == "missing_signal" — tracked via eval_status only.

        saved = self.repo.save_results_batch(results_to_save, replace_existing=force) if results_to_save else 0
        if saved:
            self._recompute_summaries(touched_codes=sorted(touched_codes), eval_window_days=eval_window_days)

        logger.info(
            "[Backtest] run done: processed=%d saved=%d completed=%d insufficient=%d errors=%d",
            processed, saved, completed, insufficient, errors,
        )
        return {
            "processed": processed, "saved": saved, "completed": completed,
            "insufficient": insufficient, "errors": errors,
        }

    def _resolve_run_config(
        self, eval_window_days: Optional[int], min_age_days: Optional[int],
    ) -> tuple[int, int, EvaluationConfig]:
        config = get_config()
        ew = int(eval_window_days if eval_window_days is not None
                 else getattr(config, "backtest_eval_window_days", 10))
        ma = int(min_age_days if min_age_days is not None
                 else getattr(config, "backtest_min_age_days", 14))
        return ew, ma, EvaluationConfig(
            eval_window_days=ew,
            neutral_band_pct=float(getattr(config, "backtest_neutral_band_pct", 2.0)),
        )

    @staticmethod
    def _log_run_start(
        candidates: List[AnalysisHistory], code: Optional[str], force: bool,
        eval_window_days: int, min_age_days: int, limit: int,
    ) -> None:
        n = len(candidates)
        logger.info(
            "[Backtest] run start: candidates=%d code=%s force=%s eval_window_days=%d limit=%d",
            n, code or "*", force, eval_window_days, limit,
        )
        if n == 0 and code:
            logger.warning(
                "[Backtest] no candidates for code=%s — no analysis_history row aged "
                ">=%d days, or all already evaluated (use --backtest-force).",
                code, min_age_days,
            )

    @staticmethod
    def _log_progress(processed: int, total: int, analysis: AnalysisHistory) -> None:
        if processed == 1 or processed % 25 == 0 or processed == total:
            logger.info(
                "[Backtest] progress %d/%d (code=%s id=%s)",
                processed, total, analysis.code, getattr(analysis, "id", "?"),
            )

    # ── Per-candidate workflow ───────────────────────────────────────────

    def _evaluate_one_candidate(
        self,
        analysis: AnalysisHistory,
        eval_window_days: int,
        eval_config: EvaluationConfig,
    ) -> tuple[BacktestResult, str]:
        """Evaluate one analysis row.

        Returns (BacktestResult, kind) where kind ∈
        {completed, insufficient, error, missing_signal}.
        """
        try:
            analysis_date = self._resolve_analysis_date(analysis)
            if analysis_date is None:
                return self._stub_result(analysis, eval_window_days, "error", None), "error"

            start_daily = self._resolve_start_daily(analysis.code, analysis_date, eval_window_days)
            if start_daily is None or start_daily.close is None:
                return (
                    self._stub_result(analysis, eval_window_days, "insufficient_data", analysis_date),
                    "insufficient",
                )

            forward_bars = self._resolve_forward_bars(
                analysis.code, start_daily.date, eval_window_days,
            )

            evaluation = BacktestEngine.evaluate_single(
                analysis=self._build_snapshot(analysis),
                analysis_date=start_daily.date,
                start_price=float(start_daily.close),
                forward_bars=forward_bars,
                config=eval_config,
            )
            kind_map = {
                "completed": "completed",
                "insufficient_data": "insufficient",
                "missing_signal": "missing_signal",
            }
            kind = kind_map.get(evaluation.get("eval_status", ""), "error")
            return self._evaluation_to_result(evaluation, analysis, eval_window_days), kind

        except Exception as exc:
            logger.error("回测失败: %s#%s: %s", analysis.code, analysis.id, exc)
            return (
                self._stub_result(
                    analysis, eval_window_days, "error", self._resolve_analysis_date(analysis),
                ),
                "error",
            )

    def _resolve_start_daily(self, code: str, analysis_date: date, eval_window_days: int):
        """Get the analysis-day daily bar; lazily backfill from data sources if missing."""
        start_daily = self.stock_repo.get_start_daily(code=code, analysis_date=analysis_date)
        if start_daily is not None and start_daily.close is not None:
            return start_daily

        self._try_fill_daily_data(
            code=code, anchor_date=analysis_date,
            eval_window_days=eval_window_days, pull_history_before_anchor=True,
        )
        start_daily = self.stock_repo.get_start_daily(code=code, analysis_date=analysis_date)
        if start_daily is not None and start_daily.close is not None:
            return start_daily

        market_today = self._market_calendar_today(code)
        self._try_fill_daily_data(
            code=code, anchor_date=analysis_date,
            eval_window_days=eval_window_days, pull_history_before_anchor=True,
            lookback_days=600,
            force_end_today=analysis_date >= market_today - timedelta(days=500),
        )
        return self.stock_repo.get_start_daily(code=code, analysis_date=analysis_date)

    def _resolve_forward_bars(self, code: str, anchor: date, eval_window_days: int):
        """Get N forward bars; backfill in escalating passes if short."""
        bars = self.stock_repo.get_forward_bars(
            code=code, analysis_date=anchor, eval_window_days=eval_window_days,
        )
        if len(bars) >= eval_window_days:
            return bars

        self._try_fill_daily_data(
            code=code, anchor_date=anchor, eval_window_days=eval_window_days,
        )
        bars = self.stock_repo.get_forward_bars(
            code=code, analysis_date=anchor, eval_window_days=eval_window_days,
        )
        if len(bars) >= eval_window_days:
            return bars

        market_today = self._market_calendar_today(code)
        self._try_fill_daily_data(
            code=code, anchor_date=anchor, eval_window_days=eval_window_days,
            force_end_today=anchor >= market_today - timedelta(days=500),
        )
        bars = self.stock_repo.get_forward_bars(
            code=code, analysis_date=anchor, eval_window_days=eval_window_days,
        )
        # Last-resort widen for recent dates only — older anchors past the
        # data-source horizon won't benefit from another pass.
        if len(bars) < eval_window_days and anchor >= market_today - timedelta(days=500):
            self._try_fill_daily_data(
                code=code, anchor_date=anchor, eval_window_days=eval_window_days,
                force_end_today=True, widen_span=True,
            )
            bars = self.stock_repo.get_forward_bars(
                code=code, analysis_date=anchor, eval_window_days=eval_window_days,
            )
        return bars

    @staticmethod
    def _stub_result(
        analysis: AnalysisHistory,
        eval_window_days: int,
        eval_status: str,
        analysis_date: Optional[date],
    ) -> BacktestResult:
        return BacktestResult(
            analysis_history_id=analysis.id,
            code=analysis.code,
            analysis_date=analysis_date,
            eval_window_days=int(eval_window_days),
            eval_status=eval_status,
            evaluated_at=datetime.now(),
            operation_advice=analysis.operation_advice,
            strategy_id=getattr(analysis, "strategy_id", None) or "buy_pullback",
        )

    def get_recent_evaluations(self, *, code: Optional[str], eval_window_days: Optional[int] = None, limit: int = 50, page: int = 1) -> Dict[str, Any]:
        offset = max(page - 1, 0) * limit
        rows, total = self.repo.get_results_paginated(
            code=code,
            eval_window_days=eval_window_days,
            days=None,
            offset=offset,
            limit=limit,
        )

        name_map = self._build_name_map([r.analysis_history_id for r in rows])
        items = [self._result_to_dict(r, name_map) for r in rows]
        return {"total": total, "page": page, "limit": limit, "items": items}

    def get_summary(self, *, scope: str, code: Optional[str], eval_window_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
        lookup_code = OVERALL_SENTINEL_CODE if scope == "overall" else code
        summary = self.repo.get_summary(
            scope=scope,
            code=lookup_code,
            eval_window_days=eval_window_days,
        )
        if summary is None:
            return None
        return self._summary_to_dict(summary)

    # Map legacy/Chinese signal text → canonical English enum used by the engine.
    # Older AnalysisHistory rows store the LLM operation_advice text in `buy_signal`
    # (e.g. "买入" / "持有" / "强烈卖出") instead of the system signal. We bridge
    # those here so they still drive valid long/cash positions in backtest.
    _SIGNAL_TEXT_MAP = {
        "STRONG_BUY": "STRONG_BUY", "BUY": "BUY", "HOLD": "HOLD",
        "AVOID": "AVOID", "STRONG_AVOID": "STRONG_AVOID",
        "强烈买入": "STRONG_BUY", "买入": "BUY", "加仓": "BUY",
        "持有": "HOLD", "持有/逢低加仓": "BUY",
        "观望": "HOLD", "减仓/观望": "HOLD", "观望/减仓": "HOLD", "减仓": "AVOID",
        "卖出": "AVOID", "强烈卖出": "STRONG_AVOID", "清仓": "STRONG_AVOID",
    }

    @classmethod
    def _normalize_buy_signal(cls, raw: Optional[str]) -> Optional[str]:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None
        return cls._SIGNAL_TEXT_MAP.get(s, cls._SIGNAL_TEXT_MAP.get(s.upper(), None))

    @classmethod
    def _build_snapshot(cls, analysis: AnalysisHistory) -> AnalysisSnapshot:
        """Build an `AnalysisSnapshot` from a stored AnalysisHistory row.

        `strategy_id` defaults to `buy_pullback` because pre-v3 analyses were
        not tagged with the picker strategy that produced them. New analyses
        should plumb `strategy_id` end-to-end so per-strategy breakdowns work.
        """
        return AnalysisSnapshot(
            code=analysis.code,
            operation_advice=analysis.operation_advice,
            signal_score=getattr(analysis, "signal_score", None),
            buy_signal=cls._normalize_buy_signal(getattr(analysis, "buy_signal", None)),
            market_environment=getattr(analysis, "market_environment", None),
            strategy_id=getattr(analysis, "strategy_id", None) or "buy_pullback",
            ideal_buy=getattr(analysis, "ideal_buy", None),
            stop_loss=getattr(analysis, "stop_loss", None),
            take_profit=getattr(analysis, "take_profit", None),
            risk_reward=getattr(analysis, "risk_reward", None),
            position_pct=getattr(analysis, "position_pct", None),
            trend_score=getattr(analysis, "trend_score", None),
            bias_score=getattr(analysis, "bias_score", None),
            volume_score=getattr(analysis, "volume_score", None),
            support_score=getattr(analysis, "support_score", None),
            macd_score=getattr(analysis, "macd_score", None),
            rsi_score=getattr(analysis, "rsi_score", None),
            capital_flow_score=getattr(analysis, "capital_flow_score", None),
        )

    @staticmethod
    def _evaluation_to_result(
        evaluation: Dict[str, Any],
        analysis: AnalysisHistory,
        eval_window_days: int,
    ) -> BacktestResult:
        """Map an evaluation dict to a BacktestResult ORM row."""
        return BacktestResult(
            analysis_history_id=analysis.id,
            code=analysis.code,
            analysis_date=evaluation.get("analysis_date"),
            eval_window_days=int(evaluation.get("eval_window_days") or eval_window_days),
            eval_status=str(evaluation.get("eval_status") or "error"),
            evaluated_at=datetime.now(),
            operation_advice=evaluation.get("operation_advice"),
            position_recommendation=evaluation.get("position_recommendation"),
            start_price=evaluation.get("start_price"),
            end_close=evaluation.get("end_close"),
            max_high=evaluation.get("max_high"),
            min_low=evaluation.get("min_low"),
            stock_return_pct=evaluation.get("stock_return_pct"),
            direction_expected=evaluation.get("direction_expected"),
            direction_correct=evaluation.get("direction_correct"),
            outcome=evaluation.get("outcome"),
            stop_loss=evaluation.get("stop_loss"),
            take_profit=evaluation.get("take_profit"),
            hit_stop_loss=evaluation.get("hit_stop_loss"),
            hit_take_profit=evaluation.get("hit_take_profit"),
            first_hit=evaluation.get("first_hit"),
            first_hit_date=evaluation.get("first_hit_date"),
            first_hit_trading_days=evaluation.get("first_hit_trading_days"),
            simulated_entry_price=evaluation.get("simulated_entry_price"),
            simulated_exit_price=evaluation.get("simulated_exit_price"),
            simulated_exit_reason=evaluation.get("simulated_exit_reason"),
            simulated_return_pct=evaluation.get("simulated_return_pct"),
            # v2 additions
            signal_score_at_eval=evaluation.get("signal_score_at_eval"),
            buy_signal_at_eval=evaluation.get("buy_signal_at_eval"),
            market_environment_at_eval=evaluation.get("market_environment_at_eval"),
            strategy_id=evaluation.get("strategy_id"),
            risk_reward_at_eval=evaluation.get("risk_reward_at_eval"),
            position_pct_at_eval=evaluation.get("position_pct_at_eval"),
            trend_score_at_eval=evaluation.get("trend_score_at_eval"),
            bias_score_at_eval=evaluation.get("bias_score_at_eval"),
            volume_score_at_eval=evaluation.get("volume_score_at_eval"),
            support_score_at_eval=evaluation.get("support_score_at_eval"),
            macd_score_at_eval=evaluation.get("macd_score_at_eval"),
            rsi_score_at_eval=evaluation.get("rsi_score_at_eval"),
            capital_flow_score_at_eval=evaluation.get("capital_flow_score_at_eval"),
            exit_reason=evaluation.get("exit_reason"),
            hold_days=evaluation.get("hold_days"),
            # v3 trade-execution metrics
            entry_status=evaluation.get("entry_status"),
            r_multiple=evaluation.get("r_multiple"),
            mae_pct=evaluation.get("mae_pct"),
            mfe_pct=evaluation.get("mfe_pct"),
        )

    def _resolve_analysis_date(self, analysis) -> Optional[date]:
        parsed = self.repo.parse_analysis_date_from_snapshot(analysis.context_snapshot)
        if parsed:
            return parsed
        if getattr(analysis, "created_at", None):
            return analysis.created_at.date()
        logger.warning(f"无法确定分析日期，跳过记录: {analysis.code}#{getattr(analysis, 'id', '?')}")
        return None

    def _market_calendar_today(self, code: str) -> date:
        """Listing-market calendar date (avoids UTC host skew for backtest end ranges)."""
        from src.core.trading_calendar import get_calendar_today_for_market, get_market_for_stock

        return get_calendar_today_for_market(get_market_for_stock(code))

    def _try_fill_daily_data(
        self,
        *,
        code: str,
        anchor_date: date,
        eval_window_days: int,
        pull_history_before_anchor: bool = False,
        force_end_today: bool = False,
        widen_span: bool = False,
        lookback_days: Optional[int] = None,
    ) -> bool:
        """
        Fetch daily OHLC from data providers and persist to DB when backtest lacks bars.

        Returns True if a non-empty frame was returned and save_daily_data ran (may update 0 new rows).
        """
        try:
            from data_provider.base import DataFetcherManager

            ew = int(eval_window_days)
            base_span = max(ew * 3 + 21, 60)
            calendar_span = base_span * 2 if widen_span else base_span
            today_m = self._market_calendar_today(code)

            if pull_history_before_anchor:
                if lookback_days is not None:
                    lb = timedelta(days=lookback_days)
                elif anchor_date > today_m:
                    lb = timedelta(days=120)
                else:
                    lb = timedelta(
                        days=min(
                            400,
                            max(120, (today_m - anchor_date).days + calendar_span + 45),
                        )
                    )
                start_date = anchor_date - lb
            else:
                start_date = anchor_date

            end_date = anchor_date + timedelta(days=calendar_span)
            recent_anchor = anchor_date >= (today_m - timedelta(days=min(max(calendar_span * 2, 120), 800)))
            if force_end_today or recent_anchor:
                end_date = max(end_date, today_m)

            if start_date > anchor_date:
                start_date = anchor_date

            fetch_cap = min(max((end_date - start_date).days + 20, ew + 50), 800)

            manager = DataFetcherManager()
            df, source = manager.get_daily_data(
                stock_code=code,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                days=fetch_cap,
            )
            if df is None or df.empty:
                logger.warning(
                    "[Backtest] daily fetch empty code=%s anchor=%s range=%s..%s",
                    code,
                    anchor_date,
                    start_date,
                    end_date,
                )
                return False
            self.db.save_daily_data(df, code=code, data_source=source)
            logger.info(
                "[Backtest] daily fill saved code=%s anchor=%s rows=%d source=%s range=%s..%s",
                code,
                anchor_date,
                len(df),
                source,
                start_date,
                end_date,
            )
            return True
        except Exception as exc:
            logger.warning("补全日线数据失败(%s): %s", code, exc)
            return False

    def _recompute_summaries(self, *, touched_codes: List[str], eval_window_days: int) -> None:
        with self.db.get_session() as session:
            # overall
            overall_rows = session.execute(
                select(BacktestResult).where(BacktestResult.eval_window_days == eval_window_days)
            ).scalars().all()
            overall_data = BacktestEngine.compute_summary(
                results=overall_rows,
                scope="overall",
                code=OVERALL_SENTINEL_CODE,
                eval_window_days=eval_window_days,
            )
            self.repo.upsert_summary(self._build_summary_model(overall_data))

            for code in touched_codes:
                rows = session.execute(
                    select(BacktestResult).where(
                        and_(
                            BacktestResult.code == code,
                            BacktestResult.eval_window_days == eval_window_days,
                        )
                    )
                ).scalars().all()
                data = BacktestEngine.compute_summary(
                    results=rows,
                    scope="stock",
                    code=code,
                    eval_window_days=eval_window_days,
                )
                self.repo.upsert_summary(self._build_summary_model(data))

    @staticmethod
    def _build_summary_model(summary_data: Dict[str, Any]) -> BacktestSummary:
        return BacktestSummary(
            scope=summary_data.get("scope"),
            code=summary_data.get("code"),
            eval_window_days=summary_data.get("eval_window_days"),
            computed_at=datetime.now(),
            total_evaluations=summary_data.get("total_evaluations") or 0,
            completed_count=summary_data.get("completed_count") or 0,
            insufficient_count=summary_data.get("insufficient_count") or 0,
            long_count=summary_data.get("long_count") or 0,
            cash_count=summary_data.get("cash_count") or 0,
            win_count=summary_data.get("win_count") or 0,
            loss_count=summary_data.get("loss_count") or 0,
            neutral_count=summary_data.get("neutral_count") or 0,
            direction_accuracy_pct=summary_data.get("direction_accuracy_pct"),
            win_rate_pct=summary_data.get("win_rate_pct"),
            neutral_rate_pct=summary_data.get("neutral_rate_pct"),
            avg_stock_return_pct=summary_data.get("avg_stock_return_pct"),
            avg_simulated_return_pct=summary_data.get("avg_simulated_return_pct"),
            stop_loss_trigger_rate=summary_data.get("stop_loss_trigger_rate"),
            take_profit_trigger_rate=summary_data.get("take_profit_trigger_rate"),
            ambiguous_rate=summary_data.get("ambiguous_rate"),
            avg_days_to_first_hit=summary_data.get("avg_days_to_first_hit"),
            # v3 metrics
            fill_rate_pct=summary_data.get("fill_rate_pct"),
            filled_count=summary_data.get("filled_count") or 0,
            not_filled_count=summary_data.get("not_filled_count") or 0,
            not_filled_limit_up_count=summary_data.get("not_filled_limit_up_count") or 0,
            trade_win_rate_pct=summary_data.get("trade_win_rate_pct"),
            expectancy_pct=summary_data.get("expectancy_pct"),
            avg_r_multiple=summary_data.get("avg_r_multiple"),
            profit_factor=summary_data.get("profit_factor"),
            max_drawdown_pct=summary_data.get("max_drawdown_pct"),
            avg_mae_pct=summary_data.get("avg_mae_pct"),
            avg_mfe_pct=summary_data.get("avg_mfe_pct"),
            ambiguous_count=summary_data.get("ambiguous_count") or 0,
            diagnostics_json=json.dumps(summary_data.get("diagnostics") or {}, ensure_ascii=False),
            signal_breakdown_json=json.dumps(summary_data.get("signal_breakdown") or {}, ensure_ascii=False),
            score_bucket_breakdown_json=json.dumps(summary_data.get("score_bucket_breakdown") or {}, ensure_ascii=False),
            risk_reward_breakdown_json=json.dumps(summary_data.get("risk_reward_breakdown") or {}, ensure_ascii=False),
            exit_reason_breakdown_json=json.dumps(summary_data.get("exit_reason_breakdown") or {}, ensure_ascii=False),
            regime_breakdown_json=json.dumps(summary_data.get("regime_breakdown") or {}, ensure_ascii=False),
            strategy_breakdown_json=json.dumps(summary_data.get("strategy_breakdown") or {}, ensure_ascii=False),
        )

    def _build_name_map(self, analysis_ids: List[int]) -> Dict[int, str]:
        """Batch-fetch stock names from analysis_history for a list of analysis IDs."""
        from src.storage import AnalysisHistory
        ids = [i for i in analysis_ids if i is not None]
        if not ids:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(AnalysisHistory.id, AnalysisHistory.name)
                .where(AnalysisHistory.id.in_(ids))
            ).all()
            return {r[0]: r[1] or "" for r in rows}

    @staticmethod
    def _result_to_dict(row: BacktestResult, name_map: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
        name = (name_map or {}).get(row.analysis_history_id, "")
        return {
            "analysis_history_id": row.analysis_history_id,
            "code": row.code,
            "name": name,
            "analysis_date": row.analysis_date.isoformat() if row.analysis_date else None,
            "eval_window_days": row.eval_window_days,
            "eval_status": row.eval_status,
            "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
            "operation_advice": row.operation_advice,
            "position_recommendation": row.position_recommendation,
            "start_price": row.start_price,
            "end_close": row.end_close,
            "max_high": row.max_high,
            "min_low": row.min_low,
            "stock_return_pct": row.stock_return_pct,
            "direction_expected": row.direction_expected,
            "direction_correct": row.direction_correct,
            "outcome": row.outcome,
            "stop_loss": row.stop_loss,
            "take_profit": row.take_profit,
            "hit_stop_loss": row.hit_stop_loss,
            "hit_take_profit": row.hit_take_profit,
            "first_hit": row.first_hit,
            "first_hit_date": row.first_hit_date.isoformat() if row.first_hit_date else None,
            "first_hit_trading_days": row.first_hit_trading_days,
            "simulated_entry_price": row.simulated_entry_price,
            "simulated_exit_price": row.simulated_exit_price,
            "simulated_exit_reason": row.simulated_exit_reason,
            "simulated_return_pct": row.simulated_return_pct,
            # v2 additions
            "signal_score_at_eval": getattr(row, "signal_score_at_eval", None),
            "buy_signal_at_eval": getattr(row, "buy_signal_at_eval", None),
            "market_environment_at_eval": getattr(row, "market_environment_at_eval", None),
            "strategy_id": getattr(row, "strategy_id", None),
            "risk_reward_at_eval": getattr(row, "risk_reward_at_eval", None),
            "position_pct_at_eval": getattr(row, "position_pct_at_eval", None),
            "trend_score_at_eval": getattr(row, "trend_score_at_eval", None),
            "bias_score_at_eval": getattr(row, "bias_score_at_eval", None),
            "volume_score_at_eval": getattr(row, "volume_score_at_eval", None),
            "support_score_at_eval": getattr(row, "support_score_at_eval", None),
            "macd_score_at_eval": getattr(row, "macd_score_at_eval", None),
            "rsi_score_at_eval": getattr(row, "rsi_score_at_eval", None),
            "capital_flow_score_at_eval": getattr(row, "capital_flow_score_at_eval", None),
            "exit_reason": getattr(row, "exit_reason", None),
            "hold_days": getattr(row, "hold_days", None),
            # v3
            "entry_status": getattr(row, "entry_status", None),
            "r_multiple": getattr(row, "r_multiple", None),
            "mae_pct": getattr(row, "mae_pct", None),
            "mfe_pct": getattr(row, "mfe_pct", None),
        }

    @staticmethod
    def _summary_to_dict(row: BacktestSummary) -> Dict[str, Any]:
        return {
            "scope": row.scope,
            "code": None if row.code == OVERALL_SENTINEL_CODE else row.code,
            "eval_window_days": row.eval_window_days,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
            "total_evaluations": row.total_evaluations,
            "completed_count": row.completed_count,
            "insufficient_count": row.insufficient_count,
            "long_count": row.long_count,
            "cash_count": row.cash_count,
            "win_count": row.win_count,
            "loss_count": row.loss_count,
            "neutral_count": row.neutral_count,
            "direction_accuracy_pct": row.direction_accuracy_pct,
            "win_rate_pct": row.win_rate_pct,
            "neutral_rate_pct": row.neutral_rate_pct,
            "avg_stock_return_pct": row.avg_stock_return_pct,
            "avg_simulated_return_pct": row.avg_simulated_return_pct,
            "stop_loss_trigger_rate": row.stop_loss_trigger_rate,
            "take_profit_trigger_rate": row.take_profit_trigger_rate,
            "ambiguous_rate": row.ambiguous_rate,
            "avg_days_to_first_hit": row.avg_days_to_first_hit,
            "fill_rate_pct": getattr(row, "fill_rate_pct", None),
            "filled_count": getattr(row, "filled_count", None) or 0,
            "not_filled_count": getattr(row, "not_filled_count", None) or 0,
            "not_filled_limit_up_count": getattr(row, "not_filled_limit_up_count", None) or 0,
            "trade_win_rate_pct": getattr(row, "trade_win_rate_pct", None),
            "expectancy_pct": getattr(row, "expectancy_pct", None),
            "avg_r_multiple": getattr(row, "avg_r_multiple", None),
            "profit_factor": getattr(row, "profit_factor", None),
            "max_drawdown_pct": getattr(row, "max_drawdown_pct", None),
            "avg_mae_pct": getattr(row, "avg_mae_pct", None),
            "avg_mfe_pct": getattr(row, "avg_mfe_pct", None),
            "ambiguous_count": getattr(row, "ambiguous_count", None) or 0,
            "diagnostics": json.loads(row.diagnostics_json) if row.diagnostics_json else {},
            "signal_breakdown": json.loads(row.signal_breakdown_json) if getattr(row, "signal_breakdown_json", None) else {},
            "score_bucket_breakdown": json.loads(row.score_bucket_breakdown_json) if getattr(row, "score_bucket_breakdown_json", None) else {},
            "risk_reward_breakdown": json.loads(row.risk_reward_breakdown_json) if getattr(row, "risk_reward_breakdown_json", None) else {},
            "exit_reason_breakdown": json.loads(row.exit_reason_breakdown_json) if getattr(row, "exit_reason_breakdown_json", None) else {},
            "regime_breakdown": json.loads(row.regime_breakdown_json) if getattr(row, "regime_breakdown_json", None) else {},
            "strategy_breakdown": json.loads(row.strategy_breakdown_json) if getattr(row, "strategy_breakdown_json", None) else {},
        }
