# -*- coding: utf-8 -*-
"""Picker history and picker-backtest history persistence."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, desc, func, select

from .models import PickerBacktestHistory, PickerHistory

logger = logging.getLogger(__name__)


class _PickerMixin:
    """Mixin: ``save_picker_history`` / ``get_picker_history*`` / picker backtest."""

    def save_picker_history(
        self,
        result_dict: Dict[str, Any],
        picker_mode: Optional[str] = None,
        picker_strategies: Optional[List[str]] = None,
    ) -> int:
        """Persist a successful picker run. Returns the new row id, or 0 on failure."""
        strategies = picker_strategies or result_dict.get("picker_strategies") or ["buy_pullback"]
        record = PickerHistory(
            market_summary=result_dict.get("market_summary", ""),
            picks_json=json.dumps(result_dict.get("picks", []), ensure_ascii=False),
            sectors_json=json.dumps(result_dict.get("sectors_to_watch", []), ensure_ascii=False),
            risk_warning=result_dict.get("risk_warning", ""),
            screen_stats_json=json.dumps(result_dict.get("screen_stats"), ensure_ascii=False)
            if result_dict.get("screen_stats") else None,
            screened_pool_json=json.dumps(result_dict.get("screened_pool", []), ensure_ascii=False)
            if result_dict.get("screened_pool") else None,
            screened_pool_by_strategy_json=(
                json.dumps(result_dict.get("screened_pool_by_strategy", {}), ensure_ascii=False)
                if result_dict.get("screened_pool_by_strategy") else None
            ),
            pick_count=len(result_dict.get("picks", [])),
            elapsed_seconds=result_dict.get("elapsed_seconds", 0),
            created_at=datetime.now(),
            picker_mode=picker_mode,
            picker_strategies_json=json.dumps(strategies, ensure_ascii=False),
        )
        with self.get_session() as session:
            try:
                session.add(record)
                session.commit()
                session.refresh(record)
                return record.id
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to save picker history: {e}")
                return 0

    def get_picker_history_list(self, limit: int = 20, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        """Return (items, total_count) for the picker history list view."""
        with self.get_session() as session:
            total = session.execute(select(func.count(PickerHistory.id))).scalar() or 0
            rows = session.execute(
                select(PickerHistory)
                .order_by(desc(PickerHistory.created_at))
                .offset(offset)
                .limit(limit)
            ).scalars().all()
            return [r.to_summary_dict() for r in rows], total

    def get_picker_history_detail(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Return full picker result by id, or None."""
        with self.get_session() as session:
            row = session.execute(
                select(PickerHistory).where(PickerHistory.id == record_id)
            ).scalars().first()
            return row.to_full_dict() if row else None

    def clear_picker_history(self) -> int:
        """Delete all picker history records. Returns deleted count."""
        with self.get_session() as session:
            result = session.execute(delete(PickerHistory))
            session.commit()
            return result.rowcount or 0
    # ── Picker Backtest History ────────────────────────────────────

    def save_picker_backtest_history(
        self,
        result: Dict[str, Any],
        *,
        start_date: str = "",
        end_date: str = "",
        hold_days: int = 10,
        top_n: int = 5,
        picker_strategies: Optional[List[str]] = None,
    ) -> int:
        """Persist a picker backtest run. Returns the new row id, or 0 on failure."""
        summary = result.get("summary") or {}
        strategies = picker_strategies or summary.get("picker_strategies")
        record = PickerBacktestHistory(
            start_date=start_date or summary.get("start_date", ""),
            end_date=end_date or summary.get("end_date", ""),
            hold_days=hold_days or summary.get("hold_days", 10),
            top_n=top_n or summary.get("top_n", 5),
            picker_strategies_json=(
                json.dumps(strategies, ensure_ascii=False) if strategies else None
            ),
            trade_dates_count=result.get("trade_dates_count", 0),
            results_json=json.dumps(result.get("results", []), ensure_ascii=False),
            summary_json=json.dumps(summary, ensure_ascii=False),
            created_at=datetime.now(),
        )
        with self.get_session() as session:
            try:
                session.add(record)
                session.commit()
                session.refresh(record)
                return record.id
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to save picker backtest history: {e}")
                return 0

    def get_picker_backtest_history_list(
        self, limit: int = 20, offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return (items, total_count) for picker backtest history list."""
        with self.get_session() as session:
            total = (
                session.execute(select(func.count(PickerBacktestHistory.id))).scalar() or 0
            )
            rows = (
                session.execute(
                    select(PickerBacktestHistory)
                    .order_by(desc(PickerBacktestHistory.created_at))
                    .offset(offset)
                    .limit(limit)
                )
                .scalars().all()
            )
            return [r.to_summary_dict() for r in rows], total

    def get_picker_backtest_history_detail(
        self, record_id: int
    ) -> Optional[Dict[str, Any]]:
        """Return full picker backtest result by id, or None."""
        with self.get_session() as session:
            row = (
                session.execute(
                    select(PickerBacktestHistory).where(PickerBacktestHistory.id == record_id)
                )
                .scalars().first()
            )
            return row.to_full_dict() if row else None

    def get_latest_picker_backtest(self) -> Optional[Dict[str, Any]]:
        """Return the most recent picker backtest run, or None."""
        with self.get_session() as session:
            row = (
                session.execute(
                    select(PickerBacktestHistory).order_by(
                        desc(PickerBacktestHistory.created_at)
                    ).limit(1)
                )
                .scalars().first()
            )
            return row.to_full_dict() if row else None

