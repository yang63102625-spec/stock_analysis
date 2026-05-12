# -*- coding: utf-8 -*-
"""Backtest orchestration service."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import replace
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

    # Allowed picker strategies (mirrors trade_levels strategy ids).
    _ALLOWED_STRATEGIES = ("buy_pullback", "breakout", "bottom_reversal", "eod_buyback")

    def run_backtest(
        self,
        *,
        code: Optional[str] = None,
        force: bool = False,
        eval_window_days: Optional[int] = None,
        min_age_days: Optional[int] = None,
        limit: int = 200,
        strategies: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        config = get_config()

        if eval_window_days is None:
            eval_window_days = getattr(config, "backtest_eval_window_days", 10)
        if min_age_days is None:
            min_age_days = getattr(config, "backtest_min_age_days", 14)

        # Normalize strategies list: filter to known ids; default to single buy_pullback.
        wanted = [s for s in (strategies or []) if s in self._ALLOWED_STRATEGIES] or ["buy_pullback"]

        eval_config = EvaluationConfig(
            eval_window_days=int(eval_window_days),
            neutral_band_pct=float(getattr(config, "backtest_neutral_band_pct", 2.0)),
        )

        candidates = self.repo.get_candidates(
            code=code,
            min_age_days=int(min_age_days),
            limit=int(limit),
            eval_window_days=int(eval_window_days),
            force=force,
            strategies=wanted,
        )

        total_candidates = len(candidates)
        logger.info(
            "[Backtest] run start: candidates=%d code=%s force=%s eval_window_days=%d limit=%d",
            total_candidates,
            code or "*",
            force,
            int(eval_window_days),
            int(limit),
        )

        processed = 0
        completed = 0
        insufficient = 0
        errors = 0
        touched_codes: set[str] = set()

        results_to_save: List[BacktestResult] = []

        for analysis in candidates:
            processed += 1
            touched_codes.add(analysis.code)
            if processed == 1 or processed % 25 == 0 or processed == total_candidates:
                logger.info(
                    "[Backtest] progress %d/%d (code=%s id=%s)",
                    processed,
                    total_candidates,
                    analysis.code,
                    getattr(analysis, "id", "?"),
                )

            try:
                analysis_date = self._resolve_analysis_date(analysis)
                if analysis_date is None:
                    errors += 1
                    results_to_save.append(
                        BacktestResult(
                            analysis_history_id=analysis.id,
                            code=analysis.code,
                            eval_window_days=int(eval_window_days),
                            eval_status="error",
                            evaluated_at=datetime.now(),
                            operation_advice=analysis.operation_advice,
                            strategy_id=wanted[0],
                        )
                    )
                    continue
                start_daily = self.stock_repo.get_start_daily(code=analysis.code, analysis_date=analysis_date)

                if start_daily is None or start_daily.close is None:
                    self._try_fill_daily_data(
                        code=analysis.code,
                        anchor_date=analysis_date,
                        eval_window_days=eval_window_days,
                        pull_history_before_anchor=True,
                    )
                    start_daily = self.stock_repo.get_start_daily(code=analysis.code, analysis_date=analysis_date)

                if start_daily is None or start_daily.close is None:
                    mt0 = self._market_calendar_today(analysis.code)
                    self._try_fill_daily_data(
                        code=analysis.code,
                        anchor_date=analysis_date,
                        eval_window_days=eval_window_days,
                        pull_history_before_anchor=True,
                        lookback_days=600,
                        force_end_today=analysis_date >= mt0 - timedelta(days=500),
                    )
                    start_daily = self.stock_repo.get_start_daily(code=analysis.code, analysis_date=analysis_date)

                if start_daily is None or start_daily.close is None:
                    insufficient += 1
                    results_to_save.append(
                        BacktestResult(
                            analysis_history_id=analysis.id,
                            code=analysis.code,
                            analysis_date=analysis_date,
                            eval_window_days=int(eval_window_days),
                            eval_status="insufficient_data",
                            evaluated_at=datetime.now(),
                            operation_advice=analysis.operation_advice,
                            strategy_id=wanted[0],
                        )
                    )
                    continue

                forward_bars = self.stock_repo.get_forward_bars(
                    code=analysis.code,
                    analysis_date=start_daily.date,
                    eval_window_days=int(eval_window_days),
                )

                if len(forward_bars) < int(eval_window_days):
                    self._try_fill_daily_data(
                        code=analysis.code,
                        anchor_date=start_daily.date,
                        eval_window_days=eval_window_days,
                    )
                    forward_bars = self.stock_repo.get_forward_bars(
                        code=analysis.code,
                        analysis_date=start_daily.date,
                        eval_window_days=int(eval_window_days),
                    )

                if len(forward_bars) < int(eval_window_days):
                    mt1 = self._market_calendar_today(analysis.code)
                    self._try_fill_daily_data(
                        code=analysis.code,
                        anchor_date=start_daily.date,
                        eval_window_days=eval_window_days,
                        force_end_today=start_daily.date >= mt1 - timedelta(days=500),
                    )
                    forward_bars = self.stock_repo.get_forward_bars(
                        code=analysis.code,
                        analysis_date=start_daily.date,
                        eval_window_days=int(eval_window_days),
                    )

                # Last-resort refetch when forward_bars are still short (recent dates).
                if len(forward_bars) < int(eval_window_days):
                    mkt_today = self._market_calendar_today(analysis.code)
                    if start_daily.date >= mkt_today - timedelta(days=500):
                        self._try_fill_daily_data(
                            code=analysis.code,
                            anchor_date=start_daily.date,
                            eval_window_days=eval_window_days,
                            force_end_today=True,
                            widen_span=True,
                        )
                        forward_bars = self.stock_repo.get_forward_bars(
                            code=analysis.code,
                            analysis_date=start_daily.date,
                            eval_window_days=int(eval_window_days),
                        )

                # Multi-strategy evaluation: same forward_bars, different trade_levels rules.
                # One result row per (analysis, strategy) pair so users can compare.
                base_snapshot = self._build_snapshot(analysis)
                for strategy_id in wanted:
                    snapshot = replace(base_snapshot, strategy_id=strategy_id)
                    evaluation = BacktestEngine.evaluate_single(
                        analysis=snapshot,
                        analysis_date=start_daily.date,
                        start_price=float(start_daily.close),
                        forward_bars=forward_bars,
                        config=eval_config,
                    )
                    status = evaluation.get("eval_status")
                    if status == "completed":
                        completed += 1
                    elif status == "insufficient_data":
                        insufficient += 1
                    elif status != "missing_signal":
                        errors += 1
                    results_to_save.append(
                        self._evaluation_to_result(evaluation, analysis, eval_window_days)
                    )

            except Exception as exc:
                errors += 1
                logger.error(f"回测失败: {analysis.code}#{analysis.id}: {exc}")
                results_to_save.append(
                    BacktestResult(
                        analysis_history_id=analysis.id,
                        code=analysis.code,
                        analysis_date=self._resolve_analysis_date(analysis),
                        eval_window_days=int(eval_window_days),
                        eval_status="error",
                        evaluated_at=datetime.now(),
                        operation_advice=analysis.operation_advice,
                        strategy_id=wanted[0],
                    )
                )

        saved = 0
        if results_to_save:
            saved = self.repo.save_results_batch(results_to_save, replace_existing=force)

        if saved:
            self._recompute_summaries(
                touched_codes=sorted(touched_codes),
                eval_window_days=int(eval_window_days),
            )

        logger.info(
            "[Backtest] run done: processed=%d saved=%d completed=%d insufficient=%d errors=%d",
            processed,
            saved,
            completed,
            insufficient,
            errors,
        )

        return {
            "processed": processed,
            "saved": saved,
            "completed": completed,
            "insufficient": insufficient,
            "errors": errors,
        }

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

    @staticmethod
    def _build_snapshot(analysis: AnalysisHistory) -> AnalysisSnapshot:
        """Build the v2 AnalysisSnapshot from a stored AnalysisHistory row.

        strategy_id defaults to 'buy_pullback' (most general). Future enhancement:
        plumb strategy_id through the analysis pipeline so analyses know which
        picker strategy generated them.
        """
        return AnalysisSnapshot(
            code=analysis.code,
            operation_advice=analysis.operation_advice,
            signal_score=getattr(analysis, "signal_score", None),
            buy_signal=getattr(analysis, "buy_signal", None),
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
            diagnostics_json=json.dumps(summary_data.get("diagnostics") or {}, ensure_ascii=False),
            signal_breakdown_json=json.dumps(summary_data.get("signal_breakdown") or {}, ensure_ascii=False),
            score_bucket_breakdown_json=json.dumps(summary_data.get("score_bucket_breakdown") or {}, ensure_ascii=False),
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
            "diagnostics": json.loads(row.diagnostics_json) if row.diagnostics_json else {},
            "signal_breakdown": json.loads(row.signal_breakdown_json) if getattr(row, "signal_breakdown_json", None) else {},
            "score_bucket_breakdown": json.loads(row.score_bucket_breakdown_json) if getattr(row, "score_bucket_breakdown_json", None) else {},
            "exit_reason_breakdown": json.loads(row.exit_reason_breakdown_json) if getattr(row, "exit_reason_breakdown_json", None) else {},
            "regime_breakdown": json.loads(row.regime_breakdown_json) if getattr(row, "regime_breakdown_json", None) else {},
            "strategy_breakdown": json.loads(row.strategy_breakdown_json) if getattr(row, "strategy_breakdown_json", None) else {},
        }
