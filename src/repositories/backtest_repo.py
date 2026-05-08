# -*- coding: utf-8 -*-
"""Backtest repository.

Provides database access helpers for backtest tables.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import and_, delete, desc, func, select

from src.storage import BacktestResult, BacktestSummary, DatabaseManager, AnalysisHistory

logger = logging.getLogger(__name__)


class BacktestRepository:
    """DB access layer for backtesting."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def get_candidates(
        self,
        *,
        code: Optional[str],
        min_age_days: int,
        limit: int,
        eval_window_days: int,
        force: bool,
        strategies: Optional[List[str]] = None,
    ) -> List[AnalysisHistory]:
        """Return AnalysisHistory rows eligible for backtest.

        When `strategies` is given, an analysis is treated as "already done" only when
        ALL requested strategies have a result row for it (so partially-evaluated
        analyses get re-run for the missing strategies).
        """
        cutoff_dt = datetime.now() - timedelta(days=min_age_days)

        with self.db.get_session() as session:
            conditions = [AnalysisHistory.created_at <= cutoff_dt]
            if code:
                conditions.append(AnalysisHistory.code == code)

            query = select(AnalysisHistory).where(and_(*conditions))

            if not force:
                if strategies:
                    # Skip analyses that already have results for ALL requested strategies.
                    fully_done_ids: Optional[set] = None
                    for sid in strategies:
                        sub = session.execute(
                            select(BacktestResult.analysis_history_id).where(
                                and_(
                                    BacktestResult.eval_window_days == eval_window_days,
                                    BacktestResult.strategy_id == sid,
                                )
                            )
                        ).scalars().all()
                        ids_for_sid = set(sub)
                        fully_done_ids = ids_for_sid if fully_done_ids is None else fully_done_ids & ids_for_sid
                    if fully_done_ids:
                        query = query.where(AnalysisHistory.id.not_in(list(fully_done_ids)))
                else:
                    existing_ids = select(BacktestResult.analysis_history_id).where(
                        BacktestResult.eval_window_days == eval_window_days
                    )
                    query = query.where(AnalysisHistory.id.not_in(existing_ids))

            query = query.order_by(desc(AnalysisHistory.created_at)).limit(limit)
            rows = session.execute(query).scalars().all()
            return list(rows)

    def save_result(self, result: BacktestResult) -> None:
        with self.db.get_session() as session:
            session.add(result)
            session.commit()

    def save_results_batch(self, results: List[BacktestResult], *, replace_existing: bool = False) -> int:
        if not results:
            return 0

        with self.db.get_session() as session:
            try:
                if replace_existing:
                    # Delete rows that conflict with the new ones, scoped by the unique
                    # key (analysis_history_id, eval_window_days, strategy_id) so other
                    # strategies for the same analysis aren't wiped.
                    analysis_ids = sorted({r.analysis_history_id for r in results if r.analysis_history_id is not None})
                    key_pairs = sorted({(r.eval_window_days, r.strategy_id) for r in results})
                    if analysis_ids and key_pairs:
                        for window_days, strategy_id in key_pairs:
                            session.execute(
                                delete(BacktestResult).where(
                                    and_(
                                        BacktestResult.analysis_history_id.in_(analysis_ids),
                                        BacktestResult.eval_window_days == window_days,
                                        BacktestResult.strategy_id == strategy_id,
                                    )
                                )
                            )

                session.add_all(results)
                session.commit()
                return len(results)
            except Exception as exc:
                session.rollback()
                logger.error(f"批量保存回测结果失败: {exc}")
                raise

    def get_results_paginated(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        days: Optional[int],
        offset: int,
        limit: int,
    ) -> Tuple[List[BacktestResult], int]:
        with self.db.get_session() as session:
            conditions = []
            if code:
                conditions.append(BacktestResult.code == code)
            if eval_window_days is not None:
                conditions.append(BacktestResult.eval_window_days == eval_window_days)
            if days:
                cutoff = datetime.now() - timedelta(days=int(days))
                conditions.append(BacktestResult.evaluated_at >= cutoff)

            where_clause = and_(*conditions) if conditions else True

            total = session.execute(select(func.count(BacktestResult.id)).where(where_clause)).scalar() or 0
            rows = session.execute(
                select(BacktestResult)
                .where(where_clause)
                .order_by(desc(BacktestResult.evaluated_at))
                .offset(offset)
                .limit(limit)
            ).scalars().all()
            return list(rows), int(total)

    def upsert_summary(self, summary: BacktestSummary) -> None:
        """Insert or replace summary row by unique key."""
        with self.db.get_session() as session:
            existing = session.execute(
                select(BacktestSummary)
                .where(
                    and_(
                        BacktestSummary.scope == summary.scope,
                        BacktestSummary.code == summary.code,
                        BacktestSummary.eval_window_days == summary.eval_window_days,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()

            if existing:
                for attr in (
                    "computed_at",
                    "total_evaluations",
                    "completed_count",
                    "insufficient_count",
                    "long_count",
                    "cash_count",
                    "win_count",
                    "loss_count",
                    "neutral_count",
                    "direction_accuracy_pct",
                    "win_rate_pct",
                    "neutral_rate_pct",
                    "avg_stock_return_pct",
                    "avg_simulated_return_pct",
                    "stop_loss_trigger_rate",
                    "take_profit_trigger_rate",
                    "ambiguous_rate",
                    "avg_days_to_first_hit",
                    "diagnostics_json",
                    "signal_breakdown_json",
                    "score_bucket_breakdown_json",
                    "exit_reason_breakdown_json",
                    "regime_breakdown_json",
                    "strategy_breakdown_json",
                ):
                    setattr(existing, attr, getattr(summary, attr))
                session.commit()
                return

            session.add(summary)
            session.commit()

    def get_summary(
        self,
        *,
        scope: str,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
    ) -> Optional[BacktestSummary]:
        with self.db.get_session() as session:
            conditions = [
                BacktestSummary.scope == scope,
                BacktestSummary.code == code,
            ]
            if eval_window_days is not None:
                conditions.append(BacktestSummary.eval_window_days == eval_window_days)

            row = session.execute(
                select(BacktestSummary)
                .where(and_(*conditions))
                .order_by(desc(BacktestSummary.computed_at))
                .limit(1)
            ).scalar_one_or_none()
            return row

    @staticmethod
    def parse_analysis_date_from_snapshot(context_snapshot: Optional[str]) -> Optional[date]:
        if not context_snapshot:
            return None

        try:
            payload = json.loads(context_snapshot)
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        enhanced = payload.get("enhanced_context")
        if not isinstance(enhanced, dict):
            return None

        date_str = enhanced.get("date")
        if not date_str:
            return None

        try:
            return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        except Exception:
            return None
